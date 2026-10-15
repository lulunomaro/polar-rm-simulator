"""Independent synthetic receipt mutations; no ROS, process or physics IO."""
import copy
import hashlib

import pytest

from rm_match.deployment.json_adapter import SCHEMA as JSONL_SCHEMA
from rm_match.deployment.navigation_plugin import navigation_status_for
from rm_match.platform_v2.contracts import IDENTITY
from rm_match.platform_v2.decision_contracts import build_decision_observation,decision_intent_for
from rm_match.platform_v2.goal_navigation_contracts import goal_navigation_result
from rm_match.platform_v2.navigation_feedback_contracts import navigation_feedback
from rm_match.integrations.ros2_bridge import encode_json,MAX_RESPONSE
from test_navigation_plugin import observation,action
from tools.qa_registered_pb_goal_sil import (audit_registered_route,audit_stages,audit_native_estimates,
    audit_estimated_goal_origins,audit_emit_gates)


PROVENANCE=dict(producer_source_sha256='1'*64,localization_binary_sha256='2'*64,mapping_binary_sha256='3'*64)


def fixture():
    original=observation()
    original.update(robot_id='red_sentry',episode=0,binding_epoch=1,observed_seq=5,wall_deadline=100.15)
    source={k:original[k] for k in IDENTITY};cloud=original['sensors']['pointcloud']
    scan=dict(cloud_frame_id=cloud['frame_id'],acquisition_start_ns=cloud['acquisition_start_ns'],
        acquisition_end_ns=cloud['acquisition_end_ns'],profile_sha256=cloud['profile_sha256'])
    nav=dict(available=True,reason='available',frame='map',child_frame='base_link',stamp_ns=100000000,
        localization_stamp_ns=100000000,position_m=[.2,.3,0.],rotation_xyzw=[0.,0.,0.,1.],
        provenance=dict(method='tf_buffer_exact_localization_stamp_v1',**PROVENANCE))
    feedback=navigation_feedback(original,nav,goal_status=dict(available=True,selection=None,history=[],
        operation_count=0,stop_requested=False,fault=None))
    decision=build_decision_observation(original,feedback,profile='own_referee_navigation_v2')
    intent=decision_intent_for(decision,dict(behavior='navigate_to_pose',reason='synthetic estimated goal',
        goal=dict(frame='map',position_m=[1.2,.3],yaw_rad=0.)))
    selection=dict(operation_id='1'*32,origin_intent=copy.deepcopy(intent),latest_authorization=copy.deepcopy(source),
        goal_uuids=dict(planner='2'*32,navigation='3'*32),state='active',cancel_requested=False,
        terminal=False,stop_confirmed=False)
    value=action(original)
    result=goal_navigation_result(original,intent,selection,'3'*32,value)
    def exchange(index,peer,packet,payload):
        return dict(event='peer_exchange',record_index=index,peer=peer,packet=packet,
            response=dict(schema=JSONL_SCHEMA,op=packet['op'],ok=True,**payload),
            started_wall=100.+index*.001,completed_wall=100.+(index+.5)*.001)
    rows=[exchange(0,'navigation',dict(op='observe',observation=original),dict(feedback=feedback)),
        exchange(1,'decision',dict(op='act',observation=decision),dict(intent=copy.deepcopy(intent))),
        exchange(2,'navigation',dict(op='act',source=copy.deepcopy(source),intent=copy.deepcopy(intent)),dict(result=result))]
    def stage(event,stamp,**extra):
        return dict(event=event,source=copy.deepcopy(source),scan=copy.deepcopy(scan),local_wall=stamp,
            local_deadline=200.05,clock='linux_local_perf_counter',**extra)
    stages=[stage('stage_begin',200.,begin_wall=200.,response_timeout_s=.05,published_count=0),
        stage('stage_published',200.001,published_count=1),stage('stage_feedback',200.002,available=True,reason='available'),
        stage('stage_act_enter',200.003),stage('stage_act_exit',200.004,value_kind='action',goal_uuid='3'*32,status=None),
        stage('stage_discard',200.005,reason='consumed')]
    loc=dict(schema='polar.sim.pb-localization-result.v1',adapter_id='custom_pb_navigation',**source,
        cloud_frame_id=cloud['frame_id'],acquisition_start_ns=cloud['acquisition_start_ns'],
        acquisition_end_ns=cloud['acquisition_end_ns'],localization_stamp_ns=100000000)
    tf=dict(source=copy.deepcopy(source),scan=copy.deepcopy(scan),requested_stamp_ns=100000000,
        transform=dict(header=dict(stamp=dict(sec=0,nanosec=100000000),frame_id='map'),child_frame_id='base_link',
            transform=dict(translation=dict(x=.2,y=.3,z=0.),rotation=dict(x=0.,y=0.,z=0.,w=1.))))
    native=dict(schema='polar.sim.pb-navigation-result.v2',adapter_id='custom_pb_navigation',action=copy.deepcopy(value),
        source=dict(cloud_frame_id=cloud['frame_id'],localization_stamp_ns=100000000,controller_stamp_ns=100000000,
            controller_id='nav2_server_pb_pid_goal_v1',goal_uuid='3'*32))
    ros=[dict(topic_kind=kind,value=item,receive_clock='linux_local_perf_counter',receive_wall=stamp)
        for kind,item,stamp in (('localization',loc,200.001),('estimated_transform',tf,200.002),('controller_result',native,200.0035))]
    return rows,stages,ros


