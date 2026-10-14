"""Deterministic startup file races; no peer or algorithm factory is executed."""
import copy
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import Mock, patch

import pytest

from rm_match.deployment import aim_plugin, decision_plugin, navigation_plugin, robotio_plugin
from rm_match.deployment.decision_plugin import (
    CAPABILITIES as DECISION_CAPS, MANIFEST_SCHEMA as DECISION_SCHEMA)
from rm_match.platform_v2.adapters import Registry, descriptor
from rm_match.platform_v2.contracts import ContractError


@pytest.fixture(autouse=True)
def no_new_component_factory_may_construct_an_adapter():
    with patch.object(navigation_plugin, 'NavigationPluginAdapter') as navigation, \
         patch.object(aim_plugin, 'AimPluginAdapter') as aim, \
         patch.object(decision_plugin, 'DecisionPluginAdapter') as decision:
        for constructor in (navigation, aim, decision):
            constructor.side_effect = AssertionError('Registration cannot execute a component factory')
        yield
        for constructor in (navigation, aim, decision):
            constructor.assert_not_called()


def write_json(path, value):
    path.write_text(json.dumps(value) + '\n', encoding='utf-8')


def graph_files(tmp_path):
    definitions = {
        'navigation': (navigation_plugin.MANIFEST_SCHEMA,
                       dict(copy.deepcopy(navigation_plugin.CAPABILITIES),
                            goal_input_modes=['decision_intent_v1'])),
        'decision': (DECISION_SCHEMA, copy.deepcopy(DECISION_CAPS)),
        'aim': (aim_plugin.MANIFEST_SCHEMA, copy.deepcopy(aim_plugin.CAPABILITIES)),
    }
    files = {}
    for category, (schema, capabilities) in definitions.items():
        files[category] = tmp_path / (category + '.json')
        row = dict(adapter_id='custom_race_' + category, label='Validation only ' + category,
                   command=[sys.executable, '-c', 'raise RuntimeError("must not execute")'],
                   cwd=str(tmp_path), supported_robots=['red_infantry'],
                   transport='jsonl_v1', capabilities=capabilities)
        write_json(files[category], dict(schema=schema, adapters=[row]))
    files['graph'] = tmp_path / 'robotio.json'
    write_json(files['graph'], dict(schema=robotio_plugin.SCHEMA,
        manifests={category: files[category].name for category in definitions},
        pipelines=[dict(adapter_id='custom_race_pipeline', label='Validation only pipeline',
                        decision_plugin_id='custom_race_decision',
                        navigation_plugin_id='custom_race_navigation',
                        supported_robots=['red_infantry'])]))
    return files


def existing_target():
    registry = Registry()
    factory = Mock(side_effect=AssertionError('No factory may run during registration'))
    registry.register(descriptor('existing_navigation', 'navigation', 'Existing', ['ranges']), factory)
    registry.set_plugin_catalog([dict(plugin_id='existing_navigation', category='navigation',
                                     supported_robots=['red_infantry'])])
    saved = dict(specs=registry._specs, capabilities=registry._capabilities,
                 catalog=registry._plugin_catalog, descriptors=registry.descriptors(),
                 public_catalog=registry.plugin_catalog(),
                 spec=registry._specs['existing_navigation'],
                 capability=registry._capabilities['existing_navigation'])
    return registry, factory, saved


def assert_target_untouched(registry, factory, saved):
    assert registry._specs is saved['specs']
    assert registry._capabilities is saved['capabilities']
    assert registry._plugin_catalog is saved['catalog']
    assert registry.descriptors() == saved['descriptors']
    assert registry.plugin_catalog() == saved['public_catalog']
    assert registry._specs['existing_navigation'] is saved['spec']
    assert registry._capabilities['existing_navigation'] is saved['capability']
    factory.assert_not_called()


