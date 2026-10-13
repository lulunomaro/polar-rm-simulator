"""Trusted local JSON-lines adapters. Process separation is not a security sandbox.

HTTP callers choose pre-registered IDs and config, never commands or filenames.
The existing runtime independently validates every observation/action and deadline.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
from .profile import digest, read_json
from ..platform_v2.adapters import BaseAdapter, descriptor, require_sensors
from ..platform_v2.contracts import ContractError, exact, validate_action

SCHEMA = 'polar.sim.adapter.jsonl.v1'
MAX_REQUEST = 12 * 1024 * 1024
MAX_RESPONSE = 64 * 1024


def load_registrations(path):
    path = Path(path).absolute()
    value = read_json(path)
    exact(value, ('schema', 'adapters'), 'local_adapter_manifest')
    if value['schema'] != SCHEMA or type(value['adapters']) is not list or len(value['adapters']) > 16:
        raise ContractError('invalid_local_adapter_manifest')
    result = []
    seen = set()
    for row in value['adapters']:
        exact(row, ('adapter_id', 'kind', 'label', 'command', 'cwd', 'required_sensors'), 'local_adapter')
        aid = row['adapter_id']
        if type(aid) is not str or not re.fullmatch(r'custom_[a-z0-9_]{1,100}', aid) or aid in seen:
            raise ContractError('custom_adapter_id_required')
        seen.add(aid)
        if row['kind'] not in ('navigation', 'aim') or type(row['label']) is not str or not 1 <= len(row['label']) <= 200:
            raise ContractError('invalid_custom_kind_or_label')
        sensors = row['required_sensors']
        if type(sensors) is not list or len(set(sensors)) != len(sensors) or set(sensors) - {'camera', 'ranges', 'odometry'}:
            raise ContractError('invalid_custom_sensors')
        command = row['command']
        if type(command) is not list or not 1 <= len(command) <= 32 or any(type(v) is not str or not v or len(v) > 4096 for v in command):
            raise ContractError('invalid_custom_command')
        command = [sys.executable if v == '{python}' else v for v in command]
        binary = Path(command[0])
        if not binary.is_absolute() or not binary.is_file() or not os.access(binary, os.X_OK):
            raise ContractError('custom_executable_requires_existing_absolute_path_or_python')
        if type(row['cwd']) is not str:
            raise ContractError('invalid_custom_cwd')
        cwd = (path.parent / row['cwd']).resolve()
        if not cwd.is_dir():
            raise ContractError('custom_working_directory_missing')
        result.append(dict(row, command=command, cwd=str(cwd)))
    return result


class JsonLineAdapter(BaseAdapter):
    def __init__(self, config, *, registration, manifest, manifest_sha):
        self.config = config
        self.registration = registration
        self.manifest = Path(manifest)
        self.manifest_sha = manifest_sha
        self.process = None
        self.requests = queue.Queue(1)
        self.responses = queue.Queue(1)
        self.failed = False
        self.descriptor = descriptor(registration['adapter_id'], registration['kind'],
            registration['label'], registration['required_sensors'])

    def reset(self, context):
        super().reset(context)
        if digest(self.manifest) != self.manifest_sha:
            raise ContractError('custom_manifest_changed_after_registration')
        if self.process is not None or self.failed:
            raise ContractError('custom_instance_cannot_restart')
        env = dict(os.environ)
        for key in ('PYTHONPATH', 'PYTHONHOME'):
            env.pop(key, None)
        self.process = subprocess.Popen(self.registration['command'], cwd=self.registration['cwd'],
            env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, bufsize=0, shell=False)
        child = self.process
        def io_loop():
            try:
                while True:
                    raw = self.requests.get()
                    if raw is None:
                        return
                    # A dedicated thread owns blocking pipe operations; the caller
                    # enforces a deadline and kills this owned child on timeout.
                    view = memoryview(raw)
                    while view:
                        size = child.stdin.write(view)
                        if not size:
                            raise BrokenPipeError('Adapter input closed')
                        view = view[size:]
                    child.stdin.flush()
                    row = child.stdout.readline(MAX_RESPONSE + 1)
                    if not row.endswith(b'\n') or len(row) > MAX_RESPONSE:
                        raise ContractError('custom_response_missing_or_oversized')
                    def reject(_):
                        raise ContractError('custom_nonfinite_json')
                    def pairs(rows):
                        value = {}
                        for key, item in rows:
                            if key in value:
                                raise ContractError('custom_duplicate_json_key')
                            value[key] = item
                        return value
                    value = json.loads(row, parse_constant=reject, object_pairs_hook=pairs)
                    self.responses.put_nowait(value)
            except Exception as exc:
                try:
                    self.responses.put_nowait(exc)
                except queue.Full:
                    pass
        self.thread = threading.Thread(target=io_loop, daemon=True, name='json-adapter-io')
        self.thread.start()
        self._exchange(dict(op='reset', context=context, config=self.config), timeout=2.)

    def _exchange(self, packet, *, timeout):
        if self.failed or self.process is None or timeout <= 0:
            raise ContractError('custom_adapter_unavailable_or_expired')
        deadline = time.monotonic() + timeout
        if packet['op'] == 'act':
            deadline = min(deadline, packet['observation']['wall_deadline'])
        raw = (json.dumps(dict(schema=SCHEMA, **packet), allow_nan=False, separators=(',', ':')) + '\n').encode()
        if len(raw) > MAX_REQUEST:
            raise ContractError('custom_request_oversized')
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('custom_deadline_expired_during_serialization')
            self.requests.put_nowait(raw)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('custom_deadline_expired_before_response_wait')
            result = self.responses.get(timeout=remaining)
            if isinstance(result, Exception):
                raise result
            exact(result, ('schema', 'op', 'ok', 'action') if packet['op'] == 'act' else ('schema', 'op', 'ok'), 'custom_response')
            if result['schema'] != SCHEMA or result['op'] != packet['op'] or result['ok'] is not True:
                raise ContractError('custom_response_identity_or_status')
            return result
        except Exception:
            self.failed = True
            self.close()
            raise

    def act(self, observation):
        o = self.checked(observation)
        require_sensors(o, self.registration['required_sensors'])
        response = self._exchange(dict(op='act', observation=o),
                                  timeout=min(.25, o['wall_deadline'] - time.monotonic()))
        return validate_action(response['action'], o, self.descriptor)

    def close(self):
        child = self.process
        if child is not None:
            if child.poll() is None:
                try:
                    child.kill()
                except ProcessLookupError:
                    pass
            try:
                child.wait(timeout=1.)
            finally:
                for stream in (child.stdin, child.stdout):
                    if stream:
                        stream.close()
        try:
            self.requests.put_nowait(None)
        except queue.Full:
            pass
        self.process = None


def register_json_adapters(registry, path):
    path = Path(path).absolute()
    manifest_sha = digest(path)
    for row in load_registrations(path):
        def factory(config, row=row):
            return JsonLineAdapter(config, registration=row, manifest=path, manifest_sha=manifest_sha)
        d = descriptor(row['adapter_id'], row['kind'], row['label'], row['required_sensors'],
                       local_registration=True, process_isolation='not_a_security_sandbox')
        registry.register(d, factory)
