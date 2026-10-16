"""Actual MuJoCo / synthetic time; own position following, not aim accuracy."""
import math
from unittest.mock import patch
import numpy as np
import pytest
from rm_match.platform_v2.backend import MuJoCoBackend
from rm_match.platform_v2.runtime import PlatformRuntime
from rm_match.platform_v2.test_control import Clock
from rm_match.platform_v2.gimbal_servo import yaw_gain
from tests.test_native_target_motion import load_smoke


def run_profile(gain,profile,*,rid='red_infantry'):
    b=MuJoCoBackend(gimbal_servo='position_gravity_v1',gimbal_yaw_gain=gain);clock=Clock()
    r=PlatformRuntime(b,clock=clock,telemetry_publish_interval_s=.02);rows=[]
    session=r.control.open_session('operator','server_window_v1');token=session['token']
    epochs=r.control.claim(token,rid,['gimbal'])['lease_epochs'];seq=0
    arrays={k:getattr(b._sim.model,k).copy() for k in ('body_mass','body_ipos','actuator_gainprm','actuator_biasprm','actuator_ctrlrange','dof_damping','jnt_range')}
    try:
        for step in range(1500):
            if step%75==0:
                r.control.renew(token,rid,epochs);window=r.control.control_window(token,rid,epochs)
                reference=profile(step*.002)
                r.control.control(token,rid,'gimbal',epochs['gimbal'],seq,
                    dict(frame='base_link',yaw_rad=reference,pitch_rad=0.),.04,window['window_id']);seq+=1
            r.step_once();clock.advance(.002);sample=b._gimbal_servo.last[rid]
            q=float(b._sim.data.qpos[b._sim.qindices[rid][3]])
            rows.append(dict(step=step,sim_time=b.sim_time,qpos=q,reference=reference,
                active=r.cached['applied_targets'][rid]['gimbal'] is not None if r.cached['steps']==r.steps else sample['yaw_feedback_enabled'],
                feedback_enabled=sample['yaw_feedback_enabled'],raw_reference=sample['raw_yaw_rad'],ctrl=sample['ctrl_yaw_rad']))
        for k,a in arrays.items():np.testing.assert_array_equal(getattr(b._sim.model,k),a)
        return rows
    finally:r.close()


@pytest.mark.parametrize('direction',[-1,1])
def test_intermittent_ramp_follows_raw_reference_with_original_expiry(direction):
    base=run_profile(1.,lambda t:direction*.04*t);boost=run_profile(4.,lambda t:direction*.04*t)
    def rms(rows):
        errors=[row['qpos']-row['raw_reference'] for row in rows if row['feedback_enabled'] and row['sim_time']>2.]
        return math.sqrt(sum(e*e for e in errors)/len(errors))
    assert rms(boost)<.45*rms(base)
    for row in boost:
        if not row['feedback_enabled']:assert row['ctrl']==row['raw_reference']
    assert any(row['feedback_enabled'] for row in boost) and any(not row['feedback_enabled'] for row in boost)


@pytest.mark.parametrize('rid',['red_hero','red_infantry','red_sentry','blue_hero','blue_infantry','blue_sentry'])
def test_step_is_bounded_and_settles_for_each_declared_robot(rid):
    rows=run_profile(4.,lambda t:.2 if t>=.3 else 0.,rid=rid)
    assert all(-3.14<=row['ctrl']<=3.14 and -.005<=row['qpos']<=.205 for row in rows)
    assert abs(rows[-1]['qpos']-.2)<.003


@pytest.mark.parametrize('bad',[True,False,None,'4',0,.99,4.01,float('nan'),float('inf'),10**500])
def test_invalid_gain_rejected_before_model_resources(bad):
    with patch('rm_match.match_engine.MatchSimulation') as sim,pytest.raises(ValueError):
        MuJoCoBackend(gimbal_servo='position_gravity_v1',gimbal_yaw_gain=bad)
    sim.assert_not_called()
    with pytest.raises(ValueError):load_smoke().build_plan('wsl_stdio_v1',gimbal_servo='position_gravity_v1',gimbal_yaw_gain=bad)