def test_original_estimate_decision_current_goal_native_and_stage_route():
    rows,stages,ros=fixture()
    route=audit_registered_route(rows);stage=audit_stages(rows,stages,ros)
    estimate=audit_native_estimates(rows,ros,PROVENANCE)
    assert route['passed'] and route['actions']==1 and route['available_estimates']==1
    assert stage['passed'] and stage['qualified_action_stages']==1
    assert estimate['passed'] and estimate['exact_lio_TF_joins']==1


@pytest.mark.parametrize('index',[0,1,2])
@pytest.mark.parametrize('field,value',[('schema','wrong'),('schema',True),('op','reset'),('op',True),('ok',1)])
def test_each_outer_protocol_boundary_is_strict(index,field,value):
    rows,_,_=fixture();rows[index]['response'][field]=value
    assert not audit_registered_route(rows)['passed']


@pytest.mark.parametrize('mutation',[
    lambda r:r[2]['packet']['source'].update(binding_epoch=1.),
    lambda r:r[2]['packet']['intent']['command']['goal'].update(yaw_rad=.5),
    lambda r:r[1]['packet']['observation']['navigation']['navigation']['position_m'].__setitem__(0,99.),
    lambda r:r[0]['response']['feedback']['scan'].update(cloud_frame_id=99),
    lambda r:r[2]['response']['result'].update(controller_goal_uuid='4'*32),
    lambda r:r[2].update(record_index=0),
    lambda r:r[2].update(completed_wall=100.16),
    lambda r:r.pop(0),
    lambda r:r.insert(0,copy.deepcopy(r[0])),
    lambda r:r.insert(1,copy.deepcopy(r[1])),
    lambda r:r.append(copy.deepcopy(r[2])),
])
def test_feedback_source_intent_current_uuid_order_and_deadline_corruption_rejected(mutation):
    rows,_,_=fixture();mutation(rows)
    assert not audit_registered_route(rows)['passed']


@pytest.mark.parametrize('mutation',[
    lambda s,ros:s[0].update(response_timeout_s=.1),
    lambda s,ros:[e.update(local_deadline=200.1) for e in s],
    lambda s,ros:s[0].update(published_count=False),
    lambda s,ros:s[1].update(published_count=True),
    lambda s,ros:s.append(copy.deepcopy(s[1])),
    lambda s,ros:s[2].update(local_wall=200.06),
    lambda s,ros:s[3]['source'].update(episode=True),
    lambda s,ros:s[4].update(local_wall=200.051),
    lambda s,ros:s[4].update(goal_uuid='4'*32),
    lambda s,ros:s[4].update(clock='host_perf_counter'),
    lambda s,ros:ros[2].update(receive_wall=200.06),
    lambda s,ros:ros[1].update(receive_wall=199.),
    lambda s,ros:ros[0].update(receive_clock='host_perf_counter'),
    lambda s,ros:ros[2]['value']['action']['command'].update(vx_mps=.9),
])
def test_stage_republication_new_deadline_late_action_and_native_substitution_rejected(mutation):
    rows,stages,ros=fixture();mutation(stages,ros)
    assert not audit_stages(rows,stages,ros)['passed']


