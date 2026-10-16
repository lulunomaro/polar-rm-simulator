"""Bounded wire/fault checks and separately opted-in actual GL equivalence."""
import io
import json
import os
import struct
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from rm_match.platform_v2 import camera_process as wire


class ShortStream(io.BytesIO):
    def readinto(self, view):
        return super().readinto(view[:3])

    def write(self, data):
        return super().write(data[:5])


def test_wire_handles_actual_partial_binary_reads_and_writes():
    stream = ShortStream()
    header = dict(op='pixels', capture_wall=12.123456789123)
    payload = bytes(range(256)) * 100
    wire._write(stream, header, payload)
    stream.seek(0)
    received, data = wire._read(stream)
    assert received == dict(header, schema=wire.SCHEMA)
    assert data == payload


@pytest.mark.parametrize('head,size', [(0, 0), (wire.MAX_HEADER+1, 0), (1, wire.MAX_PAYLOAD+1)])
def test_read_rejects_lengths_before_allocation(head, size):
    with pytest.raises(ValueError, match='bounds'):
        wire._read(io.BytesIO(struct.pack('!II', head, size)))


@pytest.mark.parametrize('data', [b'', b'1234567', struct.pack('!II', 10, 0)+b'{}'])
def test_truncated_frames_reject(data):
    with pytest.raises(EOFError):
        wire._read(io.BytesIO(data))


@pytest.mark.parametrize('value', [[], {}, {'schema': 'wrong'}])
def test_schema_rejects(value):
    blob = json.dumps(value).encode()
    with pytest.raises(ValueError, match='schema'):
        wire._read(io.BytesIO(struct.pack('!II', len(blob), 0)+blob))


def bare_renderer():
    r = object.__new__(wire.ProcessCameraRenderer)
    r.closed = threading.Event();r.cancel = threading.Event()
    r.shutdown_status = None;r.owned = None;r.io = None
    return r


def test_cleanup_unproved_is_sticky():
    r = bare_renderer()
    r.owned = SimpleNamespace(child=SimpleNamespace(stdin=io.BytesIO(), stdout=io.BytesIO()),
        cleanup=lambda deadline: dict(clean=False, group_empty=False), release_handles=lambda: None)
    with pytest.raises(RuntimeError, match='cleanup unproved'):r.close()
    assert not r.shutdown_status['clean']
    with pytest.raises(RuntimeError, match='cleanup unproved'):r.close()


def test_close_before_launch_is_idempotent():
    r = bare_renderer();r.close();r.close()
    assert r.shutdown_status['clean'] and r.shutdown_status['ownership']['not_spawned']


@pytest.mark.skipif(wire.sys.platform not in ('win32','linux'),reason='Owned process supported platforms')
@pytest.mark.parametrize('cancel', [False,True])
def test_actual_silent_child_pipe_timeout_or_cancel_is_reaped(cancel):
    from rm_match.deployment.json_owned_process import OwnedJsonProcess
    import queue
    r=bare_renderer();r.jobs=queue.Queue(maxsize=1)
    r.owned=OwnedJsonProcess([wire.sys.executable,'-u','-c','import time;time.sleep(10)'],
        cwd=os.getcwd(),env=dict(os.environ),stop_event=r.cancel)
    r.io=threading.Thread(target=r._io_loop,daemon=True);r.io.start()
    timer=threading.Timer(.025,r.cancel.set) if cancel else None
    try:
        if timer:timer.start()
        started=time.perf_counter()
        with pytest.raises((RuntimeError,TimeoutError)):
            r._request(dict(op='fixture-no-response'),b'actual test bytes',.06)
        r.close()
        assert time.perf_counter()-started<1.5
        assert r.shutdown_status['clean']
        assert r.shutdown_status['ownership']['reaped'] and r.shutdown_status['ownership']['group_empty']
        assert not r.io.is_alive()
    finally:
        if timer:timer.cancel();timer.join()
        r.close()


@pytest.mark.parametrize('value',[None,True,1,'','process','OWNED_PROCESS_V1'])
def test_camera_mode_rejects_unknown_before_start(value):
    from rm_match.platform_v2.backend import MuJoCoBackend
    from rm_match.platform_v2.camera import CameraProvider
    backend=MuJoCoBackend(camera=True)
    try:
        with pytest.raises(ValueError,match='renderer mode'):CameraProvider(backend._sim,renderer_mode=value)
    finally:backend.close()


def test_process_selection_is_explicit_and_thread_default_is_unchanged():
    from rm_match.platform_v2.backend import MuJoCoBackend
    from rm_match.platform_v2.camera import CameraProvider,MuJoCoCameraRenderer
    backend=MuJoCoBackend(camera=True)
    try:
        default=CameraProvider(backend._sim);process=CameraProvider(backend._sim,renderer_mode='owned_process_v1')
        assert default.renderer_factory is MuJoCoCameraRenderer and default.thread is None
        assert process.renderer_factory is wire.ProcessCameraRenderer and process.thread is None
        assert process.status()['max_renderer_processes']==1 and default.status()['max_renderer_processes']==0
        default.stop();process.stop()
    finally:backend.close()


