from dataclasses import replace
import numpy as np
import pytest
from rm_match.rmcs_stop_aim import StationaryGate,source_fire_allowed,verify_own_contract
from rm_match.integrations.rmcs_contract import own_state,command_from_direction
from rm_match.contracts import Command
from test_opening_strategy import sentry


def test_stationary_gate_requires_continuous_dwell_and_occupation_mode():
    gate=StationaryGate();o=sentry(xy=(-.6,-1.2))
    for t in (0.,.2,.4,1.):assert not gate.update(replace(o,sim_time=t),'opening_rush')
    assert not gate.update(replace(o,sim_time=2),'occupation')
    assert not gate.update(replace(o,sim_time=2.39),'occupation')
    assert gate.update(replace(o,sim_time=2.4),'occupation')
    assert not gate.update(replace(o,sim_time=2.5,odom_vxyw=(.031,0,0)),'occupation')
    assert not gate.update(replace(o,sim_time=2.6),'occupation')
    assert gate.update(replace(o,sim_time=3.),'occupation')


@pytest.mark.parametrize('changes',[dict(own_hp=0),dict(own_weak=True),dict(match_phase='paused'),
    dict(emergency_stop=True),dict(odom_vxyw=(0,0,.031)),dict(odom_xyyaw=(-.57,-1.2,0.))])
def test_motion_origin_shift_and_lifecycle_revoke_stationary_gate(changes):
    gate=StationaryGate();o=sentry(xy=(-.6,-1.2))
    gate.update(o,'occupation');assert gate.update(replace(o,sim_time=.4),'occupation')
    assert not gate.update(replace(o,sim_time=.41,**changes),'occupation')
    assert gate.anchor is None and not gate.active


def test_outer_fire_gate_never_grants_source_denial_or_stale_visual():
    o=sentry(t=10,xy=(-.6,-1.2))
    response=dict(tracking=True,should_shoot=True,target_age_s=.01,direction=[1.,0.,0.])
    assert source_fire_allowed(response,o,9.99)[0]
    for changes,last in [(dict(should_shoot=False),9.99),(dict(tracking=False),9.99),
                         (dict(target_age_s=.081),9.99),({},9.9),({},None),
                         (dict(direction=[float('nan'),0,0]),9.99)]:
        assert not source_fire_allowed({**response,**changes},o,last)[0]


def test_world_direction_conversion_uses_current_own_base_yaw_and_no_target_position():
    o=replace(sentry(),odom_xyyaw=(-5.,2.,.4),own_qpos=(0,0,.4,.2,.1))
    c=command_from_direction(dict(should_control=True,should_shoot=False,
        direction=[np.cos(.7),np.sin(.7),0.],direction_frame='world'),o)
    assert c.gimbal_yaw==pytest.approx(.3) and c.gimbal_pitch==0 and not c.fire
    assert command_from_direction(dict(should_control=False),o).fire is False
    with pytest.raises(ValueError):
        command_from_direction(dict(should_control=True,direction=[1,0,0],direction_frame='guessed'),o)


def test_mujoco_own_extrinsics_match_frame_contract_while_articulated():
    from rm_match.match_engine import MatchSimulation
    s=MatchSimulation(render=False)
    try:
        for _ in range(800):s.step({'red_sentry':Command(yaw_torque=.1,gimbal_yaw=.3,gimbal_pitch=.2)})
        errors=verify_own_contract(s,'red_sentry')
        assert max(errors.values())<1e-9
        frame=own_state(s.observe('red_sentry',False,False))
        assert 'enemies' not in frame and 'targets' not in frame
    finally:s.close()


def test_motion_request_revokes_before_chassis_measured_motion_and_restarts_dwell():
    gate=StationaryGate();o=sentry(xy=(-.6,-1.2))
    gate.update(o,'occupation');assert gate.update(replace(o,sim_time=.4),'occupation')
    assert not gate.update(replace(o,sim_time=.41),'engage',(.5,0.))
    assert gate.reason=='navigation_motion_requested' and gate.anchor is None
    assert not gate.update(replace(o,sim_time=.42),'occupation',(0.,0.))
    assert gate.update(replace(o,sim_time=.82),'occupation',(0.,0.))


