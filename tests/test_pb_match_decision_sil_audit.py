"""Synthetic ledger mutations only; no native/ROS/build/physics is executed."""
import copy
import argparse
import hashlib
import math
import threading

import pytest

from rm_match.integrations.pb_match_decision_peer import UPSTREAM
from rm_match.platform_v2.contracts import IDENTITY
from rm_match.platform_v2.decision_contracts import decision_intent_for
from rm_match.deployment.navigation_plugin import navigation_status_for
from tools import qa_pb_match_decision_sil as module
from test_registered_pb_goal_sil_audit import fixture as registered_fixture


def fixture(branches=('healthy',)):
    rows, _, _ = registered_fixture()
    base = rows[1]['packet']['observation']
    base['own'].update(hp=400., heat=0., ammo=100., alive=True)
    base['referee'].update(phase='running', emergency_stop=False, remaining_seconds=400.)
    spec = dict(run_uuid='a' * 32,
        native_ref=dict(path='/root/fixture/bin/native', sha256='b' * 64),
        xml_ref=dict(path='/root/fixture/tree.xml', sha256='c' * 64),
        build_ref=dict(path='/mnt/c/fixture/BUILD_RESULT.json', sha256='d' * 64),
        expected_generation=dict(robot_id='red_sentry', episode=0, binding_epoch=1),
        waypoints=dict(schema='polar.pb.local-waypoints.v1', attack_offset_m=[1., 0.],
                       supply_offset_m=[0., 0.], yaw_offset_rad=0.))
    anchor = None; ticks = []; public = []
    def pose(x, y, stamp=0):
        return dict(header=dict(frame_id='map', stamp=dict(sec=stamp, nanosec=0)),
                    position_m=[x, y, 0.], rotation_xyzw=[0., 0., 0., 1.])
    for index, branch in enumerate(branches):
        original = copy.deepcopy(base)
        original['observed_seq'] += index
        if branch == 'low':
            original['own']['hp'] = 199.9
        elif branch == 'paused':
            original['referee']['phase'] = 'paused'
        elif branch == 'estop':
            original['referee']['emergency_stop'] = True
        elif branch == 'pending':
            original['navigation']['navigation'] = dict(available=False, reason='pending_navigation')
        source = {k: original[k] for k in IDENTITY}
        original['navigation']['source'] = copy.deepcopy(source)
        nav = original['navigation']['navigation']
        if nav['available'] and anchor is None:
            anchor = dict(source=copy.deepcopy(source), stamp_ns=nav['stamp_ns'],
                position_m=copy.deepcopy(nav['position_m']), rotation_xyzw=copy.deepcopy(nav['rotation_xyzw']),
                attack_pose=pose(nav['position_m'][0] + 1., nav['position_m'][1]),
                supply_pose=pose(nav['position_m'][0], nav['position_m'][1]))
        nodes = [dict(path='root/game', node_id='IsGameStatus', status='SUCCESS')]
        events = []
        if branch in ('paused', 'estop'):
            nodes[0]['status'] = 'FAILURE'
            nodes.append(dict(path='root/stop', node_id='ScopedHold', status='SUCCESS'))
            command = dict(behavior='hold', reason='pb_game_or_safety_hold')
        else:
            nodes.append(dict(path='root/status', node_id='IsStatusOK', status='FAILURE' if branch == 'low' else 'SUCCESS'))
            if branch == 'low':
                nodes.append(dict(path='root/rfid', node_id='IsRfidDetected', status='FAILURE'))
                message = copy.deepcopy(anchor['supply_pose']); message['header']['stamp']['sec'] = 123
                events = [dict(source=copy.deepcopy(source), node_name='supply_goal',
                    base_set_message_called=True, allowed=False, reason='rfid_unavailable', message=message)]
                command = dict(behavior='hold', reason='pb_rfid_unavailable')
            elif branch == 'pending':
                events = [dict(source=copy.deepcopy(source), node_name='attack_goal',
                    base_set_message_called=False, allowed=False, reason='pending_navigation', message=None)]
                command = dict(behavior='hold', reason='pb_navigation_unavailable')
            else:
                message = copy.deepcopy(anchor['attack_pose']); message['header']['stamp']['sec'] = 123
                events = [dict(source=copy.deepcopy(source), node_name='attack_goal',
                    base_set_message_called=True, allowed=True, reason='allowed', message=message)]
                command = dict(behavior='navigate_to_pose', reason='pb_rmul_2025_current_tick',
                    goal=dict(frame='map', position_m=message['position_m'][:2], yaw_rad=0.))
            nodes.append(dict(path='root/goal', node_id='PubNav2Goal', status='SUCCESS' if branch == 'healthy' else 'FAILURE'))
        intent = decision_intent_for(original, command)
        own = original['own']; ref = original['referee']
        tick = dict(schema='polar.pb.match-decision-tick.v1', tick_number=index + 1,
            source=copy.deepcopy(source), observation=original, intent=intent,
            tree=dict(tree_id='rmul_2025', xml_sha256='c' * 64, upstream_xml_sha256=module.UPSTREAM_XML_SHA256,
                      root_status='RUNNING', tick_steps=1), node_statuses=nodes, goal_events=events, anchor=copy.deepcopy(anchor),
            mapped_referee=dict(game_progress=0 if branch in ('paused', 'estop') else 4,
                stage_remain_time=math.floor(ref['remaining_seconds']), current_hp=math.floor(own['hp']),
                projectile_allowance_17mm=math.floor(own['ammo']), shooter_17mm_1_barrel_heat=math.ceil(own['heat']),
                integer_policy='hp_ammo_time_floor_heat_ceil', rfid_available=False, perception_available=False))
        ticks.append(tick)
        row = copy.deepcopy(rows[1]); row['packet']['observation'] = copy.deepcopy(original)
        row['response']['intent'] = copy.deepcopy(intent); public.append(row)
    return spec, ticks, public


