"""Fake ROS envelope transport only; no DDS or ROS algorithm acceptance."""
import copy
import io
import json

import pytest

from rm_match.integrations.robotio_ros2_bridge import RobotIOEnvelopeBridge, RobotIOSettings, serve
from rm_match.integrations.ros2_bridge import BridgeError, ENVELOPE_SCHEMA, JSONL_SCHEMA
from rm_match.platform_v2.contracts import ContractError, IDENTITY, action_for
from rm_match.platform_v2.decision_contracts import build_decision_observation, decision_intent_for
from test_decision_plugin import nav_observation


class Clock:
    def __init__(self):
        self.now = 100.
    def __call__(self):
        return self.now


def settings(kind='navigation', goal_input=False):
    return RobotIOSettings('custom_ros_fixture', kind, 'robotio_fixture',
                           '/fixture/input', '/fixture/output', 80, .05, goal_input)


def context(observation):
    return {name: observation[name] for name in ('episode', 'robot_id', 'binding_epoch')}


def intent(observation, behavior='hold'):
    command = dict(behavior=behavior, reason='explicit_synthetic_intent')
    if behavior == 'navigate_to_pose':
        command['goal'] = dict(frame='map', position_m=[2., -1.], yaw_rad=.4)
    return decision_intent_for(build_decision_observation(observation), command)


class Transport:
    """Owned by the test; echoes original fields without claiming live DDS."""
    def __init__(self, core, clock, *, alter=None, delay=0., graph_delay=0.):
        self.core = core
        self.clock = clock
        self.alter = alter
        self.delay = delay
        self.graph_delay = graph_delay
        self.published = []
        self.ready_budgets = []
        self.response = None
    def wait_ready(self, timeout):
        self.ready_budgets.append(timeout)
        self.clock.now += self.graph_delay
    def publish(self, payload):
        packet = json.loads(payload)
        self.published.append(packet)
        if packet['type'] == 'capabilities_request':
            self.response = dict(schema=ENVELOPE_SCHEMA, type='capabilities',
                adapter_id=packet['adapter_id'], context=copy.deepcopy(packet['context']),
                capabilities=copy.deepcopy(packet['capabilities']))
        elif self.core.settings.kind == 'decision':
            result = decision_intent_for(packet['observation'], dict(behavior='hold', reason='synthetic'))
            self.response = dict(schema=ENVELOPE_SCHEMA, type='intent', adapter_id=packet['adapter_id'], intent=result)
        else:
            result = action_for(packet['observation'], 'navigation', 'velocity_body',
                dict(frame='base_link', vx_mps=.2, vy_mps=0., wz_rps=0.))
            self.response = dict(schema=ENVELOPE_SCHEMA, type='action', adapter_id=packet['adapter_id'], action=result)
        if self.alter is not None:
            self.alter(self.response)
    def spin_once(self, timeout):
        self.clock.now += self.delay
        response, self.response = self.response, None
        if response is not None:
            self.core.receive_action(json.dumps(response))


def negotiated(kind='navigation', goal_input=False):
    clock = Clock()
    core = RobotIOEnvelopeBridge(settings(kind, goal_input), clock=clock)
    observation = nav_observation()
    if kind == 'decision':
        observation = build_decision_observation(observation)
    core.reset(context(observation), {})
    transport = Transport(core, clock)
    core.negotiate(transport)
    return core, clock, transport, observation


@pytest.mark.parametrize('kind', ['navigation', 'decision'])
def test_capabilities_and_outputs_echo_original_identity_with_separate_local_clock(kind):
    core, clock, transport, observation = negotiated(kind)
    assert core._negotiated and transport.ready_budgets == [1.]
    assert transport.published[0]['context'] == context(observation)
    assert transport.published[0]['capabilities'] == core.capabilities
    output = core.exchange(observation, transport)
    assert all(type(output[name]) is type(observation[name]) and output[name] == observation[name]
               for name in IDENTITY)
    assert transport.published[-1]['observation']['wall_deadline'] == observation['wall_deadline']
    assert core._pending is None and core._response is None


@pytest.mark.parametrize('mutate', [
    lambda value: value['capabilities'].update(fire_authority='algorithm_fire'),
    lambda value: value['capabilities'].update(source_association='latest_twist'),
    lambda value: value['context'].update(robot_id='red_infantry'),
    lambda value: value['context'].update(episode=True),
    lambda value: value.update(adapter_id='custom_wrong_route'),
    lambda value: value.update(schema='unknown')])
