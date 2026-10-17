"""Synthetic audit joins and actual MuJoCo revocation; no native qualification."""
import copy
from types import SimpleNamespace

import pytest
from rm_match.platform_v2.backend import MuJoCoBackend
from rm_match.platform_v2.contracts import action_for,build_observation
from rm_match.platform_v2.runtime import PlatformRuntime
from rm_match.platform_v2.test_control import Clock
from rm_match.platform_v2.test_runtime import FakeBackend,TestRegistry as Registry
from tests.test_wsl_native_live_classification import smoke,measured


def evidence():
    budget=dict(robot_id='alpha',episode=1,frame_id=2,capture_wall=100.,capture_sim_time=0.,wall_deadline=100.08,sim_deadline=.08)
    target=dict(motion=None,gimbal=dict(yaw_rad=.2,pitch_rad=.1),fire=False)
    receipt=dict(robot_id='alpha',episode=1,phase='integration_entry',budget=budget,
        consume_wall=100.06,consume_sim_time=.04,target=target)
    boundary=dict(episode=1,sim_time=.04,integration_start_wall=100.06,integration_call_wall=100.07,
        post_step_wall=100.09,targets={'alpha':copy.deepcopy(target)},output_budgets={'alpha':copy.deepcopy(budget)})
    ctrl=[0.,0.,0.,.2,.1]
    command=dict(force_x=0.,force_y=0.,yaw_torque=0.,gimbal_yaw=.2,gimbal_pitch=.1,fire=False)
    return receipt,boundary,ctrl,command


def test_valid_actual_call_before_original_deadline_even_if_completion_is_later():
    assert all(smoke.physical_integration_checks(*evidence()).values())


@pytest.mark.parametrize('fault',['actuator','integration','final_revoke','different_target','different_budget',
    'bool_episode','bool_frame','different_episode','different_sim','different_entry','late_call','regressed_call',
    'nan_call','bool_call','missing_call','wrong_ctrl','short_ctrl','nan_ctrl','fire','late_sim'])
def test_preparation_revocation_wrong_identity_and_late_actual_call_never_qualify(fault):
    r,b,ctrl,c=evidence()
    if fault in ('actuator','integration'):r['phase']=fault
    elif fault=='final_revoke':b['targets']['alpha']['gimbal']=None
    elif fault=='different_target':b['targets']['alpha']['gimbal']['yaw_rad']+=.1
    elif fault=='different_budget':b['output_budgets']['alpha']['frame_id']+=1
    elif fault=='bool_episode':r['episode']=True
    elif fault=='bool_frame':r['budget']['frame_id']=True
    elif fault=='different_episode':b['episode']+=1
    elif fault=='different_sim':b['sim_time']+=.002
    elif fault=='different_entry':r['consume_wall']+=.001
    elif fault=='late_call':b['integration_call_wall']=100.08
    elif fault=='regressed_call':b['integration_call_wall']=100.05
    elif fault=='nan_call':b['integration_call_wall']=float('nan')
    elif fault=='bool_call':b['integration_call_wall']=True
    elif fault=='missing_call':b.pop('integration_call_wall')
    elif fault=='wrong_ctrl':ctrl[3]+=.1
    elif fault=='short_ctrl':ctrl.pop()
    elif fault=='nan_ctrl':ctrl[3]=float('nan')
    elif fault=='fire':c['fire']=True
    elif fault=='late_sim':r['consume_sim_time']=b['sim_time']=.081
    assert not all(smoke.physical_integration_checks(r,b,ctrl,c).values())


@pytest.mark.parametrize('proof',[None,False,1,'true'])
def test_legacy_counts_alone_cannot_promote_live_qualification(proof):
    m=measured();m['physical_integration_evidence']=proof
    result=smoke.classify(m)
    assert not result['live_static_chain_qualified']
    assert 'physical_integration_evidence' in result['rejected_or_failed_criteria']


