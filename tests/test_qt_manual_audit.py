"""Receipt audit rejects altered source IDs, expired windows and adapter mixing."""
import copy
import pytest
from tools.audit_qt_manual import audit

def rows():
    epochs={c:1 for c in ('motion','gimbal','fire')}
    w=dict(robot_id='red_infantry',session_id='synthetic',lease_epochs=epochs,window_id=1,issued_wall=10.,expires_wall=10.15,valid_for_s=.15)
    values=dict(motion=dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=0.),gimbal=dict(frame='base_link',yaw_rad=.1,pitch_rad=.05),fire=dict(fire=False))
    controls=[dict(channel=c,lease_epoch=1,seq=0,value=values[c]) for c in epochs]
    ack=[dict(accepted=True,robot_id='red_infantry',channel=c,lease_epoch=1,seq=0,window_id=1,input_expires=10.15) for c in epochs]
    batch=dict(event='sdk_manual_batch',robot_id='red_infantry',window=w,request=dict(robot_id='red_infantry',lease_epochs=epochs,window_id=1,valid_for_s=.15,adapter_inputs=[],controls=controls),ack=dict(schema='rm.sim.platform.v2',accepted=True,robot_id='red_infantry',lease_epochs=epochs,window_id=1,batch_version=1,adapter_inputs=[],controls=ack),entered_host_wall=10.01,returned_host_wall=10.02)
    receipt=dict(event='actuator_consumed',robot_id='red_infantry',phase='integration_entry',consume_wall=10.03,consume_sim_time=.1,
        adapter_authorizations=dict(navigation={'owner':None},aim={'owner':None}),manual_inputs={c:dict(owner='synthetic',epoch=1,seq=0,expires=11.,input_expires=10.15,input_window_id=1,input_window_deadline=10.15) for c in epochs},target={c:values[c]['fire'] if c=='fire' else copy.deepcopy(values[c]) for c in epochs})
    return [batch,receipt]

def test_exact_manual_batch_and_actual_consumer():
    result=audit(rows());assert result['errors']==[] and result['positive_x_steps']==1 and result['nonzero_gimbal_steps']==1

@pytest.mark.parametrize('change',[
    lambda r:r[0]['request'].update(window_id=1.0),
    lambda r:r[0]['ack']['controls'][0].update(seq=True),
    lambda r:r[0]['ack'].update(adapter_inputs=[{}]),
    lambda r:r[0]['request']['controls'].pop(),
    lambda r:r[0].update(returned_host_wall=10.15),
    lambda r:r[1]['manual_inputs']['fire'].update(epoch=1.0),
    lambda r:r[1]['manual_inputs']['gimbal'].update(input_window_id=2),
    lambda r:r[1]['manual_inputs']['motion'].update(seq=1),
    lambda r:r[1]['manual_inputs']['fire'].update(owner='other'),
    lambda r:r[1].update(consume_wall=10.15),
    lambda r:r[1]['adapter_authorizations']['navigation'].update(owner='synthetic'),
    lambda r:r[1]['target']['gimbal'].update(pitch_rad=.2),
])
def test_mutation_cannot_be_reported_as_a_pass(change):
    value=copy.deepcopy(rows());change(value);assert audit(value)['errors']
