"""Mutated independent receipts; no process, ROS, physics or clock IO."""
import copy

import pytest

from rm_match.deployment.json_adapter import SCHEMA as JSONL_SCHEMA
from rm_match.deployment.navigation_plugin import navigation_status_for
from rm_match.platform_v2.contracts import IDENTITY
from rm_match.platform_v2.decision_contracts import build_decision_observation, decision_intent_for
from rm_match.platform_v2.goal_navigation_contracts import goal_navigation_result
from test_navigation_plugin import action, observation
from tools.qa_active_goal_protocol_sil import ROBOTS, audit


def rows(*, hold=False):
    rid = 'blue_sentry' if hold else 'red_infantry'
    o = observation()
    o.update(robot_id=rid,wall_deadline=100.15)
    command = dict(behavior='hold' if hold else 'navigate_to_pose',reason='synthetic audit fixture')
    if not hold: command['goal'] = dict(frame='map',position_m=[1.,2.],yaw_rad=0.)
    d = build_decision_observation(o)
    intent = decision_intent_for(d,command)
    selected = None if hold else dict(operation_id='1'*32,origin_intent=copy.deepcopy(intent),
        latest_authorization={k:o[k] for k in IDENTITY},goal_uuids=dict(planner=None,navigation='2'*32),
        state='active',cancel_requested=False,terminal=False,stop_confirmed=False)
    value = navigation_status_for(o) if hold else action(o)
    result = goal_navigation_result(o,intent,selected,None if hold else '2'*32,value)
    result_rows = [
        dict(event='peer_exchange',robot_id=rid,peer='decision',packet=dict(op='act',observation=d),
            response=dict(schema=JSONL_SCHEMA,op='act',ok=True,intent=copy.deepcopy(intent))),
        dict(event='peer_exchange',robot_id=rid,peer='navigation',
            packet=dict(op='act',observation=o,intent=copy.deepcopy(intent)),
            response=dict(schema=JSONL_SCHEMA,op='act',ok=True,result=result)),
    ]
    if hold: return result_rows
    cloud=o['sensors']['pointcloud']
    result_rows.append(dict(event='adapter_enqueue',kind='navigation',robot_id=rid,
        episode=o['episode'],binding_epoch=o['binding_epoch'],observed_seq=o['observed_seq'],
        observation_sim_time=o['sim_time'],wall_deadline=o['wall_deadline'],
        sensor_budget=dict(source='navigation_sensor_v1',frame_id=cloud['frame_id'],
            profile_sha256=cloud['profile_sha256'],capture_sim_time=cloud['capture_sim_time'],
            capture_wall=100.,wall_deadline=100.15,sim_deadline=.25),
        cloud_acquisition={k:cloud[k] for k in ('frame_id','acquisition_start_ns','acquisition_end_ns','profile_sha256')}))
    result_rows.append(dict(event='sdk_activation',robot_id=rid,
        window=dict(window_id='original-window',issued_wall=100.,expires_wall=100.15,
            valid_for_s=.15,lease_epochs=dict(motion=7)),
        activation=dict(window_id='original-window',activation_expires=100.15,
            binding_epoch=o['binding_epoch'],seq=11)))
    result_rows.append(dict(event='actuator_consumed',robot_id=rid,episode=o['episode'],phase='running',
        source_action=copy.deepcopy(value),target=dict(motion=copy.deepcopy(value['command']),fire=False),
        adapter_output_authorizations=dict(navigation=dict(epoch=o['binding_epoch'],
            activation_seq=11,activation_window_id='original-window')),
        adapter_authorizations=dict(navigation=dict(epoch=o['binding_epoch'],adapter_id=ROBOTS[rid],
            activation_expires=100.15)),consume_wall=100.01,consume_sim_time=.11,
        manual_inputs=dict(motion=dict(epoch=7))))
    return result_rows


def test_original_current_goal_sdk_scan_and_physical_receipts_join():
    result=audit(rows())
    assert result['errors']==[]
    assert result['navigation_actions']==1 and result['navigation_statuses']==0
    assert result['physical']['red_infantry']['nonzero_sim_steps']==1
    assert result['protocol']['red_infantry']['controller_uuids']==['2'*32]


def test_real_status_is_separate_from_action_and_has_no_physical_receipt():
    result=audit(rows(hold=True))
    assert result['errors']==[]
    assert result['navigation_actions']==0 and result['navigation_statuses']==1
    assert result['physical']['blue_sentry']['receipts']==0


@pytest.mark.parametrize('peer_index',[0,1])
@pytest.mark.parametrize('field,value',[
    ('schema','wrong'),('schema',True),('op','reset'),('op',True),('ok',1),
])
def test_corrupt_outer_decision_or_navigation_reply_is_not_valid_evidence(peer_index,field,value):
    trace=rows(); trace[peer_index]['response'][field]=value
    assert audit(trace)['errors']


@pytest.mark.parametrize('mutation',[
    lambda t:t[1]['response']['result'].update(controller_goal_uuid='3'*32),
    lambda t:t[1]['response']['result']['selection']['latest_authorization'].update(binding_epoch=3.),
    lambda t:t[1]['response']['result']['selection']['origin_intent']['command']['goal'].update(yaw_rad=.5),
    lambda t:t[1]['response']['result']['source'].update(episode=True),
    lambda t:t[-1]['target']['motion'].update(vx_mps=.8),
    lambda t:t[-1].update(consume_wall=100.16),
    lambda t:t[-1].update(consume_sim_time=.26),
    lambda t:t[-1]['adapter_output_authorizations']['navigation'].update(epoch=4),
    lambda t:t[-1]['manual_inputs']['motion'].update(epoch=8),
    lambda t:t[2]['sensor_budget'].update(capture_wall=99.),
    lambda t:t[2]['sensor_budget'].update(frame_id=100),
    lambda t:t[2]['cloud_acquisition'].update(acquisition_end_ns=200000000),
    lambda t:t.pop(2),
])
def test_modified_uuid_source_scan_sdk_or_physical_receipt_is_rejected(mutation):
    trace=rows(); mutation(trace)
    assert audit(trace)['errors']


@pytest.mark.parametrize('index',[0,1,2])
def test_duplicate_original_decision_navigation_or_scan_enqueue_is_rejected(index):
    trace=rows(); trace.insert(index,copy.deepcopy(trace[index]))
    assert audit(trace)['errors']


def test_hold_status_cannot_be_replaced_by_a_fabricated_zero_action():
    trace=rows(hold=True)
    envelope=trace[1]['response']['result']; o=trace[1]['packet']['observation']
    envelope.pop('status')
    envelope['action']=action(o)
    envelope['action']['command'].update(vx_mps=0.,vy_mps=0.,wz_rps=0.)
    assert audit(trace)['errors']


def test_status_key_cannot_supply_any_physical_motion_receipt():
    trace=rows(hold=True); moving=rows()
    receipt=copy.deepcopy(moving[-1]); o=trace[1]['packet']['observation']
    receipt.update(robot_id=o['robot_id'],source_action=action(o))
    receipt['target']['motion']=copy.deepcopy(receipt['source_action']['command'])
    trace.append(receipt)
    result=audit(trace)
    assert any('status_cannot_be_action_consumption' in value for value in result['errors'])