def test_nondefault_gain_requires_explicit_controller():
    with pytest.raises(ValueError):MuJoCoBackend(gimbal_yaw_gain=4.)
    with pytest.raises(ValueError):load_smoke().build_plan('wsl_stdio_v1',gimbal_yaw_gain=4.)
    smoke=load_smoke();assert smoke.build_plan('wsl_stdio_v1')==smoke.PLAN
    plan=smoke.build_plan('wsl_stdio_v1',gimbal_servo='position_gravity_v1',gimbal_yaw_gain=4.)
    assert plan['configuration']['gimbal_yaw_gain']==4. and plan['criteria']['minimum_physics_rtf']==.98


@pytest.mark.parametrize('phase',['actuator','integration','integration_entry'])
def test_release_between_guards_disables_boost_without_reusing_old_angle(phase):
    clock=Clock();b=MuJoCoBackend(gimbal_servo='position_gravity_v1',gimbal_yaw_gain=4.)
    r=PlatformRuntime(b,clock=clock);rid='red_infantry'
    try:
        token=r.control.open_session('operator','server_window_v1')['token'];epochs=r.control.claim(token,rid,['gimbal','fire'])['lease_epochs']
        w=r.control.control_window(token,rid,epochs)
        for channel,command in (('gimbal',dict(frame='base_link',yaw_rad=.2,pitch_rad=0.)),('fire',dict(fire=True))):
            r.control.control(token,rid,channel,epochs[channel],0,command,.15,w['window_id'])
        original=b.guarded_step
        def delayed(targets,guard,**kwargs):
            def revoke(robot,command,boundary,sampled_wall=None):
                if robot==rid and boundary==phase:r.control.release(token,rid,epochs)
                return guard(robot,command,boundary,sampled_wall)
            return original(targets,revoke,**kwargs)
        b.guarded_step=delayed;r.step_once();sample=b._gimbal_servo.last[rid]
        assert sample['raw_yaw_rad']==sample['ctrl_yaw_rad']==0.
        assert sample['yaw_feedback_enabled'] is False and b._sim.projectile_counter==0
    finally:r.close()


def test_feedback_is_not_multiplied_across_three_consumption_phases():
    b=MuJoCoBackend(gimbal_servo='position_gravity_v1',gimbal_yaw_gain=4.);clock=Clock();r=PlatformRuntime(b,clock=clock)
    try:
        rid='red_infantry';token=r.control.open_session('operator','server_window_v1')['token'];epochs=r.control.claim(token,rid,['gimbal'])['lease_epochs']
        w=r.control.control_window(token,rid,epochs)
        r.control.control(token,rid,'gimbal',epochs['gimbal'],0,dict(frame='base_link',yaw_rad=.2,pitch_rad=0.),.15,w['window_id'])
        r.step_once();sample=b._gimbal_servo.last[rid]
        assert sample['phase']=='integration_entry' and sample['raw_yaw_rad']==.2
        assert sample['ctrl_yaw_rad']==pytest.approx(.8)
        assert b._sim.data.ctrl[b._sim.aindices[rid][3]]==pytest.approx(.8)
    finally:r.close()


def test_server_reports_and_forwards_gain_and_rejects_invalid_before_admission():
    import json
    from tests.test_telemetry_cli import TelemetryCliTests
    from rm_match.platform_v2 import __main__ as cli
    for args in (['--gimbal-yaw-gain','nan'],['--gimbal-yaw-gain','4']):
        with patch('rm_match.platform_v2.admission.AdmissionPolicy.from_manifest') as policy,pytest.raises(SystemExit):
            cli.main(['--admission-manifest','not-read.json',*args])
        policy.assert_not_called()
    fixture=TelemetryCliTests();fixture.setUp()
    try:
        _,created=fixture.fixture();cli.main(['--admission-manifest','fixture.json','--gimbal-servo','position_gravity_v1','--gimbal-yaw-gain','4'])
        assert created['backend_kwargs']['gimbal_yaw_gain']==4.
        assert json.loads(created['stdout'].getvalue())['gimbal_yaw_gain']==4.
    finally:fixture.doCleanups()
