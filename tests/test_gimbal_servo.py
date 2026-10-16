"""Real MuJoCo with synthetic deadlines; no NN, GL, or aim accuracy claim."""
import copy
import json
from unittest.mock import patch
import numpy as np
import pytest
from rm_match.platform_v2.backend import MuJoCoBackend
from rm_match.platform_v2.runtime import PlatformRuntime
from rm_match.platform_v2.test_control import Clock
from rm_match.platform_v2.gimbal_servo import GravityPositionServo,servo_mode
from tests.test_native_target_motion import load_smoke


def scenario(mode):
    clock=Clock();b=MuJoCoBackend(gimbal_servo=mode);r=PlatformRuntime(b,clock=clock,telemetry_publish_interval_s=.02)
    sid=r.control.open_session('operator','server_window_v1');token=sid['token'];rid='red_infantry'
    epochs=r.control.claim(token,rid,['gimbal'])['lease_epochs'];seq=0;record=[]
    try:
        for step in range(1500):
            if step%75==0:
                r.control.renew(token,rid,epochs);window=r.control.control_window(token,rid,epochs)
                r.control.control(token,rid,'gimbal',epochs['gimbal'],seq,
                    dict(frame='base_link',yaw_rad=0.,pitch_rad=0.),.04,window['window_id']);seq+=1
            r.step_once();clock.advance(.002)
            record.append(float(b._sim.data.qpos[b._sim.qindices[rid][4]]))
        return record
    finally:r.close()


def test_expiring_zero_reference_does_not_ratchet_pitch_under_gravity():
    baseline=scenario('position');compensated=scenario('position_gravity_v1')
    assert baseline[-1]<-.04  # Reproduce the old failure without changing gains/mass.
    assert max(abs(v) for v in compensated)<1e-6


@pytest.mark.parametrize('rid',['red_hero','red_infantry','red_sentry','blue_hero','blue_infantry','blue_sentry'])
def test_original_guards_do_not_accumulate_feedforward_or_keep_expired_target(rid):
    clock=Clock();b=MuJoCoBackend(gimbal_servo='position_gravity_v1');events=[]
    r=PlatformRuntime(b,clock=clock,trace=events.append)
    try:
        session=r.control.open_session('operator','server_window_v1');token=session['token']
        epochs=r.control.claim(token,rid,['gimbal'])['lease_epochs'];w=r.control.control_window(token,rid,epochs)
        r.control.control(token,rid,'gimbal',epochs['gimbal'],0,dict(frame='base_link',yaw_rad=.2,pitch_rad=.1),.04,w['window_id'])
        arrays={k:getattr(b._sim.model,k).copy() for k in ('body_mass','body_ipos','dof_damping','actuator_gainprm','actuator_biasprm','actuator_ctrlrange','jnt_range')}
        r.step_once();audit=b._gimbal_servo.last[rid]
        assert audit['phase']=='integration_entry' and audit['raw_pitch_rad']==.1
        assert audit['ctrl_pitch_rad']==pytest.approx(.1+audit['ctrl_offset_rad'])
        assert b._sim.data.ctrl[b._sim.aindices[rid][4]]==pytest.approx(audit['ctrl_pitch_rad'])
        clock.now=.04+1000.;r.step_once();audit=b._gimbal_servo.last[rid]
        assert abs(audit['raw_pitch_rad']-.1)>.05
        assert r.cached['applied_targets'][rid]['gimbal'] is None
        assert not b.last_commands[rid]['fire']
        for key,value in arrays.items():np.testing.assert_array_equal(getattr(b._sim.model,key),value)
    finally:r.close()


@pytest.mark.parametrize('mode',[None,True,1,'automatic','position_gravity_v2'])
def test_invalid_mode_rejected_before_simulation(mode):
    with patch('rm_match.match_engine.MatchSimulation') as sim,pytest.raises(ValueError):MuJoCoBackend(gimbal_servo=mode)
    sim.assert_not_called()


