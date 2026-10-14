"""No-retry batch SDK faults and actual HTTP with synthetic backend only."""
import copy
import io
import json
import threading
from unittest.mock import patch

import pytest

from rm_match.platform_v2.client import PlatformClient,ClientError,SCHEMA
from rm_match.platform_v2.control import CHANNELS
from rm_match.platform_v2.runtime import PlatformRuntime
from rm_match.platform_v2.server import PlatformHTTPServer,TransportConfig
from rm_match.platform_v2.test_control import Clock
from rm_match.platform_v2.test_runtime import FakeBackend
from rm_match.platform_v2.test_support_admission import fixture_policy,OPERATOR_CREDENTIAL


@pytest.fixture
def sdk():
    c=PlatformClient('http://127.0.0.1:12345',control_profile='server_window_v1')
    c.role='operator';c.session_id='sdk-fixture';c.control_batch_version=1;c._token='memory-only-fixture'
    c._leases={('alpha',ch):1 for ch in CHANNELS};c._seq={('alpha',ch,1):-1 for ch in CHANNELS}
    c._bindings={('alpha','navigation'):2};c._adapter_seq={('alpha','navigation',2):-1}
    now=[5000.];c._batch_clock=lambda:now[0]
    c._windows['alpha']=dict(robot_id='alpha',session_id=c.session_id,lease_epochs={ch:1 for ch in CHANNELS},window_id=1,issued_wall=10000.,expires_wall=10000.15,valid_for_s=.15)
    c._window_started['alpha']=now[0]
    return c,now


def args():
    return ('alpha',{'navigation':2},{'gimbal':dict(frame='base_link',yaw_rad=.1,pitch_rad=.05),'fire':{'fire':False}})


def response(body):
    return dict(schema=SCHEMA,accepted=True,robot_id=body['robot_id'],lease_epochs=copy.deepcopy(body['lease_epochs']),window_id=body['window_id'],batch_version=1,
        adapter_inputs=[dict(accepted=True,robot_id=body['robot_id'],window_id=body['window_id'],activation_expires=10000.15,**row) for row in body['adapter_inputs']],
        controls=[dict(accepted=True,robot_id=body['robot_id'],window_id=body['window_id'],input_expires=10000.15,**{k:row[k] for k in ('channel','lease_epoch','seq')}) for row in body['controls']])


def test_sdk_one_rpc_includes_manual_fire_and_both_sequences(sdk):
    c,_=sdk
    with patch.object(c,'_request',side_effect=lambda path,body:response(body)) as send:
        ack=c.control_batch(*args(),window_id=1)
    assert send.call_count==1 and send.call_args.args[0]=='/v2/control_batch'
    assert [r['channel'] for r in send.call_args.args[1]['controls']]==['gimbal','fire']
    assert all(r['seq']==0 for r in ack['adapter_inputs']+ack['controls'])


@pytest.mark.parametrize('mutation',[
    lambda r:r.update(batch_version=True),lambda r:r.update(window_id=1.0),
    lambda r:r.update(robot_id='beta'),lambda r:r.update(extra=True),
    lambda r:r['lease_epochs'].update(fire=True),lambda r:r['adapter_inputs'][0].update(binding_epoch=2.0),
    lambda r:r['adapter_inputs'][0].update(seq=True),lambda r:r['adapter_inputs'][0].update(kind='aim'),
    lambda r:r['adapter_inputs'][0].update(extra=True),lambda r:r['controls'][0].update(lease_epoch=True),
    lambda r:r['controls'][0].update(input_expires=10001.),lambda r:r['controls'][1].update(channel='gimbal'),
    lambda r:r['controls'].pop(),lambda r:r['controls'].append(copy.deepcopy(r['controls'][0])),
    lambda r:r['adapter_inputs'].clear(),lambda r:r.update(adapter_inputs={}),
])
def test_any_invalid_ack_latches_uncertainty_without_replay(sdk,mutation):
    c,_=sdk
    def reply(path,body):
        r=response(body);mutation(r);return r
    with patch.object(c,'_request',side_effect=reply) as send:
        with pytest.raises(ClientError):c.control_batch(*args(),window_id=1)
        assert c.uncertain and send.call_count==1
        with pytest.raises(ClientError):c.control_batch(*args(),window_id=1)
        assert send.call_count==1


@pytest.mark.parametrize('label,expiry',[('adapter_inputs','activation_expires'),('controls','input_expires')])
def test_short_ttl_original_ack_arriving_after_entry_bound_is_uncertain(sdk,label,expiry):
    c,now=sdk
    def reply(path,body):
        r=response(body);r[label][0][expiry]=10000.01;now[0]+=.011;return r
    with patch.object(c,'_request',side_effect=reply) as send:
        with pytest.raises(ClientError,match='Expired local'):c.control_batch(*args(),window_id=1,valid_for_s=.01)
        assert c.uncertain and send.call_count==1


def test_expired_window_cannot_send_or_advance_sequences(sdk):
    c,now=sdk;now[0]+=.151;before=(dict(c._seq),dict(c._adapter_seq))
    with patch.object(c,'_request') as send:
        with pytest.raises(ClientError,match='Expired local'):c.control_batch(*args(),window_id=1)
        send.assert_not_called()
    assert c.uncertain and before==(c._seq,c._adapter_seq)


