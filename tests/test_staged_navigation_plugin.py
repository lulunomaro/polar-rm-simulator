"""Protocol stages and source association; no real localization assertion."""
import copy
import io
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch
import pytest

from rm_match.deployment.navigation_plugin import (
    FEEDBACK_CAPABILITIES, GOAL_CAPABILITIES, validate_capabilities, same_typed_tree,
    MANIFEST_SCHEMA, register_navigation_plugins, navigation_status_for,
)
from rm_match.integrations.navigation_jsonl_peer import serve_navigation_plugin
from rm_match.integrations.ros2_bridge import JSONL_SCHEMA
from rm_match.platform_v2.adapters import Registry, BaseAdapter
from rm_match.platform_v2.contracts import IDENTITY, ContractError
from rm_match.platform_v2.navigation_feedback_contracts import unavailable_navigation_feedback
from test_navigation_plugin import observation
from test_active_goal_navigation_plugin import envelope, intent


def source(o):return {k:copy.deepcopy(o[k]) for k in IDENTITY}


def adapter(tmp_path):
    row=dict(adapter_id='custom_staged_navigation',label='Synthetic staged fixture',
        command=[sys.executable,'unused_fixture.py'],cwd='.',supported_robots=['blue_sentry'],
        transport='jsonl_v1',capabilities=copy.deepcopy(FEEDBACK_CAPABILITIES))
    path=tmp_path/'navigation.json'
    path.write_text(json.dumps(dict(schema=MANIFEST_SCHEMA,adapters=[row])))
    registry=Registry();register_navigation_plugins(registry,path)
    a=registry.create(row['adapter_id'],{});o=observation()
    BaseAdapter.reset(a,{k:o[k] for k in ('episode','robot_id','binding_epoch')})
    return a,o,registry


@pytest.mark.parametrize('key,value',[('schema','polar.sim.navigation-plugin.capabilities.v2'),
    ('feedback_mode','latest_pose'),('feedback_schema','unknown'),('goal_input_modes',[]),
    ('source_association','exact_capture_context_v1'),('extra',True)])
def test_explicit_v3_capability_cannot_downgrade(key,value):
    caps=copy.deepcopy(FEEDBACK_CAPABILITIES);caps[key]=value
    with pytest.raises(ContractError):validate_capabilities(caps)


def test_host_observe_then_compact_act_preserves_one_original_capture(tmp_path):
    a,o,registry=adapter(tmp_path);seen=[]
    expected=copy.deepcopy(o);current=intent(o)
    def exchange(packet,timeout):
        seen.append(copy.deepcopy(packet));assert 0<timeout<=.15
        if packet['op']=='observe':
            return dict(schema=JSONL_SCHEMA,op='observe',ok=True,
                feedback=unavailable_navigation_feedback(expected,'pending_localization'))
        assert set(packet)=={'op','source','intent'}
        assert same_typed_tree(packet['source'],source(expected)) and packet['intent']==current
        return dict(schema=JSONL_SCHEMA,op='act',ok=True,result=envelope(expected,current))
    a._exchange=exchange
    feedback=a.observe(o);assert feedback['source']==source(expected)
    returned=a.act_with_intent(o,current)
    assert returned==envelope(expected,current)['action']
    assert [row['op'] for row in seen]==['observe','act']
    assert seen[0]['observation']==expected and 'observation' not in seen[1]
    assert a._staged_observation is None
    with pytest.raises(ContractError,match='staged_observation_required'):a.act_with_intent(o,current)
    with pytest.raises(ContractError,match='replayed'):a.observe(o)
    assert registry.descriptors()[0]['navigation_plugin_capabilities']==FEEDBACK_CAPABILITIES


@pytest.mark.parametrize('change',[lambda o:o.update(episode=True),lambda o:o.update(wall_deadline=o['wall_deadline']+.1),
    lambda o:o['own'].update(hp=99.),lambda o:o['sensors']['pointcloud'].update(data_base64='')])
def test_act_cannot_change_any_original_staged_input(tmp_path,change):
    a,o,_=adapter(tmp_path)
    a._exchange=lambda packet,timeout:dict(schema=JSONL_SCHEMA,op='observe',ok=True,
        feedback=unavailable_navigation_feedback(o))
    a.observe(o);changed=copy.deepcopy(o);change(changed)
    with patch.object(a,'_exchange') as exchange:
        with pytest.raises(ContractError,match='staged_observation_required'):a.act_with_intent(changed,intent(o))
        exchange.assert_not_called()


def test_no_implicit_intent_never_emits_scan_or_motion(tmp_path):
    a,o,_=adapter(tmp_path)
    with patch.object(a,'_exchange') as exchange:
        assert a.act(o)==navigation_status_for(o)
        exchange.assert_not_called()
    with pytest.raises(ContractError):a.act_with_intent(o,intent(o))