@pytest.mark.parametrize('mutation',[
    lambda r,ros:ros[0]['value'].update(localization_stamp_ns=99999999),
    lambda r,ros:ros[1]['value'].update(requested_stamp_ns=99999999),
    lambda r,ros:ros[1]['value'].update(requested_stamp_ns=100000000.),
    lambda r,ros:ros[1]['value']['transform']['header']['stamp'].update(nanosec=99999999),
    lambda r,ros:ros[1]['value']['transform']['transform']['translation'].update(x=999.),
    lambda r,ros:ros[1]['value']['transform'].update(child_frame_id='truth_base'),
    lambda r,ros:ros[1]['value']['scan'].update(profile_sha256='4'*64),
    lambda r,ros:ros.append(copy.deepcopy(ros[1])),
    lambda r,ros:ros[1].update(receive_clock='host_perf_counter'),
    lambda r,ros:r[0]['response']['feedback']['navigation']['provenance'].update(mapping_binary_sha256='4'*64),
])
def test_available_feedback_needs_pinned_original_lio_and_one_exact_actual_tf_lookup(mutation):
    rows,_,ros=fixture();mutation(rows,ros)
    assert not audit_native_estimates(rows,ros,PROVENANCE)['passed']


def test_native_action_withheld_as_status_after_current_goal_revocation_is_not_zero_action():
    rows,stages,ros=fixture();result=rows[2]['response']['result']
    result.pop('action');result.update(selection=None,controller_goal_uuid=None,
        status=navigation_status_for(rows[0]['packet']['observation']))
    stage=audit_stages(rows,stages,ros)
    assert stage['errors']==[] and stage['withheld_native_actions']==1
    assert stage['qualified_action_stages']==0 and stage['passed'] is False
    route=audit_registered_route(rows)
    assert route['errors']==[] and route['actions']==0 and route['statuses']==1


def deadline_withheld_fixture():
    rows,stages,ros=fixture();result=rows[2]['response']['result']
    result.pop('action');result.update(controller_goal_uuid=None,
        status=navigation_status_for(rows[0]['packet']['observation']))
    marker={k:copy.deepcopy(stages[4][k]) for k in ('source','scan','local_deadline','clock')}
    marker.update(event='stage_action_withheld',local_wall=200.05,value_kind='action',
        goal_uuid=stages[4]['goal_uuid'],reason='stage_exit_budget_expired')
    stages.insert(5,marker);stages[6]['local_wall']=200.051
    return rows,stages,ros


def test_stage_journal_cost_withholds_original_action_as_same_source_public_status():
    rows,stages,ros=deadline_withheld_fixture()
    audit=audit_stages(rows,stages,ros)
    assert audit['errors']==[] and audit['deadline_withheld_actions']==1
    assert audit['withheld_native_actions']==1 and audit['qualified_action_stages']==0
    assert audit['passed'] is False  # A status does not invent a passing action.


@pytest.mark.parametrize('change',[
    lambda r,s:s[5]['source'].update(episode=99),
    lambda r,s:s[5]['source'].update(episode=False),
    lambda r,s:s[5]['scan'].update(cloud_frame_id=999),
    lambda r,s:s[5].update(local_deadline=200.06),
    lambda r,s:s[5].update(clock='host_perf_counter'),
    lambda r,s:s[5].update(local_wall=200.049),
    lambda r,s:s[5].update(goal_uuid='4'*32),
    lambda r,s:s[5].update(value_kind='status'),
    lambda r,s:s[5].update(reason='budget_renewed'),
    lambda r,s:s[4].update(value_kind='status'),
    lambda r,s:s[4].update(local_wall=200.05),
    lambda r,s:s.insert(6,copy.deepcopy(s[5])),
    lambda r,s:r[2]['response']['result'].update(controller_goal_uuid='3'*32),
    lambda r,s:r[2]['response']['result']['status'].update(status='pending_localization'),
    lambda r,s:r[2]['response']['result']['status'].update(observed_seq=999),
    lambda r,s:r[2]['response']['result'].update(action=action(r[0]['packet']['observation'])),
])
def test_deadline_withheld_marker_cannot_change_candidate_source_UUID_stage_or_public_status(change):
    rows,stages,ros=deadline_withheld_fixture();change(rows,stages)
    assert audit_stages(rows,stages,ros)['errors']


def test_shutdown_unreturned_stage_marker_is_separate_from_a_public_status_claim():
    rows,stages,ros=deadline_withheld_fixture();rows.pop(2)
    audit=audit_stages(rows,stages,ros)
    assert audit['errors']==[] and audit['unreturned_deadline_withholds']==1
    assert audit['deadline_withheld_actions']==0 and audit['qualified_action_stages']==0


@pytest.mark.parametrize('change',[
    lambda ros:ros[2]['value']['source'].update(goal_uuid='4'*32),
    lambda ros:ros[2].update(receive_clock='host_perf_counter'),
    lambda ros:ros[2].update(receive_wall=200.05),
    lambda ros:ros[2]['value']['action'].update(observed_seq=999),
])
def test_stage_deadline_withheld_marker_needs_actual_original_native_UUID_and_action(change):
    rows,stages,ros=deadline_withheld_fixture();change(ros)
    assert audit_stages(rows,stages,ros)['errors']


