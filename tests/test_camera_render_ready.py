"""Real snapshot/worker scheduling, synthetic renderer: no GL/NN qualification."""
import importlib.util
from pathlib import Path
import threading
import time

import numpy as np
import pytest

from rm_match.platform_v2.backend import MuJoCoBackend
from rm_match.platform_v2.camera import CameraProvider
from rm_match.platform_v2.test_control import Clock


def until(predicate):
    deadline=time.monotonic()+4
    while time.monotonic()<deadline:
        if predicate():return
        time.sleep(.002)
    raise AssertionError('Owned camera worker did not reach expected boundary')


@pytest.fixture
def camera_factory():
    resources=[]
    def make(policy='render_ready'):
        clock=Clock();backend=MuJoCoBackend(camera=True)
        entered=threading.Event();release=threading.Event();seen=[]
        class Renderer:
            def __init__(self,model,profile):self.profile=profile
            def render(self,cap):
                seen.append(cap)
                if len(seen)==1:
                    entered.set()
                    if not release.wait(4):raise RuntimeError('Test did not release owned renderer')
                p=self.profile
                return np.full((p.height,p.width,3),cap.frame_seq%256,np.uint8)
            def close(self):pass
        provider=CameraProvider(backend._sim,clock=clock,total_fps=15,max_views=2,
            renderer_factory=Renderer,capture_policy=policy,enable_native_pixels=True)
        resources.append((backend,provider,release))
        return clock,backend,provider,entered,release,seen
    yield make
    for backend,provider,release in reversed(resources):
        provider.stop();release.set()
        assert provider.wait_closed(4)
        backend.close()


@pytest.mark.parametrize('policy,expected_captures',[('latest_pending',2),('render_ready',1)])
def test_busy_policy_defers_new_exposure_without_restamping_old_capture(camera_factory,policy,expected_captures):
    clock,backend,p,entered,release,seen=camera_factory(policy)
    desired={'red_sentry':{('adapter','red_sentry','aim','owner',1)}}
    p.capture_from_authority(backend._sim,desired);assert entered.wait(2)
    first=seen[0];first_wall=first.wall_time;first_time=first.sim_time
    next_capture=p.next_capture;cursor=p.cursor
    clock.advance(.1)
    p.capture_from_authority(backend._sim,desired)
    assert p.capture_count==expected_captures
    assert first.wall_time==first_wall and first.sim_time==first_time
    if policy=='latest_pending':return
    assert p.sequence==1 and not p.pending
    assert p.next_capture==next_capture and p.cursor==cursor
    assert p.status()['capture_deferred_busy']==1
    release.set();until(lambda:not p.running)
    # The old render took >80ms in this injected clock: it remains rejected.
    assert not p.native_cache
    backend._sim.data.time=.002
    p.capture_from_authority(backend._sim,desired)
    until(lambda:len(seen)==2)
    fresh=seen[1]
    assert fresh.frame_seq==2 and fresh.wall_time==clock() and fresh.sim_time==.002
    assert first.wall_time==first_wall and first.sim_time==first_time
    # A completed MjData buffer may be reused; detached exposure metadata may not.
    assert fresh is not first and fresh.own is not first.own


def test_busy_capture_still_revokes_consumers_before_return(camera_factory):
    clock,backend,p,entered,release,seen=camera_factory()
    desired={'red_sentry':{('adapter','red_sentry','aim','owner',1)}}
    p.capture_from_authority(backend._sim,desired);assert entered.wait(2)
    clock.advance(.1);p.capture_from_authority(backend._sim,{})
    assert not p.desired and not p.pending
    release.set();until(lambda:not p.running)
    assert not p.native_cache and not p.cache and not p.display_pending
    assert p.capture_count==1


def test_episode_change_while_busy_rejects_old_pixels_and_preserves_round_robin(camera_factory):
    clock,backend,p,entered,release,seen=camera_factory()
    desired={r:{('adapter',r,'aim','owner',1)} for r in ('red_sentry','blue_sentry')}
    p.capture_from_authority(backend._sim,desired);assert entered.wait(2)
    old_episode=seen[0].episode;cursor=p.cursor
    backend._sim.reset();clock.advance(.1)
    p.capture_from_authority(backend._sim,desired)
    assert p.episode==backend._sim.episode and p.episode!=old_episode
    assert p.cursor==cursor and p.capture_count==1 and not p.pending
    release.set();until(lambda:not p.running)
    assert not p.native_cache and not p.cache
    p.capture_from_authority(backend._sim,desired)
    until(lambda:len(seen)==2)
    assert seen[1].robot_id=='blue_sentry' and seen[1].episode==p.episode


def test_capture_policy_is_explicit_and_default_plan_is_unchanged(camera_factory):
    spec=importlib.util.spec_from_file_location('render_ready_smoke',Path(__file__).resolve().parents[1]/'tools/smoke_wsl_native_live.py')
    smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)
    before=smoke.build_plan('wsl_async_bgr_v3')
    assert 'camera_capture_policy' not in before['configuration']
    after=smoke.build_plan('wsl_async_bgr_v3',camera_capture_policy='render_ready')
    assert after['configuration']['camera_capture_policy']=='render_ready'
    assert {k:v for k,v in after['criteria'].items() if k!='camera_capture_policy_matches_plan'}==before['criteria']
    assert {k:v for k,v in after['configuration'].items() if k!='camera_capture_policy'}==before['configuration']
    for wrong in (None,False,1):
        measured={'camera_capture_policy_matches_plan':wrong}
        assert smoke.classify(measured,plan=after)['checks']['camera_capture_policy_matches_plan'] is False
    assert smoke.classify({'camera_capture_policy_matches_plan':True},plan=after)['checks']['camera_capture_policy_matches_plan'] is True
    for invalid in (None,True,1,{},'unknown'):
        with pytest.raises(ValueError,match='capture policy'):
            smoke.build_plan('wsl_async_bgr_v3',camera_capture_policy=invalid)
    clock,backend,p,*_=camera_factory()
    with pytest.raises(ValueError,match='capture policy'):
        CameraProvider(backend._sim,capture_policy='unknown')