def test_explicit_standalone_real_runner_shape_is_not_physical_qualification():
    spec, ticks, _ = fixture(('healthy', 'low', 'paused', 'estop'))
    audit = module.audit_native_ticks(ticks, spec, required_branches=('healthy_current_goal',
        'low_status_rfid_unavailable', 'paused_hold', 'emergency_stop_hold'))
    assert audit['passed'] and audit['healthy_current_tick_goals'] == 1
    assert audit['scope'] == 'standalone_native_protocol_inputs'


def test_every_public_intent_is_original_full_v2_native_tick_not_latest_retagged():
    spec, ticks, rows = fixture(('healthy', 'healthy'))
    audit = module.audit_native_ticks(ticks, spec, rows=rows)
    assert audit['passed'] and audit['public_intent_joins'] == 2
    rows[1]['packet']['observation']['navigation']['navigation']['position_m'][0] = 99.
    assert not module.audit_native_ticks(ticks, spec, rows=rows)['passed']


@pytest.mark.parametrize('mutate', [
    lambda t: t[0].update(schema='synthetic'),
    lambda t: t[0].update(tick_number=True),
    lambda t: t[0]['source'].update(episode=False),
    lambda t: t[0]['observation'].update(binding_epoch=2),
    lambda t: t[0]['intent']['command']['goal']['position_m'].__setitem__(0, 99.),
    lambda t: t[0]['tree'].update(xml_sha256='e' * 64),
    lambda t: t[0]['tree'].update(upstream_xml_sha256='e' * 64),
    lambda t: t[0]['tree'].update(tick_steps=True),
    lambda t: t[0]['tree'].update(root_status='SUCCESS'),
    lambda t: t[0].update(node_statuses=[]),
    lambda t: t[0]['node_statuses'][0].update(status='FAILURE'),
    lambda t: t[0]['node_statuses'][1].update(node_id='SyntheticStatus'),
    lambda t: t[0]['node_statuses'][2].update(status='FAILURE'),
    lambda t: t[0]['node_statuses'].append(dict(path='root/fire', node_id='PublishTwist', status='SUCCESS')),
    lambda t: t[0]['mapped_referee'].update(rfid_available=True),
    lambda t: t[0]['mapped_referee'].update(current_hp=399),
    lambda t: t[0]['anchor']['source'].update(observed_seq=999),
    lambda t: t[0]['anchor'].update(stamp_ns=999),
    lambda t: t[0]['anchor']['position_m'].__setitem__(0, 99.),
    lambda t: t[0]['anchor']['attack_pose']['position_m'].__setitem__(0, 99.),
    lambda t: t[0]['goal_events'][0]['source'].update(observed_seq=99),
    lambda t: t[0]['goal_events'][0].update(base_set_message_called=False),
    lambda t: t[0]['goal_events'][0].update(node_name='supply_goal'),
    lambda t: t[0]['goal_events'][0]['message']['position_m'].__setitem__(0, 99.),
    lambda t: t[0]['goal_events'][0]['message']['header'].update(frame_id='truth'),
    lambda t: t.append(copy.deepcopy(t[0])),
    lambda t: t[0].update(extra='unreviewed'),
])
def test_changed_source_real_node_original_goal_and_pins_fail_closed(mutate):
    spec, ticks, _ = fixture(); mutate(ticks)
    assert not module.audit_native_ticks(ticks, spec)['passed']


