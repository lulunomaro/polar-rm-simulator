"""Generic pipeline protocol and harmless processes; no real navigation claim."""
import copy
import hashlib
import json
from pathlib import Path
import queue
import sys
import threading
import time
from unittest.mock import patch

import pytest

from rm_match.deployment.decision_plugin import CAPABILITIES as DECISION_CAPS
from rm_match.deployment.decision_plugin import MANIFEST_SCHEMA as DECISION_MANIFEST
from rm_match.deployment.navigation_plugin import CAPABILITIES as NAV_CAPS
from rm_match.deployment.navigation_plugin import MANIFEST_SCHEMA as NAV_MANIFEST, navigation_status_for
from rm_match.deployment.profile import digest
from rm_match.deployment.robotio_plugin import (
    SCHEMA, DecisionNavigationAdapter, load_robotio_plugins, register_robotio_plugins)
from rm_match.platform_v2.adapters import Registry
from rm_match.platform_v2.contracts import ContractError, IDENTITY
from rm_match.platform_v2.decision_contracts import decision_intent_for
from test_decision_plugin import nav_observation

FIXTURES = Path(__file__).parent / 'fixtures'


def graph(tmp_path, decision_fixture='decision_supply_v1.py'):
    nav_caps = dict(copy.deepcopy(NAV_CAPS), goal_input_modes=['decision_intent_v1'])
    nav_row = dict(adapter_id='custom_goal_nav_fixture', label='Synthetic goal navigation fixture',
        command=[sys.executable, '-u', str(FIXTURES / 'navigation_goal_fixture.py')], cwd=str(FIXTURES),
        supported_robots=['blue_sentry', 'red_infantry'], transport='jsonl_v1', capabilities=nav_caps)
    decision_row = dict(adapter_id='custom_decision_fixture', label=decision_fixture,
        command=[sys.executable, '-u', str(FIXTURES / decision_fixture)], cwd=str(FIXTURES),
        supported_robots=['blue_sentry', 'red_infantry'], transport='jsonl_v1',
        capabilities=copy.deepcopy(DECISION_CAPS))
    nav = tmp_path / 'navigation.json'
    dec = tmp_path / 'decision.json'
    nav.write_text(json.dumps(dict(schema=NAV_MANIFEST, adapters=[nav_row])), encoding='utf8')
    dec.write_text(json.dumps(dict(schema=DECISION_MANIFEST, adapters=[decision_row])), encoding='utf8')
    value = dict(schema=SCHEMA, manifests=dict(navigation=nav.name, decision=dec.name, aim=None),
        pipelines=[dict(adapter_id='custom_pipeline_fixture', label='Synthetic composed pipeline',
        decision_plugin_id=decision_row['adapter_id'], navigation_plugin_id=nav_row['adapter_id'],
        supported_robots=['blue_sentry', 'red_infantry'])])
    path = tmp_path / 'robotio.json'
    path.write_text(json.dumps(value), encoding='utf8')
    return path, value, nav, dec


def pipeline(tmp_path, decision_fixture='decision_supply_v1.py'):
    path, value, nav, dec = graph(tmp_path, decision_fixture)
    registry = Registry()
    register_robotio_plugins(registry, path)
    return registry.create('custom_pipeline_fixture', {}), registry, path


def context(value):
    return {name: value[name] for name in ('episode', 'robot_id', 'binding_epoch')}


def assert_clean(result):
    assert result.shutdown_status['clean'] and result.shutdown_status['resource_budget_s'] == 1.5
    for proof in result.shutdown_status['peers'].values():
        assert proof['clean'] and proof['io_thread_stopped']
        assert proof['ownership']['reaped'] and proof['ownership']['group_empty']


@pytest.mark.parametrize('decision_fixture,heat,expected_vx', [
    ('decision_supply_v1.py', 0., .2),
    ('decision_heat_v2.py', 0., 0.),
    ('decision_heat_v2.py', 140., 0.)])
