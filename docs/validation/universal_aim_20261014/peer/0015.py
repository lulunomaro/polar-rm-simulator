"""Pure transport/ownership tests. No WSL, ROS, NN or camera started."""
import copy
import io
import json
import threading
import time
from pathlib import Path
from unittest.mock import patch
import pytest
from rm_match.deployment.aim_plugin import CAPABILITIES, MANIFEST_SCHEMA,load_aim_plugins,register_aim_plugins
from rm_match.deployment.wsl_jsonl import (WslAimPluginAdapter,PreparedWslAimPlugins,
    OwnedWslJsonProcess,validate_linux_settings,validate_cleanup,checked_shared_path)
from rm_match.platform_v2.adapters import Registry
from rm_match.platform_v2.contracts import ContractError
from rm_match.deployment.json_adapter import JsonLineAdapter
from rm_match.integrations.aim_jsonl_peer import serve_aim_plugin
from rm_match.integrations.ros2_bridge import JSONL_SCHEMA

def manifest(tmp_path):
    row=dict(adapter_id='custom_arbitrary_ros_aim',label='Reviewed local WSL peer',
        command=['/opt/owned/venv/bin/python','-m','owned_real_aim'],cwd='/opt/owned/workspace',
        supported_robots=['red_sentry'],transport='wsl_jsonl_v1',capabilities=copy.deepcopy(CAPABILITIES),
        wsl=dict(distribution='Ubuntu-22.04',python='/usr/bin/python3',process_env={'ROS_DOMAIN_ID':'78'}))
    path=tmp_path/'manifest.json';path.write_text(json.dumps(dict(schema=MANIFEST_SCHEMA,adapters=[row])))
    return path,row

def peer(rows,compute):
    output=io.BytesIO();serve_aim_plugin(compute,io.BytesIO(b''.join(json.dumps(r).encode()+b'\n' for r in rows)),output)
    return [json.loads(r) for r in output.getvalue().splitlines()]

def prepare():return dict(schema=JSONL_SCHEMA,op='prepare',config={})
def reset():return dict(schema=JSONL_SCHEMA,op='reset',context=dict(episode=3,robot_id='red_sentry',binding_epoch=19),config={})

def test_prepare_is_separate_ack_and_real_reset_calls_engine_without_image():
    class Engine:
        def __init__(self):self.resets=[]
        def __call__(self,*args):raise AssertionError('preparation must not infer')
        def reset(self,c):self.resets.append(c)
    engine=Engine();rows=peer([prepare(),reset()],engine)
    assert [r['op'] for r in rows]==['prepare','reset']
    assert rows[0]==dict(schema=JSONL_SCHEMA,op='prepare',ok=True)
    assert engine.resets==[reset()['context']]
    # Existing peers may skip the optional preparation operation.
    engine2=Engine();assert peer([reset()],engine2)[0]['op']=='reset'

@pytest.mark.parametrize('rows',[lambda:[prepare(),prepare()],lambda:[reset(),prepare()],
    lambda:[dict(prepare(),context={})],lambda:[dict(prepare(),config={'command':['bad']})]])
def test_prepare_unknown_repeated_or_after_reset_rejected(rows):
    with pytest.raises(ContractError):peer(rows(),lambda *args:None)

def test_engine_reset_failure_never_acknowledged():
    class Engine:
        def __call__(self,*args):raise AssertionError
        def reset(self,c):raise RuntimeError('actual reset failed')
    with pytest.raises(RuntimeError):peer([prepare(),reset()],Engine())

def test_prepare_ack_never_authorizes_act_before_real_reset():
    act=dict(schema=JSONL_SCHEMA,op='act',observation={'not_a_valid_observation':True})
    with patch('rm_match.integrations.aim_jsonl_peer.prepare_aim_input') as decode:
        with pytest.raises(ContractError,match='reset_required'):peer([prepare(),act],lambda *args:None)
        decode.assert_not_called()

def test_manifest_is_local_linux_argv_and_unprepared_unavailable(tmp_path):
    path,row=manifest(tmp_path);rows,sha=load_aim_plugins(path)
    assert rows[0]['linux']['command']==row['command']
    registry=Registry();register_aim_plugins(registry,path)
    d=registry.descriptors()[0]
    assert d['available'] is False and d['plugin_transport']=='wsl_jsonl_v1'
    with pytest.raises(ContractError,match='prepare_required'):registry.create(row['adapter_id'],{})

@pytest.mark.parametrize('mutate',[lambda x:x.update(python='python3'),lambda x:x.update(cwd='/opt/../tmp'),
    lambda x:x.update(distribution='Ubuntu;sh'),lambda x:x['command'].__setitem__(0,'{python}'),
    lambda x:x['process_env'].update(POLAR_ADMISSION_CREDENTIAL='secret'),
    lambda x:x['process_env'].update(PYTHONPATH='/tmp')])