@pytest.mark.parametrize('revoke',[False,True])
def test_actual_mujoco_preparatory_write_is_not_physical_integration(revoke):
    clock=Clock();b=MuJoCoBackend();events=[];r=PlatformRuntime(b,clock=clock,registry=Registry(),trace=events.append)
    rid='red_sentry';r._episode=b.episode;r._schedule=lambda *_:None
    token=r.control.open_session('operator')['token'];epochs=r.control.claim(token,rid,['gimbal'])['lease_epochs']
    r.bind(token,rid,'aim',epochs,'aim',{})
    binding=r.control.snapshot()['bindings'][rid]['aim']
    o=build_observation(b.sensor_sample(rid),binding_epoch=binding['epoch'],observed_seq=1,wall_deadline=clock()+.08)
    r.outputs[rid,'aim']=action_for(o,'aim','gimbal_target',dict(frame='base_link',yaw_rad=.2,pitch_rad=.1,active=True,confidence=None,fire_permission=False))
    r.output_budgets[rid,'aim']=dict(robot_id=rid,episode=b.episode,frame_id=1,
        capture_wall=clock(),capture_sim_time=b.sim_time,wall_deadline=clock()+.08,sim_deadline=b.sim_time+.08)
    original=b.guarded_step
    def wrapped(targets,guard,**kw):
        def before_call():
            if revoke:clock.advance(.081)
            return clock()
        return original(targets,guard,clock=before_call)
    b.guarded_step=wrapped
    try:
        r.step_once()
        receipts=[e for e in events if e['event']=='actuator_consumed' and e['robot_id']==rid]
        first=next(e for e in receipts if e['phase']=='actuator')
        entry=next(e for e in receipts if e['phase']=='integration_entry')
        boundary=next(e for e in events if e['event']=='integration_boundary')
        ctrl=b._sim.data.ctrl[b._sim.aindices[rid]].tolist();command=b.last_commands[rid]
        assert first['target']['gimbal'] is not None
        assert not all(smoke.physical_integration_checks(first,boundary,ctrl,command).values())
        assert all(smoke.physical_integration_checks(entry,boundary,ctrl,command).values()) is not revoke
        assert (entry['target']['gimbal'] is None) is revoke
        assert b.sim_time==pytest.approx(.002)
    finally:r.close()


@pytest.mark.parametrize('outcome',['accepted','late_wall','late_sim','binding_changed','adapter_error','discarded','invalid'])
def test_collector_disposition_samples_original_wall_and_current_sim_without_changing_authority(outcome):
    clock=Clock();b=FakeBackend(('alpha',));events=[];r=PlatformRuntime(b,clock=clock,registry=Registry(),trace=events.append)
    r._episode=b.episode;token=r.control.open_session('operator')['token'];epochs=r.control.claim(token,'alpha',['gimbal'])['lease_epochs']
    r.bind(token,'alpha','aim',epochs,'aim',{})
    snapshot=r.control.snapshot();binding=copy.deepcopy(snapshot['bindings']['alpha']['aim'])
    o=build_observation(b.sensor_sample('alpha'),binding_epoch=binding['epoch'],observed_seq=1,wall_deadline=clock()+.08)
    budget=dict(robot_id='alpha',episode=b.episode,frame_id=1,capture_wall=clock(),capture_sim_time=b.sim_time,wall_deadline=clock()+.08,sim_deadline=b.sim_time+.08)
    value=action_for(o,'aim','gimbal_target',dict(frame='base_link',yaw_rad=.2,pitch_rad=.1,active=True,confidence=None,fire_permission=False))
    result=dict(job=dict(observation=o,binding=binding,sensor_budget=budget),value=value,error=None,completed=clock())
    sim_time=0.
    reason='accepted'
    if outcome=='late_wall':clock.advance(.08);reason='late_result'
    elif outcome=='late_sim':sim_time=.081;reason='late_result'
    elif outcome=='binding_changed':snapshot['bindings']['alpha']['aim']['epoch']+=1;reason='binding_changed'
    elif outcome=='adapter_error':result['error']='named_test_failure';reason='adapter_error'
    elif outcome=='discarded':result['discarded_reason']='test';reason='sample_discarded'
    elif outcome=='invalid':value['robot_id']='other';reason='invalid_result'
    # Publication deliberately crosses the old wall deadline. Its timestamp must
    # remain separate from the existing collection decision sample.
    original=r._trace
    def trace(event,**fields):
        if event=='adapter_result_disposition':clock.advance(.1)
        original(event,**fields)
    r._trace=trace;r.slots['alpha','aim']=SimpleNamespace(poll=lambda:result,close=lambda:None)
    sampled=clock()
    try:
        r._collect(snapshot,sim_time)
        row=next(e for e in events if e['event']=='adapter_result_disposition')
        assert row['reason']==reason and row['collect_sample_wall']==sampled and row['collect_sim_time']==sim_time
        assert row['wall_time']>row['collect_sample_wall'] and row['sensor_budget']==budget
        assert ('alpha','aim') in r.outputs if outcome=='accepted' else ('alpha','aim') not in r.outputs
        assert not {'operator_authorization','exception_diagnostic','command'} & row.keys()
    finally:r.slots.clear();r.close()
