"""Protocol and harmless process evidence, not PB decisions or match acceptance."""
import base64
import copy
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from rm_match.deployment.decision_plugin import (
    CAPABILITIES, MANIFEST_SCHEMA, DecisionPluginAdapter, load_decision_plugins)
from rm_match.deployment.json_adapter import SCHEMA as JSONL_SCHEMA
from rm_match.integrations.decision_jsonl_peer import serve_decision_plugin
from rm_match.platform_v2.contracts import ContractError, IDENTITY
from rm_match.platform_v2.decision_contracts import (
    build_decision_observation, decision_intent_for, validate_decision_intent,
    validate_decision_observation)
from rm_match.platform_v2.navigation_contracts import NAV_FRAMES, NAV_SCHEMA, POINT_ENCODING

FIXTURES = Path(__file__).parent / 'fixtures'


def nav_observation():
    ext = dict(parent_frame='base_link', translation_m=[0., 0., .5],
               rotation_xyzw=[0., 0., 0., 1.], calibration_id='decision_fixture_mount')
    return dict(schema=NAV_SCHEMA, robot_id='blue_sentry', episode=2, binding_epoch=3,
        observed_seq=1, sim_time=.1, wall_deadline=time.perf_counter() + 10.,
        frames=dict(NAV_FRAMES), own=dict(team='blue', role='sentry', hp=400.,
        ammo=10., heat=0., alive=True), referee=dict(phase='running', remaining_seconds=299.,
        emergency_stop=False), sensors=dict(pointcloud=dict(available=True, reason='available',
        frame_id=1, acquisition_start_ns=0, acquisition_end_ns=100000000,
        capture_sim_time=.1, frame='livox_frame', encoding=POINT_ENCODING, point_count=1,
        data_base64=base64.b64encode(struct.pack('<fffIBBBx', 1., 0., 0., 0, 24, 0x10, 0)).decode(),
        range_min_m=.1, range_max_m=20., time_quantization_ns=2000000,
        provenance='mujoco_ray_cast_nonrepeating_profile_v1', profile_sha256='1' * 64,
        extrinsics=ext), imu=dict(available=True, reason='available', frame='livox_frame',
        capture_sim_time=.1, extrinsics=copy.deepcopy(ext), provenance='mujoco_gyro_accelerometer_v1',
        samples=[dict(sample_sim_ns=t, angular_velocity_rps=[.1, .2, .3],
        linear_acceleration_mps2=[0., 0., 9.81]) for t in (0, 100000000)])))


def observation():
    return build_decision_observation(nav_observation())


def hold(value):
    return decision_intent_for(value, dict(behavior='hold', reason='explicit_synthetic_hold'))


def packets(value):
    context = {name: value[name] for name in ('robot_id', 'episode', 'binding_epoch')}
    return [dict(schema=JSONL_SCHEMA, op='reset', context=context, config={}),
            dict(schema=JSONL_SCHEMA, op='act', observation=value)]


def serve(rows, compute=hold):
    output = io.BytesIO()
    raw = ('\n'.join(json.dumps(row) for row in rows) + '\n').encode()
    serve_decision_plugin(compute, io.BytesIO(raw), output)
    return [json.loads(row) for row in output.getvalue().splitlines()]


def manifest(tmp_path, fixture='decision_supply_v1.py'):
    row = dict(adapter_id='custom_external_decision', label='Synthetic decision interface fixture',
        command=[sys.executable, '-u', str(FIXTURES / fixture)], cwd=str(FIXTURES),
        supported_robots=['blue_sentry', 'red_infantry'], transport='jsonl_v1',
        capabilities=copy.deepcopy(CAPABILITIES))
    path = tmp_path / 'decision.json'
    path.write_text(json.dumps(dict(schema=MANIFEST_SCHEMA, adapters=[row])), encoding='utf8')
    return path, row


def adapter(tmp_path, fixture='decision_supply_v1.py'):
    path, row = manifest(tmp_path, fixture)
    rows, sha = load_decision_plugins(path)
    return DecisionPluginAdapter({}, registration=rows[0], manifest=path, manifest_sha=sha), path


