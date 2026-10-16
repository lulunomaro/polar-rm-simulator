"""Actual six-car MuJoCo, synthetic wall clock: display sampling grants no authority.

No GL/native inference or real-time performance qualification in these tests.
"""
from unittest.mock import patch
import importlib.util
from pathlib import Path

import numpy as np
import pytest

from rm_match.platform_v2.backend import MuJoCoBackend
from rm_match.platform_v2.runtime import PlatformRuntime
from rm_match.platform_v2.test_control import Clock


class CameraCalls:
    def __init__(self):self.captures=0;self.stopped=False
    def capture_from_authority(self,sim,desired):self.captures+=1
    def status(self):return dict(available=False,reason='unit_call_counter_only')
    def stop(self):self.stopped=True


@pytest.mark.parametrize('bad',[True,False,-.01,.101,float('nan'),float('inf'),'0.02',None])
def test_bad_interval_rejected_before_registry_or_backend_use(bad):
    with patch('rm_match.platform_v2.adapters.default_registry') as registry:
        with pytest.raises(ValueError,match='telemetry_publish_interval_s'):
            PlatformRuntime(object(),telemetry_publish_interval_s=bad)
        registry.assert_not_called()


def test_sampling_keeps_all_physics_receipts_and_camera_calls_identical():
    clock=Clock();events=[[],[]];backends=[MuJoCoBackend(),MuJoCoBackend()]
    camera=CameraCalls()
    runtimes=[PlatformRuntime(backends[0],clock=clock,trace=events[0].append),
        PlatformRuntime(backends[1],clock=clock,trace=events[1].append,camera=camera,
            telemetry_publish_interval_s=.02)]
    try:
        for _ in range(40):
            for runtime in runtimes:assert runtime.step_once()
            np.testing.assert_array_equal(backends[0]._sim.data.qpos,backends[1]._sim.data.qpos)
            np.testing.assert_array_equal(backends[0]._sim.data.ctrl,backends[1]._sim.data.ctrl)
            clock.advance(.002)
        assert backends[0].sim_time==backends[1].sim_time==pytest.approx(.08)
        assert camera.captures==40
        # Trace callbacks receive every physical boundary, including deferred displays.
        assert events[0]==events[1]
        phases=[e for e in events[1] if e['event']=='actuator_consumed']
        assert len(phases)>=40*6*3
        assert len([e for e in events[1] if e['event']=='physics_apply'])==40
        default=runtimes[0].telemetry_publication_status();sampled=runtimes[1].telemetry_publication_status()
        assert default['published_steps']==40 and default['deferred_steps']==0
        assert 1<sampled['published_steps']<10
        assert sampled['published_steps']+sampled['deferred_steps']==40
    finally:
        for runtime in runtimes:runtime.close()
    assert camera.stopped


def test_cached_historical_target_cannot_extend_original_manual_deadline():
    clock=Clock();backend=MuJoCoBackend();events=[]
    runtime=PlatformRuntime(backend,clock=clock,trace=events.append,telemetry_publish_interval_s=.1)
    rid='red_sentry';control=runtime.control
    try:
        session=control.open_session('operator','server_window_v1');token=session['token']
        epochs=control.claim(token,rid,['motion'])['lease_epochs']
        window=control.control_window(token,rid,epochs)
        control.control(token,rid,'motion',epochs['motion'],0,
            dict(frame='base_link',vx_mps=.5,vy_mps=0.,wz_rps=0.),.01,window['window_id'])
        runtime.step_once();sample=runtime.cached
        original_sim=sample['sample_sim_time'];revision=control.revision
        assert backend.last_commands[rid]['force_x']>0
        clock.advance(.011);runtime.step_once()
        assert control.revision==revision  # Input expiry doesn't need a binding revision.
        assert runtime.cached is sample and sample['sample_sim_time']==original_sim
        assert sample['applied_targets'][rid]['motion'] is not None
        assert backend.last_commands[rid]['force_x']==0
        latest=[e for e in events if e['event']=='actuator_consumed' and e['robot_id']==rid][-1]
        assert latest['target']['motion'] is None
        state=runtime.snapshot(token)
        assert state['applied_sample_is_historical'] and state['sample_sim_time']==original_sim
        state['robots'].clear()
        assert runtime.cached['robots']  # Public copy is detached from cached sample.
    finally:runtime.close()
    assert runtime.cached['runtime_state']=='stopped'
    assert runtime.cached['steps']==2
    assert runtime.cached['applied_targets'][rid]['motion'] is None
    assert runtime.telemetry_publication_status()['final_display_outside_cadence']


def test_release_and_episode_force_publication_within_the_interval():
    clock=Clock();backend=MuJoCoBackend()
    runtime=PlatformRuntime(backend,clock=clock,telemetry_publish_interval_s=.1)
    try:
        token=runtime.control.open_session('operator')['token']
        epochs=runtime.control.claim(token,'red_sentry',['motion'])['lease_epochs']
        runtime.step_once();first=runtime.cached
        runtime.control.release(token,'red_sentry',epochs)
        runtime.step_once()
        assert runtime.cached is not first and runtime.cached['steps']==2
        second=runtime.cached;backend._sim.reset();runtime.step_once()
        assert runtime.cached is not second
        assert runtime.cached['episode']!=second['episode']
        assert runtime.telemetry_publication_status()['deferred_steps']==0
    finally:runtime.close()


def test_clock_regression_forces_a_new_sample_and_pause_still_neutralizes():
    clock=Clock();backend=MuJoCoBackend()
    runtime=PlatformRuntime(backend,clock=clock,telemetry_publish_interval_s=.02)
    try:
        runtime.step_once();first=runtime.cached
        clock.advance(-.001);runtime.step_once()
        assert runtime.cached is not first
        sample=runtime.cached;backend._sim.set_phase('paused')
        clock.advance(.001);runtime.step_once()
        assert runtime.cached is sample  # Phase HUD follows the explicit display cadence.
        assert all(v['force_x']==v['force_y']==v['yaw_torque']==0 for v in backend.last_commands.values())
        clock.advance(.021);runtime.step_once()
        assert runtime.cached['phase']=='paused'
    finally:runtime.close()


def test_explicit_plan_retains_all_original_thresholds_and_requires_actual_proof():
    spec=importlib.util.spec_from_file_location('cadence_smoke',Path(__file__).resolve().parents[1]/'tools/smoke_wsl_native_live.py')
    smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)
    before=smoke.build_plan('wsl_async_bgr_v3')
    assert 'telemetry_publish_interval_s' not in before['configuration']
    after=smoke.build_plan('wsl_async_bgr_v3',telemetry_publish_interval_ms=20)
    assert after['configuration']['telemetry_publish_interval_s']==.02
    assert {k:v for k,v in after['criteria'].items() if k!='telemetry_publication_matches_plan'}==before['criteria']
    assert {k:v for k,v in after['configuration'].items() if k!='telemetry_publish_interval_s'}==before['configuration']
    for wrong in (None,False,1):
        assert not smoke.classify({'telemetry_publication_matches_plan':wrong},plan=after)['checks']['telemetry_publication_matches_plan']
    assert smoke.classify({'telemetry_publication_matches_plan':True},plan=after)['checks']['telemetry_publication_matches_plan']
    for bad in (None,True,-1,101,float('nan'),float('inf'),'20'):
        with pytest.raises(ValueError):smoke.build_plan('wsl_async_bgr_v3',telemetry_publish_interval_ms=bad)
