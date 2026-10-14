"""No-NN fixtures for original context, progress and physical-command boundary."""
import copy
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest
from rm_match.platform_v2 import native_adapter,wsl_native_adapter
from rm_match.platform_v2.contracts import ContractError,IDENTITY
from rm_match.platform_v2.aim_contracts import AIM_STATUS_SCHEMA
from rm_match.platform_v2 import test_native_adapter as _fixture_module
from rm_match.integrations.wsl_aim_async import NativeAimPending


@contextmanager
def fixture():
    f=_fixture_module.NativeTests();f.setUp()
    try:
        a=f.adapter();a.transport='wsl_async_bgr_v3';a.stable_since=.1
        o=f.observation();o['sim_time']=1.5;o['sensors']['camera']['capture_sim_time']=1.49
        a.process=Mock();a.process.is_busy.return_value=False
        a.directory=f.root/'binding';a.directory.mkdir()
        a._evidence_writer=Mock();a._evidence_writer.submit.return_value=1
        a._evidence_writer.can_submit.return_value=True
        a.trace=Mock()
        with patch('rm_match.platform_v2.native_adapter.time.perf_counter',return_value=9.):
            yield a,o
    finally:f.tearDown()


def test_busy_compute_returns_status_before_pixels_or_evidence_and_preserves_frame():
    with fixture() as (a,o):
        a.process.is_busy.return_value=True
        with patch.object(native_adapter,'raw_observation',side_effect=AssertionError('No pixels while busy')):
            result=a._act_sensor(o,lambda:a._hold(o),Mock())
        assert result['schema']==AIM_STATUS_SCHEMA and result['status']=='pending_result'
        assert {k:result[k] for k in IDENTITY}=={k:o[k] for k in IDENTITY}
        assert a.last_capture==-1
        a._evidence_writer.submit.assert_not_called();a.process.control.assert_not_called();a.trace.assert_not_called()


def test_pending_does_not_emit_native_result_or_hold_angles():
    with fixture() as (a,o):
        source={k:o[k] for k in IDENTITY}
        a._native_control=Mock(return_value=NativeAimPending('not_ready',1,True,json.dumps(source).encode()))
        result=a._act_sensor(o,lambda:pytest.fail('Pending cannot fabricate hold'),Mock())
        assert result['status']=='pending_result' and 'command' not in result
        events=[c.args[0]['event'] for c in a.trace.call_args_list]
        assert events.count('native_request')==1 and events.count('native_pending_status')==1
        assert 'native_result' not in events
        assert a._native_control.call_args.kwargs['image_bytes'] is not None


@pytest.mark.parametrize('field,value',[('episode',True),('observed_seq',99),('wall_deadline',1001.)])
def test_foreign_pending_cannot_be_retagged(field,value):
    with fixture() as (a,o):
        source={k:o[k] for k in IDENTITY};source[field]=value
        a._native_control=Mock(return_value=NativeAimPending('pending',1,True,json.dumps(source).encode()))
        with pytest.raises(ContractError,match='pending_source_mismatch'):
            a._act_sensor(o,lambda:a._hold(o),Mock())
        assert 'native_result' not in [c.args[0]['event'] for c in a.trace.call_args_list]


def test_absent_target_returns_status_without_actuator_command():
    with fixture() as (a,o):
        a._native_control=Mock(return_value={'should_control':False})
        result=a._act_sensor(o,lambda:a._hold(o),Mock())
        assert result['status']=='no_target' and 'command' not in result
        assert [c.args[0]['event'] for c in a.trace.call_args_list].count('native_result')==1


@pytest.mark.parametrize('received',[10.,10.001])
@pytest.mark.parametrize('active',[False,True])
def test_source_return_at_or_after_original_deadline_cannot_emit_result_or_angles(received,active):
    with fixture() as (a,o):
        response=dict(should_control=active,observation_shoot_allowed=True,target_age_s=.01,
            direction_frame='world',direction=[1.,0.,.1],should_shoot=False)
        a._native_control=Mock(return_value=response)
        with patch('rm_match.platform_v2.native_adapter.time.perf_counter',return_value=received):
            result=a._act_sensor(o,lambda:pytest.fail('Expired response cannot fabricate hold'),lambda c:dict(command=c))
        assert result['schema']==AIM_STATUS_SCHEMA and result['status']=='pending_result'
        assert {k:result[k] for k in IDENTITY}=={k:o[k] for k in IDENTITY}
        assert 'command' not in result
        rows=[c.args[0] for c in a.trace.call_args_list]
        assert not any(r['event']=='native_result' for r in rows)
        late=next(r for r in rows if r['event']=='native_response_expired_before_action')
        assert late['wall_time']==received and late['response']==response and late['wall_deadline']==10.


def test_fault_while_busy_stays_fault_instead_of_pending():
    with fixture() as (a,o):
        a.process.is_busy.side_effect=RuntimeError('actual_worker_fault')
        with pytest.raises(RuntimeError,match='actual_worker_fault'):a._act_sensor(o,lambda:a._hold(o),Mock())
        a._evidence_writer.submit.assert_not_called()


def test_evidence_backpressure_skips_fresh_pixels_but_does_not_hide_io_fault():
    with fixture() as (a,o):
        a._evidence_writer.can_submit.return_value=False
        with patch.object(native_adapter,'raw_observation',side_effect=AssertionError('No pixels while evidence busy')):
            result=a._act_sensor(o,lambda:a._hold(o),Mock())
        assert result['status']=='pending_result' and a.last_capture==-1
        a._evidence_writer.submit.assert_not_called();a.process.control.assert_not_called()
        a._evidence_writer.can_submit.side_effect=RuntimeError('Actual failed evidence IO')
        with pytest.raises(RuntimeError,match='failed evidence IO'):a._act_sensor(o,lambda:a._hold(o),Mock())


def test_wsl_control_passes_original_six_fields_only():
    a=object.__new__(wsl_native_adapter.WslNativeSourceAdapter)
    import threading
    a._cancelled=threading.Event();a.transport='wsl_async_bgr_v3';a.process=Mock()
    o=dict(robot_id='red_sentry',episode=1,binding_epoch=2,observed_seq=3,sim_time=.422,wall_deadline=1000.08,
        secret_evaluation_truth='Never forwarded')
    raw=b'private bounded fixture';proof=object()
    a._native_control({'frame':{'frame_id':7}},o,image_bytes=raw,prepared_image=proof)
    call=a.process.control.call_args
    assert call.kwargs=={'source_context':{k:o[k] for k in IDENTITY}}
    assert call.args[0]['host_deadline']==1000.08
    assert call.args[0]['image_bytes'] is raw and call.args[0]['prepared_image'] is proof