def test_actual_independent_decision_policies_compose_with_goal_aware_jsonl_nav(
        tmp_path, decision_fixture, heat, expected_vx):
    result, registry, path = pipeline(tmp_path, decision_fixture)
    original = nav_observation()
    original['own']['heat'] = heat
    seen = []
    try:
        result.reset(context(original))
        decision_call = result.decision._exchange
        navigation_call = result.navigation._exchange
        def trace(peer, function):
            def call(packet, **kwargs):
                seen.append((peer, copy.deepcopy(packet)))
                return function(packet, **kwargs)
            return call
        result.decision._exchange = trace('decision', decision_call)
        result.navigation._exchange = trace('navigation', navigation_call)
        original['wall_deadline'] = time.perf_counter() + .15
        output = result.act(original)
        assert output['command']['vx_mps'] == expected_vx
        assert {name: output[name] for name in IDENTITY} == {name: original[name] for name in IDENTITY}
        assert len(seen) == 2
        decision_packet, nav_packet = seen[0][1], seen[1][1]
        for item in (decision_packet['observation'], nav_packet['observation'], nav_packet['intent']):
            assert all(type(item[name]) is type(original[name]) and item[name] == original[name]
                       for name in IDENTITY)
        assert not decision_packet['observation']['navigation']['available']
        assert not decision_packet['observation']['perception']['available']
        assert nav_packet['intent']['command']['behavior'] == (
            'navigate_to_pose' if expected_vx else 'cancel' if heat >= 100 else 'hold')
    finally:
        result.close()
    assert_clean(result)


def test_actual_pause_holds_then_cancelled_pipeline_has_no_future_peer_calls(tmp_path):
    result, registry, path = pipeline(tmp_path)
    value = nav_observation()
    try:
        result.reset(context(value))
        value['referee']['phase'] = 'paused'
        value['wall_deadline'] = time.perf_counter() + .15
        assert result.act(value)['command']['vx_mps'] == 0.
        result.cancel()
        value['observed_seq'] += 1
        with patch.object(result.decision, 'act') as decision, patch.object(result.navigation, 'act_with_intent') as navigation:
            with pytest.raises(ContractError, match='cancelled'):
                result.act(value)
            decision.assert_not_called()
            navigation.assert_not_called()
    finally:
        result.close()
    assert_clean(result)


def test_actual_cross_robot_rejected_before_either_peer_receives_input(tmp_path):
    result, registry, path = pipeline(tmp_path)
    value = nav_observation()
    try:
        result.reset(context(value))
        value['robot_id'] = 'red_infantry'
        with patch.object(result.decision, 'act') as decision, patch.object(result.navigation, 'act_with_intent') as navigation:
            with pytest.raises(ContractError, match='context'):
                result.act(value)
            decision.assert_not_called()
            navigation.assert_not_called()
    finally:
        result.close()
    assert_clean(result)


def test_actual_wrong_navigation_peer_caps_release_both_composed_processes(tmp_path):
    path, value, nav, dec = graph(tmp_path)
    wrong = tmp_path / 'wrong_navigation.py'
    wrong.write_text('import json,sys\n'
        'for line in sys.stdin:\n'
        ' request=json.loads(line)\n'
        ' print(json.dumps(dict(schema="polar.sim.adapter.jsonl.v1",op=request["op"],'
        'ok=True,capabilities=' + repr(NAV_CAPS) + ')),flush=True)\n', encoding='utf8')
    nav_value = json.loads(nav.read_text(encoding='utf8'))
    nav_value['adapters'][0]['command'] = [sys.executable, '-u', str(wrong)]
    nav.write_text(json.dumps(nav_value), encoding='utf8')
    registry = Registry()
    register_robotio_plugins(registry, path)
    result = registry.create('custom_pipeline_fixture', {})
    with pytest.raises(ContractError, match='capabilities_mismatch'):
        result.reset(context(nav_observation()))
    assert result._failed and result._cancelled
    assert result.decision.process is None and result.navigation.process is None
    assert_clean(result)


