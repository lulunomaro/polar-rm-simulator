"""ROS envelope core with fake transport only, never actual DDS qualification."""
import io
import json
import pytest
from rm_match.integrations.ros2_bridge import (BridgeSettings,EnvelopeBridge,ENVELOPE_SCHEMA,
    JSONL_SCHEMA,BridgeError,serve)
from rm_match.platform_v2.aim_contracts import aim_status_for
from rm_match.platform_v2.contracts import ContractError
from rm_match.platform_v2.test_contracts import sample

def core():
    now=[1.];settings=BridgeSettings('custom_any_aim','aim','reviewed_aim',
        '/polar/any_aim/observation','/polar/any_aim/response',78,.08)
    c=EnvelopeBridge(settings,clock=lambda:now[0]);o=sample(True)
    c.reset({k:o[k] for k in ('episode','robot_id','binding_epoch')},{})
    return c,o,now

def envelope(o,status='no_target'):
    return json.dumps(dict(schema=ENVELOPE_SCHEMA,type='status',adapter_id='custom_any_aim',status=aim_status_for(o,status)))

def test_no_target_is_not_a_hold_action_or_algorithm_completion():
    c,o,now=core();c.begin(o);c.receive_action(envelope(o));result=c.poll()
    assert result==aim_status_for(o,'no_target') and 'command' not in result

def test_old_source_cannot_be_rebound_to_latest_observation():
    c,o,now=core();n=dict(o,observed_seq=o['observed_seq']+1);c.begin(n)
    with pytest.raises(ContractError):c.receive_action(envelope(o))
    c.receive_action(envelope(n,'pending_result'));assert c.poll()==aim_status_for(n,'pending_result')

def test_late_status_and_unknown_output_kind_rejected():
    c,o,now=core();c.begin(o);now[0]+=.08
    with pytest.raises(BridgeError,match='timeout'):c.receive_action(envelope(o))
    c,o,now=core();c.begin(o);value=json.loads(envelope(o));value['type']='target_state'
    with pytest.raises(ContractError):c.receive_action(json.dumps(value))

def test_jsonl_status_response_does_not_use_action_key():
    c,o,now=core()
    class Transport:
        def publish(self,payload):c.receive_action(envelope(json.loads(payload)['observation']))
        def spin_once(self,timeout):raise AssertionError('No fake polling success needed')
    request=dict(schema=JSONL_SCHEMA,op='act',observation=o);output=io.BytesIO()
    serve(c,Transport(),io.BytesIO((json.dumps(request)+'\n').encode()),output)
    assert json.loads(output.getvalue())==dict(schema=JSONL_SCHEMA,op='act',ok=True,status=aim_status_for(o,'no_target'))