def test_missing_public_tick_and_unaccounted_extra_native_tick_are_rejected():
    spec, ticks, rows = fixture(('healthy', 'healthy'))
    assert not module.audit_native_ticks(ticks[:1], spec, rows=rows)['passed']
    assert not module.audit_native_ticks(ticks, spec, rows=rows[:1])['passed']
    fail = dict(event='peer_exchange_failed', peer='decision', packet=rows[1]['packet'], completed_wall=100.)
    allowed = module.audit_native_ticks(ticks, spec, rows=[rows[0], fail], allow_incomplete_after=100.)
    assert allowed['passed'] and allowed['unreturned_native_ticks'] == 1
    assert not module.audit_native_ticks(ticks, spec, rows=[rows[0], fail], allow_incomplete_after=101.)['passed']


def test_hold_and_pending_do_not_manufacture_goal_and_required_branch_is_explicit():
    spec, ticks, _ = fixture(('pending', 'healthy', 'low', 'paused', 'estop'))
    assert module.audit_native_ticks(ticks, spec)['passed']
    assert not module.audit_native_ticks(ticks[:1], spec, required_branches=('healthy_current_goal',))['passed']
    ticks[2]['intent']['command']['reason'] = 'missing_rfid_means_not_detected'
    assert not module.audit_native_ticks(ticks, spec)['passed']


def test_original_anchor_cannot_switch_to_latest_estimate():
    spec, ticks, _ = fixture(('healthy', 'healthy'))
    ticks[1]['anchor']['source'] = copy.deepcopy(ticks[1]['source'])
    assert not module.audit_native_ticks(ticks, spec)['passed']


def test_each_accepted_goal_joins_the_actual_native_set_message_not_previous_intent():
    spec, ticks, rows = fixture()
    intent = ticks[0]['intent']
    lifecycle = dict(goals=[dict(origin_intent=copy.deepcopy(intent), goal=copy.deepcopy(intent['command']['goal']))])
    assert module.audit_bt_goal_origins(rows, ticks, lifecycle)['passed']
    lifecycle['goals'][0]['origin_intent']['observed_seq'] += 1
    assert not module.audit_bt_goal_origins(rows, ticks, lifecycle)['passed']


def native_identity_fixture():
    spec, ticks, _ = fixture()
    ready = dict(schema='polar.pb.match-decision-native-ready.v1', run_uuid=spec['run_uuid'],
        native_ref=copy.deepcopy(spec['native_ref']), xml_ref=copy.deepcopy(spec['xml_ref']),
        build_ref=copy.deepcopy(spec['build_ref']), btcpp_version='4.6.2', tick_count=0, goal_sent=False)
    cleanup = dict(schema='polar.pb.match-decision-native-cleanup.v1', clean=True, tick_count=len(ticks),
        tree_halted=True, node_destroyed=True, context_shutdown=True, elapsed_s=.1, actuator_authority='none', protocol_interrupted=False)
    build = dict(schema='polar.pb.match-decision-build.v1', passed=True, source_unchanged=True, upstream=copy.deepcopy(UPSTREAM),
        native=copy.deepcopy(spec['native_ref']), xml=copy.deepcopy(spec['xml_ref']), btcpp=dict(version='4.6.2'),
        ldd=dict(all_resolved=True), commands=[dict(exit_code=0, reaped=True)])
    return spec, ready, cleanup, build