def negotiated_adapter_without_process(tmp_path):
    result, path = adapter(tmp_path)
    value = observation()
    def ack(packet, timeout):
        response = dict(schema=JSONL_SCHEMA, op=packet['op'], ok=True,
                        capabilities=copy.deepcopy(CAPABILITIES))
        result._validate_response(response, packet)
        return response
    with patch.object(result, '_open_owned_process'), patch.object(result, '_exchange', side_effect=ack):
        result.reset({name: value[name] for name in ('episode', 'robot_id', 'binding_epoch')})
    return result, value, path


def test_projection_keeps_own_referee_and_six_original_identities_only():
    original = nav_observation()
    projected = build_decision_observation(original)
    assert {name: projected[name] for name in IDENTITY} == {name: original[name] for name in IDENTITY}
    assert projected['own'] == original['own'] and projected['referee'] == original['referee']
    assert 'frames' not in projected and 'sensors' not in projected
    assert not projected['navigation']['available'] and not projected['perception']['available']
    original['own']['hp'] = 0
    assert projected['own']['hp'] == 400.
    for key, bad in [('enemy_positions', [[1., 2.]]), ('odom_xyyaw', [0., 0., 0.])]:
        polluted = nav_observation()
        polluted[key] = bad
        with pytest.raises(ContractError):
            build_decision_observation(polluted)


@pytest.mark.parametrize('mutate', [
    lambda value: value.update(enemy_positions=[[1., 2.]]),
    lambda value: value['own'].update(odom_xyyaw=[0., 0., 0.]),
    lambda value: value['perception'].update(available=True, enemies=[]),
    lambda value: value['navigation'].update(available=True, pose=[0., 0., 0.]),
    lambda value: value['own'].update(hp=float('nan'))])
def test_truth_or_unavailable_extensions_rejected_before_compute(mutate):
    value = observation()
    mutate(value)
    with patch(__name__ + '.hold') as compute:
        with pytest.raises(ContractError):
            serve(packets(value), compute)
        compute.assert_not_called()


@pytest.mark.parametrize('command', [
    dict(behavior='cancel', reason='explicit_cancel'),
    dict(behavior='hold', reason='explicit_hold'),
    dict(behavior='navigate_to_pose', reason='explicit_goal',
         goal=dict(frame='map', position_m=[2., -1.], yaw_rad=.4))])
def test_source_bound_intents_have_no_actuator_authority(command):
    value = observation()
    intent = decision_intent_for(value, command)
    assert validate_decision_intent(intent, value) == intent
    assert intent['kind'] == 'decision' and intent['mode'] == 'navigation_intent'
    assert 'action' not in intent and 'fire' not in intent['command']


@pytest.mark.parametrize('mutate', [
    lambda value: value['command'].update(fire=True),
    lambda value: value['command'].update(vx_mps=1.),
    lambda value: value['command'].update(yaw_rad=.1),
    lambda value: value['command'].update(goal=dict(frame='world', position_m=[1., 2.], yaw_rad=0.)),
    lambda value: value.update(kind='navigation'),
    lambda value: value.update(robot_id='red_infantry'),
    lambda value: value.update(episode=3),
    lambda value: value.update(observed_seq=0),
    lambda value: value.update(sim_time=.09),
    lambda value: value.update(wall_deadline=value['wall_deadline'] + 1.),
    lambda value: value.update(sim_time=0)])
def test_actuation_or_retaged_identity_rejected(mutate):
    value = observation()
    intent = hold(value)
    mutate(intent)
    with pytest.raises(ContractError):
        validate_decision_intent(intent, value)


def test_goal_frame_nan_and_boolean_position_rejected():
    value = observation()
    for field, bad in [('frame', 'world'), ('position_m', [True, 2.]),
                       ('position_m', [float('nan'), 2.]), ('yaw_rad', float('nan'))]:
        goal = dict(frame='map', position_m=[2., -1.], yaw_rad=.4)
        goal[field] = bad
        with pytest.raises(ContractError):
            decision_intent_for(value, dict(behavior='navigate_to_pose', reason='invalid', goal=goal))


