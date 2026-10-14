"""Pose-free protocol/harmless process fixtures, not navigation qualification."""
import base64
import copy
import io
import json
from pathlib import Path
import struct
import sys
import time
from unittest.mock import patch
import pytest
from rm_match.deployment.navigation_plugin import (CAPABILITIES, MANIFEST_SCHEMA,
    register_navigation_plugins, navigation_status_for, validate_capabilities)
from rm_match.integrations.navigation_jsonl_peer import serve_navigation_plugin
from rm_match.deployment.json_adapter import SCHEMA as JSONL_SCHEMA
from rm_match.platform_v2.adapters import Registry, BaseAdapter
from rm_match.platform_v2.contracts import ContractError, action_for
from rm_match.platform_v2.navigation_contracts import NAV_SCHEMA, NAV_FRAMES, POINT_ENCODING


def observation():
    ext = dict(parent_frame='base_link', translation_m=[0., 0., .5], rotation_xyzw=[0., 0., 0., 1.], calibration_id='fixture_mount')
    return dict(schema=NAV_SCHEMA, robot_id='blue_sentry', episode=2, binding_epoch=3, observed_seq=1,
        sim_time=.1, wall_deadline=time.perf_counter()+.15, frames=dict(NAV_FRAMES),
        own=dict(team='blue', role='sentry', hp=100., ammo=10., heat=0., alive=True),
        referee=dict(phase='running', remaining_seconds=299., emergency_stop=False),
        sensors=dict(pointcloud=dict(available=True, reason='available', frame_id=1, acquisition_start_ns=0,
            acquisition_end_ns=100000000, capture_sim_time=.1, frame='livox_frame', encoding=POINT_ENCODING,
            point_count=1, data_base64=base64.b64encode(struct.pack('<fffIBBBx', 1., 0., 0., 0, 24, 0x10, 0)).decode(),
            range_min_m=.1, range_max_m=20., time_quantization_ns=2000000,
            provenance='mujoco_ray_cast_nonrepeating_profile_v1', profile_sha256='1'*64, extrinsics=ext),
            imu=dict(available=True, reason='available', frame='livox_frame', capture_sim_time=.1,
                extrinsics=copy.deepcopy(ext), provenance='mujoco_gyro_accelerometer_v1', samples=[dict(
                    sample_sim_ns=t, angular_velocity_rps=[.1,.2,.3], linear_acceleration_mps2=[0.,0.,9.81]) for t in (0,100000000)])))


def action(o):
    return action_for(o, 'navigation', 'velocity_body', dict(frame='base_link', vx_mps=.2, vy_mps=.1, wz_rps=.3))


def manifest(tmp_path, *, goals=False, command=None):
    caps = copy.deepcopy(CAPABILITIES)
    if goals: caps['goal_input_modes'] = ['decision_intent_v1']
    row = dict(adapter_id='custom_other_navigation', label='Synthetic interface fixture',
        command=command or [sys.executable, '-u', 'reviewed_wrapper.py'], cwd='.',
        supported_robots=['blue_sentry', 'red_infantry'], transport='jsonl_v1', capabilities=caps)
    path = tmp_path/'navigation.json'
    path.write_text(json.dumps(dict(schema=MANIFEST_SCHEMA, adapters=[row])), encoding='utf8')
    return path, row


def adapter(tmp_path, **kw):
    path, row = manifest(tmp_path, **kw); registry = Registry()
    register_navigation_plugins(registry, path)
    a = registry.create(row['adapter_id'], {}); o = observation()
    BaseAdapter.reset(a, {k:o[k] for k in ('robot_id','episode','binding_epoch')})
    return a, o, registry, path


def request_rows(o):
    return [dict(schema=JSONL_SCHEMA,op='reset',context={k:o[k] for k in ('robot_id','episode','binding_epoch')},config={}),
        dict(schema=JSONL_SCHEMA,op='act',observation=o)]


def peer(rows, compute, *, goals=False):
    out = io.BytesIO()
    serve_navigation_plugin(compute, io.BytesIO(b''.join(json.dumps(r).encode()+b'\n' for r in rows)), out,
        goal_input_modes=['decision_intent_v1'] if goals else [])
    return [json.loads(r) for r in out.getvalue().splitlines()]