def test_wrong_capability_peer_context_or_route_never_negotiates(mutate):
    clock = Clock()
    core = RobotIOEnvelopeBridge(settings(), clock=clock)
    observation = nav_observation()
    core.reset(context(observation), {})
    with pytest.raises(ContractError):
        core.negotiate(Transport(core, clock, alter=mutate))
    assert not core._negotiated
    with pytest.raises(BridgeError, match='not_ready'):
        core.begin(observation)


@pytest.mark.parametrize('behavior', ['navigate_to_pose', 'hold', 'cancel'])
def test_goal_aware_ros_envelope_delivers_explicit_intent_without_retag(behavior):
    core, clock, transport, observation = negotiated(goal_input=True)
    wanted = intent(observation, behavior)
    output = core.exchange(observation, transport, wanted)
    packet = transport.published[-1]
    assert packet['intent'] == wanted
    assert packet['observation'] == observation
    assert {name: output[name] for name in IDENTITY} == {name: wanted[name] for name in IDENTITY}


def test_missing_goal_and_wrong_intent_generation_are_not_implicit_default_goal():
    core, clock, transport, observation = negotiated(goal_input=True)
    with pytest.raises(BridgeError, match='intent_required'):
        core.begin(observation)
    wanted = intent(observation)
    wanted['binding_epoch'] += 1
    with pytest.raises(ContractError):
        core.begin(observation, wanted)
    assert len(transport.published) == 1


@pytest.mark.parametrize('mutate', [
    lambda value: value['action'].update(observed_seq=0),
    lambda value: value['action'].update(binding_epoch=4),
    lambda value: value['action'].update(robot_id='red_infantry'),
    lambda value: value['action'].update(wall_deadline=value['action']['wall_deadline'] + 1),
    lambda value: value['action'].update(sim_time=0.),
    lambda value: value.update(action=dict(linear=dict(x=.2, y=0., z=0.), angular=dict(z=0.)))])
def test_old_context_retimed_action_and_bare_twist_rejected(mutate):
    core, clock, transport, observation = negotiated()
    transport.alter = mutate
    with pytest.raises(ContractError):
        core.exchange(observation, transport)
    assert core._response is None


def test_replayed_observation_and_closed_bridge_do_not_publish_new_request():
    core, clock, transport, observation = negotiated()
    core.exchange(observation, transport)
    before = len(transport.published)
    with pytest.raises(BridgeError, match='sequence'):
        core.exchange(observation, transport)
    assert len(transport.published) == before
    core.close()
    observation['observed_seq'] += 1
    with pytest.raises(BridgeError):
        core.begin(observation)


def test_response_and_graph_delay_respect_original_finite_local_budgets():
    core, clock, transport, observation = negotiated()
    transport.delay = .050001
    with pytest.raises(BridgeError, match='expired'):
        core.exchange(observation, transport)
    assert core._pending is None and core._response is None
    clock = Clock()
    core = RobotIOEnvelopeBridge(settings(), clock=clock)
    core.reset(context(observation), {})
    transport = Transport(core, clock, graph_delay=1.00001)
    with pytest.raises(BridgeError, match='graph_budget'):
        core.negotiate(transport)
    assert not transport.published and not core._negotiated


def test_jsonl_route_acknowledges_negotiated_caps_and_typed_decision_only():
    clock = Clock()
    core = RobotIOEnvelopeBridge(settings('decision'), clock=clock)
    value = build_decision_observation(nav_observation())
    transport = Transport(core, clock)
    packets = [dict(schema=JSONL_SCHEMA, op='reset', context=context(value), config={}),
               dict(schema=JSONL_SCHEMA, op='act', observation=value)]
    source = io.BytesIO(('\n'.join(json.dumps(packet) for packet in packets) + '\n').encode())
    output = io.BytesIO()
    serve(core, transport, source, output)
    rows = [json.loads(row) for row in output.getvalue().splitlines()]
    assert rows[0]['capabilities'] == core.capabilities
    assert 'intent' in rows[1] and 'action' not in rows[1]
    assert rows[1]['intent']['command']['behavior'] == 'hold'
