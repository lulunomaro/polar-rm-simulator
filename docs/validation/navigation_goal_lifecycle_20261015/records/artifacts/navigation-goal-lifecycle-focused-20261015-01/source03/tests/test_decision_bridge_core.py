from concurrent.futures import Future
from dataclasses import replace
import pytest
from test_opening_strategy import sentry
from rm_match.decision_bridge_core import DecisionBridgeCore


def answer(x=1.,y=0.):return dict(decision=dict(behavior='ENGAGE',target_point=dict(x=x,y=y),reason='test'),source='fake_transport_NOT_LLM')

class Submit:
    def __init__(self):self.calls=[];self.futures=[]
    def __call__(self,p):
        self.calls.append(p);f=Future();f.set_running_or_notify_cancel();self.futures.append(f);return f


def test_slow_tactical_future_cannot_delay_opening_or_state_callbacks():
    submit=Submit();core=DecisionBridgeCore(submit)
    assert core.on_observation(sentry(),now=0).source=='deterministic_opening'
    assert submit.calls==[]
    assert core.on_observation(sentry(t=12,xy=(.2,-1.)),now=12).source=='occupation_hold'
    assert len(submit.calls)==1
    for i in range(1,20):
        out=core.on_observation(sentry(t=12+i*.1,xy=(.2,-1.)),now=12+i*.1)
        assert out.source=='occupation_hold'
    assert not submit.futures[0].done()


@pytest.mark.parametrize('change',[dict(match_phase='paused'),dict(match_phase='finished'),dict(own_hp=0),dict(emergency_stop=True)])
def test_late_tactical_result_after_safety_change_is_discarded(change):
    submit=Submit();core=DecisionBridgeCore(submit)
    center=sentry(xy=(0.,0.));core.on_observation(center,now=0)
    assert core.on_observation(replace(center,sim_time=.1,**change),now=.1).stop_required
    submit.futures[0].set_result(answer())
    out=core.on_observation(replace(center,sim_time=.2),now=.2)
    if change.get('match_phase')=='finished':assert out.stop_required
    else:
        assert out.source=='occupation_hold'
        assert any(e.get('reason')=='invalid_generation' for e in core.events)


def test_expired_pose_drift_and_bad_goal_are_rejected():
    for now,xy,result,reason in [(6.,(0.,0.),answer(),'expired_result'),
                               (.2,(1.2,0.),answer(),'pose_drift'),
                               (.2,(0.,0.),answer(float('nan')),'ValueError'),
                               (.2,(0.,0.),answer(7.),'ValueError')]:
        submit=Submit();core=DecisionBridgeCore(submit)
        core.on_observation(sentry(xy=(0.,0.)),now=0);submit.futures[0].set_result(result)
        out=core.on_observation(sentry(t=now,xy=xy),now=now)
        assert out.source=='occupation_hold'
        assert any(e.get('reason')==reason for e in core.events)


def test_fresh_valid_result_accepted_but_watchdog_always_stops():
    submit=Submit();core=DecisionBridgeCore(submit)
    core.on_observation(sentry(xy=(0.,0.)),now=0);submit.futures[0].set_result(answer())
    out=core.on_observation(sentry(t=.1,xy=(0.,0.)),now=.1)
    assert out.source=='fake_transport_NOT_LLM' and out.goal['target_point']['x']==1.
    assert core.tick(now=.5)==out
    assert core.tick(now=.8).stop_required
    assert core.cached is None


def test_reset_and_out_of_order_state_do_not_reuse_old_result():
    submit=Submit();core=DecisionBridgeCore(submit)
    core.on_observation(sentry(t=20,xy=(0.,0.)),now=20)
    assert core.on_observation(sentry(t=19,xy=(0.,0.)),now=20.1).stop_required
    submit.futures[0].set_result(answer())
    assert core.on_observation(sentry(episode=1),now=21).source=='deterministic_opening'
    assert core.opening.started_at==0.


def test_unknown_missing_control_stage_is_never_opening():
    submit=Submit();core=DecisionBridgeCore(submit)
    assert core.on_observation(replace(sentry(),match_phase='EARLY'),now=0).stop_required
    assert core.opening.started_at is None and submit.calls==[]