def test_linux_local_configuration_rejects_ambiguous_or_inherited_execution(tmp_path,mutate):
    path,row=manifest(tmp_path);settings=dict(row['wsl'],command=row['command'],cwd=row['cwd'])
    mutate(settings)
    with pytest.raises(ContractError):validate_linux_settings(settings)

def test_preparation_reset_keeps_unknown_future_generation_and_two_second_gate(tmp_path):
    path,row=manifest(tmp_path);rows,sha=load_aim_plugins(path)
    adapter=WslAimPluginAdapter({},registration=rows[0],manifest=path,manifest_sha=sha,
        repo_root=tmp_path,shared_root=tmp_path/'artifacts')
    events=[];adapter._open_owned_process=lambda:events.append('open')
    adapter._exchange=lambda packet,timeout:events.append((copy.deepcopy(packet),timeout))
    adapter.prepare(startup_timeout=15.)
    adapter._owned_process=type('Owned',(),{'verify_unchanged':lambda self:None})()
    context=dict(episode=72,robot_id='red_sentry',binding_epoch=917)
    adapter.reset(context)
    assert events==['open',({'op':'prepare','config':{}},15.),({'op':'reset','context':context,'config':{}},2.)]
    with pytest.raises(ContractError,match='fresh_local'):adapter.reset(context)

def test_cancel_or_manifest_change_cannot_handover_prepared_instance(tmp_path):
    path,row=manifest(tmp_path);rows,sha=load_aim_plugins(path)
    adapter=WslAimPluginAdapter({},registration=rows[0],manifest=path,manifest_sha=sha,repo_root=tmp_path,shared_root=tmp_path)
    adapter.prepared=True;adapter._cancelled.set()
    with patch.object(adapter,'_exchange') as exchange:
        with pytest.raises(ContractError):adapter.reset(reset()['context'])
        exchange.assert_not_called()
    pool=PreparedWslAimPlugins.__new__(PreparedWslAimPlugins);pool.path=path;pool.sha=sha;pool.instances={row['adapter_id']:adapter}
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ContractError,match='manifest_changed'):pool.take(row['adapter_id'],sha)
    assert row['adapter_id'] in pool.instances

def proof():
    hello=dict(event='hello',run_id='run',spec_sha256='sha',worker_pid=23,worker_start_ticks=31,
        boot_id='boot',peer_identity=dict(run_id='owned',supervisor_pid=23,boot_id='boot',pid=45,pgid=45,leader_start_ticks=71),algorithm_ready=False)
    ownership=dict(hello['peer_identity'],clean=True,reaped=True,group_empty=True,errors=[])
    record=dict(event='cleanup',run_id='run',spec_sha256='sha',hello=hello,ownership=ownership,
        io_thread_stopped=True,clean=True,error_type=None)
    return record,hello

def test_cleanup_requires_matching_linux_birth_and_actual_group_proof():
    record,hello=proof();assert validate_cleanup(record,'run','sha',hello)==record
    for change in ('wrongrun','wrongbirth','remaininggroup','io_alive','missingreap'):
        bad=copy.deepcopy(record)
        if change=='wrongrun':bad['run_id']='other'
        elif change=='wrongbirth':bad['ownership']['leader_start_ticks']+=1
        elif change=='remaininggroup':bad['ownership']['group_empty']=False
        elif change=='io_alive':bad['io_thread_stopped']=False
        else:bad['ownership']['reaped']=False
        with pytest.raises(ContractError):validate_cleanup(bad,'run','sha',hello)

def test_shared_output_rejects_escape_and_link(tmp_path):
    assert checked_shared_path(tmp_path/'artifacts'/'new',tmp_path)==tmp_path/'artifacts'/'new'
    with pytest.raises(ContractError):checked_shared_path(tmp_path.parent/'outside',tmp_path)
    try:(tmp_path/'link').symlink_to(tmp_path,target_is_directory=True)
    except OSError:pytest.skip('Windows symlink privilege unavailable')
    with pytest.raises(ContractError):checked_shared_path(tmp_path/'link'/'out',tmp_path)

def fake_host(tmp_path):
    owner=OwnedWslJsonProcess.__new__(OwnedWslJsonProcess)
    owner.repo_root=tmp_path;owner.out=tmp_path/'owned';owner.out.mkdir()
    owner.run_id='run';owner.sha='sha';owner.hello=None;owner.status=None
    owner._stop=threading.Event();owner._reader=None;owner._launch_status=None
    owner._owned=None
    return owner

def test_windows_reaped_alone_does_not_prove_linux_cleanup(tmp_path):
    owner=fake_host(tmp_path)
    owner._owned=type('Windows',(),dict(cleanup=lambda self,deadline:dict(clean=True,reaped=True,group_empty=True)))()
    result=owner.cleanup(time.perf_counter()+.05)
    assert result['clean'] is False and result['group_empty'] is False
    assert 'linux_owned_cleanup_unproved' in result['errors']

