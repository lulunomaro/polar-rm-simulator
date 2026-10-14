"""Pure lifecycle/source-file fixtures. These do not import ROS or load a model."""
import copy
import hashlib
import json
from pathlib import Path
import threading
import time
from unittest.mock import patch
import pytest
from rm_match.integrations.pb_aim_configure import ConfigureOnce,NODES,CONFIGURED_SCHEMA
from rm_match.integrations.pb_aim_engine import PBAimEngine
from rm_match.integrations.pb_aim_stack import scoped_parameters,checked_ref
from rm_match.platform_v2.contracts import ContractError

ROOT=Path(__file__).resolve().parents[1]
CONTEXT=dict(robot_id='blue_hero',episode=3,binding_epoch=7)

def ack(config,node):
    return json.dumps(dict(json.loads(config),schema=CONFIGURED_SCHEMA,node=node))

def test_source_configuration_requires_three_exact_actual_node_acknowledgements():
    gate=ConfigureOnce('a'*32,'actual-camera-calibration')
    with pytest.raises(ContractError):gate.receive('{}')
    raw=gate.begin(CONTEXT)
    assert 'wall_deadline' not in json.loads(raw) and not gate.ready
    for node in NODES[:2]:gate.receive(ack(raw,node))
    assert not gate.ready
    gate.receive(ack(raw,NODES[2]));assert gate.ready
    gate.receive(ack(raw,NODES[0]));assert gate.ready
    with pytest.raises(ContractError):gate.begin(dict(CONTEXT,binding_epoch=8))

@pytest.mark.parametrize('key,value',[('run_uuid','b'*32),('robot_id','red_sentry'),('episode',True),
    ('binding_epoch',8),('calibration_id','changed'),('node','other_node')])
def test_configuration_ack_rejects_cross_run_generation_type_calibration_and_extra_nodes(key,value):
    gate=ConfigureOnce('a'*32,'calibration');raw=gate.begin(CONTEXT)
    bad=json.loads(ack(raw,NODES[0]));bad[key]=value
    with pytest.raises(ContractError):gate.receive(json.dumps(bad))
    assert not gate.ready

def test_scoped_parameters_keep_every_original_algorithm_value_and_explicit_frames():
    import yaml
    source=ROOT/'external/pb2025-aim-interface-review/pb2025_vision_bringup/params/simulation/vision_params.yaml'
    if not source.exists():pytest.skip('Pinned audited upstream absent')
    raw=source.read_bytes();before=hashlib.sha256(raw).hexdigest();original=yaml.safe_load(raw)
    scoped=json.loads(scoped_parameters(raw,'/owned_aim_session'))
    assert set(scoped)=={'/owned_aim_session/'+name for name in NODES}
    for name in NODES:
        expected=copy.deepcopy(original[name]['ros__parameters']);expected['use_sim_time']=True
        if name=='armor_tracker':expected['target_frame']='gimbal_aim_origin'
        if name=='projectile_motion':expected['projectile']['target_frame']='shooter_link'
        assert scoped['/owned_aim_session/'+name]['ros__parameters']==expected
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before
    with pytest.raises(ContractError):scoped_parameters(raw,'/invalid//namespace')

class StackFixture:
    def __init__(self,calls):self.calls=calls
    def start(self,env):self.calls.append(('start',env['ROS_DOMAIN_ID']))
    def check_alive(self):self.calls.append(('alive',))
    def close(self,budget):self.calls.append(('stack_close',budget))

class TransportFixture:
    def __init__(self,calls):self.calls=calls;self.gate=ConfigureOnce('a'*32,'calibration')
    def wait_ready(self,budget):self.calls.append(('graph_ready',budget))
    def configure(self,ctx,mount,budget):
        self.calls.append(('configure',dict(ctx),budget));raw=self.gate.begin(ctx)
        for node in NODES:self.gate.receive(ack(raw,node))
    def close(self):self.calls.append(('transport_close',))