def test_multiple_robots_detached_caps_empty_http_config(tmp_path):
    a,o,r,p = adapter(tmp_path)
    d = r.descriptors()[0]
    assert d['observation_profile']=='pointcloud_imu_v1' and d['supported_robots']==['blue_sentry','red_infantry']
    d['navigation_plugin_capabilities']['output_modes'].clear()
    assert r.descriptors()[0]['navigation_plugin_capabilities']==CAPABILITIES
    with pytest.raises(ContractError): r.create('custom_other_navigation', {'goal':[1,2]})
    with patch.object(a, '_open_owned_process') as spawn:
        with pytest.raises(ContractError, match='robot_unsupported'): a.reset(dict(a.context,robot_id='red_sentry'))
        spawn.assert_not_called()


@pytest.mark.parametrize('key,value', [('sensor_profile','ideal_odom'),('source_association','latest'),
    ('fire_authority','algorithm'),('goal_input_modes',['arbitrary_goal']),('output_modes',['gimbal_target']),('extra',True)])
def test_unknown_capabilities_fail_closed(tmp_path,key,value):
    path,row = manifest(tmp_path); row['capabilities'][key]=value
    path.write_text(json.dumps(dict(schema=MANIFEST_SCHEMA,adapters=[row])))
    registry=Registry()
    with pytest.raises(ContractError): register_navigation_plugins(registry,path)
    assert registry.descriptors()==[]


def test_reset_capability_handshake_strict_and_manifest_change_before_spawn(tmp_path):
    a,o,r,p=adapter(tmp_path);packet=dict(op='reset')
    reply=dict(schema=JSONL_SCHEMA,op='reset',ok=True,capabilities=copy.deepcopy(CAPABILITIES))
    a._validate_response(reply,packet)
    reply['capabilities']['goal_input_modes']=['decision_intent_v1']
    with pytest.raises(ContractError,match='capabilities_mismatch'):a._validate_response(reply,packet)
    del reply['capabilities']
    with pytest.raises(ContractError):a._validate_response(reply,packet)
    p.write_bytes(p.read_bytes()+b' ')
    with patch('rm_match.deployment.json_adapter.OwnedJsonProcess') as spawn:
        with pytest.raises(ContractError,match='manifest_changed'):a.reset(a.context)
        spawn.assert_not_called()


def test_velocity_receives_original_sensor_bytes_not_pose(tmp_path):
    a,o,r,p=adapter(tmp_path);expected=copy.deepcopy(o)
    def exchange(packet,timeout):
        assert packet['observation']==expected and 'intent' not in packet
        assert set(packet['observation']['own'])=={'team','role','hp','ammo','heat','alive'}
        assert 0<timeout<=.15
        result=dict(schema=JSONL_SCHEMA,op='act',ok=True,action=action(expected))
        a._validate_response(result,packet)
        return result
    a._exchange=exchange
    assert a.act(o)==action(o)


def test_goal_aware_without_intent_never_computes_or_spawns(tmp_path):
    a,o,r,p=adapter(tmp_path,goals=True)
    with patch.object(a,'_exchange') as exchange:
        assert a.act(o)==navigation_status_for(o)
        exchange.assert_not_called()
    with pytest.raises(ContractError):a.act_with_intent(o,None)
    result=peer(request_rows(o),lambda *args:pytest.fail('no implicit goal'),goals=True)
    assert result[-1]['status']==navigation_status_for(o)


def test_peer_preserves_clock_and_rejects_callback_mutation_stale_generation_and_replay():
    o=observation();o['wall_deadline']=17. # Opaque foreign monotonic; not compared to peer clock.
    def compute(current,intent):
        assert intent is None and current==o
        return action(current)
    rows=request_rows(o);result=peer(rows,compute)
    assert result[0]['capabilities']==CAPABILITIES and result[-1]['action']==action(o)
    rows.append(rows[-1])
    with pytest.raises(ContractError,match='replayed'):peer(rows,compute)
    def mutate(current,intent):
        current['binding_epoch']+=1
        return action(current)
    with pytest.raises(ContractError):peer(request_rows(o),mutate)
    rows=request_rows(o);rows[0]['context']['episode']=True
    with pytest.raises(ContractError):peer(rows,compute)


