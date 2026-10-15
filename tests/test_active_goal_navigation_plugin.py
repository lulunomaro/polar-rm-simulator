"""Registered protocol and owned-process checks; no team algorithm proof."""
import copy
import io
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

import pytest

from rm_match.deployment.navigation_plugin import (
    CAPABILITIES, GOAL_CAPABILITIES, MANIFEST_SCHEMA, NavigationPluginAdapter,
    navigation_status_for, register_navigation_plugins, validate_capabilities,
)
from rm_match.integrations.navigation_jsonl_peer import serve_navigation_plugin
from rm_match.integrations.ros2_bridge import JSONL_SCHEMA
from rm_match.platform_v2.adapters import BaseAdapter, Registry
from rm_match.platform_v2.contracts import ContractError, IDENTITY
from rm_match.platform_v2.decision_contracts import build_decision_observation, decision_intent_for
from test_navigation_plugin import observation, action


def intent(o, behavior='navigate_to_pose'):
    command = dict(behavior=behavior, reason='synthetic protocol test')
    if behavior == 'navigate_to_pose':
        command['goal'] = dict(frame='map', position_m=[1., 2.], yaw_rad=.1)
    return decision_intent_for(build_decision_observation(o), command)


def envelope(o, current=None, *, status=False):
    current = intent(o) if current is None else current
    source = {k: copy.deepcopy(o[k]) for k in IDENTITY}
    selection = dict(operation_id='a'*32, origin_intent=copy.deepcopy(current),
        latest_authorization=copy.deepcopy(source), goal_uuids=dict(planner=None, navigation='b'*32),
        state='active', cancel_requested=False, terminal=False, stop_confirmed=False)
    if current['command']['behavior'] != 'navigate_to_pose':
        selection = None
    return dict(schema='polar.sim.navigation-goal-result.v1', source=source, intent=copy.deepcopy(current),
        selection=selection, controller_goal_uuid=None if status else 'b'*32,
        **{'status' if status else 'action': navigation_status_for(o) if status else action(o)})


def make_adapter(tmp_path, *, transport='jsonl_v1', command=None):
    row = dict(adapter_id='custom_active_goal', label='Synthetic active goal fixture',
        command=command or [sys.executable, '-u', 'unused_fixture.py'], cwd='.',
        supported_robots=['blue_sentry', 'red_infantry'], transport=transport,
        capabilities=copy.deepcopy(GOAL_CAPABILITIES))
    path = tmp_path/'navigation.json'
    path.write_text(json.dumps(dict(schema=MANIFEST_SCHEMA, adapters=[row])), encoding='utf8')
    registry = Registry()
    register_navigation_plugins(registry, path)
    adapter = registry.create('custom_active_goal', {})
    o = observation()
    BaseAdapter.reset(adapter, {k: o[k] for k in ('robot_id', 'episode', 'binding_epoch')})
    return adapter, o, registry


def wire(value):
    return dict(schema=JSONL_SCHEMA, op='act', ok=True, result=value)


def test_v2_registration_catalog_and_detached_negotiation(tmp_path):
    adapter, o, registry = make_adapter(tmp_path)
    assert isinstance(adapter, NavigationPluginAdapter)
    descriptor = registry.descriptors()[0]
    assert descriptor['navigation_plugin_capabilities'] == GOAL_CAPABILITIES
    assert descriptor['goal_input_modes'] == ['decision_intent_v1']
    descriptor['navigation_plugin_capabilities']['output_modes'].clear()
    assert registry.descriptors()[0]['navigation_plugin_capabilities'] == GOAL_CAPABILITIES
    response = dict(schema=JSONL_SCHEMA, op='reset', ok=True, capabilities=copy.deepcopy(GOAL_CAPABILITIES))
    adapter._validate_response(response, dict(op='reset'))
    response['capabilities'] = dict(copy.deepcopy(CAPABILITIES), goal_input_modes=['decision_intent_v1'])
    with pytest.raises(ContractError, match='capabilities_mismatch'):
        adapter._validate_response(response, dict(op='reset'))


@pytest.mark.parametrize('key,value', [
    ('source_association', 'exact_capture_context_v1'), ('goal_input_modes', []),
    ('goal_result_schema', 'unknown'), ('schema', 'polar.sim.navigation-plugin.capabilities.v1'),
    ('fire_authority', 'algorithm'), ('output_modes', ['gimbal_target']), ('extra', True),
])
def test_v2_capabilities_cannot_silently_downgrade(key, value):
    caps = copy.deepcopy(GOAL_CAPABILITIES)
    caps[key] = value
    with pytest.raises(ContractError):
        validate_capabilities(caps)


def test_host_returns_only_action_and_retains_detached_original_goal_receipt(tmp_path):
    adapter, o, _ = make_adapter(tmp_path)
    current = intent(o)
    result = envelope(o, current)
    original = copy.deepcopy(result)
    def exchange(packet, timeout):
        assert packet['intent'] == current and packet['observation'] == o
        assert 0 < timeout <= .15
        adapter._validate_response(wire(result), packet)
        return wire(result)
    adapter._exchange = exchange
    assert adapter.act_with_intent(o, current) == action(o)
    assert adapter.last_goal_result == original
    result['selection']['goal_uuids']['navigation'] = 'c'*32
    assert adapter.last_goal_result == original


