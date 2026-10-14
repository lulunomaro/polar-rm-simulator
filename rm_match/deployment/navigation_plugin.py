"""Trusted local, pose-free navigation plugins; interface declaration only.

Commands and supported robots come from a frozen local manifest, never HTTP.
ROS transport labels require a reviewed JSONL envelope wrapper; this module
does not qualify DDS, localization, planning or a particular team's algorithm.
"""
from __future__ import annotations
import copy
import os
from pathlib import Path
import re
import sys
from .json_adapter import JsonLineAdapter, SCHEMA as JSONL_SCHEMA
from .profile import read_json_snapshot
from ..platform_v2.adapters import descriptor, require_sensors
from ..platform_v2.contracts import ContractError, IDENTITY, exact, identity, validate_action
from ..platform_v2.navigation_contracts import (
    NAV_SCHEMA, NAV_PROFILE, NAV_STATUS_SCHEMA, validate_navigation_status)

MANIFEST_SCHEMA = 'polar.sim.navigation-plugins.v1'
CAPABILITY_SCHEMA = 'polar.sim.navigation-plugin.capabilities.v1'
CAPABILITIES = dict(schema=CAPABILITY_SCHEMA, observation_schema=NAV_SCHEMA,
    action_schema='polar.sim.action.v2', status_schema=NAV_STATUS_SCHEMA,
    sensor_profile=NAV_PROFILE, source_association='exact_capture_context_v1',
    output_modes=['velocity_body'], fire_authority='manual_only',
    ui_config_contract='empty_v1', goal_input_modes=[])


def validate_capabilities(value):
    exact(value, CAPABILITIES, 'navigation_plugin_capabilities')
    for key, wanted in CAPABILITIES.items():
        if key == 'goal_input_modes':
            if type(value[key]) is not list or value[key] not in ([], ['decision_intent_v1']):
                raise ContractError('unsupported_navigation_plugin_goal_input')
        elif type(value[key]) is not type(wanted) or value[key] != wanted:
            raise ContractError('unsupported_navigation_plugin_capability_' + key)
    return copy.deepcopy(value)


def navigation_status_for(observation, status='no_associated_command'):
    return validate_navigation_status(dict(schema=NAV_STATUS_SCHEMA,
        **{k: observation[k] for k in IDENTITY}, kind='navigation', status=status), observation)


def validate_intent(value, observation):
    # Import lazily: independent velocity plugins need no decision implementation.
    from ..platform_v2.decision_contracts import build_decision_observation, validate_decision_intent
    return validate_decision_intent(value, build_decision_observation(observation))


def validate_result(value, observation):
    if type(value) is dict and value.get('schema') == NAV_STATUS_SCHEMA:
        return 'status', validate_navigation_status(value, observation)
    checked = validate_action(value, observation, dict(kind='navigation', output_modes=['velocity_body']))
    if any(type(checked[k]) is not type(observation[k]) or checked[k] != observation[k] for k in IDENTITY):
        raise ContractError('navigation_action_identity_type_mismatch')
    return 'action', checked


def validate_result_for_intent(value, observation, intent=None):
    """A stop intent cannot authorize renewed motion from a retained goal.

    The navigation callback still receives hold/cancel and owns real goal
    cancellation. Do not turn a violating response into synthetic zero motion.
    Validate original result/source first, then the original intent/source.
    """
    kind, checked = validate_result(value, observation)
    if intent is not None:
        intent = validate_intent(intent, observation)
        if intent['command']['behavior'] in ('hold', 'cancel') and kind == 'action':
            if any(checked['command'][axis] != 0 for axis in ('vx_mps', 'vy_mps', 'wz_rps')):
                raise ContractError('navigation_motion_violates_stop_intent')
    return kind, checked