def test_native_identity_requires_actual_self_and_xml_ready_build_and_clean_shutdown():
    spec, ready, cleanup, build = native_identity_fixture()
    assert module.audit_native_identity(ready, cleanup, spec, build)['passed']


@pytest.mark.parametrize('change', [
    lambda r, c, b: r['native_ref'].update(sha256='e' * 64),
    lambda r, c, b: r['xml_ref'].update(sha256='e' * 64),
    lambda r, c, b: r.update(btcpp_version='3.8.7'),
    lambda r, c, b: r.update(tick_count=False),
    lambda r, c, b: r.update(goal_sent=True),
    lambda r, c, b: b.update(source_unchanged=False),
    lambda r, c, b: b['ldd'].update(all_resolved=False),
    lambda r, c, b: b['commands'][0].update(exit_code=False),
    lambda r, c, b: b['commands'][0].update(reaped=False),
    lambda r, c, b: c.update(clean=False),
    lambda r, c, b: c.update(elapsed_s=1.3),
    lambda r, c, b: c.update(actuator_authority='fire'),
    lambda r, c, b: c.update(protocol_interrupted=1),
])
def test_native_build_loader_readiness_and_owned_cleanup_corruption_rejected(change):
    spec, ready, cleanup, build = native_identity_fixture(); change(ready, cleanup, build)
    assert not module.audit_native_identity(ready, cleanup, spec, build)['passed']


def test_public_status_or_failed_candidate_never_counts_as_actual_consumption():
    rows, _, _ = registered_fixture(); action = copy.deepcopy(rows[2]['response']['result']['action'])
    rows.append(dict(event='navigation_consumed', phase='integration_entry', action=action,
        target=dict(motion=copy.deepcopy(action['command'])), consume_sim_time=.102))
    assert module.audit_public_consumption(rows)['passed']
    rows[2]['response']['result'].pop('action')
    assert not module.audit_public_consumption(rows)['passed']


@pytest.mark.parametrize('module_name', [
    'tests.fixtures.decision_navigation_feedback_v2', 'rm_match.integrations.pb_match_behavior_adapter',
    'rm_match.integrations.aim_jsonl_peer'])
def test_manifest_explicitly_rejects_synthetic_or_different_decision_peer(module_name):
    row = dict(command=['/usr/bin/python3', '-m', module_name, '--spec', '/mnt/c/fixture/SPEC.json', '--sha256', 'a' * 64])
    with pytest.raises(ValueError, match='real_native_pb_match_decision_peer_required_no_fixture'):
        module.decision_spec_reference(row)


def test_both_real_registered_peers_must_use_wsl_and_original_pipeline_ids(monkeypatch):
    monkeypatch.setattr(module, 'host_input_path', lambda p: p)
    nav = dict(adapter_id='nav', transport='wsl_jsonl_v1',
        capabilities=dict(schema='polar.sim.navigation-plugin.capabilities.v3'),
        command=['/usr/bin/python3', '-m', 'rm_match.integrations.pb_goal_plugin_peer',
                 '--spec', '/mnt/c/fixture/nav.json', '--sha256', 'a' * 64])
    decision = dict(adapter_id='decision', transport='wsl_jsonl_v1',
        capabilities=dict(schema='polar.sim.decision-plugin.capabilities.v2'),
        command=['/usr/bin/python3', '-m', 'rm_match.integrations.pb_match_decision_peer',
                 '--spec', '/mnt/c/fixture/decision.json', '--sha256', 'b' * 64])
    monkeypatch.setattr(module, 'navigation_spec_reference', lambda r: ('unused', 'a' * 64))
    graph = dict(pipelines=[dict(adapter_id='pipeline', supported_robots=['red_sentry'],
        navigation_plugin_id='nav', decision_plugin_id='decision')], rows=dict(aim=[], navigation=[nav], decision=[decision]))
    assert module.validate_graph(graph, 'pipeline')[2] is decision
    decision['transport'] = 'jsonl_v1'
    with pytest.raises(ValueError, match='registered_wsl_native_decision'):
        module.validate_graph(graph, 'pipeline')