@pytest.mark.parametrize('category', ['navigation', 'aim'])
@pytest.mark.parametrize('interleaving', ['actual_file', 'memory_snapshot'])
def test_component_second_read_cannot_replace_first_reviewed_scope(tmp_path, category, interleaving):
    files = graph_files(tmp_path)
    registry, factory, saved = existing_target()
    module = navigation_plugin if category == 'navigation' else aim_plugin
    original = module.read_json_snapshot
    reads = 0

    def snapshot(path):
        nonlocal reads
        reads += 1
        if reads == 2 and interleaving == 'actual_file':
            value = json.loads(files[category].read_text(encoding='utf-8'))
            value['adapters'][0]['supported_robots'].append('blue_sentry')
            write_json(files[category], value)
        value, sha = original(path)
        if reads == 2 and interleaving == 'memory_snapshot':
            value = copy.deepcopy(value)
            value['adapters'][0]['supported_robots'].append('blue_sentry')
            sha = hashlib.sha256(json.dumps(value).encode()).hexdigest()
        return value, sha

    with patch.object(module, 'read_json_snapshot', side_effect=snapshot):
        with pytest.raises(ContractError, match='^robotio_component_changed_during_registration$'):
            robotio_plugin.register_robotio_plugins(registry, files['graph'])
    assert reads == 2
    assert_target_untouched(registry, factory, saved)


def test_later_component_validation_failure_keeps_target_registry_unmodified(tmp_path):
    files = graph_files(tmp_path)
    registry, factory, saved = existing_target()
    original = aim_plugin.read_json_snapshot
    reads = 0

    def snapshot(path):
        nonlocal reads
        reads += 1
        value, sha = original(path)
        if reads == 2:
            value['adapters'][0]['capabilities']['output_modes'] = ['world_truth']
        return value, sha

    with patch.object(aim_plugin, 'read_json_snapshot', side_effect=snapshot):
        with pytest.raises(ContractError, match='unsupported_aim_plugin_capability_output_modes'):
            robotio_plugin.register_robotio_plugins(registry, files['graph'])
    assert reads == 2
    assert_target_untouched(registry, factory, saved)


def test_same_bytes_reread_commits_all_metadata_preserving_original_specs_and_public_isolation(tmp_path):
    files = graph_files(tmp_path)
    registry, factory, saved = existing_target()
    original = navigation_plugin.read_json_snapshot
    reads = 0

    def snapshot(path):
        nonlocal reads
        reads += 1
        if reads == 2:
            content = files['navigation'].read_bytes()
            files['navigation'].write_bytes(content)
        return original(path)

    with patch.object(navigation_plugin, 'read_json_snapshot', side_effect=snapshot):
        result = robotio_plugin.register_robotio_plugins(registry, files['graph'])
    assert reads == 2
    assert set(result['registered_adapter_ids']) == {
        'custom_race_navigation', 'custom_race_aim', 'custom_race_pipeline'}
    assert registry._specs['existing_navigation'] is saved['spec']
    assert registry._capabilities['existing_navigation'] is saved['capability']
    assert registry.get('existing_navigation').factory is factory
    assert registry.capability('existing_navigation', 'requires_camera') is False
    assert registry.capability('custom_race_aim', 'requires_camera') is True
    assert {row['plugin_id'] for row in registry.plugin_catalog()} == {
        'existing_navigation', 'custom_race_navigation', 'custom_race_decision',
        'custom_race_aim', 'custom_race_pipeline'}
    public = registry.plugin_catalog()
    public[0]['supported_robots'].clear()
    nav = next(row for row in public if row['plugin_id'] == 'custom_race_navigation')
    nav['supported_robots'].append('blue_sentry')
    nav['capabilities']['goal_input_modes'].clear()
    checked = registry.plugin_catalog()
    assert checked[0] == saved['public_catalog'][0]
    nav = next(row for row in checked if row['plugin_id'] == 'custom_race_navigation')
    assert nav['supported_robots'] == ['red_infantry']
    assert nav['capabilities']['goal_input_modes'] == ['decision_intent_v1']
    factory.assert_not_called()


