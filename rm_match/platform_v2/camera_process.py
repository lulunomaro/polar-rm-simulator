"""Opt-in owned render process; original exposure admission stays in CameraProvider.

One bounded request in flight. The trusted renderer receives a private model and
integration-state snapshot, never an algorithm connection. Only rendered RGB
returns; no pickles, network endpoints, configurable commands or truth DTOs.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
import queue
import struct
import sys
import tempfile
import threading
import time

MAX_HEADER = 16 * 1024
MAX_PAYLOAD = 64 * 1024 * 1024
SCHEMA = 'polar.camera.render-process.v1'


def _exact(stream, size):
    chunks = bytearray(size)
    view = memoryview(chunks)
    offset = 0
    while offset < size:
        count = stream.readinto(view[offset:])
        if not count:
            raise EOFError('render process pipe closed')
        offset += count
    return chunks


def _read(stream):
    header_size, size = struct.unpack('!II', _exact(stream, 8))
    if not 0 < header_size <= MAX_HEADER or size > MAX_PAYLOAD:
        raise ValueError('render process message exceeds bounds')
    header = json.loads(_exact(stream, header_size))
    if type(header) is not dict or header.get('schema') != SCHEMA:
        raise ValueError('render process schema mismatch')
    return header, _exact(stream, size)


def _write(stream, header, payload=b''):
    data = json.dumps(dict(header, schema=SCHEMA), allow_nan=False, separators=(',', ':')).encode()
    if not 0 < len(data) <= MAX_HEADER or len(payload) > MAX_PAYLOAD:
        raise ValueError('render process message exceeds bounds')
    for part in (struct.pack('!II', len(data), len(payload)), data, payload):
        view = memoryview(part)
        while view:
            count = stream.write(view)
            if not count:
                raise EOFError('render process write closed')
            view = view[count:]
    stream.flush()


def _identity(cap):
    return dict(robot_id=cap.robot_id, episode=cap.episode, frame_seq=cap.frame_seq,
                sim_time=cap.sim_time, wall_time=cap.wall_time)


def _geometry_digest(data):
    """Private fidelity audit only; never sent to an algorithm or HTTP client."""
    digest = hashlib.sha256()
    for name in ('xpos', 'xmat', 'geom_xpos', 'geom_xmat', 'site_xpos', 'site_xmat',
                 'cam_xpos', 'cam_xmat', 'light_xpos', 'light_xdir'):
        digest.update(getattr(data, name).tobytes())
    return digest.hexdigest()


class ProcessCameraRenderer:
    """Same MuJoCo/lens renderer in a separately owned Python/GL process.

    Cancellation kills only this owned job/group, unblocks pipes and joins its
    one I/O thread. An unproved cleanup is an error, never a clean shutdown.
    """
    def __init__(self, model, profile, *, stop_event=None):
        import cv2
        import mujoco
        import numpy as np
        from ..deployment.json_owned_process import OwnedJsonProcess
        self.model = model
        self.profile = profile
        self.cancel = stop_event if stop_event is not None else threading.Event()
        self.closed = threading.Event()
        self.jobs = queue.Queue(maxsize=1)
        self.io = None
        self.owned = None
        self.shutdown_status = None
        self.last_timings = {}
        self.signature = mujoco.mjtState.mjSTATE_INTEGRATION
        self.state = np.empty(mujoco.mj_stateSize(model, self.signature), dtype=np.float64)
        self.sequence = 0
        try:
            self.owned = OwnedJsonProcess(
                [sys.executable, '-u', '-m', __name__, '--worker'],
                cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                env=dict(os.environ), stop_event=self.cancel)
            self.io = threading.Thread(target=self._io_loop, name='sim-v2-render-process-io', daemon=True)
            self.io.start()
            model_size = mujoco.mj_sizeModel(model)
            if model_size > MAX_PAYLOAD:
                raise ValueError('render process model exceeds bounds')
            model_bytes = np.empty(model_size, dtype=np.uint8)
            mujoco.mj_saveModel(model, buffer=model_bytes)
            digest = hashlib.sha256(model_bytes).hexdigest()
            reply, data = self._request(dict(op='init', profile=asdict(profile), model_sha256=digest,
                opencv_threads=cv2.getNumThreads(), python_switch_interval_s=sys.getswitchinterval()), model_bytes, 15.)
            if data or reply.get('op') != 'ready' or reply.get('model_sha256') != digest:
                raise ValueError('render process initialization mismatch')
            self.identity = dict(reply['identity'], isolation='owned_process_v1', worker_pid=self.owned.child.pid,
                                 model_sha256=digest)
        except BaseException as exc:
            if self.owned is None and hasattr(exc, 'cleanup_status'):
                proof = exc.cleanup_status
                self.shutdown_status = dict(clean=proof['clean'], ownership=proof,
                    errors=[], io_thread_stopped=True)
            self.close()
            raise

    def _io_loop(self):
        while not self.closed.is_set():
            try:
                header, payload, done, result = self.jobs.get(timeout=.05)
            except queue.Empty:
                continue
            try:
                _write(self.owned.child.stdin, header, payload)
                result.append(_read(self.owned.child.stdout))
            except BaseException as exc:
                result.append(exc)
            finally:
                done.set()

    def _request(self, header, payload, seconds):
        if self.closed.is_set() or self.cancel.is_set():
            raise RuntimeError('render process cancelled')
        done = threading.Event()
        result = []
        self.jobs.put_nowait((header, payload, done, result))
        deadline = time.perf_counter() + seconds
        while not done.wait(.01):
            if self.cancel.is_set() or self.closed.is_set():
                raise RuntimeError('render process cancelled')
            if time.perf_counter() >= deadline:
                raise TimeoutError('render process response timed out')
        if isinstance(result[0], BaseException):
            raise result[0]
        reply, data = result[0]
        if reply.get('op') == 'error':
            raise RuntimeError('render worker: ' + str(reply.get('error')))
        return reply, data

    def render(self, capture):
        try:
            return self._render(capture)
        except BaseException:
            self.close()
            raise

    def _render(self, capture):
        import mujoco
        import numpy as np
        mujoco.mj_getState(self.model, capture.buffer, self.state, self.signature)
        self.sequence += 1
        key = _identity(capture)
        header = dict(op='render', request=self.sequence, capture=key,
            projectiles=[(radius, position.tolist()) for radius, position in capture.projectiles])
        reply, pixels = self._request(header, self.state.tobytes(), .5)
        if reply.get('op') != 'rendered' or type(reply.get('request')) is not int or reply['request'] != self.sequence:
            raise ValueError('render process request mismatch')
        echoed = reply.get('capture')
        if type(echoed) is not dict or echoed.keys() != key.keys() or any(
                type(echoed[k]) is not type(v) or echoed[k] != v for k, v in key.items()):
            raise ValueError('render process exposure mismatch')
        if len(pixels) != self.profile.width * self.profile.height * 3:
            raise ValueError('render process RGB size mismatch')
        self.last_timings = reply['timings']
        self.last_geometry_sha256 = reply['geometry_sha256']
        return np.frombuffer(pixels, dtype=np.uint8).reshape(self.profile.height, self.profile.width, 3)

    def close(self):
        if self.shutdown_status is not None:
            if not self.shutdown_status['clean']:
                raise RuntimeError('render process cleanup unproved')
            return
        self.closed.set()
        errors = []
        proof = dict(clean=True, not_spawned=True, reaped=False, group_empty=True)
        deadline = time.perf_counter() + 1.25
        try:
            if self.owned is not None:
                proof = self.owned.cleanup(deadline)
        except Exception as exc:
            proof = dict(clean=False, group_empty=False)
            errors.append('owned_cleanup:' + type(exc).__name__)
        if self.owned is not None:
            for stream in (self.owned.child.stdin, self.owned.child.stdout):
                try:
                    stream.close()
                except Exception as exc:
                    errors.append('pipe_close:' + type(exc).__name__)
        if self.io is not None and self.io.ident is not None:
            self.io.join(max(0., deadline - time.perf_counter()))
            if self.io.is_alive():
                errors.append('io_thread_unfinished')
        if self.owned is not None:
            try:
                self.owned.release_handles()
            except Exception as exc:
                errors.append('handle_close:' + type(exc).__name__)
        self.shutdown_status = dict(clean=proof['clean'] and not errors, ownership=proof, errors=errors,
                                    io_thread_stopped=self.io is None or not self.io.is_alive())
        if not self.shutdown_status['clean']:
            raise RuntimeError('render process cleanup unproved: ' + str(self.shutdown_status))


def _worker():
    import cv2
    import mujoco
    import numpy as np
    from ..camera_profile import SourceCameraProfile
    from .camera import Capture, MuJoCoCameraRenderer
    reader, writer = sys.stdin.buffer, sys.stdout.buffer
    renderer = None
    try:
        init, binary = _read(reader)
        digest = hashlib.sha256(binary).hexdigest()
        if init.get('op') != 'init' or digest != init.get('model_sha256'):
            raise ValueError('render worker model identity mismatch')
        with tempfile.TemporaryDirectory(prefix='polar-render-model-') as folder:
            path = os.path.join(folder, 'model.mjb')
            with open(path, 'wb') as stream:
                stream.write(binary)
            model = mujoco.MjModel.from_binary_path(path)
        profile = SourceCameraProfile(**init['profile'])
        cv2.setNumThreads(init['opencv_threads'])
        sys.setswitchinterval(init['python_switch_interval_s'])
        data = mujoco.MjData(model)
        renderer = MuJoCoCameraRenderer(model, profile)
        _write(writer, dict(op='ready', model_sha256=digest, identity=renderer.identity))
        signature = mujoco.mjtState.mjSTATE_INTEGRATION
        state_bytes = mujoco.mj_stateSize(model, signature) * 8
        previous = 0
        while True:
            header, payload = _read(reader)
            if header.get('op') != 'render' or type(header.get('request')) is not int or header['request'] != previous + 1:
                raise ValueError('render worker request sequence mismatch')
            if len(payload) != state_bytes:
                raise ValueError('render worker state size mismatch')
            state = np.frombuffer(payload, dtype=np.float64)
            if not np.isfinite(state).all():
                raise ValueError('render worker state is not finite')
            mujoco.mj_setState(model, data, state, signature)
            mujoco.mj_forward(model, data)
            key = header['capture']
            cap = Capture(**key, buffer=data, own={}, consumers=frozenset(),
                projectiles=tuple((r, np.array(p)) for r, p in header['projectiles']))
            rgb = renderer.render(cap)
            _write(writer, dict(op='rendered', request=header['request'], capture=key,
                                geometry_sha256=_geometry_digest(data), timings=renderer.last_timings), rgb.tobytes())
            previous = header['request']
    except EOFError:
        pass
    except Exception as exc:
        _write(writer, dict(op='error', error=type(exc).__name__ + ':' + str(exc)[:500]))
    finally:
        if renderer is not None:
            renderer.close()


if __name__ == '__main__':
    if sys.argv[1:] != ['--worker']:
        raise SystemExit('Internal render worker requires --worker')
    _worker()