@pytest.mark.parametrize('bad', ['none','fire','old','float_identity','both'])
def test_response_cannot_add_fire_or_loosen_original_identity(tmp_path,bad):
    a,o,r,p=adapter(tmp_path);value=action(o)
    if bad=='none':value=None
    elif bad=='fire':value['command']['fire']=True
    elif bad=='old':value['binding_epoch']+=1
    elif bad=='float_identity':value['sim_time']=1 # Different float/int exact type, not permissive numeric echo.
    response=dict(schema=JSONL_SCHEMA,op='act',ok=True,action=value)
    if bad=='both':response['status']=navigation_status_for(o)
    with pytest.raises(ContractError):a._validate_response(response,dict(op='act',observation=o))


def test_peer_prepare_and_strict_json_partial_duplicate_extra():
    o=observation();prepare=dict(schema=JSONL_SCHEMA,op='prepare',config={})
    result=peer([prepare]+request_rows(o),lambda o,i:navigation_status_for(o,'pending_localization'))
    assert result[0]==dict(schema=JSONL_SCHEMA,op='prepare',ok=True)
    with pytest.raises(ContractError):peer([prepare,prepare],lambda *a:None)
    with pytest.raises(ContractError):peer([request_rows(o)[1]],lambda *a:None)
    for raw in (b'{"schema":"x","schema":"x"}\n',b'{}',b'{"schema":NaN}\n'):
        with pytest.raises(ContractError):serve_navigation_plugin(lambda *a:None,io.BytesIO(raw),io.BytesIO())


def test_actual_owned_jsonl_child_reset_action_and_clean_shutdown(tmp_path):
    root=Path(__file__).resolve().parents[1];wrapper=tmp_path/'fixture.py'
    wrapper.write_text('import os,sys\nsys.path.insert(0,'+repr(str(root))+')\n'
        'from rm_match.integrations.navigation_jsonl_peer import run_navigation_plugin\n'
        'from rm_match.deployment.navigation_plugin import navigation_status_for\n'
        'def factory():\n'
        ' os.write(1,b"synthetic library startup\\n")\n'
        ' def compute(o,intent):\n'
        '  print("synthetic callback",flush=True)\n'
        '  return navigation_status_for(o,"pending_localization")\n'
        ' return compute\n'
        'raise SystemExit(run_navigation_plugin(factory))\n',encoding='utf8')
    a,o,r,p=adapter(tmp_path,command=[sys.executable,'-u',str(wrapper)])
    try:
        a.reset(a.context)
        o['wall_deadline']=time.perf_counter()+.15
        assert a.act(o)==navigation_status_for(o,'pending_localization')
    finally:a.close()
    assert a.shutdown_status['clean'] is True


@pytest.mark.parametrize('command', [dict(behavior='hold',reason='explicit_wait'),
    dict(behavior='cancel',reason='explicit_cancel'),
    dict(behavior='navigate_to_pose',reason='policy_goal',goal=dict(frame='map',position_m=[1.,2.],yaw_rad=.1))])
def test_explicit_decision_intent_same_request_original_deadline(tmp_path,command):
    from rm_match.platform_v2.decision_contracts import build_decision_observation, decision_intent_for
    a,o,r,p=adapter(tmp_path,goals=True)
    intent=decision_intent_for(build_decision_observation(o),command)
    seen=[]
    def compute(current,received):
        assert current==o and received==intent
        seen.append(received)
        return navigation_status_for(current,'pending_localization')
    rows=request_rows(o);rows[-1]['intent']=intent
    assert peer(rows,compute,goals=True)[-1]['status']==navigation_status_for(o,'pending_localization')
    def exchange(packet,timeout):
        assert packet['intent']==intent and packet['observation']['wall_deadline']==intent['wall_deadline']
        return dict(status=navigation_status_for(o,'pending_localization'))
    a._exchange=exchange
    assert a.act_with_intent(o,intent)==navigation_status_for(o,'pending_localization')
    assert len(seen)==1
    ordinary,plain,_,_=adapter(tmp_path)
    with pytest.raises(ContractError,match='goal_input_unsupported'):ordinary.act_with_intent(plain,intent)
    with pytest.raises(ContractError,match='goal_input_unsupported'):peer(rows,compute)