def load_navigation_plugins(path):
    path = Path(path).absolute()
    value, sha = read_json_snapshot(path)
    exact(value, ('schema', 'adapters'), 'navigation_plugin_manifest')
    if type(value['schema']) is not str or value['schema'] != MANIFEST_SCHEMA:
        raise ContractError('unsupported_navigation_plugin_manifest')
    if type(value['adapters']) is not list or not 1 <= len(value['adapters']) <= 16:
        raise ContractError('invalid_navigation_plugin_count')
    rows = []; seen = set()
    for row in value['adapters']:
        fields=('adapter_id','label','command','cwd','supported_robots','transport','capabilities')
        if type(row) is dict and row.get('transport')=='wsl_jsonl_v1':fields+=('wsl',)
        exact(row, fields, 'navigation_plugin_registration')
        aid = row['adapter_id']
        if type(aid) is not str or not re.fullmatch(r'custom_[a-z0-9_]{1,100}', aid) or aid in seen:
            raise ContractError('invalid_or_duplicate_navigation_plugin_id')
        seen.add(aid)
        if type(row['label']) is not str or not 1 <= len(row['label']) <= 200:
            raise ContractError('invalid_navigation_plugin_label')
        if type(row['transport']) is not str or row['transport'] not in ('jsonl_v1', 'ros2_navigation_envelope_v1','wsl_jsonl_v1'):
            raise ContractError('unsupported_navigation_plugin_transport')
        robots = row['supported_robots']
        if type(robots) is not list or not 1 <= len(robots) <= 64 or any(type(r) is not str or not re.fullmatch(r'[a-z][a-z0-9_]{0,127}', r) for r in robots) or len(set(robots)) != len(robots):
            raise ContractError('invalid_navigation_plugin_robots')
        validate_capabilities(row['capabilities'])
        command = row['command']
        if type(command) is not list or not 1 <= len(command) <= 32 or any(type(s) is not str or not s or len(s) > 4096 or '\0' in s for s in command):
            raise ContractError('invalid_navigation_plugin_argv')
        if row['transport']=='wsl_jsonl_v1':
            from .wsl_jsonl import validate_linux_settings
            exact(row['wsl'],('distribution','python','process_env'),'navigation_plugin_wsl')
            linux=validate_linux_settings(dict(row['wsl'],command=command,cwd=row['cwd']))
            rows.append(dict(copy.deepcopy(row),linux=linux,kind='navigation',required_sensors=['pointcloud','imu']))
            continue
        command = [sys.executable if s == '{python}' else s for s in command]
        binary = Path(command[0])
        if not binary.is_absolute() or not binary.is_file() or not os.access(binary, os.X_OK):
            raise ContractError('navigation_plugin_requires_local_absolute_executable')
        if type(row['cwd']) is not str or '\0' in row['cwd']:
            raise ContractError('invalid_navigation_plugin_cwd')
        cwd = (path.parent / row['cwd']).resolve()
        if not cwd.is_dir(): raise ContractError('navigation_plugin_cwd_missing')
        rows.append(dict(copy.deepcopy(row), command=command, cwd=str(cwd), kind='navigation', required_sensors=['pointcloud', 'imu']))
    return rows, sha