def test_exact_xml_overlay_preserves_conditions_and_marks_all_five_edits(monkeypatch):
    # Small synthetic XML exercises the comparison; not an upstream-tree proof.
    original = b'<root BTCPP_format="4"><BehaviorTree ID="rmul_2025"><Sequence><IsStatusOK hp_min="200"/><PublishSpinSpeed spin_speed="0"/><PublishSpinSpeed spin_speed="7"/><PublishTwist v_x="0" v_y="0" v_yaw="0" duration="0"/><PubNav2Goal goal="0;0;0" topic_name="goal_pose"/><PubNav2Goal goal="4.65;-3.5;0" topic_name="goal_pose"/></Sequence></BehaviorTree></root>'
    overlay = b'<root BTCPP_format="4"><BehaviorTree ID="rmul_2025"><Sequence><IsStatusOK hp_min="200"/><AlwaysSuccess name="spin_disabled_explicit_overlay"/><AlwaysSuccess name="spin_disabled_explicit_overlay"/><ScopedHold name="game_safety_hold"/><PubNav2Goal goal="{@supply_pose}" name="supply_goal" topic_name="goal_pose_audit"/><PubNav2Goal goal="{@attack_pose}" name="attack_goal" topic_name="goal_pose_audit"/></Sequence></BehaviorTree></root>'
    monkeypatch.setattr(module, 'UPSTREAM_XML_SHA256', hashlib.sha256(original).hexdigest())
    spec = dict(xml_ref=dict(sha256=hashlib.sha256(overlay).hexdigest()))
    source = dict(original_xml_sha256=module.UPSTREAM_XML_SHA256,
        overlay_xml_sha256=spec['xml_ref']['sha256'], overlay=[{}] * 5)
    assert module.audit_xml_overlay(original, overlay, source, spec)['passed']
    changed = overlay.replace(b'hp_min="200"', b'hp_min="1"')
    spec['xml_ref']['sha256'] = source['overlay_xml_sha256'] = hashlib.sha256(changed).hexdigest()
    assert not module.audit_xml_overlay(original, changed, source, spec)['passed']


@pytest.mark.parametrize('value,expected', [('0.02', .02), ('0.06', .06), ('0.05', .05), (.02, .02), (.06, .06)])
def test_public_sdk_activation_period_accepts_only_bounded_legal_cadences(value, expected):
    assert module.activation_period_s(value) == expected


def test_original_public_sdk_cadence_remains_default_without_new_source_time():
    assert module.ORIGINAL_ACTIVATION_PERIOD_S == .05


@pytest.mark.parametrize('value', ['0.019999', '0.060001', 'nan', 'inf', '-inf', 'bad', True, None])
def test_public_sdk_activation_period_rejects_invalid_cli_values(value):
    with pytest.raises(argparse.ArgumentTypeError):
        module.activation_period_s(value)


def test_invalid_activation_period_fails_cli_before_artifact_or_runtime_actions(tmp_path):
    out = tmp_path / 'never-created'
    with pytest.raises(SystemExit) as error:
        module.main(['--run', '--decision-evidence-dir', str(tmp_path / 'peer'),
                     '--out', str(out), '--activation-period-s', '0.15'])
    assert error.value.code == 2 and not out.exists()


def test_actual_adapter_fault_interrupts_probe_and_sdk_with_original_claimed_cleanup_deadline():
    from rm_match.deployment.json_adapter import SharedCleanupBudget
    budget = SharedCleanupBudget(); original_deadline = budget.claim()
    sdk_stop = threading.Event(); authority_stop = threading.Event()
    row = dict(event='adapter_result', robot_id='red_sentry', error='ContractError')
    with pytest.raises(module.ObservedAdapterFault, match='actual_adapter_fault:ContractError'):
        module.stop_on_adapter_fault(row, sdk_stop=sdk_stop, claim_cleanup=budget.claim,
                                     request_stop=authority_stop.set)
    assert sdk_stop.is_set() and authority_stop.is_set()
    assert budget.claim() == original_deadline  # No new 1.5s after failure.


@pytest.mark.parametrize('row', [
    dict(event='adapter_result', robot_id='red_sentry', error=None),
    dict(event='adapter_result', robot_id='blue_sentry', error='ContractError'),
    dict(event='adapter_enqueue', robot_id='red_sentry', error='unrelated'),
])
def test_status_and_other_events_do_not_abort_or_start_cleanup(row):
    sdk_stop = threading.Event()
    def forbidden():
        raise AssertionError('normal status must not claim cleanup or stop authority')
    assert module.stop_on_adapter_fault(row, sdk_stop=sdk_stop, claim_cleanup=forbidden,
                                       request_stop=forbidden) is False
    assert not sdk_stop.is_set()