def test_actual_slow_reset_peers_share_total_two_second_budget(tmp_path):
    path, value, nav, dec = graph(tmp_path)
    root = FIXTURES.parents[1]
    slow_decision = tmp_path / 'slow_decision.py'
    slow_decision.write_text('import sys,time\n'
        'sys.path.insert(0,' + repr(str(root)) + ')\n'
        'from rm_match.integrations.decision_jsonl_peer import run_decision_plugin\n'
        'from rm_match.platform_v2.decision_contracts import decision_intent_for\n'
        'class Compute:\n'
        ' def reset(self,context): time.sleep(1.1)\n'
        ' def __call__(self,o): return decision_intent_for(o,dict(behavior="hold",reason="synthetic"))\n'
        'raise SystemExit(run_decision_plugin(Compute))\n', encoding='utf8')
    slow_nav = tmp_path / 'slow_nav.py'
    slow_caps = dict(copy.deepcopy(NAV_CAPS), goal_input_modes=['decision_intent_v1'])
    slow_nav.write_text('import json,sys,time\n'
        'for line in sys.stdin:\n'
        ' request=json.loads(line)\n'
        ' time.sleep(1.1)\n'
        ' print(json.dumps(dict(schema="polar.sim.adapter.jsonl.v1",op=request["op"],'
        'ok=True,capabilities=' + repr(slow_caps) + ')),flush=True)\n', encoding='utf8')
    for source, wrapper in ((nav, slow_nav), (dec, slow_decision)):
        content = json.loads(source.read_text(encoding='utf8'))
        content['adapters'][0]['command'] = [sys.executable, '-u', str(wrapper)]
        source.write_text(json.dumps(content), encoding='utf8')
    registry = Registry()
    register_robotio_plugins(registry, path)
    result = registry.create('custom_pipeline_fixture', {})
    started = time.perf_counter()
    with pytest.raises((queue.Empty, TimeoutError, ContractError)):
        result.reset(context(nav_observation()))
    elapsed = time.perf_counter() - started
    assert elapsed < 3.7  # 2 s shared reset + 1.5 s cleanup, with runner tolerance.
    assert result._failed and result._cancelled
    assert_clean(result)


def test_catalog_exposes_contract_and_components_without_command_or_cwd(tmp_path):
    result, registry, path = pipeline(tmp_path)
    try:
        catalog = registry.plugin_catalog()
        assert {row['category'] for row in catalog} == {'decision', 'navigation', 'pipeline'}
        public = json.dumps(catalog)
        assert 'command' not in public and str(FIXTURES) not in public and 'cwd' not in public
        catalog[0]['supported_robots'].clear()
        assert registry.plugin_catalog()[0]['supported_robots']
        with pytest.raises(ContractError):
            registry.create('custom_pipeline_fixture', {'command': ['bad']})
        assert {row['kind'] for row in registry.descriptors()} == {'navigation'}
    finally:
        result.close()


def test_actual_loopback_sdk_plugin_catalog_filters_to_authorized_robot(tmp_path):
    from rm_match.platform_v2.admission import AdmissionPolicy
    from rm_match.platform_v2.client import ClientError, PlatformClient
    from rm_match.platform_v2.runtime import PlatformRuntime
    from rm_match.platform_v2.server import PlatformHTTPServer, TransportConfig
    from rm_match.platform_v2.test_control import Clock as RuntimeClock
    from rm_match.platform_v2.test_runtime import FakeBackend
    from rm_match.platform_v2.test_support_admission import OPERATOR_CREDENTIAL
    path, value, nav, dec = graph(tmp_path)
    for source in (nav, dec):
        content = json.loads(source.read_text(encoding='utf8'))
        content['adapters'][0]['supported_robots'] = ['alpha', 'beta']
        source.write_text(json.dumps(content), encoding='utf8')
    value['pipelines'][0]['supported_robots'] = ['alpha', 'beta']
    path.write_text(json.dumps(value), encoding='utf8')
    registry = Registry()
    register_robotio_plugins(registry, path)
    runtime = PlatformRuntime(FakeBackend(), registry=registry, clock=RuntimeClock())
    policy = AdmissionPolicy([dict(credential_sha256=hashlib.sha256(OPERATOR_CREDENTIAL.encode()).hexdigest(),
        role='operator', allowed_robots=['alpha'], audit_authorized=False)])
    server = PlatformHTTPServer(TransportConfig(port=0, admission_policy=policy), runtime)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    thread.start()
    client = PlatformClient('http://127.0.0.1:' + str(server.server_address[1]),
                            admission_credential=OPERATOR_CREDENTIAL)
    try:
        with pytest.raises(ClientError):
            client.plugins()
        client.open('operator')
        result = client.plugins()
        assert result['catalog_schema'] == 'polar.sim.robotio-plugin-catalog.v1'
        assert {row['category'] for row in result['plugins']} == {'decision', 'navigation', 'pipeline'}
        assert all(row['supported_robots'] == ['alpha'] for row in result['plugins'])
        assert result['fire_authority'] == 'manual_only'
        assert result['control_channels'] == ['motion', 'gimbal', 'fire']
        public = json.dumps(result)
        assert 'command' not in public and 'cwd' not in public and str(FIXTURES) not in public
        with pytest.raises(ClientError):
            client.bind_pipeline('alpha', 'custom_pipeline_fixture')
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(1.)
        runtime.close()
    assert not thread.is_alive()