@pytest.mark.parametrize('change', [
    lambda result: result.update(controller_goal_uuid='c'*32),
    lambda result: result['selection'].update(state='canceling', cancel_requested=True),
    lambda result: result['selection'].update(terminal=True),
    lambda result: result['selection']['latest_authorization'].update(observed_seq=0),
    lambda result: result['source'].update(episode=True),
    lambda result: result['selection']['origin_intent']['command']['goal'].update(position_m=[9., 9.]),
])
def test_custom_exchange_cannot_bypass_active_goal_validation(tmp_path, change):
    adapter, o, _ = make_adapter(tmp_path)
    result = envelope(o)
    change(result)
    with patch.object(adapter, '_exchange', return_value=wire(result)):
        with pytest.raises(ContractError):
            adapter.act_with_intent(o, intent(o))
    assert getattr(adapter, 'last_goal_result', None) is None


def test_v1_bare_response_rejected_under_v2_and_no_implicit_goal(tmp_path):
    adapter, o, _ = make_adapter(tmp_path)
    with patch.object(adapter, '_exchange') as exchange:
        assert adapter.act(o) == navigation_status_for(o)
        exchange.assert_not_called()
    with patch.object(adapter, '_exchange', return_value=dict(schema=JSONL_SCHEMA, op='act', ok=True, action=action(o))):
        with pytest.raises(ContractError):
            adapter.act_with_intent(o, intent(o))


@pytest.mark.parametrize('behavior', ['hold', 'cancel'])
def test_stop_status_preserves_original_intent_and_never_returns_zero_action(tmp_path, behavior):
    adapter, o, _ = make_adapter(tmp_path)
    current = intent(o, behavior)
    result = envelope(o, current, status=True)
    with patch.object(adapter, '_exchange', return_value=wire(result)):
        assert adapter.act_with_intent(o, current) == navigation_status_for(o)
    assert adapter.last_goal_result['intent'] == current


def test_host_history_rejects_same_operation_with_rewritten_origin(tmp_path):
    adapter, o, _ = make_adapter(tmp_path)
    first = envelope(o)
    with patch.object(adapter, '_exchange', return_value=wire(first)):
        adapter.act_with_intent(o, intent(o))
    later = copy.deepcopy(o)
    later['observed_seq'] += 1
    later['wall_deadline'] += .01
    # Each envelope passes stateless shape checks; a reused operation may not
    # acquire a newly invented origin just because the scan is newer.
    second = envelope(later)
    with patch.object(adapter, '_exchange', return_value=wire(second)):
        with pytest.raises(ContractError):
            adapter.act_with_intent(later, intent(later))
    assert adapter.last_goal_result is None


def test_receipt_is_not_cached_as_current_when_no_explicit_intent(tmp_path):
    adapter, o, _ = make_adapter(tmp_path)
    with patch.object(adapter, '_exchange', return_value=wire(envelope(o))):
        adapter.act_with_intent(o, intent(o))
    assert adapter.last_goal_result is not None
    assert adapter.act(o) == navigation_status_for(o)
    assert adapter.last_goal_result is None


def test_peer_v2_requires_intent_and_does_not_accept_plain_action():
    o = observation()
    reset = dict(schema=JSONL_SCHEMA, op='reset', context={k:o[k] for k in ('robot_id','episode','binding_epoch')}, config={})
    request = dict(schema=JSONL_SCHEMA, op='act', observation=o, intent=intent(o))
    def run(compute, packet):
        output = io.BytesIO()
        serve_navigation_plugin(compute, io.BytesIO(b''.join(json.dumps(r).encode()+b'\n' for r in (reset, packet))),
            output, goal_input_modes=['decision_intent_v1'], goal_result_profile='active_goal_v1')
        return [json.loads(row) for row in output.getvalue().splitlines()]
    responses = run(lambda o, i: envelope(o, i), request)
    assert responses[0]['capabilities'] == GOAL_CAPABILITIES
    assert responses[1] == wire(envelope(o))
    with pytest.raises(ContractError):
        run(lambda o, i: action(o), request)
    del request['intent']
    with pytest.raises(ContractError, match='intent_required'):
        run(lambda *args: pytest.fail('missing intent reached compute'), request)


def test_actual_owned_v2_jsonl_peer_reset_action_and_cancellation_cleanup(tmp_path):
    fixture = Path(__file__).parent/'fixtures'/'active_goal_navigation_fixture.py'
    adapter, o, _ = make_adapter(tmp_path, command=[sys.executable, '-u', str(fixture.resolve())])
    try:
        adapter.reset(adapter.context)
        o['wall_deadline'] = time.perf_counter()+.15
        result = adapter.act_with_intent(o, intent(o))
        assert result['mode'] == 'velocity_body' and result['command']['vx_mps'] == .2
        assert adapter.last_goal_result['selection']['goal_uuids']['navigation'] == adapter.last_goal_result['controller_goal_uuid']
        later = copy.deepcopy(o)
        later['observed_seq'] += 1
        later['wall_deadline'] = time.perf_counter()+.15
        assert adapter.act_with_intent(later, intent(later, 'hold')) == navigation_status_for(later)
    finally:
        adapter.close()
    assert adapter.shutdown_status['clean']