def peer(requests,compute,profile='staged_scan_v1'):
    out=io.BytesIO()
    serve_navigation_plugin(compute,io.BytesIO(b''.join(json.dumps(r).encode()+b'\n' for r in requests)),out,
        goal_input_modes=['decision_intent_v1'],goal_result_profile=profile)
    return [json.loads(row) for row in out.getvalue().splitlines()]


def requests(o):
    return [dict(schema=JSONL_SCHEMA,op='reset',context={k:o[k] for k in ('episode','robot_id','binding_epoch')},config={}),
        dict(schema=JSONL_SCHEMA,op='observe',observation=o),
        dict(schema=JSONL_SCHEMA,op='act',source=source(o),intent=intent(o))]


class Compute:
    def __init__(self):self.calls=[]
    def observe(self,o):self.calls.append(('observe',copy.deepcopy(o)));return unavailable_navigation_feedback(o)
    def __call__(self,o,i):self.calls.append(('act',copy.deepcopy(o)));return envelope(o,i)


def test_peer_compact_act_uses_only_previously_observed_original_bytes():
    o=observation();o['wall_deadline']=17.;c=Compute()
    result=peer(requests(o),c)
    assert result[0]['capabilities']==FEEDBACK_CAPABILITIES
    assert result[1]['feedback']['source']==source(o)
    assert c.calls==[('observe',o),('act',o)] and result[2]['result']==envelope(o)


@pytest.mark.parametrize('bad',['no_stage','old_source','float_identity','duplicate_act','full_observation','duplicate_observe'])
def test_peer_rejects_missing_replayed_or_retagged_stages(bad):
    o=observation();rows=requests(o);c=Compute()
    if bad=='no_stage':rows.pop(1)
    elif bad=='old_source':rows[-1]['source']['observed_seq']-=1
    elif bad=='float_identity':rows[-1]['source']['episode']=float(o['episode'])
    elif bad=='duplicate_act':rows.append(copy.deepcopy(rows[-1]))
    elif bad=='duplicate_observe':rows.insert(2,copy.deepcopy(rows[1]))
    elif bad=='full_observation':rows[-1].pop('source');rows[-1]['observation']=o
    with pytest.raises(ContractError):peer(rows,c)


def test_legacy_profile_rejects_observe_operation():
    o=observation()
    with pytest.raises(ContractError,match='feedback_unsupported'):peer(requests(o)[:2],Compute(),'active_goal_v1')


def test_peer_ignores_stale_stage_when_new_scan_is_explicitly_observed():
    o=observation();later=copy.deepcopy(o);later['observed_seq']+=1
    later['wall_deadline']+=.01
    rows=requests(o);rows.insert(2,dict(schema=JSONL_SCHEMA,op='observe',observation=later))
    rows[-1]=dict(schema=JSONL_SCHEMA,op='act',source=source(later),intent=intent(later))
    c=Compute();result=peer(rows,c)
    assert c.calls[-1]==('act',later) and result[-1]['result']['source']==source(later)


def test_staged_local_emit_guard_runs_after_encoding_and_before_any_write(monkeypatch):
    from rm_match.integrations import navigation_jsonl_peer as module
    o=observation();c=Compute();events=[];out=io.BytesIO()
    original_encode=module.encode_json
    def encode(response,limit):
        raw=original_encode(response,limit)
        events.append(('encoded',response['op']))
        return raw
    def guard(response,encoded):
        assert events[-1]==('encoded',response['op'])
        assert json.loads(encoded)==response and encoded.endswith(b'\n')
        # The current response has not reached the stream yet.
        assert len(out.getvalue().splitlines())==len([e for e in events if e[0]=='guard'])
        events.append(('guard',response['op']))
        if response['op']=='act':raise ContractError('fixture_original_local_deadline_expired')
    c.before_emit=guard;monkeypatch.setattr(module,'encode_json',encode)
    data=b''.join(json.dumps(r).encode()+b'\n' for r in requests(o))
    with pytest.raises(ContractError,match='original_local_deadline_expired'):
        serve_navigation_plugin(c,io.BytesIO(data),out,
            goal_input_modes=['decision_intent_v1'],goal_result_profile='staged_scan_v1')
    assert [json.loads(r)['op'] for r in out.getvalue().splitlines()]==['reset','observe']
    assert events[-2:]==[('encoded','act'),('guard','act')]


def test_staged_emit_guard_must_be_callable_before_response_is_written():
    o=observation();c=Compute();c.before_emit=True;out=io.BytesIO()
    with pytest.raises(ContractError,match='emit_guard_callable_required'):
        serve_navigation_plugin(c,io.BytesIO(json.dumps(requests(o)[0]).encode()+b'\n'),out,
            goal_input_modes=['decision_intent_v1'],goal_result_profile='staged_scan_v1')
    assert out.getvalue()==b''