@pytest.mark.parametrize('change', [dict(binding_epoch=4),dict(observed_seq=2),dict(wall_deadline=1.),dict(episode=True)])
def test_stale_or_type_confused_intent_never_reaches_compute(tmp_path,change):
    from rm_match.platform_v2.decision_contracts import build_decision_observation, decision_intent_for
    a,o,r,p=adapter(tmp_path,goals=True)
    intent=decision_intent_for(build_decision_observation(o),dict(behavior='hold',reason='explicit'))
    intent.update(change)
    with patch.object(a,'_exchange') as exchange:
        with pytest.raises(ContractError):a.act_with_intent(o,intent)
        exchange.assert_not_called()
    rows=request_rows(o);rows[-1]['intent']=intent
    with pytest.raises(ContractError):peer(rows,lambda *a:pytest.fail('invalid intent called algorithm'),goals=True)


def test_composed_absolute_deadlines_forwarded_without_new_budget(tmp_path):
    from rm_match.deployment.json_adapter import JsonLineAdapter
    a,o,r,p=adapter(tmp_path)
    with patch.object(JsonLineAdapter,'reset') as reset:
        a.reset(a.context,deadline=123.)
        reset.assert_called_once_with(a.context,deadline=123.)
    with patch.object(JsonLineAdapter,'close') as close:
        a.close(deadline=456.)
        close.assert_called_once_with(deadline=456.)


def test_invalid_reset_context_rejected_before_process_launch(tmp_path):
    a,o,r,p=adapter(tmp_path)
    with patch.object(a,'_open_owned_process') as spawn:
        with pytest.raises(ContractError):a.reset(dict(a.context,episode=True))
        with pytest.raises(ContractError):a.reset(dict(a.context,extra='argv'))
        spawn.assert_not_called()


def stop_intent(o, behavior):
    from rm_match.platform_v2.decision_contracts import build_decision_observation, decision_intent_for
    command = dict(behavior=behavior, reason='original_policy')
    if behavior == 'navigate_to_pose':
        command['goal'] = dict(frame='map', position_m=[1.,2.], yaw_rad=.1)
    return decision_intent_for(build_decision_observation(o), command)


@pytest.mark.parametrize('behavior', ['hold','cancel'])
@pytest.mark.parametrize('axis', ['vx_mps','vy_mps','wz_rps'])
@pytest.mark.parametrize('speed', [.2, 1e-12])
def test_stop_intent_rejects_nonzero_at_host_and_peer_boundaries(tmp_path, behavior, axis, speed):
    a,o,_,_=adapter(tmp_path,goals=True)
    intent=stop_intent(o,behavior)
    command=dict(frame='base_link',vx_mps=0.,vy_mps=0.,wz_rps=0.)
    command[axis]=speed
    value=action_for(o,'navigation','velocity_body',command)
    packet=dict(op='act',observation=o,intent=intent)
    response=dict(schema=JSONL_SCHEMA,op='act',ok=True,action=value)
    with pytest.raises(ContractError,match='violates_stop_intent'):
        a._validate_response(response,packet)
    # Also guard after exchange, even for a reviewed custom transport hook.
    with patch.object(a,'_exchange',return_value=response):
        with pytest.raises(ContractError,match='violates_stop_intent'):
            a.act_with_intent(o,intent)
    seen=[]
    def malicious(current,received):
        seen.append(copy.deepcopy(received))
        return value
    rows=request_rows(o);rows[-1]['intent']=intent
    with pytest.raises(ContractError,match='violates_stop_intent'):
        peer(rows,malicious,goals=True)
    assert seen==[intent]  # Cancel/hold reaches the actual goal owner first.


