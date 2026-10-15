"""Deterministic ROS envelope transport tests; no live DDS or Nav2 claim."""
import copy
import io
import json

import pytest

from rm_match.deployment.navigation_plugin import GOAL_CAPABILITIES
from rm_match.integrations.robotio_ros2_bridge import RobotIOEnvelopeBridge, RobotIOSettings, serve
from rm_match.integrations.ros2_bridge import BridgeError, ENVELOPE_SCHEMA, JSONL_SCHEMA
from rm_match.platform_v2.contracts import ContractError
from test_active_goal_navigation_plugin import envelope, intent
from test_navigation_plugin import observation, action
from test_robotio_ros2_bridge import Clock, context


def settings(**kwargs):
    return RobotIOSettings(**dict(dict(adapter_id='custom_active_goal_ros', kind='navigation',
        node_name='active_goal_fixture', observation_topic='/fixture/input', action_topic='/fixture/output',
        domain_id=80, response_timeout=.05, goal_input=True, goal_result_profile='active_goal_v1'), **kwargs))


class Transport:
    def __init__(self, core, clock, *, mutate=None, delay=0.):
        self.core = core
        self.clock = clock
        self.mutate = mutate
        self.delay = delay
        self.response = None
        self.published = []

    def wait_ready(self, timeout):
        assert 0 < timeout <= 1.

    def publish(self, payload):
        packet = json.loads(payload)
        self.published.append(packet)
        if packet['type'] == 'capabilities_request':
            self.response = dict(schema=ENVELOPE_SCHEMA, type='capabilities', adapter_id=packet['adapter_id'],
                context=packet['context'], capabilities=copy.deepcopy(packet['capabilities']))
        else:
            current = packet['intent']
            result = envelope(packet['observation'], current,
                status=current['command']['behavior'] != 'navigate_to_pose')
            self.response = dict(schema=ENVELOPE_SCHEMA, type='result', adapter_id=packet['adapter_id'], result=result)
        if self.mutate is not None:
            self.mutate(self.response)

    def spin_once(self, timeout):
        assert 0 < timeout <= .005
        self.clock.now += self.delay
        response, self.response = self.response, None
        if response is not None:
            self.core.receive_action(json.dumps(response))


def negotiated():
    clock = Clock()
    core = RobotIOEnvelopeBridge(settings(), clock=clock)
    o = observation()
    o['wall_deadline'] = 17.  # Host deadline is opaque to this ROS peer.
    core.reset(context(o), {})
    transport = Transport(core, clock)
    core.negotiate(transport)
    return core, clock, transport, o


@pytest.mark.parametrize('changes', [dict(goal_input=False), dict(kind='decision', goal_input=False),
    dict(goal_result_profile='latest_uuid'), dict(goal_result_profile=True), dict(response_timeout=.051)])
def test_explicit_goal_result_profile_keeps_original_navigation_budget(changes):
    with pytest.raises(ContractError):
        settings(**changes)


def test_v2_capability_handshake_and_original_foreign_deadline():
    core, clock, transport, o = negotiated()
    assert core.capabilities == GOAL_CAPABILITIES
    assert transport.published[0]['capabilities'] == GOAL_CAPABILITIES
    current = intent(o)
    result = core.exchange(o, transport, current)
    assert result == envelope(o, current)
    assert transport.published[-1]['intent'] == current
    assert transport.published[-1]['observation'] == o
    assert clock.now == 100. and result['source']['wall_deadline'] == 17.
    assert core._pending is None and core._pending_intent is None


@pytest.mark.parametrize('behavior', ['hold', 'cancel'])
def test_stop_is_current_status_never_relabelled_zero_velocity(behavior):
    core, _, transport, o = negotiated()
    result = core.exchange(o, transport, intent(o, behavior))
    assert result['controller_goal_uuid'] is None and result['selection'] is None
    assert 'status' in result and 'action' not in result


@pytest.mark.parametrize('change', [
    lambda row: row['result'].update(controller_goal_uuid='c'*32),
    lambda row: row['result']['source'].update(observed_seq=0),
    lambda row: row['result']['selection'].update(cancel_requested=True),
    lambda row: row.update(adapter_id='custom_other'),
    lambda row: row.update(type='action'),
])
def test_invalid_goal_route_source_or_current_selection_fails_closed(change):
    core, _, transport, o = negotiated()
    transport.mutate = change
    with pytest.raises(ContractError):
        core.exchange(o, transport, intent(o))
    assert core._response is None


def test_v2_rejects_legacy_bare_velocity_response():
    core, _, transport, o = negotiated()
    def bare(row):
        row.pop('result')
        row.update(type='action', action=action(o))
    transport.mutate = bare
    with pytest.raises(ContractError):
        core.exchange(o, transport, intent(o))


def test_original_local50ms_not_extended_by_goal_proof():
    core, clock, transport, o = negotiated()
    transport.delay = .05
    with pytest.raises(BridgeError, match='expired'):
        core.exchange(o, transport, intent(o))
    assert clock.now == 100.05 and core._response is None


def test_serve_preserves_envelope_over_jsonl_including_capability_ack():
    clock = Clock()
    core = RobotIOEnvelopeBridge(settings(), clock=clock)
    transport = Transport(core, clock)
    o = observation()
    rows = [dict(schema=JSONL_SCHEMA, op='reset', context=context(o), config={}),
        dict(schema=JSONL_SCHEMA, op='act', observation=o, intent=intent(o))]
    output = io.BytesIO()
    serve(core, transport, io.BytesIO(b''.join(json.dumps(row).encode()+b'\n' for row in rows)), output)
    responses = [json.loads(row) for row in output.getvalue().splitlines()]
    assert responses[0]['capabilities'] == GOAL_CAPABILITIES
    assert responses[1] == dict(schema=JSONL_SCHEMA, op='act', ok=True, result=envelope(o))
