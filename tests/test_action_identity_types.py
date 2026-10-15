"""Exact source identity regression; no algorithm or process qualification."""
import copy

import pytest

from rm_match.deployment.aim_plugin import AimPluginAdapter,CAPABILITIES
from rm_match.deployment.json_adapter import SCHEMA as JSONL_SCHEMA
from rm_match.platform_v2.contracts import (
    ContractError, IDENTITY, action_for, validate_action, validate_observation)
from rm_match.platform_v2.test_contracts import sample


def aim_action(observation):
    return action_for(observation, 'aim', 'gimbal_target', dict(
        frame='base_link', yaw_rad=.2, pitch_rad=.1, active=True,
        confidence=None, fire_permission=False))


def validate_aim_response(action, observation):
    # Instantiate the real host adapter without reset/spawn. This exercises the
    # wire-response boundary used by JSONL, ROS relay and WSL transports.
    adapter = AimPluginAdapter({}, registration=dict(
        adapter_id='custom_identity_validator', kind='aim',
        label='Validation only', required_sensors=['camera'],transport='jsonl_v1',capabilities=copy.deepcopy(CAPABILITIES)),
        manifest=__file__, manifest_sha='0' * 64)
    adapter._validate_response(
        dict(schema=JSONL_SCHEMA, op='act', ok=True, action=action),
        dict(op='act', observation=observation))


@pytest.mark.parametrize('field', ['sim_time', 'wall_deadline'])
@pytest.mark.parametrize('source_type,other_type', [(float, int), (int, float)])
@pytest.mark.parametrize('entry', ['canonical_navigation', 'canonical_aim', 'aim_response'])
def test_equal_clock_value_with_changed_type_is_rejected(field, source_type, other_type, entry):
    observation = sample(True)
    observation[field] = source_type(observation[field])
    validate_observation(observation)
    if entry == 'canonical_navigation':
        action = action_for(observation, 'navigation', 'velocity_body', dict(
            frame='base_link', vx_mps=.2, vy_mps=0., wz_rps=0.))
    else:
        action = aim_action(observation)
    action[field] = other_type(action[field])
    assert action[field] == observation[field]
    assert type(action[field]) is not type(observation[field])
    with pytest.raises(ContractError, match='^action_observation_mismatch$'):
        if entry == 'aim_response':
            validate_aim_response(action, observation)
        else:
            validate_action(action, observation, dict(
                kind=action['kind'], output_modes=[action['mode']]))


@pytest.mark.parametrize('sim_type,deadline_type', [
    (float, float), (int, float), (float, int), (int, int)])
def test_same_type_source_clocks_remain_valid_without_normalization(sim_type, deadline_type):
    observation = sample(True)
    observation['sim_time'] = sim_type(observation['sim_time'])
    observation['wall_deadline'] = deadline_type(observation['wall_deadline'])
    checked_observation = validate_observation(observation)
    original = copy.deepcopy(checked_observation)
    action = aim_action(checked_observation)
    result = validate_action(action, checked_observation, dict(
        kind='aim', output_modes=['gimbal_target']))
    validate_aim_response(action, checked_observation)
    assert checked_observation == original
    assert result == action
    assert all(type(result[key]) is type(checked_observation[key]) for key in IDENTITY)


@pytest.mark.parametrize('field', ['episode', 'binding_epoch', 'observed_seq', 'sim_time', 'wall_deadline'])
def test_boolean_cannot_impersonate_a_numeric_identity(field):
    observation = sample(True)
    observation[field] = 1 if field in ('episode', 'binding_epoch', 'observed_seq') else 1.
    validate_observation(observation)
    action = aim_action(observation)
    action[field] = True
    for entry in (
        lambda: validate_action(action, observation, dict(kind='aim', output_modes=['gimbal_target'])),
        lambda: validate_aim_response(action, observation),
    ):
        with pytest.raises(ContractError, match='^invalid_' + field + '$'):
            entry()
