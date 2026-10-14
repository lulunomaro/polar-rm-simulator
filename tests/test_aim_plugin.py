"""Interface/unit checks, not detector or live-camera qualification."""
import copy
import json
import sys
from unittest.mock import patch
import pytest
from rm_match.deployment.aim_plugin import (CAPABILITIES,MANIFEST_SCHEMA,
    load_aim_plugins,register_aim_plugins,validate_capabilities)
from rm_match.deployment.json_adapter import SCHEMA as JSONL_SCHEMA
from rm_match.platform_v2.adapters import Registry,BaseAdapter
from rm_match.platform_v2.contracts import ContractError,IDENTITY,action_for
from rm_match.platform_v2.test_contracts import sample

def manifest(tmp_path):
    row=dict(adapter_id='custom_unrelated_team_aim',label='Reviewed interface; detector not qualified',
        command=[sys.executable,'-u','reviewed_wrapper.py'],cwd='.',supported_robots=['red_infantry'],
        transport='jsonl_v1',capabilities=copy.deepcopy(CAPABILITIES))
    path=tmp_path/'plugins.json';path.write_text(json.dumps(dict(schema=MANIFEST_SCHEMA,adapters=[row])))
    return path,row

def adapter(tmp_path):
    path,row=manifest(tmp_path);registry=Registry();register_aim_plugins(registry,path,clock=lambda:1.)
    a=registry.create(row['adapter_id'],{});o=sample(True)
    BaseAdapter.reset(a,{k:o[k] for k in ('robot_id','episode','binding_epoch')})
    return a,o,registry,path

def action(o):
    return action_for(o,'aim','gimbal_target',dict(frame='base_link',yaw_rad=.2,pitch_rad=.1,
        active=True,confidence=None,fire_permission=False))

def test_registration_is_detached_and_has_negotiable_camera_contract(tmp_path):
    a,o,r,p=adapter(tmp_path);d=r.descriptors()[0]
    assert d['aim_plugin_contract']=='camera_gimbal_v1' and d['required_sensors']==['camera']
    assert d['ui_config_contract']=='empty_v1' and d['fire_authority']=='manual_only'
    d['aim_plugin_capabilities']['image_encodings'].clear()
    assert r.descriptors()[0]['aim_plugin_capabilities']==CAPABILITIES
    with pytest.raises(ContractError):r.create('custom_unrelated_team_aim',{'command':['bad']})

@pytest.mark.parametrize('key,value',[('sensor_profile','world_truth'),('action_schema','unknown'),
    ('image_encodings',['jpeg']),('fire_authority','algorithm_fire'),('unknown',True)])
def test_unknown_capabilities_rejected_before_registration(tmp_path,key,value):
    path,row=manifest(tmp_path);row['capabilities'][key]=value
    path.write_text(json.dumps(dict(schema=MANIFEST_SCHEMA,adapters=[row])))
    r=Registry()
    with pytest.raises(ContractError):register_aim_plugins(r,path)
    assert r.descriptors()==[]

def test_manifest_snapshot_changed_before_spawn_rejected(tmp_path):
    a,o,r,p=adapter(tmp_path);p.write_bytes(p.read_bytes()+b' ')
    with patch('rm_match.deployment.json_adapter.OwnedJsonProcess') as spawn:
        with pytest.raises(ContractError,match='manifest_changed'):a.reset(a.context)
        spawn.assert_not_called()

def test_capture_metadata_and_pixels_preserved_separately_from_current_own(tmp_path):
    a,o,r,p=adapter(tmp_path);original=copy.deepcopy(o)
    o['own']['qpos'][3]=.6;o['sensors']['camera']['own_qpos_at_capture'][3]=.1
    def exchange(packet,timeout):
        a._validate_response(dict(schema=JSONL_SCHEMA,op='act',ok=True,action=action(packet['observation'])),packet)
        seen=packet['observation'];assert seen['own']['qpos'][3]==.6
        assert seen['sensors']['camera']['own_qpos_at_capture'][3]==.1
        assert seen['sensors']['camera']['image']==original['sensors']['camera']['image']
        assert seen['sensors']['camera']['intrinsics']==original['sensors']['camera']['intrinsics']
        assert 'robots' not in seen and 'enemy_positions' not in seen
        return dict(action=action(seen))
    a._exchange=exchange;result=a.act(o)
    assert result==action(o) and result['command']['confidence'] is None

@pytest.mark.parametrize('mutate',[lambda o:o['sensors'].update(camera={'available':False,'reason':'no_frame'}),
    lambda o:o['sensors']['camera']['intrinsics'].update(fx=0),
    lambda o:o['sensors']['camera'].update(own_qpos_at_capture=[0]),
    lambda o:o.update(enemy_positions=[[1,2]])])
def test_invalid_or_missing_camera_never_reaches_plugin(tmp_path,mutate):
    a,o,r,p=adapter(tmp_path);mutate(o)
    with patch.object(a,'_exchange') as exchange:
        with pytest.raises(ContractError):a.act(o)
        exchange.assert_not_called()

def test_old_epoch_and_ambiguous_action_plus_status_rejected(tmp_path):
    a,o,r,p=adapter(tmp_path);value=action(o);value['binding_epoch']+=1
    with pytest.raises(ContractError):a._validate_response(dict(schema=JSONL_SCHEMA,op='act',ok=True,action=value),dict(op='act',observation=o))
    with pytest.raises(ContractError):a._validate_response(dict(schema=JSONL_SCHEMA,op='act',ok=True,action=action(o),status={}),dict(op='act',observation=o))

def test_no_target_is_typed_no_action_and_preserves_identity(tmp_path):
    a,o,r,p=adapter(tmp_path)
    status=dict(schema='polar.sim.aim-status.v1',**{k:o[k] for k in IDENTITY},kind='aim',status='no_target')
    response=dict(schema=JSONL_SCHEMA,op='act',ok=True,status=status)
    a._validate_response(response,dict(op='act',observation=o));a._exchange=lambda packet,timeout:response
    result=a.act(o);assert result==status and 'command' not in result
