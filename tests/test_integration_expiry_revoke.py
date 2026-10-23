"""Actual MuJoCo source expiry after entry, before integration; no NN claim."""
import pytest
from rm_match.platform_v2.backend import MuJoCoBackend
from rm_match.platform_v2.runtime import PlatformRuntime
from rm_match.platform_v2.test_control import Clock
from rm_match.platform_v2.test_runtime import TestRegistry as Registry
from rm_match.platform_v2.contracts import build_observation,action_for


@pytest.mark.parametrize('servo',['position','position_gravity_v1'])
@pytest.mark.parametrize('boundary',['early','exact','late'])
@pytest.mark.parametrize('expiry',['source','output','activation','lease'])
def test_source_expiring_after_uniform_entry_is_revoked_in_actual_command(servo,boundary,expiry):
    late=boundary!='early'
    clock=Clock();b=MuJoCoBackend(gimbal_servo=servo);events=[]
    r=PlatformRuntime(b,clock=clock,registry=Registry(),trace=events.append)
    rid='red_sentry';r._episode=b.episode;r._schedule=lambda *_:None
    token=r.control.open_session('operator')['token'];epochs=r.control.claim(token,rid,['gimbal'])['lease_epochs']
    r.bind(token,rid,'aim',epochs,'aim',{})
    delta=.08 if expiry=='source' else .04
    if expiry=='activation':
        state=r.control.bindings[rid,'aim'];state.activation_required=True;state.activation_seq=0;state.activation_expires=clock()+delta
    if expiry=='lease':r.control.leases[rid,'gimbal'].expires=clock()+delta
    binding=r.control.snapshot()['bindings'][rid]['aim']
    o=build_observation(b.sensor_sample(rid),binding_epoch=binding['epoch'],observed_seq=1,wall_deadline=clock()+(delta if expiry=='output' else .15))
    r.outputs[rid,'aim']=action_for(o,'aim','gimbal_target',dict(frame='base_link',yaw_rad=.2,pitch_rad=.1,active=True,confidence=None,fire_permission=False))
    r.output_budgets[rid,'aim']=dict(robot_id=rid,episode=b.episode,frame_id=1,capture_wall=clock(),capture_sim_time=0.,wall_deadline=clock()+.08,sim_deadline=.08)
    before=b.own_pose(rid);original=b.guarded_step
    def delayed(targets,guard,**kwargs):
        samples=[0]
        def integration_clock():
            samples[0]+=1
            if samples[0]==2:clock.advance(delta+{'early':-.001,'exact':0.,'late':.001}[boundary])
            return clock()
        return original(targets,guard,clock=integration_clock)
    b.guarded_step=delayed
    try:
        r.step_once()
        receipts=[e for e in events if e['event']=='actuator_consumed' and e['robot_id']==rid]
        entry=next(e for e in receipts if e['phase']=='integration_entry')
        assert entry['target']['gimbal'] is not None and entry['consume_wall']<o['wall_deadline']
        revokes=[e for e in receipts if e['phase']=='integration_expired']
        assert bool(revokes) is late
        target=r.cached['applied_targets'][rid]
        assert (target['gimbal'] is None) is late
        assert b.last_commands[rid]['gimbal_yaw']==pytest.approx(before['gimbal_yaw'] if late else .2)
        if servo=='position':assert b.last_commands[rid]['gimbal_pitch']==pytest.approx(before['gimbal_pitch'] if late else .1)
        else:
            raw=b._gimbal_servo.last[rid]
            assert raw['raw_pitch_rad']==pytest.approx(before['gimbal_pitch'] if late else .1)
            assert raw['yaw_feedback_enabled'] is not late
        assert b.sim_time==pytest.approx(.002)
        assert not any(e['event']=='actuator_consumed' and e['phase']=='integration_expired' and e['robot_id']!=rid for e in events)
    finally:r.close()


def test_expired_manual_motion_does_not_clear_still_authorized_gimbal():
    clock=Clock();b=MuJoCoBackend();r=PlatformRuntime(b,clock=clock,registry=Registry())
    rid='red_sentry';r._episode=b.episode;r._schedule=lambda *_:None
    token=r.control.open_session('operator')['token'];r.control.claim(token,rid,['motion','gimbal'])
    motion=r.control.leases[rid,'motion'];motion.input=dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=0.);motion.input_expires=clock()+.04
    gimbal=r.control.leases[rid,'gimbal'];gimbal.input=dict(frame='base_link',yaw_rad=.2,pitch_rad=.1);gimbal.input_expires=clock()+.15
    original=b.guarded_step
    def delayed(targets,guard,**kwargs):
        calls=[0]
        def sample():
            calls[0]+=1
            if calls[0]==2:clock.advance(.041)
            return clock()
        return original(targets,guard,clock=sample)
    b.guarded_step=delayed
    try:
        r.step_once();c=b.last_commands[rid]
        assert c['force_x']==c['force_y']==c['yaw_torque']==0.
        assert c['gimbal_yaw']==pytest.approx(.2) and c['gimbal_pitch']==pytest.approx(.1)
        assert r.cached['applied_targets'][rid]['motion'] is None
        assert r.cached['applied_targets'][rid]['gimbal'] is not None
    finally:r.close()


def test_broken_trusted_expiry_hint_cannot_spin_or_enter_physics():
    from rm_match.contracts import Command
    b=MuJoCoBackend();rid='red_sentry';sim=b._sim;calls=[]
    def guard(r,c,phase,*args):calls.append((r,phase));return c
    guard.integration_deadlines={rid:0.}
    try:
        with pytest.raises(RuntimeError,match='made no progress'):
            sim.step({rid:Command(gimbal_yaw=.2)},command_guard=guard,integration_clock=lambda:1.)
        assert sim.time==0. and sum(phase=='integration_expired' for _,phase in calls)==3*len(sim.robot_ids)
    finally:b.close()


def test_expiry_pass_cannot_spawn_an_extra_projectile():
    from rm_match.contracts import Command
    b=MuJoCoBackend();sim=b._sim;rid='red_sentry';fires=[];times=iter([0.,1.,1.,1.])
    def guard(r,c,phase,*args):
        if phase=='integration_expired':
            guard.integration_deadlines.pop(r,None)
            return Command()
        return c
    guard.integration_deadlines={rid:.5}
    original=sim._fire;sim._fire=lambda r:fires.append(r)
    try:
        sim.step({rid:Command(fire=True)},command_guard=guard,integration_clock=lambda:next(times))
        assert fires==[rid] and sim.commands[rid].fire is False and sim.time==pytest.approx(.002)
    finally:sim._fire=original;b.close()