def test_duplicate_raw_json_ack_is_uncertain_and_sends_once(sdk):
    c,_=sdk
    raw=json.dumps(dict(schema=SCHEMA,accepted=True)).replace('"accepted": true','"accepted": true, "accepted": true').encode()
    with patch.object(c._opener,'open',return_value=io.BytesIO(raw)) as send:
        with pytest.raises(ClientError,match='Uncertain'):c.control_batch(*args(),window_id=1)
        assert c.uncertain and send.call_count==1
        with pytest.raises(ClientError):c.control_batch(*args(),window_id=1)
        assert send.call_count==1


@pytest.mark.parametrize('binding,controls',[
    ({'navigation':True},{'gimbal':{},'fire':{}}),
    ({'navigation':2},{'motion':{},'gimbal':{},'fire':{}}),
    ({'navigation':2},{'gimbal':{}}),
    ({'unknown':2},{'gimbal':{},'fire':{}}),
])
def test_incomplete_overlap_or_invalid_binding_rejected_before_send(sdk,binding,controls):
    c,_=sdk;before=(dict(c._seq),dict(c._adapter_seq))
    with patch.object(c,'_request') as send:
        with pytest.raises(ClientError):c.control_batch('alpha',binding,controls,window_id=1)
        send.assert_not_called()
    assert not c.uncertain and before==(c._seq,c._adapter_seq)


@pytest.mark.parametrize('value',[True,1.0,2,'1',None])
def test_malformed_advertisement_cannot_enable_batch(sdk,value):
    c,_=sdk;c._token=None
    opened=dict(schema=SCHEMA,token='temporary',session_id='fresh',role='operator',session_expires=20.,server_monotonic_s=10.,control_profile='server_window_v1',control_window_version=1,control_window_ttl_s=.15,control_batch_version=value)
    with patch.object(c,'_request',return_value=opened):
        with pytest.raises(ClientError,match='batch negotiation'):c.open('operator')
    assert c.uncertain


def test_missing_capability_keeps_old_control_api(sdk):
    c,_=sdk;c._token=None
    opened=dict(schema=SCHEMA,token='temporary',session_id='fresh',role='operator',session_expires=20.,server_monotonic_s=10.,control_profile='server_window_v1',control_window_version=1,control_window_ttl_s=.15)
    with patch.object(c,'_request',return_value=opened):c.open('operator')
    assert c.control_batch_version is None
    with patch.object(c,'_request') as send:
        with pytest.raises(ClientError,match='Negotiated'):c.control_batch(*args(),window_id=1)
        send.assert_not_called()


@pytest.fixture
def actual_http():
    clock=Clock();runtime=PlatformRuntime(FakeBackend(),clock=clock)
    server=PlatformHTTPServer(TransportConfig(port=0,admission_policy=fixture_policy(runtime.control.robot_ids)),runtime)
    thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01});thread.start()
    c=PlatformClient('http://127.0.0.1:'+str(server.server_address[1]),control_profile='server_window_v1',admission_credential=OPERATOR_CREDENTIAL)
    c._batch_clock=lambda:clock.now;c.open('operator');c.claim('alpha',list(CHANNELS))
    try:yield c,runtime,clock
    finally:
        c.close();server.shutdown();server.server_close();thread.join(1);runtime.close()
        assert not thread.is_alive() and runtime.shutdown_status['clean']


@pytest.mark.parametrize('kinds',[(),('navigation',),('navigation','aim')])
def test_actual_http_batches_manual_and_bound_kinds_without_implicit_window(actual_http,kinds):
    c,runtime,_=actual_http;bindings={}
    for kind in kinds:bindings[kind]=c.bind('alpha',kind,'nav_stop_test_v1' if kind=='navigation' else 'aim_hold_test_v1')['binding_epoch']
    w=c.control_window('alpha',list(CHANNELS));mapped={'navigation':'motion','aim':'gimbal'}
    values={'motion':dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=0.),'gimbal':dict(frame='base_link',yaw_rad=.1,pitch_rad=.05),'fire':{'fire':False}}
    controls={ch:value for ch,value in values.items() if ch not in {mapped[k] for k in kinds}}
    ack=c.control_batch('alpha',bindings,controls,window_id=w['window_id'])
    assert ack['window_id']==w['window_id'] and c._last_window_ids['alpha']==w['window_id']
    snapshot=runtime.control.snapshot()
    for kind in kinds:assert snapshot['bindings']['alpha'][kind]['activation_seq']==0
    for ch in controls:assert snapshot['leases']['alpha'][ch]['seq']==0


def test_actual_http_known_rejection_cannot_partially_send_fire(actual_http):
    c,runtime,_=actual_http;w=c.control_window('alpha',list(CHANNELS))
    values={'motion':dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=0.),'gimbal':dict(frame='base_link',yaw_rad=.1,pitch_rad=9.),'fire':{'fire':True}}
    with pytest.raises(ClientError,match='gimbal_limit'):c.control_batch('alpha',{},values,window_id=w['window_id'])
    assert not c.uncertain
    assert all(runtime.control.leases['alpha',ch].seq==-1 and runtime.control.leases['alpha',ch].input is None for ch in CHANNELS)