def wire_fixture(*, withheld=False, encoded=False):
    from rm_match.integrations.ros2_bridge import encode_json, MAX_RESPONSE
    rows, stages, ros = registered_fixture()
    candidate = copy.deepcopy(rows[2]['response']['result']); rejected = []
    if withheld:
        final = copy.deepcopy(candidate); final.pop('action')
        final.update(controller_goal_uuid=None, status=navigation_status_for(rows[0]['packet']['observation']))
        rows[2]['response']['result'] = copy.deepcopy(final)
        rejection = dict(reason='encoded_stage_deadline_expired' if encoded else 'original_stage_deadline_expired',
            original_deadline=stages[0]['local_deadline'], rejected_wall=200.051, result=candidate)
        if encoded:
            response = dict(schema=rows[2]['response']['schema'], op='act', ok=True, result=candidate)
            rejection['encoded_sha256'] = hashlib.sha256(encode_json(response, MAX_RESPONSE - 1) + b'\n').hexdigest()
        rejected = [rejection]
    return rows, stages, ros, [copy.deepcopy(rows[2]['response']['result'])], rejected


@pytest.mark.parametrize('withheld,encoded', [(False, False), (True, False), (True, True)])
def test_final_results_join_actual_wire_and_expired_native_action_becomes_original_source_status(withheld, encoded):
    rows, stages, ros, finals, rejected = wire_fixture(withheld=withheld, encoded=encoded)
    audit = module.audit_final_navigation_results(rows, finals, rejected, stages, ros_rows=ros)
    assert audit['passed'] and audit['public_final_result_joins'] == 1
    assert audit['rejected_actions_withheld_as_final_status'] == int(withheld)
    if withheld:
        # Source callback really saw the original native action. Final public
        # status withholds it, and cannot be credited as an emitted zero action.
        assert module.audit_stages(rows, stages, ros)['withheld_native_actions'] == 1
        assert module.audit_stages(rows, stages, ros)['errors'] == []
        assert module.audit_emit_gates(rows, [], stages)['errors'] == []


@pytest.mark.parametrize('change', [
    lambda r, f, x, ros: f.clear(),
    lambda r, f, x, ros: f.append(copy.deepcopy(f[0])),
    lambda r, f, x, ros: x.append(copy.deepcopy(x[0])),
    lambda r, f, x, ros: x[0].update(original_deadline=200.06),
    lambda r, f, x, ros: x[0].update(rejected_wall=200.049),
    lambda r, f, x, ros: x[0].update(reason='new_deadline_allowed'),
    lambda r, f, x, ros: x[0]['result']['source'].update(observed_seq=999),
    lambda r, f, x, ros: x[0]['result']['action']['command'].update(vx_mps=.9),
    lambda r, f, x, ros: x[0]['result'].update(controller_goal_uuid='f' * 32),
    lambda r, f, x, ros: f[0].update(selection=None),
    lambda r, f, x, ros: x[0].update(encoded_sha256='f' * 64),
    lambda r, f, x, ros: ros[2].update(receive_wall=200.05),
    lambda r, f, x, ros: ros[2].update(receive_clock='host_clock'),
])
def test_rejected_candidate_source_UUID_original_deadline_hash_and_final_wire_corruption_rejected(change):
    rows, stages, ros, finals, rejected = wire_fixture(withheld=True, encoded=True)
    change(rows, finals, rejected, ros)
    assert not module.audit_final_navigation_results(rows, finals, rejected, stages, ros_rows=ros)['passed']


def test_rejected_candidate_can_never_appear_as_a_public_action_or_physical_consumption():
    rows, stages, ros, finals, rejected = wire_fixture(withheld=True)
    action = copy.deepcopy(rejected[0]['result']['action'])
    rows.append(dict(event='navigation_consumed', phase='integration_entry', action=action,
        target=dict(motion=copy.deepcopy(action['command'])), consume_sim_time=.102))
    audit = module.audit_final_navigation_results(rows, finals, rejected, stages, ros_rows=ros)
    assert 'rejected_original_action_was_physically_consumed' in audit['errors']
    assert not module.audit_public_consumption(rows)['passed']
    rows.pop(); rows[2]['response']['result'] = copy.deepcopy(rejected[0]['result'])
    finals = [copy.deepcopy(rows[2]['response']['result'])]
    assert not module.audit_final_navigation_results(rows, finals, rejected, stages, ros_rows=ros)['passed']