def test_smoke_plan_requires_selected_process_cleanup_proof():
    from tools.smoke_wsl_native_live import build_plan,classify
    plan=build_plan('wsl_async_bgr_v3',camera_renderer_mode='owned_process_v1')
    assert plan['configuration']['camera_renderer_mode']=='owned_process_v1'
    assert plan['configuration']['camera_native_budget_s']==.08
    assert plan['configuration']['server_input_window_s']==.15
    assert plan['criteria']['minimum_physics_rtf']==.98
    assert plan['criteria']['camera_renderer_configuration_matches_plan']
    assert 'camera_renderer_mode' not in build_plan('wsl_async_bgr_v3')['configuration']
    with pytest.raises(ValueError):build_plan('wsl_async_bgr_v3',camera_renderer_mode='process')
    from tests.test_wsl_native_live_classification import measured
    m=measured();m['configuration']=plan['configuration'];m['original_async_transactions_accounted']=True
    for wrong in (None,False,1,'true'):
        m['camera_renderer_configuration_matches_plan']=wrong
        assert 'camera_renderer_configuration_matches_plan' in classify(m,plan=plan)['rejected_or_failed_criteria']
    m['camera_renderer_configuration_matches_plan']=True
    assert classify(m,plan=plan)['live_static_chain_qualified']


@pytest.mark.parametrize('fault', ['timeout', 'exposure', 'request_type', 'request', 'rgb', 'worker'])
def test_render_fault_is_terminal_and_cleans_owned_process(fault):
    import mujoco
    model=mujoco.MjModel.from_xml_string('<mujoco/>');data=mujoco.MjData(model)
    r=bare_renderer();r.model=model;r.signature=mujoco.mjtState.mjSTATE_INTEGRATION
    r.state=np.empty(mujoco.mj_stateSize(model,r.signature));r.sequence=0
    r.profile=SimpleNamespace(width=2,height=2)
    cap=SimpleNamespace(robot_id='unit',episode=1,frame_seq=4,sim_time=.002,wall_time=45.9,
                        buffer=data,projectiles=())
    def response(*args):
        if fault=='timeout':raise TimeoutError('fixture blocked')
        if fault=='worker':raise EOFError('fixture died')
        reply=dict(op='rendered',request=1,capture=wire._identity(cap),timings={})
        pixels=bytes(12)
        if fault=='exposure':reply['capture']['wall_time']+=.001
        if fault=='request_type':reply['request']=True
        if fault=='request':reply['request']=0
        if fault=='rgb':pixels=bytes(11)
        return reply,pixels
    r._request=response
    with pytest.raises((ValueError,TimeoutError,EOFError)):r.render(cap)
    assert r.closed.is_set() and r.shutdown_status['clean']


@pytest.mark.skipif(os.getenv('POLAR_TEST_CAMERA_PROCESS')!='1',reason='Explicit serialized real GL/process window')
def test_actual_gl_process_matches_all_six_cameras_motion_projectiles_and_reset():
    import hashlib
    import mujoco
    from rm_match.platform_v2.backend import MuJoCoBackend
    from rm_match.platform_v2.camera import Capture,MuJoCoCameraRenderer
    from rm_match.camera_profile import SourceCameraProfile
    backend=MuJoCoBackend(camera=True);sim=backend._sim
    profile=SourceCameraProfile(overscan_pixels=64)
    direct=MuJoCoCameraRenderer(sim.model,profile)
    isolated=wire.ProcessCameraRenderer(sim.model,profile)
    results=[]
    try:
        assert 'NVIDIA' in str(direct.identity) and 'NVIDIA' in str(isolated.identity)
        assert direct.identity['renderer']==isolated.identity['renderer']
        assert isolated.identity['worker_pid']!=os.getpid()
        for index in range(8):
            rid=sim.robot_ids[index%6]
            if index==7:sim.reset()
            else:
                for _ in range(index*3):mujoco.mj_step(sim.model,sim.data)
            mujoco.mj_forward(sim.model,sim.data)
            cap=Capture(rid,int(sim.episode),index+1,float(sim.data.time),time.perf_counter(),frozenset(),
                sim.data,{},((.03,np.array([-1.,2.,.5])),) if index%2 else ())
            before=[v.copy() for v in (sim.data.qpos,sim.data.qvel,sim.data.ctrl)]
            a=direct.render(cap);b=isolated.render(cap)
            if not np.array_equal(a,b):
                repeated=direct.render(cap);again=isolated.render(cap)
                print(json.dumps(dict(frame=index+1,differing_channels=int(np.count_nonzero(a!=b)),
                    direct_repeat_changes=int(np.count_nonzero(a!=repeated)),
                    process_repeat_changes=int(np.count_nonzero(b!=again)),
                    direct_repeat_vs_process=int(np.count_nonzero(repeated!=again)))))
            assert wire._geometry_digest(sim.data)==isolated.last_geometry_sha256
            # Actual NVIDIA GL also varies by one channel level on repeated
            # unchanged input (failure artifacts retain the initial exact-byte
            # experiment). This sensor-fidelity bound is not an admission-gate
            # change: every native frame still binds to its own exact RGB bytes.
            max_error=int(np.max(np.abs(a.astype(int)-b.astype(int))))
            changed=int(np.count_nonzero(a!=b))
            assert max_error<=1 and changed<=32, (index,max_error,changed)
            assert b.shape==(1080,1440,3) and b.dtype==np.uint8
            assert all(np.array_equal(a,b) for a,b in zip(before,(sim.data.qpos,sim.data.qvel,sim.data.ctrl)))
            results.append(dict(robot_id=rid,frame=index+1,rgb_sha256=hashlib.sha256(b).hexdigest(),
                direct_rgb_sha256=hashlib.sha256(a).hexdigest(),differing_channels=changed,max_channel_error=max_error,
                geometry_sha256=isolated.last_geometry_sha256,geometry_identical=True))
        print(json.dumps(dict(pixel_equivalence=results,identity=isolated.identity)))
        # An independently owned process exits cleanly with a blocked pipe/idle worker.
        isolated.close();assert isolated.shutdown_status['clean']
        assert isolated.shutdown_status['ownership']['reaped']
        assert isolated.shutdown_status['ownership']['group_empty']
        assert isolated.shutdown_status['io_thread_stopped']
    finally:
        direct.close();isolated.close();backend.close()
