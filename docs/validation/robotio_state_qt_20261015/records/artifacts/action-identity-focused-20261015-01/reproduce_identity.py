"""Validation-only repro: no external peer, ROS, physics or camera process."""
import json

from rm_match.platform_v2.test_contracts import sample
from rm_match.platform_v2.contracts import IDENTITY, action_for, validate_action
from rm_match.deployment.aim_plugin import AimPluginAdapter
from rm_match.deployment.json_adapter import SCHEMA
from rm_match.deployment.navigation_plugin import validate_result

observation = sample(True)
aim = action_for(observation, 'aim', 'gimbal_target', dict(
    frame='base_link', yaw_rad=0., pitch_rad=0., active=False,
    confidence=None, fire_permission=False))
aim['sim_time'] = int(observation['sim_time'])
aim['wall_deadline'] = int(observation['wall_deadline'])
adapter = AimPluginAdapter({}, registration=dict(
    adapter_id='custom_validation_only_aim', kind='aim', label='Validation only',
    required_sensors=['camera']), manifest=__file__, manifest_sha='0' * 64)
navigation = action_for(observation, 'navigation', 'velocity_body', dict(
    frame='base_link', vx_mps=0., vy_mps=0., wz_rps=0.))
navigation['sim_time'] = int(observation['sim_time'])
navigation['wall_deadline'] = int(observation['wall_deadline'])
result = {'identity_types': {
    key: [type(observation[key]).__name__, type(aim[key]).__name__]
    for key in IDENTITY}}
for name, validator in (
    ('canonical_aim', lambda: validate_action(aim, observation, adapter.descriptor)),
    ('actual_aim_response_validator', lambda: adapter._validate_response(
        dict(schema=SCHEMA, op='act', ok=True, action=aim),
        dict(op='act', observation=observation))),
    ('navigation_result_validator', lambda: validate_result(navigation, observation)),
):
    try:
        validator()
        result[name] = 'ACCEPT'
    except ValueError as error:
        result[name] = 'REJECT:' + str(error)
print(json.dumps(result, indent=2))