@pytest.mark.parametrize('changed_file', ['graph', 'navigation', 'decision', 'aim'])
def test_late_file_change_is_rejected_before_any_metadata_is_published(tmp_path, changed_file):
    files = graph_files(tmp_path)
    registry, factory, saved = existing_target()
    original = robotio_plugin.digest
    changed = False

    def digest(path):
        nonlocal changed
        if not changed:
            files[changed_file].write_bytes(files[changed_file].read_bytes() + b' ')
            changed = True
        return original(path)

    with patch.object(robotio_plugin, 'digest', side_effect=digest):
        with pytest.raises(ContractError, match='^robotio_graph_changed_during_registration$'):
            robotio_plugin.register_robotio_plugins(registry, files['graph'])
    assert changed
    assert_target_untouched(registry, factory, saved)


def test_pipeline_registration_failure_discards_all_staged_components(tmp_path):
    files = graph_files(tmp_path)
    registry, factory, saved = existing_target()
    original = Registry.register

    def register(target, metadata, make):
        if metadata['adapter_id'] == 'custom_race_pipeline':
            raise ContractError('pipeline_test_registration_failure')
        return original(target, metadata, make)

    with patch.object(Registry, 'register', new=register):
        with pytest.raises(ContractError, match='^pipeline_test_registration_failure$'):
            robotio_plugin.register_robotio_plugins(registry, files['graph'])
    assert_target_untouched(registry, factory, saved)


@pytest.mark.parametrize('collision', ['navigation', 'decision', 'aim', 'pipeline'])
def test_existing_registry_component_collision_is_checked_before_staging(tmp_path, collision):
    files = graph_files(tmp_path)
    registry, factory, _ = existing_target()
    registry.register(descriptor('custom_race_' + collision, 'navigation', 'Collision', []), factory)
    saved = dict(specs=registry._specs, capabilities=registry._capabilities,
                 catalog=registry._plugin_catalog, descriptors=registry.descriptors(),
                 public_catalog=registry.plugin_catalog(), spec=registry._specs['existing_navigation'],
                 capability=registry._capabilities['existing_navigation'])
    with patch.object(navigation_plugin, 'register_navigation_plugins') as navigation:
        with pytest.raises(ContractError, match='^robotio_registry_collision_or_capacity$'):
            robotio_plugin.register_robotio_plugins(registry, files['graph'])
        navigation.assert_not_called()
    assert_target_untouched(registry, factory, saved)


@pytest.mark.parametrize('limit', ['specs', 'catalog', 'catalog_collision'])
def test_capacity_and_catalog_only_collision_are_checked_before_staging(tmp_path, limit):
    files = graph_files(tmp_path)
    registry, factory, _ = existing_target()
    if limit == 'specs':
        for index in range(29):
            registry.register(descriptor('existing_' + str(index), 'navigation', 'Existing', []), factory)
    elif limit == 'catalog':
        registry.set_plugin_catalog(registry.plugin_catalog() + [
            dict(plugin_id='prior_intent_' + str(index), category='decision',
                 supported_robots=['red_infantry']) for index in range(60)])
    else:
        registry.set_plugin_catalog(registry.plugin_catalog() + [
            dict(plugin_id='custom_race_decision', category='decision',
                 supported_robots=['red_infantry'])])
    saved = dict(specs=registry._specs, capabilities=registry._capabilities,
                 catalog=registry._plugin_catalog, descriptors=registry.descriptors(),
                 public_catalog=registry.plugin_catalog(), spec=registry._specs['existing_navigation'],
                 capability=registry._capabilities['existing_navigation'])
    with patch.object(navigation_plugin, 'register_navigation_plugins') as navigation:
        with pytest.raises(ContractError, match='^robotio_registry_collision_or_capacity$'):
            robotio_plugin.register_robotio_plugins(registry, files['graph'])
        navigation.assert_not_called()
    assert_target_untouched(registry, factory, saved)