def engine_fixture(tmp_path):
    calls=[];env=tmp_path/'ENV.json';env.write_text(json.dumps({'process_environment':{'FIXTURE_ENV':'data'}}))
    spec=dict(adapter_id='custom_pb_aim',namespace='/owned_aim',domain_id=85,run_uuid='a'*32,
        calibration_id='calibration',environment=dict(path=str(env),sha256=hashlib.sha256(env.read_bytes()).hexdigest()),
        mount=dict(path='fixture-only-no-model',sha256='0'*64))
    engine=PBAimEngine(spec,stack=StackFixture(calls),transport_factory=lambda core,spec:TransportFixture(calls))
    return engine,calls

def test_prepare_loads_resource_graph_without_fake_generation_or_image_then_reset_arms_once(tmp_path):
    engine,calls=engine_fixture(tmp_path)
    with patch.dict('os.environ',{},clear=False),patch('rm_match.integrations.pb_aim_engine.checked_mount',return_value=({},'0'*64)):
        engine.prepare()
        assert engine.core.context is None and not engine.transport.gate.ready
        assert [item[0] for item in calls]==['start','graph_ready','alive']
        with pytest.raises(ContractError):engine(None,{})
        engine.reset(CONTEXT);assert engine.transport.gate.ready
        assert ('configure',CONTEXT,1.) in calls
        with pytest.raises(ContractError):engine.reset(dict(CONTEXT,binding_epoch=8))
        engine.close()
    assert calls[-1][0]=='stack_close' or calls[-1][0]=='transport_close'

def test_failed_configure_cannot_retry_or_act_in_same_prepared_instance(tmp_path):
    engine,calls=engine_fixture(tmp_path)
    with patch.dict('os.environ',{},clear=False),patch('rm_match.integrations.pb_aim_engine.checked_mount',return_value=({},'0'*64)):
        engine.prepare()
        engine.transport.configure=lambda *a:(_ for _ in ()).throw(ContractError('fixture_missing_ack'))
        with pytest.raises(ContractError,match='missing_ack'):engine.reset(CONTEXT)
        with pytest.raises(ContractError,match='single_reset'):engine.reset(CONTEXT)
        with pytest.raises(ContractError,match='real_reset'):engine(None,{})
        engine.close()

def test_blocked_ros_close_is_bounded_and_sticky_unclean_without_thread_leak(tmp_path):
    engine,calls=engine_fixture(tmp_path);release=threading.Event();entered=threading.Event()
    def blocked():entered.set();release.wait(2.)
    engine.transport=TransportFixture(calls);engine.transport.close=blocked
    # The explicit fake clock consumes the original shared budget in stack
    # cleanup; no real ROS process or clock mapping is involved in this fixture.
    clock=[5.];engine.clock=lambda:clock[0]
    engine.stack.close=lambda budget:clock.__setitem__(0,6.1)
    try:
        started=time.perf_counter()
        with pytest.raises(ContractError,match='cleanup_incomplete'):engine.close()
        assert time.perf_counter()-started<.3 and entered.wait(.1)
        assert engine._close_thread.is_alive()
        with pytest.raises(ContractError,match='cleanup_incomplete'):engine.close()
    finally:
        release.set();engine._close_thread.join(1.)
    assert not engine._close_thread.is_alive()

def test_ref_hash_drift_and_parent_symlink_rejected(tmp_path):
    source=tmp_path/'source';source.mkdir();file=source/'asset';file.write_bytes(b'original')
    ref=dict(path=str(file),sha256=hashlib.sha256(b'original').hexdigest())
    checked_ref(ref);file.write_bytes(b'changed')
    with pytest.raises(ContractError,match='hash_changed'):checked_ref(ref)
    file.write_bytes(b'original');link=tmp_path/'alias'
    try:link.symlink_to(source,target_is_directory=True)
    except OSError:pytest.skip('Actual symlink creation unavailable')
    with pytest.raises(ContractError,match='ref_path'):checked_ref(dict(ref,path=str(link/'asset')))