def test_launch_proof_not_spawned_is_distinct_from_reaped(tmp_path):
    owner=fake_host(tmp_path);owner._launch_status=dict(clean=True,reaped=False,not_spawned=True,group_empty=True,errors=[])
    result=owner.cleanup(time.perf_counter()+.1)
    assert result['clean'] and result['not_spawned'] and not result['reaped']
    assert result['linux']['source']=='owned_windows_before_execute_launch_proof'

def test_stop_targets_original_run_even_when_shared_spec_changed(tmp_path):
    owner=fake_host(tmp_path);owner._spec_path=owner.out/'SPEC.json';owner._spec_path.write_bytes(b'changed')
    owner._spec_bytes=b'original';owner.request_stop()
    assert json.loads((owner.out/'STOP').read_text())==dict(run_id='run',spec_sha256='sha')
    assert owner._stop.is_set() and not list(owner.out.glob('*.tmp'))

def test_unused_pool_cleanup_failure_remains_explicit():
    pool=PreparedWslAimPlugins.__new__(PreparedWslAimPlugins)
    class Unclean:
        def close(self):raise RuntimeError('Linux proof unknown')
    pool.instances={'custom_owned':Unclean()}
    with pytest.raises(RuntimeError,match='Unclaimed WSL cleanup unproved'):pool.close_unclaimed()

def test_registered_pool_handover_once_with_detached_public_descriptor(tmp_path):
    path,row=manifest(tmp_path);rows,sha=load_aim_plugins(path)
    instance=WslAimPluginAdapter({},registration=rows[0],manifest=path,manifest_sha=sha,repo_root=tmp_path,shared_root=tmp_path)
    instance.prepared=True;instance._owned_process=type('Owned',(),dict(verify_unchanged=lambda self:None))()
    pool=PreparedWslAimPlugins.__new__(PreparedWslAimPlugins);pool.path=path;pool.sha=sha;pool.instances={row['adapter_id']:instance}
    registry=Registry();register_aim_plugins(registry,path,wsl_prepared=pool)
    assert registry.descriptors()[0]['available'] is True
    assert registry.create(row['adapter_id'],{}) is instance
    with pytest.raises(ContractError,match='claimed'):registry.create(row['adapter_id'],{})
    public=registry.descriptors()[0];public['aim_plugin_capabilities']['image_encodings'].clear()
    assert instance.descriptor['aim_plugin_capabilities']['image_encodings']==['rgb8','bgr8']

def test_cancel_wakes_blocked_real_reset_wait_without_running_close_on_caller(tmp_path):
    path,row=manifest(tmp_path);rows,sha=load_aim_plugins(path)
    a=WslAimPluginAdapter({},registration=rows[0],manifest=path,manifest_sha=sha,repo_root=tmp_path,shared_root=tmp_path)
    a.process=object();closed=[];failures=[]
    a.close=lambda:closed.append(threading.get_ident())
    def exchange():
        try:a._exchange(dict(op='reset',context=reset()['context'],config={}),timeout=2.)
        except Exception as exc:failures.append(exc)
    thread=threading.Thread(target=exchange);thread.start()
    # Wait for actual request admission without a long timed sleep.
    assert a.requests.get(timeout=.5)
    caller=threading.get_ident();JsonLineAdapter.cancel(a);thread.join(.5)
    assert not thread.is_alive() and isinstance(failures[0],RuntimeError)
    assert closed==[thread.ident] and closed[0]!=caller

def test_cancel_full_response_queue_cannot_accept_old_reset_ack(tmp_path):
    path,row=manifest(tmp_path);rows,sha=load_aim_plugins(path)
    a=WslAimPluginAdapter({},registration=rows[0],manifest=path,manifest_sha=sha,repo_root=tmp_path,shared_root=tmp_path)
    a.process=object();a.responses.put_nowait(dict(schema=JSONL_SCHEMA,op='reset',ok=True))
    JsonLineAdapter.cancel(a)
    with patch.object(a,'_validate_response') as validate:
        with pytest.raises(ContractError):a._exchange(dict(op='reset',context={},config={}),timeout=2.)
        validate.assert_not_called()
    assert a.requests.empty()

def test_cancel_during_response_delivery_is_rechecked_before_validation(tmp_path):
    path,row=manifest(tmp_path);rows,sha=load_aim_plugins(path)
    a=WslAimPluginAdapter({},registration=rows[0],manifest=path,manifest_sha=sha,repo_root=tmp_path,shared_root=tmp_path)
    a.process=object();a.close=lambda:None
    def delivery(timeout):
        a._cancelled.set()
        return dict(schema=JSONL_SCHEMA,op='reset',ok=True)
    a.responses.get=delivery
    with patch.object(a,'_validate_response') as validate:
        with pytest.raises(RuntimeError,match='cancelled'):a._exchange(dict(op='reset',context={},config={}),timeout=2.)
        validate.assert_not_called()