def test_default_python_switch_scope_never_sets_interpreter_scheduling(monkeypatch):
    monkeypatch.setattr(module.sys, 'getswitchinterval', lambda: .005)
    def forbidden(_):
        raise AssertionError('default None must preserve interpreter scheduling')
    monkeypatch.setattr(module.sys, 'setswitchinterval', forbidden)
    record = {}
    with module.python_switch_interval_scope(None, record):
        assert record['original_s'] == record['actual_s'] == .005 and not record['changed']
    assert record['restored'] and record['restored_s'] == .005 and not record['restore_attempted']


@pytest.mark.parametrize('error', [None, ValueError, KeyboardInterrupt])
def test_explicit_python_1ms_scope_restores_original_even_for_aborted_run(monkeypatch, error):
    state = dict(interval=.005); sets = []; record = {}
    monkeypatch.setattr(module.sys, 'getswitchinterval', lambda: state['interval'])
    def set_interval(value):
        sets.append(value); state['interval'] = value
    monkeypatch.setattr(module.sys, 'setswitchinterval', set_interval)
    def execute():
        with module.python_switch_interval_scope(.001, record):
            assert state['interval'] == record['actual_s'] == .001
            if error is not None:
                raise error('test run aborted')
    if error is None:
        execute()
    else:
        with pytest.raises(error):
            execute()
    assert sets == [.001, .005] and state['interval'] == .005
    assert record['requested_s'] == .001 and record['restore_attempted'] and record['restored']
    assert record['scope_error_type'] == (None if error is None else error.__name__)


def test_failed_python_switch_readback_refuses_run_and_still_restores_original(monkeypatch):
    state = dict(interval=.005); sets = []; record = {}; ran = False
    monkeypatch.setattr(module.sys, 'getswitchinterval', lambda: .002 if state['interval'] == .001 else state['interval'])
    def set_interval(value):
        sets.append(value); state['interval'] = value
    monkeypatch.setattr(module.sys, 'setswitchinterval', set_interval)
    with pytest.raises(RuntimeError, match='python_switch_interval_readback_failed'):
        with module.python_switch_interval_scope(.001, record):
            ran = True
    assert not ran and sets == [.001, .005] and state['interval'] == .005
    assert record['actual_s'] == .002 and record['restored'] and record['restored_s'] == .005


def test_failed_python_switch_restoration_is_explicit_failure(monkeypatch):
    state = dict(interval=.005); record = {}
    monkeypatch.setattr(module.sys, 'getswitchinterval', lambda: state['interval'])
    def set_interval(value):
        if value == .001:
            state['interval'] = value
    monkeypatch.setattr(module.sys, 'setswitchinterval', set_interval)
    with pytest.raises(RuntimeError, match='python_switch_interval_restore_readback_failed'):
        with module.python_switch_interval_scope(.001, record):
            pass
    assert not record['restored'] and record['restored_s'] == .001
    assert record['restore_error_type'] == 'RuntimeError'


@pytest.mark.parametrize('value', ['0.001', .001])
def test_python_switch_cli_supports_only_explicit_1ms(value):
    assert module.python_switch_interval_s(value) == .001


@pytest.mark.parametrize('value', ['0.005', '0', 'nan', 'inf', True, None])
def test_python_switch_cli_rejects_other_intervals(value):
    with pytest.raises(argparse.ArgumentTypeError):
        module.python_switch_interval_s(value)


def test_invalid_python_switch_cli_fails_before_artifact_or_runtime_actions(tmp_path):
    out = tmp_path / 'never-created'
    with pytest.raises(SystemExit) as error:
        module.main(['--run', '--decision-evidence-dir', str(tmp_path / 'peer'),
                     '--out', str(out), '--python-switch-interval-s', '.005'])
    assert error.value.code == 2 and not out.exists()
