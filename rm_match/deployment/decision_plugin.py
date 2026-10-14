"""Reviewed local decision wrappers; high-level intent has no actuator authority.

The manifest hash pins the trusted command and working directory declaration.
Process ownership is reused from JSONL adapters, not a security sandbox. Actual
reset capabilities must match the declaration before a peer is negotiated.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
import re
import sys
import time

from .json_adapter import JsonLineAdapter, SCHEMA as JSONL_SCHEMA
from .profile import digest, read_json_snapshot
from ..platform_v2.contracts import ContractError, exact, identity
from ..platform_v2.decision_contracts import (
    DECISION_INTENT_SCHEMA, DECISION_OBSERVATION_SCHEMA,
    validate_decision_intent, validate_decision_observation)

MANIFEST_SCHEMA = 'polar.sim.decision-plugins.v1'
CAPABILITY_SCHEMA = 'polar.sim.decision-plugin.capabilities.v1'
CAPABILITIES = dict(
    schema=CAPABILITY_SCHEMA, observation_schema=DECISION_OBSERVATION_SCHEMA,
    intent_schema=DECISION_INTENT_SCHEMA, sensor_profile='own_referee_v1',
    output_modes=['navigation_intent'], source_association='exact_observation_context_v1',
    fire_authority='none', ui_config_contract='empty_v1')


def validate_capabilities(value):
    exact(value, CAPABILITIES, 'decision_plugin_capabilities')
    for name, wanted in CAPABILITIES.items():
        if type(value[name]) is not type(wanted) or value[name] != wanted:
            raise ContractError('unsupported_decision_plugin_capability_' + name)
    return copy.deepcopy(value)


def load_decision_plugins(path):
    path = Path(path).absolute()
    value, manifest_sha = read_json_snapshot(path)
    exact(value, ('schema', 'adapters'), 'decision_plugin_manifest')
    if type(value['schema']) is not str or value['schema'] != MANIFEST_SCHEMA:
        raise ContractError('unsupported_decision_plugin_manifest')
    if type(value['adapters']) is not list or not 1 <= len(value['adapters']) <= 16:
        raise ContractError('invalid_decision_plugin_count')
    rows, seen = [], set()
    for row in value['adapters']:
        fields=('adapter_id','label','command','cwd','supported_robots','transport','capabilities')
        if type(row) is dict and row.get('transport')=='wsl_jsonl_v1':fields+=('wsl',)
        exact(row, fields, 'decision_plugin_registration')
        aid = row['adapter_id']
        if (type(aid) is not str or not re.fullmatch(r'custom_[a-z0-9_]{1,100}', aid)
                or aid in seen):
            raise ContractError('invalid_or_duplicate_decision_plugin_id')
        seen.add(aid)
        if type(row['label']) is not str or not 1 <= len(row['label']) <= 200:
            raise ContractError('invalid_decision_plugin_label')
        if type(row['transport']) is not str or row['transport'] not in ('jsonl_v1','ros2_decision_envelope_v1','wsl_jsonl_v1'):
            raise ContractError('unsupported_decision_plugin_transport')
        robots = row['supported_robots']
        if (type(robots) is not list or not 1 <= len(robots) <= 64 or
                any(type(robot) is not str or
                    not re.fullmatch(r'[a-z][a-z0-9_]{0,127}', robot) for robot in robots) or
                len(set(robots)) != len(robots)):
            raise ContractError('invalid_decision_plugin_robots')
        validate_capabilities(row['capabilities'])
        command = row['command']
        if (type(command) is not list or not 1 <= len(command) <= 32 or
                any(type(arg) is not str or not arg or len(arg) > 4096 or '\0' in arg
                    for arg in command)):
            raise ContractError('invalid_decision_plugin_argv')
        if row['transport']=='wsl_jsonl_v1':
            from .wsl_jsonl import validate_linux_settings
            exact(row['wsl'],('distribution','python','process_env'),'decision_plugin_wsl')
            linux=validate_linux_settings(dict(row['wsl'],command=command,cwd=row['cwd']))
            rows.append(dict(copy.deepcopy(row),linux=linux,kind='decision',required_sensors=[]))
            continue
        command = [sys.executable if arg == '{python}' else arg for arg in command]
        binary = Path(command[0])
        if not binary.is_absolute() or not binary.is_file() or not os.access(binary, os.X_OK):
            raise ContractError('decision_plugin_requires_local_absolute_executable')
        if type(row['cwd']) is not str or '\0' in row['cwd']:
            raise ContractError('invalid_decision_plugin_cwd')
        cwd = (path.parent / row['cwd']).resolve()
        if not cwd.is_dir():
            raise ContractError('decision_plugin_cwd_missing')
        rows.append(dict(copy.deepcopy(row), command=command, cwd=str(cwd),
                         kind='decision', required_sensors=[]))
    return rows, manifest_sha


class DecisionPluginAdapter(JsonLineAdapter):
    """An intent component for a composer; never register as a physical channel."""

    def __init__(self, config, *, registration, manifest, manifest_sha,
                 clock=time.perf_counter):
        exact(config, (), 'decision_plugin_binding_config')
        validate_capabilities(registration['capabilities'])
        # Existing JSONL process setup constructs navigation/aim metadata. It
        # owns transport only; decision responses use the strict contract below.
        transport_registration = dict(copy.deepcopy(registration), kind='navigation')
        super().__init__(copy.deepcopy(config), registration=transport_registration,
                         manifest=manifest, manifest_sha=manifest_sha, clock=clock)
        self.descriptor = dict(
            adapter_id=registration['adapter_id'], version='1.0.0', kind='decision',
            label=registration['label'], required_sensors=[], output_modes=['navigation_intent'],
            supported_robots=list(registration['supported_robots']), fire_authority='none',
            ui_config_contract='empty_v1', capabilities=copy.deepcopy(registration['capabilities']),
            qualification='interface_declared_not_algorithm_or_live_acceptance')
        self._prepared = False
        self._negotiated = False
        self._reset_completed = False
        self._last_seq = -1
        self._last_sim_time = -1.

    def _open_owned_process(self):
        if digest(self.manifest) != self.manifest_sha:
            raise ContractError('custom_manifest_changed_after_registration')
        if self._prepared and self.process is not None and not self.failed:
            return
        return super()._open_owned_process()

    def prepare(self):
        if self._prepared or self._reset_completed:
            raise ContractError('decision_plugin_prepare_once_before_reset')
        self._open_owned_process()
        self._exchange(dict(op='prepare', config=self.config), timeout=2.)
        self._prepared = True

    def reset(self, context, *, deadline=None):
        exact(context, ('episode', 'robot_id', 'binding_epoch'), 'decision_plugin_context')
        identity(dict(context, observed_seq=0, sim_time=0., wall_deadline=0.))
        if context['robot_id'] not in self.descriptor['supported_robots']:
            raise ContractError('decision_plugin_robot_unsupported')
        if self._reset_completed:
            raise ContractError('decision_plugin_reset_once')
        exact(self.config, (), 'decision_plugin_binding_config')
        if deadline is None:
            super().reset(context)
        else:
            super().reset(context, deadline=deadline)
        self._negotiated = True
        self._reset_completed = True

    def _validate_response(self, result, packet):
        field = 'intent' if packet['op'] == 'act' else 'capabilities'
        exact(result, ('schema', 'op', 'ok', field), 'decision_plugin_response')
        if (type(result['schema']) is not str or result['schema'] != JSONL_SCHEMA or
                type(result['op']) is not str or result['op'] != packet['op'] or
                result['ok'] is not True):
            raise ContractError('decision_plugin_response_identity')
        if field == 'capabilities':
            capabilities = validate_capabilities(result[field])
            if capabilities != self.descriptor['capabilities']:
                raise ContractError('decision_plugin_peer_capabilities_mismatch')
        else:
            validate_decision_intent(result['intent'], packet['observation'])

    def checked(self, observation):
        if not self._negotiated or not self._reset_completed:
            raise ContractError('decision_plugin_reset_negotiation_required')
        value = validate_decision_observation(observation)
        if any(type(value[name]) is not type(wanted) or value[name] != wanted
               for name, wanted in self.context.items()):
            raise ContractError('decision_plugin_context_mismatch')
        if value['observed_seq'] <= self._last_seq or value['sim_time'] < self._last_sim_time:
            raise ContractError('decision_plugin_replayed_observation')
        return value

    def act(self, observation):
        value = self.checked(observation)
        response = self._exchange(dict(op='act', observation=value),
                                  timeout=min(.15, value['wall_deadline'] - self.clock()))
        intent = validate_decision_intent(response['intent'], value)
        self._last_seq = value['observed_seq']
        self._last_sim_time = value['sim_time']
        return intent