@pytest.mark.parametrize('fault',['tilted_ancestor','free_ancestor','tilted_pitch_axis','extra_pitch_mass'])
def test_unverified_models_fail_closed(fault):
    b=MuJoCoBackend();m=b._sim.model;rid='red_sentry'
    try:
        if fault=='tilted_ancestor':m.body_quat[m.body(rid+'__yaw').id]=[.707106781, .707106781,0,0]
        elif fault=='free_ancestor':m.jnt_type[m.joint(rid+'__base_yaw').id]=0
        elif fault=='tilted_pitch_axis':m.jnt_axis[m.joint(rid+'__gimbal_pitch').id]=[0,1,0]
        elif fault=='extra_pitch_mass':m.body_subtreemass[m.body(rid+'__pitch').id]+=.1
        with pytest.raises(ValueError):GravityPositionServo(m,(rid,))
    finally:b._sim.close()


def test_reference_mapping_is_bounded_and_has_no_authority_or_truth_input():
    from rm_match.contracts import Command
    b=MuJoCoBackend(gimbal_servo='position_gravity_v1');servo=b._gimbal_servo
    try:
        command=Command(force_x=3.,gimbal_yaw=100.,gimbal_pitch=100.,fire=False)
        mapped=servo.apply('red_sentry',command,.1,'test')
        assert mapped.force_x==3. and mapped.fire is False
        assert mapped.gimbal_yaw==3.14 and mapped.gimbal_pitch==.5
        assert servo.last['red_sentry']['clamped']
        assert not hasattr(servo,'model')
        for rid,c in servo.controllers.items():assert not hasattr(c,'model')
    finally:b._sim.close()


@pytest.mark.parametrize('phase',['actuator','integration','integration_entry'])
def test_revocation_during_consumption_uses_measured_hold_instead_of_old_reference(phase):
    clock=Clock();b=MuJoCoBackend(gimbal_servo='position_gravity_v1');r=PlatformRuntime(b,clock=clock);rid='red_infantry'
    try:
        session=r.control.open_session('operator','server_window_v1');token=session['token']
        epochs=r.control.claim(token,rid,['gimbal','fire'])['lease_epochs'];w=r.control.control_window(token,rid,epochs)
        for channel,command in (('gimbal',dict(frame='base_link',yaw_rad=.3,pitch_rad=.2)),('fire',dict(fire=True))):
            r.control.control(token,rid,channel,epochs[channel],0,command,.15,w['window_id'])
        original=b.guarded_step
        def delayed(targets,guard,**kwargs):
            def wrapped(robot,command,boundary,sampled_wall=None):
                if robot==rid and boundary==phase:
                    r.control.release(token,rid,epochs)
                return guard(robot,command,boundary,sampled_wall)
            return original(targets,wrapped,**kwargs)
        b.guarded_step=delayed;r.step_once();audit=b._gimbal_servo.last[rid]
        assert abs(audit['raw_pitch_rad'])<1e-9
        assert audit['ctrl_pitch_rad']==pytest.approx(audit['ctrl_offset_rad'])
        assert b._sim.projectile_counter==0 and not b.last_commands[rid]['fire']
        assert r.cached['applied_targets'][rid]['gimbal'] is None
    finally:r.close()


def test_default_static_plan_and_explicit_servo_classification():
    smoke=load_smoke();assert smoke.build_plan('wsl_stdio_v1')==smoke.PLAN
    plan=smoke.build_plan('wsl_stdio_v1',gimbal_servo='position_gravity_v1')
    assert plan['criteria']['gimbal_servo_configuration_matches_plan'] is True
    assert plan['criteria']['minimum_physics_rtf']==.98
    assert plan['configuration']['camera_native_budget_s']==.08 and plan['configuration']['server_input_window_s']==.15
    from tests.test_wsl_native_live_classification import measured
    m=measured();m['configuration']=copy.deepcopy(plan['configuration'])
    assert not smoke.classify(m,plan=plan)['live_static_chain_qualified']
    m['gimbal_servo_configuration_matches_plan']=True
    assert smoke.classify(m,plan=plan)['live_static_chain_qualified']


def test_server_cli_forwards_explicit_servo_and_reports_mode():
    from tests.test_telemetry_cli import TelemetryCliTests
    from rm_match.platform_v2 import __main__ as cli
    fixture=TelemetryCliTests();fixture.setUp()
    try:
        events,created=fixture.fixture()
        cli.main(['--admission-manifest','fixture.json','--gimbal-servo','position_gravity_v1'])
        assert created['backend_kwargs']['gimbal_servo']=='position_gravity_v1'
        assert json.loads(created['stdout'].getvalue())['gimbal_servo']=='position_gravity_v1'
        assert 'runtime_close' in events
    finally:fixture.doCleanups()
