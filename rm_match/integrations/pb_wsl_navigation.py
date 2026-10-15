"""Opt-in Windows-host / owned WSL Humble navigation session.

Only the host clock authorizes control. Linux-local waits never reinterpret the
original observation's wall deadline. Process isolation is not a sandbox.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import uuid

from ..deployment.wsl_profile import _host_path, host_to_linux_path

SCHEMA = 'polar.pb.wsl-session.v1'
SPEC_SCHEMA = 'polar.pb.wsl-session-spec.v1'
CLEANUP_SCHEMA = 'polar.pb.wsl-session-cleanup.v1'
JSONL_SCHEMA = 'polar.sim.adapter.jsonl.v1'
MAX_LINE = 64 * 1024
MAX_REQUEST = 12 * 1024 * 1024
CHUNK = 64 * 1024
WSL_EXECUTABLE = Path('C:/Windows/System32/wsl.exe')
PHASE_CAPACITY = 4096
MAX_PHASE_ARCHIVE = 2 * 1024 * 1024
SOURCE_FILES = (
    'rm_match/integrations/pb_wsl_navigation.py',
    'rm_match/integrations/pb_wsl_navigation_worker.py',
    'tools/pb_navigation_stack.py',
    'tools/qa_pb_navigation_sil.py',
    'rm_match/integrations/pb_navigation_bridge.py',
    'rm_match/integrations/pb_navigation_transport.py',
    'rm_match/integrations/pb_navigation_phases.py',
    'rm_match/integrations/ros2_bridge.py',
    'rm_match/integrations/pb_request_context.hpp',
    'rm_match/integrations/pb_controller_context.hpp',
    'rm_match/integrations/pb_goal_controller_context.hpp',
    'tools/prepare_nav2_goal_controller_overlay.py',
    'rm_match/platform_v2/contracts.py',
    'rm_match/platform_v2/navigation_contracts.py',
    'rm_match/deployment/profile.py',
    'rm_match/deployment/wsl_profile.py',
)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _exact(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(label)


def _json(raw):
    def constant(_):
        raise ValueError('nonfinite_session_json')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate_session_json_key')
            result[key] = value
        return result
    def floating(text):
        result = float(text)
        if not math.isfinite(result):
            raise ValueError('nonfinite_session_json')
        return result
    return json.loads(raw, parse_constant=constant, parse_float=floating, object_pairs_hook=pairs)


def _encode(value, limit):
    raw = (json.dumps(value, allow_nan=False, separators=(',', ':')) + '\n').encode('utf8')
    if len(raw) > limit:
        raise ValueError('session_packet_oversized')
    return raw


def _valid_timeout(value):
    try:return type(value) in (int,float) and math.isfinite(value) and value>0
    except OverflowError:return False


def _ref(value, root, out):
    _exact(value, ('path', 'sha256'), 'session_reference_fields')
    if type(value['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', value['sha256']):
        raise ValueError('session_reference_sha256')
    if type(value['path']) is not str:
        raise ValueError('session_reference_path')
    path = _host_path(value['path'])
    linux = host_to_linux_path(path, repo_root=root, shared_out=out, must_exist=True)
    if not path.is_file() or _sha(path) != value['sha256']:
        raise ValueError('session_reference_changed')
    return path, dict(path=linux, sha256=value['sha256'])


class WslNavigationBusy(RuntimeError):
    """Valid monitor request declined without modifying a live transaction."""


class WslNavigationSession:
    """Single generation, single transaction; no automatic restart or fallback.

    exchange/reset/act return the original JSONL reply. status returns a worker
    report, never an action. prepare performs configuration only, before physics.
    """
    def __init__(self, root, out, config_ref, environment_ref, *, distribution='Ubuntu-22.04',
                 clock=time.perf_counter, diagnostics=False, relative_test_goal=False):
        if distribution != 'Ubuntu-22.04' or type(distribution) is not str:
            raise ValueError('session_distribution_not_reviewed')
        if not callable(clock) or type(diagnostics) is not bool or type(relative_test_goal) is not bool:
            raise ValueError('session_settings')
        self.root = _host_path(root)
        self.out = _host_path(out)
        if not self.root.is_dir() or not self.out.is_relative_to(self.root / 'artifacts') or self.out.exists():
            raise ValueError('session_requires_fresh_owned_output')
        self.clock = clock
        self.distribution = distribution
        self.run_uuid = uuid.uuid4().hex
        self.namespace = '/polar_sil_' + self.run_uuid + '/red_sentry'
        self.config_path, config = _ref(config_ref, self.root, self.out)
        self.environment_path, environment = _ref(environment_ref, self.root, self.out)
        self.source_sha256 = {}
        for relative in SOURCE_FILES:
            selected = _host_path(self.root / relative)
            if not selected.is_file():
                raise ValueError('session_source_missing:' + relative)
            self.source_sha256[relative] = _sha(selected)
        self.spec = dict(schema=SPEC_SCHEMA, run_uuid=self.run_uuid, namespace=self.namespace,
            root_linux=self._map(self.root), out_linux=self._map(self.out), config_ref=config,
            environment_ref=environment, source_sha256=dict(self.source_sha256),
            diagnostics=diagnostics, relative_test_goal=relative_test_goal,
            expected_generation=dict(robot_id='red_sentry', episode=0, binding_epoch=1))
        self.out.mkdir(parents=True)
        self.spec_path = self.out / 'SESSION_SPEC.json'
        self.spec_path.write_bytes(_encode(self.spec, MAX_LINE))
        self.spec_sha256 = _sha(self.spec_path)
        self.process = None
        self.ready = None
        self.cleanup = None
        self._resource_cleanup = None
        self.stderr = None
        self._incoming = queue.Queue(1)
        self._outgoing = queue.Queue(1)
        self._stop = threading.Event()
        self._broken = threading.Event()
        self._transaction = threading.Lock()
        self._close_lock = threading.Lock()
        self._threads = []
        self._serial = 0
        self._reset = False
        self._closed = False
        self._close_failure = None
        self._stop_write_error = None
        self._stop_written = threading.Event()
        self.phase_rows = []
        self.phase_total = 0
        self.phase_dropped = 0
        self._phase_lock = threading.Lock()
        self._ledger_ready = threading.Event()
        self._ledger_error = None
        self._ledger_payload = None
        self._ledger_deadline = None
        self._ledger_writer = None
        self._stop_writer = threading.Thread(target=self._persist_stop, daemon=True, name='pb-wsl-stop-writer')
        self._threads.append(self._stop_writer)
        self._stop_writer.start()
        if diagnostics:
            self._ledger_writer = threading.Thread(target=self._persist_phases, daemon=True, name='pb-wsl-phase-writer')
            self._threads.append(self._ledger_writer)
            self._ledger_writer.start()

    def _map(self, path):
        return host_to_linux_path(path, repo_root=self.root, shared_out=self.out)

    def _now(self):
        result = self.clock()
        if type(result) not in (int, float) or not math.isfinite(result):
            raise ValueError('invalid_host_session_clock')
        return result

    def _verify(self):
        for path, expected in ((self.config_path, self.spec['config_ref']['sha256']),
                               (self.environment_path, self.spec['environment_ref']['sha256']),
                               (self.spec_path, self.spec_sha256)):
            _host_path(path)
            if not path.is_file() or _sha(path) != expected:
                raise ValueError('session_reference_changed')
        for relative, expected in self.source_sha256.items():
            selected = _host_path(self.root / relative)
            if not selected.is_file() or _sha(selected) != expected:
                raise ValueError('session_source_changed:' + relative)

    def _phase(self, phase, serial=None, op=None):
        # Bounded scalar diagnostics in memory; no hot-path filesystem access.
        if not self.spec['diagnostics']:return
        with self._phase_lock:
            self.phase_total += 1
            if len(self.phase_rows) < PHASE_CAPACITY:
                self.phase_rows.append(dict(phase=phase, id=serial, op=op,
                    local_wall=time.perf_counter(), clock='windows_local_perf_counter'))
            else:self.phase_dropped += 1

    def phase_snapshot(self):
        with self._phase_lock:
            return dict(rows=copy.deepcopy(self.phase_rows), total=self.phase_total,
                dropped=self.phase_dropped, capacity=PHASE_CAPACITY,
                complete=self.phase_dropped == 0, clock='windows_local_perf_counter')

    def _write_phases(self, payload):
        _host_path(self.out)
        path=self.out/'HOST_RPC_PHASES.json'
        if path.exists() or path.is_symlink():raise ValueError('session_phase_archive_exists')
        temporary=self.out/'HOST_RPC_PHASES.tmp'
        with temporary.open('xb') as stream:stream.write(payload)
        os.replace(temporary,path)

    def _persist_phases(self):
        self._ledger_ready.wait()
        try:
            if self._ledger_payload is None:raise TimeoutError('session_phase_archive_budget_exhausted')
            if time.perf_counter() >= self._ledger_deadline:raise TimeoutError('session_phase_archive_budget_exhausted')
            payload=_encode(self._ledger_payload, MAX_PHASE_ARCHIVE)
            if time.perf_counter() >= self._ledger_deadline:raise TimeoutError('session_phase_archive_budget_exhausted')
            self._write_phases(payload)
            if time.perf_counter() >= self._ledger_deadline:raise TimeoutError('session_phase_archive_after_deadline')
        except BaseException as error:self._ledger_error=type(error).__name__+':'+str(error)

    def _read(self, child):
        buffer = bytearray()
        try:
            while not self._stop.is_set():
                raw = child.stdout.read(CHUNK)
                if not raw:
                    raise EOFError('session_supervisor_stdout_closed')
                buffer.extend(raw)
                while b'\n' in buffer:
                    line, _, tail = buffer.partition(b'\n')
                    buffer = bytearray(tail)
                    if len(line) + 1 > MAX_LINE:
                        raise ValueError('session_reply_oversized')
                    value = _json(line)
                    self._phase('stdout_line_received', value.get('id'), value.get('op'))
                    self._incoming.put_nowait(value)
                if len(buffer) + 1 > MAX_LINE:
                    raise ValueError('session_reply_oversized')
        except BaseException:
            self._broken.set()
            self.request_stop()

    def _write(self, child):
        try:
            while not self._stop.is_set():
                try:
                    raw, deadline, serial, op = self._outgoing.get(timeout=.01)
                except queue.Empty:
                    continue
                if type(raw) is not bytes or len(raw) > MAX_REQUEST:
                    raise ValueError('session_write_packet')
                view = memoryview(raw)
                self._phase('stdin_write_begin', serial, op)
                while view:
                    if self._stop.is_set() or self._now() >= deadline:
                        raise TimeoutError('session_write_deadline')
                    size = child.stdin.write(view)
                    if type(size) is not int or size <= 0 or size > len(view):
                        raise BrokenPipeError('session_short_write_failed')
                    view = view[size:]
                child.stdin.flush()
                self._phase('stdin_write_end', serial, op)
        except BaseException:
            self._broken.set()
            self.request_stop()

    def _receive(self, deadline):
        while True:
            remaining = deadline - self._now()
            if remaining <= 0:
                raise TimeoutError('session_original_deadline_expired')
            if self._broken.is_set() or self._stop.is_set():
                raise RuntimeError('session_io_failed_or_cancelled')
            if self.process is None or self.process.poll() is not None:
                raise RuntimeError('session_supervisor_exited')
            try:
                value = self._incoming.get(timeout=min(.01, remaining))
            except queue.Empty:
                continue
            if self._now() >= deadline:
                raise TimeoutError('session_reply_after_original_deadline')
            return value

    def _ready(self, value):
        _exact(value, ('schema', 'event', 'run_uuid', 'namespace', 'config_sha256',
            'environment_sha256', 'supervisor_pid', 'start_ticks', 'boot_id', 'state'), 'session_ready_fields')
        for key, expected in dict(schema=SCHEMA, event='ready', run_uuid=self.run_uuid,
                namespace=self.namespace, config_sha256=self.spec['config_ref']['sha256'],
                environment_sha256=self.spec['environment_ref']['sha256'], state='CONFIGURED').items():
            if type(value[key]) is not str or value[key] != expected:
                raise ValueError('session_ready_identity:' + key)
        if (type(value['supervisor_pid']) is not int or value['supervisor_pid'] <= 0
            or type(value['start_ticks']) is not int or value['start_ticks'] < 0
            or type(value['boot_id']) is not str
            or not re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', value['boot_id'])):
            raise ValueError('session_linux_process_identity')
        return copy.deepcopy(value)

    def prepare(self):
        if sys.platform != 'win32':
            raise RuntimeError('session_requires_windows_host')
        if not self._transaction.acquire(blocking=False):
            self.request_stop()
            raise RuntimeError('session_concurrent_transaction')
        deadline = self._now() + 10.
        try:
            if self._closed or self._stop.is_set() or self.process is not None:
                raise RuntimeError('session_prepare_single_use')
            self._verify()
            executable = _host_path(WSL_EXECUTABLE)
            if not executable.is_file():
                raise ValueError('session_wsl_executable_missing')
            command = [str(executable), '-d', self.distribution, '--cd', self._map(self.root),
                '--', '/usr/bin/python3', '-u', self._map(self.root / 'rm_match/integrations/pb_wsl_navigation_worker.py'),
                '--spec', self._map(self.spec_path), '--spec-sha256', self.spec_sha256]
            if len(command) > 32 or self._now() >= deadline:
                raise TimeoutError('session_prepare_budget_exhausted')
            self.stderr = (self.out / 'supervisor_stderr.log').open('wb')
            self.process = subprocess.Popen(command, cwd=self.root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self.stderr, bufsize=0, shell=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            for method in (self._read, self._write):
                thread = threading.Thread(target=method, args=(self.process,), daemon=True,
                    name='pb-wsl-' + method.__name__)
                thread.start()
                self._threads.append(thread)
            self.ready = self._ready(self._receive(deadline))
            ready = copy.deepcopy(self.ready)
            if self._now() >= deadline:
                raise TimeoutError('session_ready_validation_deadline')
            return ready
        except BaseException:
            self.request_stop()
            raise
        finally:
            self._transaction.release()

    def exchange(self, packet, *, timeout=None):
        if not self._transaction.acquire(blocking=False):
            # Exempt only a structurally valid monitoring request. Malformed
            # status/control/reset packets retain the original fail-closed path.
            if (type(packet) is dict and type(packet.get('op')) is str and packet['op']=='status'
                and set(packet) in ({'op'}, {'schema','op'})
                and ('schema' not in packet or (type(packet['schema']) is str and packet['schema']==JSONL_SCHEMA))
                and (timeout is None or _valid_timeout(timeout))):
                raise WslNavigationBusy('session_status_busy')
            self.request_stop()
            raise RuntimeError('session_concurrent_transaction')
        try:
            started = self._now()
            diagnostic_op=(packet.get('op') if type(packet) is dict and type(packet.get('op')) is str
                and packet['op'] in ('reset','act','status') else None)
            self._phase('exchange_enter',self._serial+1,diagnostic_op)
            if self.ready is None or self._closed or self._stop.is_set():
                raise RuntimeError('session_not_ready')
            if type(packet) is not dict or packet.get('schema', JSONL_SCHEMA) != JSONL_SCHEMA:
                raise ValueError('session_packet_schema')
            # The adapter's existing _exchange supplies packet WITHOUT schema.
            packet = copy.deepcopy(packet)
            packet.setdefault('schema', JSONL_SCHEMA)
            op = packet.get('op')
            if op == 'reset':
                _exact(packet, ('schema', 'op', 'context', 'config'), 'session_reset_fields')
                _exact(packet['context'], self.spec['expected_generation'], 'session_reset_context')
                if self._reset or packet['context'] != self.spec['expected_generation'] or any(
                        type(packet['context'].get(k)) is not type(v) for k, v in self.spec['expected_generation'].items()):
                    raise ValueError('session_reset_generation')
                _exact(packet['config'], (), 'session_reset_config')
                cap = 2.
            elif op == 'act':
                _exact(packet, ('schema', 'op', 'observation'), 'session_act_fields')
                if not self._reset:
                    raise ValueError('session_reset_required')
                cap = .15
            elif op == 'status':
                _exact(packet, ('schema', 'op'), 'session_status_fields')
                cap = .15
            else:
                raise ValueError('session_op')
            if timeout is not None:
                if not _valid_timeout(timeout):
                    raise ValueError('session_timeout')
                cap = min(cap, timeout)
            deadline = started + cap
            if op == 'reset':
                self._verify()
            if op == 'act':
                from ..platform_v2.navigation_contracts import validate_navigation_observation
                o = validate_navigation_observation(packet['observation'])
                if any(type(o[k]) is not type(v) or o[k] != v for k, v in self.spec['expected_generation'].items()):
                    raise ValueError('session_act_generation')
                deadline = min(deadline, o['wall_deadline'])
            if self._now() >= deadline:
                raise TimeoutError('session_original_deadline_expired')
            self._phase('packet_validated',self._serial+1,op)
            self._serial += 1
            serial = self._serial
            self._phase('encode_begin', serial, op)
            raw = _encode(dict(schema=SCHEMA, op=op, id=serial, run_uuid=self.run_uuid, packet=packet), MAX_REQUEST)
            if self._now() >= deadline:
                raise TimeoutError('session_serialization_deadline')
            self._phase('encode_end', serial, op)
            self._outgoing.put_nowait((raw, deadline, serial, op))
            value = self._receive(deadline)
            self._phase('caller_received', serial, op)
            _exact(value, ('schema', 'op', 'id', 'run_uuid', 'result'), 'session_reply_fields')
            if (type(value['id']) is not int or value['id'] != serial or type(value['op']) is not str
                or value['op'] != op or type(value['schema']) is not str or value['schema'] != SCHEMA
                or type(value['run_uuid']) is not str or value['run_uuid'] != self.run_uuid):
                raise ValueError('session_transaction_identity')
            result = value['result']
            if type(result) is not dict or (op == 'status' and 'action' in result):
                raise ValueError('session_result_shape')
            if op == 'reset':
                _exact(result, ('schema', 'op', 'ok'), 'session_reset_reply')
                if result != dict(schema=JSONL_SCHEMA, op='reset', ok=True) or result['ok'] is not True:
                    raise ValueError('session_reset_reply')
                self._reset = True
            elif op == 'act':
                from ..platform_v2.contracts import IDENTITY, validate_action
                from ..platform_v2.navigation_contracts import validate_navigation_status
                if ('action' in result) == ('status' in result):
                    raise ValueError('session_act_reply_shape')
                field = 'action' if 'action' in result else 'status'
                _exact(result, ('schema', 'op', 'ok', field), 'session_act_reply_fields')
                if (type(result['schema']) is not str or result['schema'] != JSONL_SCHEMA
                    or type(result['op']) is not str or result['op'] != 'act' or result['ok'] is not True):
                    raise ValueError('session_act_reply_identity')
                if field == 'status':
                    validate_navigation_status(result[field], o)
                else:
                    action = validate_action(result[field], o, dict(kind='navigation', output_modes=['velocity_body']))
                    if any(type(action[k]) is not type(o[k]) or action[k] != o[k] for k in IDENTITY):
                        raise ValueError('session_act_reply_source_identity')
            self._phase('result_validated',serial,op)
            result = copy.deepcopy(result)
            self._phase('return_copy_end',serial,op)
            if self._now() >= deadline:
                raise TimeoutError('session_result_validation_deadline')
            return result
        except BaseException:
            self.request_stop()
            raise
        finally:
            self._transaction.release()

    def reset(self, context, config=None):
        return self.exchange(dict(op='reset', context=context, config={} if config is None else config))

    def act(self, observation):
        return self.exchange(dict(op='act', observation=observation))

    def status(self):
        return self.exchange(dict(op='status'))

    def request_stop(self):
        """No file or pipe I/O; one pre-existing owned thread publishes STOP."""
        self._stop.set()

    def _write_stop(self):
        _host_path(self.out)
        path = self.out / 'STOP'
        temporary = self.out / 'STOP.tmp'
        # Atomic publication prevents Linux from parsing an unfinished signal.
        # Existing aliases/files are rejected, never opened or overwritten.
        if path.exists() or path.is_symlink():
            raise ValueError('session_stop_file_already_exists')
        with temporary.open('xb') as stream:
            stream.write(_encode(dict(run_uuid=self.run_uuid,
                config_sha256=self.spec['config_ref']['sha256']), MAX_LINE))
        os.replace(temporary, path)

    def _persist_stop(self):
        self._stop.wait()
        try:
            self._write_stop()
        except BaseException as error:
            self._stop_write_error = type(error).__name__ + ':' + str(error)
            self._broken.set()
        finally:
            self._stop_written.set()

    def _check_cleanup(self, value):
        _exact(value, ('schema', 'run_uuid', 'config_sha256', 'supervisor_pid', 'start_ticks',
            'boot_id', 'clean', 'owned_groups', 'errors'), 'session_cleanup_fields')
        for k, expected in dict(schema=CLEANUP_SCHEMA, run_uuid=self.run_uuid,
                config_sha256=self.spec['config_ref']['sha256']).items():
            if type(value[k]) is not str or value[k] != expected:
                raise ValueError('session_cleanup_identity')
        identity = self.ready
        if identity is None:
            # Caller has already reaped this WSL launcher before this read.
            # Birth identity proves resources only; it never makes us ready.
            path = _host_path(self.out/'WORKER_STARTED.json')
            with path.open('rb') as stream:raw = stream.read(MAX_LINE+1)
            if len(raw)>MAX_LINE:raise ValueError('session_worker_marker_oversized')
            identity=_json(raw)
            _exact(identity, ('run_uuid','config_sha256','supervisor_pid','start_ticks','boot_id'), 'session_worker_marker_fields')
            if (type(identity['run_uuid']) is not str or identity['run_uuid']!=self.run_uuid
                or type(identity['config_sha256']) is not str or identity['config_sha256']!=self.spec['config_ref']['sha256']
                or type(identity['supervisor_pid']) is not int or identity['supervisor_pid']<=0
                or type(identity['start_ticks']) is not int or identity['start_ticks']<0
                or type(identity['boot_id']) is not str
                or not re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',identity['boot_id'])):
                raise ValueError('session_worker_marker_identity')
        if any(type(value[k]) is not type(identity[k]) or value[k] != identity[k]
                for k in ('supervisor_pid', 'start_ticks', 'boot_id')):
            raise ValueError('session_cleanup_process_identity')
        if (value['clean'] is not True or type(value['owned_groups']) is not list or value['owned_groups']
            or type(value['errors']) is not list or value['errors']):
            raise RuntimeError('session_linux_cleanup_incomplete')
        return copy.deepcopy(value)

    def close(self):
        if not self._close_lock.acquire(blocking=False):
            raise RuntimeError('session_close_in_progress')
        if self._closed:
            self._close_lock.release()
            if self._close_failure:raise RuntimeError(self._close_failure)
            return
        errors = []
        deadline = time.perf_counter() + 1.3
        resource_cleanup = None
        try:
            self.request_stop()
            child = self.process
            if child is not None:
                path = self.out / 'CLEANUP.json'
                reaped=False
                try:
                    code = child.wait(timeout=max(0., deadline - time.perf_counter()))
                    reaped=True
                    if code != 0:
                        errors.append('session_supervisor_exit_nonzero')
                except subprocess.TimeoutExpired:
                    errors.append('session_supervisor_not_reaped')
                if reaped and path.exists():
                    try:
                        _host_path(path)
                        with path.open('rb') as stream:raw = stream.read(MAX_LINE+1)
                        if len(raw)>MAX_LINE:raise ValueError('session_cleanup_oversized')
                        resource_cleanup=self._check_cleanup(_json(raw))
                    except BaseException as exc:errors.append(type(exc).__name__+':'+str(exc))
                if resource_cleanup is None:
                    errors.append('session_linux_cleanup_unproved')
            elif self.ready is not None:
                errors.append('session_supervisor_missing')
        except BaseException as error:
            errors.append('session_close_error:'+type(error).__name__+':'+str(error))
        finally:
            # Never taskkill a launcher and call that Linux cleanup. Unreaped
            # supervisors remain visible to the caller via process and failure.
            for thread in self._threads:
                if thread is not threading.current_thread() and thread is not self._ledger_writer:
                    thread.join(timeout=max(0., deadline - time.perf_counter()))
                    if thread.is_alive():
                        errors.append('session_stop_writer_not_joined' if thread is self._stop_writer else 'session_io_thread_not_joined')
            if self._stop_write_error:
                errors.append('session_stop_write_failed:' + self._stop_write_error)
            child = self.process
            if child is not None:
                for stream in (child.stdin, child.stdout):
                    if stream is not None:
                        try:stream.close()
                        except OSError:errors.append('session_pipe_close_failed')
            if self.stderr is not None:
                try:self.stderr.close()
                except OSError:errors.append('session_stderr_close_failed')
            if self._ledger_writer is not None:
                try:
                    if time.perf_counter() < deadline:
                        self._ledger_payload = self.phase_snapshot()
                    self._ledger_deadline = deadline
                    self._ledger_ready.set()
                    self._ledger_writer.join(timeout=max(0., deadline-time.perf_counter()))
                    if self._ledger_writer.is_alive():errors.append('session_phase_writer_not_joined')
                    if self._ledger_error:errors.append('session_phase_archive_failed:'+self._ledger_error)
                except BaseException as error:
                    errors.append('session_phase_archive_failed:'+type(error).__name__+':'+str(error))
                    self._ledger_ready.set()
                    self._ledger_writer.join(timeout=max(0.,deadline-time.perf_counter()))
            self._resource_cleanup = resource_cleanup
            self.cleanup = resource_cleanup if not errors else None
            self._close_failure = ';'.join(errors) if errors else None
            self._closed = True
            self._close_lock.release()
        if errors:
            raise RuntimeError(self._close_failure)