@pytest.mark.parametrize('behavior', ['hold','cancel'])
@pytest.mark.parametrize('output', ['zero','status'])
def test_stop_intent_accepts_original_zero_or_status_without_synthesis(tmp_path,behavior,output):
    from rm_match.platform_v2.contracts import IDENTITY
    a,o,_,_=adapter(tmp_path,goals=True)
    intent=stop_intent(o,behavior)
    value=(action_for(o,'navigation','velocity_body',dict(frame='base_link',vx_mps=0.,vy_mps=-0.,wz_rps=0.))
        if output=='zero' else navigation_status_for(o))
    field='action' if output=='zero' else 'status'
    response=dict(schema=JSONL_SCHEMA,op='act',ok=True,**{field:value})
    before=copy.deepcopy((o,intent,value))
    with patch.object(a,'_exchange',return_value=response):
        actual=a.act_with_intent(o,intent)
    assert actual==value and (o,intent,value)==before
    assert all(type(actual[k]) is type(o[k]) and actual[k]==o[k] for k in IDENTITY)
    rows=request_rows(o);rows[-1]['intent']=intent
    assert peer(rows,lambda current,received:value,goals=True)[-1][field]==value


def test_navigation_intent_still_accepts_real_nonzero_result(tmp_path):
    a,o,_,_=adapter(tmp_path,goals=True)
    intent=stop_intent(o,'navigate_to_pose');value=action(o)
    response=dict(schema=JSONL_SCHEMA,op='act',ok=True,action=value)
    a._validate_response(response,dict(op='act',observation=o,intent=intent))
    with patch.object(a,'_exchange',return_value=response):
        assert a.act_with_intent(o,intent)==value
    rows=request_rows(o);rows[-1]['intent']=intent
    assert peer(rows,lambda current,received:action(current),goals=True)[-1]['action']==value


def test_stop_result_validates_original_identity_before_velocity_semantics(tmp_path):
    a,o,_,_=adapter(tmp_path,goals=True)
    intent=stop_intent(o,'cancel');value=action(o)
    value['observed_seq']+=1
    with pytest.raises(ContractError) as error:
        a._validate_response(dict(schema=JSONL_SCHEMA,op='act',ok=True,action=value),
            dict(op='act',observation=o,intent=intent))
    assert 'violates_stop_intent' not in str(error.value)


@pytest.mark.parametrize('behavior', ['hold','cancel'])
def test_actual_noncompliant_child_stop_motion_is_rejected_and_tree_reaped(tmp_path,behavior):
    """Harmless stdlib child bypasses peer helper to exercise real host cleanup."""
    root=Path(__file__).resolve().parents[1];wrapper=tmp_path/'noncompliant.py'
    received=tmp_path/'received.json'
    caps=dict(copy.deepcopy(CAPABILITIES),goal_input_modes=['decision_intent_v1'])
    wrapper.write_text('import json,sys\n'
        'from pathlib import Path\n'
        'sys.path.insert(0,'+repr(str(root))+')\n'
        'from rm_match.platform_v2.contracts import action_for\n'
        'for line in sys.stdin:\n'
        ' request=json.loads(line)\n'
        ' if request["op"]=="reset":\n'
        '  response=dict(schema="polar.sim.adapter.jsonl.v1",op="reset",ok=True,capabilities='+repr(caps)+')\n'
        ' else:\n'
        '  Path('+repr(str(received))+').write_text(json.dumps(request),encoding="utf8")\n'
        '  value=action_for(request["observation"],"navigation","velocity_body",dict(frame="base_link",vx_mps=.2,vy_mps=0.,wz_rps=0.))\n'
        '  response=dict(schema="polar.sim.adapter.jsonl.v1",op="act",ok=True,action=value)\n'
        ' print(json.dumps(response),flush=True)\n',encoding='utf8')
    a,o,_,_=adapter(tmp_path,goals=True,command=[sys.executable,'-u',str(wrapper)])
    try:
        a.reset(a.context)
        o['wall_deadline']=time.perf_counter()+.15
        intent=stop_intent(o,behavior);before=copy.deepcopy((o,intent))
        with pytest.raises(ContractError,match='violates_stop_intent'):
            a.act_with_intent(o,intent)
        assert (o,intent)==before
        packet=json.loads(received.read_text(encoding='utf8'))
        assert packet['observation']==o and packet['intent']==intent
        assert a.failed and a.process is None
        proof=a.shutdown_status
        assert proof['clean'] and proof['io_thread_stopped']
        assert proof['ownership']['reaped'] and proof['ownership']['group_empty']
    finally:a.close()