def test_reset_capabilities_are_negotiated_not_just_locally_declared(tmp_path):
    result, value, path = negotiated_adapter_without_process(tmp_path)
    assert result._negotiated and result.descriptor['kind'] == 'decision'
    packet = packets(value)[0]
    correct = dict(schema=JSONL_SCHEMA, op='reset', ok=True, capabilities=copy.deepcopy(CAPABILITIES))
    for bad in [dict(schema=JSONL_SCHEMA, op='reset', ok=True),
                dict(correct, capabilities=dict(CAPABILITIES, fire_authority='manual_only')),
                dict(correct, capabilities=dict(CAPABILITIES, sensor_profile='ideal_world_pose'))]:
        with pytest.raises(ContractError):
            result._validate_response(bad, packet)


@pytest.mark.parametrize('field,bad', [('fire_authority', 'algorithm_fire'),
    ('sensor_profile', 'full_world_truth'), ('output_modes', ['velocity_body']),
    ('source_association', 'latest_response'), ('unknown', True)])
def test_unsupported_capabilities_rejected_before_any_spawn(tmp_path, field, bad):
    path, row = manifest(tmp_path)
    row['capabilities'][field] = bad
    path.write_text(json.dumps(dict(schema=MANIFEST_SCHEMA, adapters=[row])), encoding='utf8')
    with patch('rm_match.deployment.json_adapter.OwnedJsonProcess') as spawn:
        with pytest.raises(ContractError):
            load_decision_plugins(path)
        spawn.assert_not_called()


def test_http_config_manifest_changes_and_cross_robot_rejected_before_spawn(tmp_path):
    result, path = adapter(tmp_path)
    with pytest.raises(ContractError):
        DecisionPluginAdapter({'command': ['bad']}, registration=result.registration,
                              manifest=path, manifest_sha=result.manifest_sha)
    value = observation()
    context = {name: value[name] for name in ('episode', 'robot_id', 'binding_epoch')}
    with patch('rm_match.deployment.json_adapter.OwnedJsonProcess') as spawn:
        with pytest.raises(ContractError):
            result.reset(dict(context, robot_id='red_hero'))
        path.write_bytes(path.read_bytes() + b' ')
        with pytest.raises(ContractError, match='manifest_changed'):
            result.reset(context)
        spawn.assert_not_called()


def test_original_deadline_and_replay_stop_host_before_new_exchange(tmp_path):
    result, value, path = negotiated_adapter_without_process(tmp_path)
    result._last_seq = value['observed_seq']
    with patch.object(result, '_exchange') as exchange:
        with pytest.raises(ContractError, match='replayed'):
            result.act(value)
        exchange.assert_not_called()
    result._last_seq = -1
    value['wall_deadline'] = time.perf_counter() - 1.
    with patch.object(result, '_open_owned_process') as spawn:
        with pytest.raises(ContractError):
            result.act(value)
        spawn.assert_not_called()


def test_peer_reset_prepare_order_replay_and_callback_mutation():
    value = observation()
    rows = packets(value)
    rows.insert(0, dict(schema=JSONL_SCHEMA, op='prepare', config={}))
    replies = serve(rows)
    assert replies[0]['capabilities'] == replies[1]['capabilities'] == CAPABILITIES
    assert replies[-1]['intent'] == hold(value)
    with pytest.raises(ContractError, match='replayed'):
        serve([*packets(value), packets(value)[-1]])
    with pytest.raises(ContractError, match='reset_required'):
        serve([packets(value)[-1]])
    def mutate(current):
        current['binding_epoch'] += 1
        return hold(current)
    with pytest.raises(ContractError):
        serve(packets(value), mutate)
    with pytest.raises(ContractError):
        serve(packets(value), lambda current: None)


def test_peer_partial_duplicate_and_nonfinite_wire_have_no_implicit_intent():
    for raw in [b'{"schema":"x"}',
                b'{"schema":"x","schema":"x"}\n',
                b'{"schema":"x","hp":NaN}\n']:
        output = io.BytesIO()
        with pytest.raises(ContractError):
            serve_decision_plugin(hold, io.BytesIO(raw), output)
        assert output.getvalue() == b''


