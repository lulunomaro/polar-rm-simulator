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
from .profile import digest, read_json_snapshot
from .json_owned_process import OwnedJsonProcess
from ..platform_v2.adapters import BaseAdapter, descriptor, require_sensors
from ..platform_v2.contracts import ContractError, exact, validate_action

SCHEMA = 'polar.sim.adapter.jsonl.v1'
MAX_REQUEST = 12 * 1024 * 1024
MAX_RESPONSE = 64 * 1024


def load_registrations(path, *, with_digest=False):
    path = Path(path).absolute()
    value, manifest_sha = read_json_snapshot(path)
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
    return (result,manifest_sha) if with_digest else result


class JsonLineAdapter(BaseAdapter):
    def __init__(self, config, *, registration, manifest, manifest_sha, clock=time.perf_counter):
        if not callable(clock):raise ContractError('invalid_custom_clock')
        # This host clock must match PlatformRuntime's deadline domain. On
        # Windows Python3.12, monotonic() is not the QPC perf_counter clock.
        self.clock = clock
        self.config = config
        self.registration = registration
        self.manifest = Path(manifest)
        self.manifest_sha = manifest_sha
        self.process = None
        self.requests = queue.Queue(1)
        self.responses = queue.Queue(1)
        self.failed = False
        self._close_lock = threading.Lock()
        self._cancelled = threading.Event()
        self._owned_process = None
        self.shutdown_status = None
        self._close_error = None
        self._launch_cleanup_status = None
        self.descriptor = descriptor(registration['adapter_id'], registration['kind'],
            registration['label'], registration['required_sensors'])

    def reset(self, context):
        super().reset(context)
        self._open_owned_process()
        self._exchange(dict(op='reset', context=context, config=self.config), timeout=2.)

    def _start_owned_process(self, env):
        """Reviewed transports replace ownership, never deadline enforcement."""
        return OwnedJsonProcess(self.registration['command'], cwd=self.registration['cwd'],
            env=env, stop_event=self._cancelled)

    def _open_owned_process(self):
        if digest(self.manifest) != self.manifest_sha:
            raise ContractError('custom_manifest_changed_after_registration')
        if self.process is not None or self.failed:
            raise ContractError('custom_instance_cannot_restart')
        env = dict(os.environ)
        for key in ('PYTHONPATH', 'PYTHONHOME'):
            env.pop(key, None)
        thread_start_error = None
        with self._close_lock:
            if self.failed or self._cancelled.is_set():raise ContractError('custom_instance_cannot_restart')
            try:
                self._owned_process = self._start_owned_process(env)
            except BaseException as exc:
                self._launch_cleanup_status=getattr(exc,'cleanup_status',None)
                self.failed=True;self._cancelled.set()
                raise
            self.process = self._owned_process.child
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
            try:self.thread.start()
            except Exception as exc:thread_start_error=exc
        if thread_start_error is not None:
            self.close()
            raise thread_start_error

    def _exchange(self, packet, *, timeout):
        if self.failed or self._cancelled.is_set() or self.process is None or timeout <= 0:
            raise ContractError('custom_adapter_unavailable_or_expired')
        deadline = self.clock() + timeout
        if packet['op'] == 'act':
            deadline = min(deadline, packet['observation']['wall_deadline'])
        raw = (json.dumps(dict(schema=SCHEMA, **packet), allow_nan=False, separators=(',', ':')) + '\n').encode()
        if len(raw) > MAX_REQUEST:
            raise ContractError('custom_request_oversized')
        try:
            remaining = deadline - self.clock()
            if self._cancelled.is_set():raise RuntimeError('custom_adapter_cancelled')
            if remaining <= 0:
                raise TimeoutError('custom_deadline_expired_during_serialization')
            self.requests.put_nowait(raw)
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise TimeoutError('custom_deadline_expired_before_response_wait')
            result = self.responses.get(timeout=remaining)
            if self._cancelled.is_set():raise RuntimeError('custom_adapter_cancelled')
            if self.clock() >= deadline:
                raise TimeoutError('custom_response_after_original_deadline')
            if isinstance(result, Exception):
                raise result
            self._validate_response(result, packet)
            return result
        except Exception:
            self.failed = True
            self.close()
            raise

    def _validate_response(self, result, packet):
        """Default wire shape; reviewed local adapters may add typed no-action."""
        exact(result, ('schema', 'op', 'ok', 'action') if packet['op'] == 'act' else ('schema', 'op', 'ok'), 'custom_response')
        if result['schema'] != SCHEMA or result['op'] != packet['op'] or result['ok'] is not True:
            raise ContractError('custom_response_identity_or_status')

    def act(self, observation):
        o = self.checked(observation)
        require_sensors(o, self.registration['required_sensors'])
        response = self._exchange(dict(op='act', observation=o),
                                  timeout=min(.25, o['wall_deadline'] - self.clock()))
        return validate_action(response['action'], o, self.descriptor)

    def cancel(self):
        """Reviewed nonblocking request; lifecycle worker owns close/reaping."""
        self._cancelled.set()
        try:self.responses.put_nowait(RuntimeError('custom_adapter_cancelled'))
        except queue.Full:pass

    def close(self):
        # One resource deadline covers ownership cleanup, leader and IO join.
        # It cannot replace the original reset or action deadline.
        self._cancelled.set(); self.failed = True
        deadline = time.perf_counter() + 1.5
        if not self._close_lock.acquire(timeout=max(0,deadline-time.perf_counter())):
            self._close_error = 'Custom adapter launch still owns lifecycle lock'
            self.shutdown_status = dict(clean=False, errors=[self._close_error], io_thread_stopped=False)
            raise RuntimeError(self._close_error)
        errors=[];proof=None
        try:
            self.failed = True
            child = self.process
            self.process = None
            try:
                if self._owned_process is not None:
                    proof=self._owned_process.cleanup(deadline)
                    if not proof.get('clean') or not proof.get('reaped') or not proof.get('group_empty'):
                        errors.append('Custom adapter owned process cleanup unproved')
                elif self._launch_cleanup_status is not None:
                    proof=self._launch_cleanup_status
                    if not proof.get('clean') or not proof.get('group_empty') or not (proof.get('reaped') or proof.get('not_spawned')):
                        errors.append('Custom adapter failed launch cleanup unproved')
            except Exception as exc:
                errors.append(type(exc).__name__+':'+str(exc))
            finally:
                if child is not None:
                    for stream in (child.stdin,child.stdout):
                        try:
                            if stream is not None:stream.close()
                        except Exception as exc:errors.append('pipe_close:'+type(exc).__name__)
                if self._owned_process is not None:
                    try:self._owned_process.release_handles()
                    except Exception as exc:errors.append('owned_handle_close:'+type(exc).__name__)
                try:
                    self.requests.put_nowait(None)
                except queue.Full:
                    pass
                thread=getattr(self,'thread',None)
                if thread is not None and thread is not threading.current_thread():
                    try:
                        if thread.ident is not None:thread.join(max(0,deadline-time.perf_counter()))
                    except Exception as exc:errors.append('io_thread_join:'+type(exc).__name__)
                    if thread.is_alive():
                        errors.append('Custom adapter IO thread failed to stop')
                if self._close_error:errors.append(self._close_error)
                self.shutdown_status=dict(clean=not errors, errors=errors, ownership=proof,
                    io_thread_stopped=thread is None or not thread.is_alive(),
                    resource_budget_s=1.5)
                self._close_error='; '.join(errors) if errors else None
        finally:self._close_lock.release()
        if errors:raise RuntimeError(self._close_error)


def register_json_adapters(registry, path, *, clock=time.perf_counter):
    path = Path(path).absolute()
    rows,manifest_sha = load_registrations(path,with_digest=True)
    for row in rows:
        def factory(config, row=row):
            return JsonLineAdapter(config, registration=row, manifest=path, manifest_sha=manifest_sha,clock=clock)
        d = descriptor(row['adapter_id'], row['kind'], row['label'], row['required_sensors'],
                       local_registration=True, process_isolation='not_a_security_sandbox')
        registry.register(d, factory)