def test_synthetic_goal_is_joined_to_original_estimate_not_current_or_world_position():
    rows,_,_=fixture();origin=copy.deepcopy(rows[1]['response']['intent'])
    result=audit_estimated_goal_origins(rows,dict(goals=[dict(origin_intent=origin)]))
    assert result['passed'] and result['exact_estimated_goal_origins']==1


@pytest.mark.parametrize('mutation',[
    lambda rows,goal:goal['command']['goal']['position_m'].__setitem__(0,9.),
    lambda rows,goal:goal['command']['goal'].update(yaw_rad=.5),
    lambda rows,goal:rows[0]['response']['feedback']['navigation']['position_m'].__setitem__(0,9.),
    lambda rows,goal:rows[0]['response']['feedback']['goal_status'].update(available=False),
    lambda rows,goal:rows[0]['response']['feedback']['goal_status'].update(fault='original_fault'),
    lambda rows,goal:rows.insert(0,copy.deepcopy(rows[0])),
])
def test_goal_geometry_origin_available_feedback_and_single_original_observation_are_required(mutation):
    rows,_,_=fixture();origin=copy.deepcopy(rows[1]['response']['intent']);mutation(rows,origin)
    assert not audit_estimated_goal_origins(rows,dict(goals=[dict(origin_intent=origin)]))['passed']


def emit_fixture():
    rows,stages,_=fixture();response=rows[2]['response']
    gate=dict(source=copy.deepcopy(stages[0]['source']),scan=copy.deepcopy(stages[0]['scan']),
        local_deadline=stages[0]['local_deadline'],gate_wall=200.0045,clock='linux_local_perf_counter',
        result=copy.deepcopy(response['result']),
        encoded_sha256=hashlib.sha256(encode_json(response,MAX_RESPONSE-1)+b'\n').hexdigest())
    return rows,stages,[gate]


def test_original_encoded_public_action_has_one_final_same_stage_50ms_gate():
    rows,stages,gates=emit_fixture();result=audit_emit_gates(rows,gates,stages)
    assert result['passed'] and result['qualified_final_emit_gates']==1


@pytest.mark.parametrize('mutation',[
    lambda r,s,g:g.clear(),
    lambda r,s,g:g.append(copy.deepcopy(g[0])),
    lambda r,s,g:g[0]['source'].update(episode=True),
    lambda r,s,g:g[0]['source'].update(observed_seq=99),
    lambda r,s,g:g[0]['source'].update(extra=1),
    lambda r,s,g:g[0]['scan'].update(cloud_frame_id=99),
    lambda r,s,g:g[0]['scan'].update(profile_sha256='4'*64),
    lambda r,s,g:g[0].update(local_deadline=200.1),
    lambda r,s,g:g[0]['result']['action']['command'].update(vx_mps=.9),
    lambda r,s,g:g[0]['result'].update(controller_goal_uuid='4'*32),
    lambda r,s,g:g[0].update(encoded_sha256='4'*64),
    lambda r,s,g:g[0].update(encoded_sha256='malformed'),
    lambda r,s,g:g[0].update(gate_wall=200.05),
    lambda r,s,g:g[0].update(gate_wall=200.051),
    lambda r,s,g:g[0].update(gate_wall=199.),
    lambda r,s,g:g[0].update(clock='host_perf_counter'),
    lambda r,s,g:g[0].update(extra=True),
    lambda r,s,g:s.append(copy.deepcopy(s[0])),
])
def test_emit_source_scan_result_bytes_original_deadline_and_single_receipt_are_required(mutation):
    rows,stages,gates=emit_fixture();mutation(rows,stages,gates)
    assert not audit_emit_gates(rows,gates,stages)['passed']


def test_hash_without_actual_trailing_newline_is_not_the_transmitted_bytes_hash():
    rows,stages,gates=emit_fixture()
    gates[0]['encoded_sha256']=hashlib.sha256(encode_json(rows[2]['response'],MAX_RESPONSE-1)).hexdigest()
    assert not audit_emit_gates(rows,gates,stages)['passed']


def test_final_gate_without_an_actual_public_response_cannot_count_as_delivered():
    rows,stages,gates=emit_fixture();rows.pop(2)
    result=audit_emit_gates(rows,gates,stages)
    assert not result['passed'] and result['qualified_final_emit_gates']==0 and result['unmatched_gate_records']==1