def test_peer_cross_robot_and_backwards_sim_time_do_not_reach_compute():
    value = observation()
    wrong_robot = copy.deepcopy(value)
    wrong_robot['robot_id'] = 'red_infantry'
    seen = []
    def compute(current):
        seen.append(current['observed_seq'])
        return hold(current)
    with pytest.raises(ContractError, match='generation'):
        serve([packets(value)[0], packets(wrong_robot)[1]], compute)
    assert seen == []
    backwards = copy.deepcopy(value)
    backwards['observed_seq'] += 1
    backwards['sim_time'] -= .01
    with pytest.raises(ContractError, match='replayed'):
        serve([*packets(value), packets(backwards)[1]], compute)
    assert seen == [value['observed_seq']]


@pytest.mark.parametrize('fixture,version,behavior', [
    ('decision_supply_v1.py', b'synthetic_supply_v1', 'navigate_to_pose'),
    ('decision_heat_v2.py', b'synthetic_heat_v2', 'hold')])
def test_two_independent_actual_jsonl_implementations_are_interchangeable(fixture, version, behavior):
    value = observation()
    raw = ('\n'.join(json.dumps(row) for row in packets(value)) + '\n').encode()
    child = subprocess.run([sys.executable, '-u', str(FIXTURES / fixture)], input=raw,
                           capture_output=True, timeout=5.)
    assert child.returncode == 0
    replies = [json.loads(row) for row in child.stdout.splitlines()]
    assert len(replies) == 2 and replies[0]['capabilities'] == CAPABILITIES
    intent = validate_decision_intent(replies[-1]['intent'], value)
    assert intent['command']['behavior'] == behavior
    assert version + b' resource initialization' in child.stderr
    assert version + b' callback' in child.stderr


@pytest.mark.parametrize('fixture,behavior', [('decision_supply_v1.py', 'navigate_to_pose'),
                                            ('decision_heat_v2.py', 'hold')])
def test_actual_owned_host_negotiates_each_policy_and_preserves_deadline(tmp_path, fixture, behavior):
    result, path = adapter(tmp_path, fixture)
    value = observation()
    context = {name: value[name] for name in ('episode', 'robot_id', 'binding_epoch')}
    try:
        result.reset(context, deadline=time.perf_counter() + 2.)
        assert result._negotiated
        value['wall_deadline'] = time.perf_counter() + .15
        intent = result.act(value)
        assert {name: intent[name] for name in IDENTITY} == {name: value[name] for name in IDENTITY}
        assert intent['command']['behavior'] == behavior
    finally:
        result.close()
    assert result.shutdown_status['clean'] and result.shutdown_status['io_thread_stopped']
    assert result.shutdown_status['ownership']['reaped']
    assert result.shutdown_status['ownership']['group_empty']


def test_actual_wrong_peer_capabilities_cannot_become_negotiated(tmp_path):
    wrong_peer = tmp_path / 'wrong_peer.py'
    wrong_caps = dict(CAPABILITIES, fire_authority='algorithm_fire')
    wrong_peer.write_text(
        'import json,sys\n'
        'for line in sys.stdin:\n'
        ' request=json.loads(line)\n'
        ' response=dict(schema=' + repr(JSONL_SCHEMA) + ',op=request["op"],ok=True,capabilities=' +
        repr(wrong_caps) + ')\n'
        ' print(json.dumps(response),flush=True)\n', encoding='utf8')
    path, row = manifest(tmp_path)
    row['command'] = [sys.executable, '-u', str(wrong_peer)]
    path.write_text(json.dumps(dict(schema=MANIFEST_SCHEMA, adapters=[row])), encoding='utf8')
    rows, sha = load_decision_plugins(path)
    result = DecisionPluginAdapter({}, registration=rows[0], manifest=path, manifest_sha=sha)
    value = observation()
    context = {name: value[name] for name in ('episode', 'robot_id', 'binding_epoch')}
    with pytest.raises(ContractError, match='capability_fire_authority'):
        result.reset(context)
    assert not result._negotiated and result.failed and result.process is None
    assert result.shutdown_status['clean']
    assert result.shutdown_status['ownership']['reaped']
    assert result.shutdown_status['ownership']['group_empty']