def test_graph_scope_cannot_exceed_component_or_goal_capability(tmp_path):
    path, value, nav, dec = graph(tmp_path)
    value['pipelines'][0]['supported_robots'].append('red_hero')
    path.write_text(json.dumps(value), encoding='utf8')
    with pytest.raises(ContractError, match='scope'):
        load_robotio_plugins(path)
    path, value, nav, dec = graph(tmp_path)
    source = json.loads(nav.read_text(encoding='utf8'))
    source['adapters'][0]['capabilities']['goal_input_modes'] = []
    nav.write_text(json.dumps(source), encoding='utf8')
    with pytest.raises(ContractError, match='goal_navigation'):
        load_robotio_plugins(path)


class Clock:
    def __init__(self):
        self.now = 100.
    def __call__(self):
        return self.now


class ResourcePeer:
    """Lifecycle timing fixture; reports no actual process qualification."""
    def __init__(self, clock, *, reset_seconds=0., act_seconds=0., decision=False):
        self.clock = clock
        self.reset_seconds = reset_seconds
        self.act_seconds = act_seconds
        self.decision = decision
        self._cancelled = threading.Event()
        self.responses = queue.Queue(1)
        self.reset_deadlines = []
        self.close_deadlines = []
        self.shutdown_status = None
    def reset(self, context, *, deadline):
        self.reset_deadlines.append(deadline)
        self.clock.now += self.reset_seconds
        if self.clock() >= deadline:
            raise TimeoutError('synthetic_total_reset_budget')
    def act(self, observation):
        self.clock.now += self.act_seconds
        return decision_intent_for(observation, dict(behavior='hold', reason='synthetic'))
    def act_with_intent(self, observation, intent):
        self.clock.now += self.act_seconds
        return navigation_status_for(observation)
    def close(self, *, deadline):
        self.close_deadlines.append(deadline)
        self.shutdown_status = dict(clean=True, scope='lifecycle_fixture_only')


def resource_pipeline(clock, decision, navigation, hashes=None):
    return DecisionNavigationAdapter({}, make_decision=lambda: decision,
        make_navigation=lambda: navigation, hashes=hashes or {}, clock=clock)


def test_reset_total_two_seconds_and_cleanup_share_one_original_budget():
    clock = Clock()
    decision = ResourcePeer(clock, reset_seconds=1.2)
    navigation = ResourcePeer(clock, reset_seconds=.81)
    result = resource_pipeline(clock, decision, navigation)
    with pytest.raises(TimeoutError, match='total_reset'):
        result.reset(context(nav_observation()))
    assert decision.reset_deadlines == navigation.reset_deadlines == [102.]
    assert decision.close_deadlines == navigation.close_deadlines
    assert result.shutdown_status['resource_budget_s'] == 1.5
    assert decision._cancelled.is_set() and navigation._cancelled.is_set()


def test_decision_exhausting_original_control_window_does_not_relabel_for_nav():
    clock = Clock()
    decision = ResourcePeer(clock, act_seconds=.151)
    navigation = ResourcePeer(clock)
    result = resource_pipeline(clock, decision, navigation)
    value = nav_observation()
    value['wall_deadline'] = 100.15
    result.reset(context(value))
    with patch.object(navigation, 'act_with_intent') as call:
        with pytest.raises(ContractError, match='intent_expired'):
            result.act(value)
        call.assert_not_called()
    assert result._failed and decision._cancelled.is_set() and navigation._cancelled.is_set()


def test_changed_graph_releases_already_claimed_resources_before_reset(tmp_path):
    source = tmp_path / 'graph.json'
    source.write_text('{}', encoding='utf8')
    clock = Clock()
    decision, navigation = ResourcePeer(clock), ResourcePeer(clock)
    result = resource_pipeline(clock, decision, navigation, {str(source): digest(source)})
    source.write_text('{"changed":true}', encoding='utf8')
    with pytest.raises(ContractError, match='graph_changed'):
        result.reset(context(nav_observation()))
    assert decision.reset_deadlines == navigation.reset_deadlines == []
    assert decision._cancelled.is_set() and navigation._cancelled.is_set()
    assert decision.close_deadlines and navigation.close_deadlines
    assert result.shutdown_status['clean']