@pytest.mark.parametrize('changes,reason',[
    (dict(episode=1),'episode_changed'),(dict(sim_time=.2),'time_reversed'),
    (dict(own_hp=float('nan')),'invalid_own_state'),(dict(sim_time=float('nan')),'invalid_own_state')])
def test_stationary_epoch_and_invalid_values_clear_active_segment(changes,reason):
    gate=StationaryGate();o=sentry(xy=(-.6,-1.2));gate.update(o,'occupation')
    assert gate.update(replace(o,sim_time=.4),'occupation')
    assert not gate.update(replace(o,**{'sim_time':.41,**changes}),'occupation')
    assert gate.reason==reason and not gate.active and gate.anchor is None


def test_real_wrapper_closes_before_restart_drive_and_negative_frame_revokes_fire(tmp_path):
    import io
    from rm_match.rmcs_stop_aim import RMCSStopAim
    from rm_match.match_engine import MatchSimulation
    from rm_match.integrations.own_gravity import OwnGravityCompensator
    from rm_match.match_controllers import MatchNavigationPolicy,compose_navigation_and_aim
    class Transport:
        closed=False
        def control(self,packet):
            return dict(tracking=True,should_control=True,should_shoot=True,target_age_s=0.,
                direction=[1.,0.,0.],direction_frame='world',detector_executed=packet['frame'] is not None,
                frame_stats=dict(accepted3d=0))
        def close(self):self.closed=True
    sim=MatchSimulation(render=False)
    try:
        o=sentry(t=.6,xy=(-.6,-1.2))
        a=RMCSStopAim.__new__(RMCSStopAim);a.gate=StationaryGate()
        a.gate.update(replace(o,sim_time=0.),'occupation');a.gate.update(replace(o,sim_time=.4),'occupation')
        client=Transport();a.client=client;a.last_bucket=-1;a.segment=1
        a.source_calls=a.tracking_ticks=a.fire_ticks=0;a.last_accepted_s=.59;a.latest_response=None
        a.out=tmp_path;a.gravity=OwnGravityCompensator(sim.model);a.events=[];a.last_status=None
        a.io=io.StringIO();a.error=None;a.capture=lambda obs:dict(frame_id=1)
        command=a.act(o,'occupation',(0.,0.))
        assert not command.fire and a.last_accepted_s is None and a.client is client
        # Real policy re-targets from a new pixel contact while odometry is still
        # stationary; the wrapper must close before these new forces are applied.
        p=MatchNavigationPolicy();p.decide(replace(o,sim_time=0.));p.decide(replace(o,sim_time=.4))
        rgb=np.zeros((240,320,3),np.uint8);rgb[110:130,157:164,2]=255
        o=replace(o,rgb=rgb,sim_time=.61);d=p.decide(o)
        assert np.linalg.norm(p.desired_velocity)>0 and d.mode=='engage'
        a.last_accepted_s=o.sim_time
        aim=a.act(o,d.mode,p.desired_velocity)
        combined=compose_navigation_and_aim(d.command,aim)
        assert client.closed and a.client is None and not combined.fire
        assert a.status=='navigation_motion_requested' and a.error is None
    finally:sim.close()


def test_candidate_lease_uses_selected_completion_exposure_not_any_3d_or_control_time():
    from rm_match.rmcs_stop_aim import update_visual_lease
    response=dict(completed_result_event=True,completed_result_observed_now=True,
        result_exposure_time_s=9.98,observation_shoot_allowed=True,detector_executed=True,frame_accepted=True,
        frame_stats=dict(accepted3d=4))
    assert update_visual_lease(response,{},10.,None,repaired=True)==9.98
    assert update_visual_lease({**response,'completed_result_observed_now':False},{},10.,9.97,repaired=True) is None
    assert update_visual_lease(response,None,10.1,9.97,repaired=True) is None
    assert update_visual_lease({**response,'completed_result_event':False},None,10.,9.97,repaired=True)==9.97
    assert update_visual_lease({**response,'completed_result_event':False,'observation_shoot_allowed':False},None,10.,9.97,repaired=True) is None
    legacy=dict(tracking=True,should_shoot=True,target_age_s=.01,direction=[1,0,0])
    assert not source_fire_allowed(legacy,sentry(t=10),9.99,require_observation_contract=True)[0]