class NavigationPluginAdapter(JsonLineAdapter):
    def reset(self, context, *, deadline=None):
        exact(self.config, (), 'navigation_plugin_binding_config')
        exact(context, ('episode', 'robot_id', 'binding_epoch'), 'navigation_plugin_context')
        identity(dict(context, observed_seq=0, sim_time=0., wall_deadline=0.))
        if context['robot_id'] not in self.registration['supported_robots']:
            raise ContractError('navigation_plugin_robot_unsupported')
        kwargs = {} if deadline is None else {'deadline': deadline}
        return super().reset(context, **kwargs)

    def close(self, *, deadline=None):
        kwargs = {} if deadline is None else {'deadline': deadline}
        return super().close(**kwargs)

    def _validate_response(self, result, packet):
        if packet['op'] == 'reset':
            exact(result, ('schema', 'op', 'ok', 'capabilities'), 'navigation_plugin_reset_response')
            if type(result['schema']) is not str or result['schema'] != JSONL_SCHEMA or type(result['op']) is not str or result['op'] != 'reset' or result['ok'] is not True:
                raise ContractError('navigation_plugin_reset_identity')
            if validate_capabilities(result['capabilities']) != self.registration['capabilities']:
                raise ContractError('navigation_plugin_capabilities_mismatch')
            return
        if packet['op'] != 'act': return super()._validate_response(result, packet)
        if type(result) is not dict: raise ContractError('invalid_navigation_plugin_response')
        field = 'status' if 'status' in result else 'action'
        exact(result, ('schema', 'op', 'ok', field), 'navigation_plugin_response')
        if type(result['schema']) is not str or result['schema'] != JSONL_SCHEMA or type(result['op']) is not str or result['op'] != 'act' or result['ok'] is not True:
            raise ContractError('navigation_plugin_response_identity')
        expected, _ = validate_result_for_intent(result[field], packet['observation'], packet.get('intent'))
        if field != expected: raise ContractError('navigation_plugin_response_kind')

    def act(self, observation):
        return self._act(observation, None)

    def act_with_intent(self, observation, intent):
        if self.registration['capabilities']['goal_input_modes'] != ['decision_intent_v1']:
            raise ContractError('navigation_plugin_goal_input_unsupported')
        if intent is None: raise ContractError('navigation_plugin_explicit_intent_required')
        return self._act(observation, intent)

    def _act(self, observation, intent):
        o = self.checked(observation)
        if o['schema'] != NAV_SCHEMA: raise ContractError('navigation_plugin_observation_profile')
        require_sensors(o, ['pointcloud', 'imu'])
        packet = dict(op='act', observation=o)
        if self.registration['capabilities']['goal_input_modes']:
            if intent is None: return navigation_status_for(o)
            packet['intent'] = validate_intent(intent, o)
        response = self._exchange(packet, timeout=min(.25, o['wall_deadline'] - self.clock()))
        field = 'status' if 'status' in response else 'action'
        return validate_result_for_intent(response[field], o, packet.get('intent'))[1]


def register_navigation_plugins(registry, path, *, clock=None,wsl_prepared=None):
    path = Path(path).absolute(); rows, sha = load_navigation_plugins(path)
    for row in rows:
        d = descriptor(row['adapter_id'], 'navigation', row['label'], ['pointcloud', 'imu'])
        d.update(ui_config_contract='empty_v1', observation_profile=NAV_PROFILE,
            navigation_plugin_contract=NAV_PROFILE, navigation_plugin_capabilities=copy.deepcopy(row['capabilities']),
            goal_input_modes=list(row['capabilities']['goal_input_modes']), supported_robots=list(row['supported_robots']),
            local_registration=True, plugin_transport=row['transport'],
            process_isolation='trusted_local_process_not_a_security_sandbox',
            qualification='interface_declared_not_algorithm_or_live_acceptance')
        if row['transport']=='wsl_jsonl_v1':
            ready=wsl_prepared is not None and wsl_prepared.sha==sha and row['adapter_id'] in wsl_prepared.instances
            d.update(available=ready,reason='available' if ready else 'explicit_local_wsl_prepare_required',
                lifecycle='one_prepared_instance_one_binding_restart_for_rebind')
        def factory(config, row=row, d=d):
            exact(config, (), 'navigation_plugin_binding_config')
            kwargs = {} if clock is None else {'clock': clock}
            if row['transport']=='wsl_jsonl_v1':
                if wsl_prepared is None:raise ContractError('wsl_plugin_requires_explicit_preparation')
                adapter=wsl_prepared.take(row['adapter_id'],sha)
            else:adapter = NavigationPluginAdapter(config, registration=row, manifest=path, manifest_sha=sha, **kwargs)
            adapter.descriptor = copy.deepcopy(d)
            return adapter
        registry.register(d, factory)
    return dict(schema=MANIFEST_SCHEMA, manifest_sha256=sha, registered_ids=[r['adapter_id'] for r in rows],
        qualification='interface_declared_not_algorithm_or_live_acceptance')
