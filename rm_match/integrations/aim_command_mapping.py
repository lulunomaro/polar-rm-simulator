"""Local angle declarations for actual, capture-associated gimbal commands.

This is an output codec, not a Target-to-command solver or source-association
mechanism. A reviewed wrapper must carry source_context through the actual
algorithm callback. Merely asserting command_origin cannot prove that callback.
Use prepare_aim_input once upstream; pass its validated observation and bundle.
Runtime still owns expiry, permission, current consumption and actuator limits.
"""
from __future__ import annotations
from dataclasses import dataclass
import math

from .aim_camera_codec import CameraSensorBundle, validate_source_echo
from ..platform_v2.contracts import (
    ContractError, IDENTITY, OBS_SCHEMA, action_for, exact, finite, identity,
    validate_action, vector,
)
from ..platform_v2.aim_contracts import aim_status_for

MAPPING_SCHEMA = 'polar.sim.aim-command-mapping.v1'
RESULT_SCHEMA = 'polar.sim.aim-angle-result.v1'
COMMAND_ORIGIN = 'capture_associated_gimbal_command_v1'


@dataclass(frozen=True)
class AimCommandMapping:
    angle_unit: str
    yaw_sign: int
    pitch_sign: int
    yaw_offset_rad: float
    pitch_offset_rad: float
    input_frame: str

    def __post_init__(self):
        if type(self.angle_unit) is not str or self.angle_unit not in ('rad', 'deg'):
            raise ContractError('unsupported_aim_angle_unit')
        if type(self.input_frame) is not str or self.input_frame not in ('base_link', 'inertial'):
            raise ContractError('unsupported_aim_input_frame')
        if any(type(v) is not int or v not in (-1, 1) for v in (self.yaw_sign, self.pitch_sign)):
            raise ContractError('invalid_aim_axis_sign')
        for name in ('yaw_offset_rad', 'pitch_offset_rad'):
            finite(getattr(self, name), name, -math.pi, math.pi)


def load_command_mapping(declaration):
    """Parse an exact trusted-local JSON object; not HTTP binding config.

    Offsets are always radians, applied AFTER sign and unit conversion. Yaw is
    CCW about +Z and pitch is up. base_link means the base AT EXPOSURE;
    inertial means the algorithm's inertial axes aligned with own odometry yaw.
    The wrapper must actually establish that alignment, never identity-TF it.
    Local registration must separately pin this declaration's bytes/SHA.
    """
    fields = ('angle_unit', 'yaw_sign', 'pitch_sign', 'yaw_offset_rad',
              'pitch_offset_rad', 'input_frame')
    exact(declaration, ('schema', *fields), 'aim_command_mapping')
    if type(declaration['schema']) is not str or declaration['schema'] != MAPPING_SCHEMA:
        raise ContractError('unsupported_aim_mapping_schema')
    return AimCommandMapping(**{key: declaration[key] for key in fields})


def _source_observation(observation, bundle, echoed):
    if type(bundle) is not CameraSensorBundle:
        raise ContractError('invalid_aim_sensor_bundle')
    if type(observation) is not dict or observation.get('schema') != OBS_SCHEMA:
        raise ContractError('aim_mapping_requires_validated_observation_v2')
    identity(observation)
    source = validate_source_echo(echoed, bundle)
    if any(type(source[k]) is not type(observation[k]) or source[k] != observation[k] for k in IDENTITY):
        raise ContractError('aim_mapping_observation_source_mismatch')
    # The bundle came from the one strict canonical input decode upstream.
    # Verify this exact exposure's metadata without another multi-MB decode.
    try:
        camera = observation['sensors']['camera']
        metadata = bundle.camera
        if type(camera) is not dict or camera.get('available') is not True:
            raise ContractError('aim_mapping_camera_unavailable')
        for key in ('frame_id', 'capture_sim_time'):
            if type(camera[key]) is not type(metadata[key]) or camera[key] != metadata[key]:
                raise ContractError('aim_mapping_camera_source_mismatch')
        if camera['extrinsics'] != metadata['extrinsics']:
            raise ContractError('aim_mapping_calibration_mismatch')
        age = observation['sim_time'] - source['capture_sim_time']
        if not 0 <= age <= .08:
            raise ContractError('aim_mapping_original_capture_expired')
    except (KeyError, TypeError):
        raise ContractError('aim_mapping_missing_capture_metadata') from None
    return metadata


def map_aim_result(mapping, result, observation, bundle, *, capabilities, host_now=None):
    """Convert a real wrapper result to canonical action OR explicit status.

    result is an exact union: tracking additionally requires yaw, pitch,
    confidence (unknown=None) and command_origin=COMMAND_ORIGIN. no_target and
    pending_result carry NO angles. source_context echoes the entire original
    camera bundle, including six typed request identities and exposure fields.

    host_now, when supplied, must be the ORIGINAL host perf_counter domain.
    Linux peers leave it None; they must not subtract Linux clocks from host
    deadlines. Returning the original deadline is not authority acceptance.
    No fire, new timestamp, nearest/latest-message association or frame guess.
    """
    if type(mapping) is not AimCommandMapping:
        raise ContractError('invalid_aim_command_mapping')
    # Declaration can only promise a direct gimbal command, not raw Target data.
    from ..deployment.aim_plugin import validate_capabilities
    validate_capabilities(capabilities)
    if type(result) is not dict or type(result.get('status')) is not str:
        raise ContractError('invalid_aim_angle_result')
    status = result['status']
    fields = ('schema', 'status', 'source_context')
    if status == 'tracking':
        fields += ('yaw', 'pitch', 'confidence', 'command_origin')
    elif status not in ('no_target', 'pending_result'):
        raise ContractError('unsupported_aim_result_status')
    exact(result, fields, 'aim_angle_result')
    if type(result['schema']) is not str or result['schema'] != RESULT_SCHEMA:
        raise ContractError('unsupported_aim_angle_result_schema')
    metadata = _source_observation(observation, bundle, result['source_context'])
    if host_now is not None:
        now = finite(host_now, 'host_now', 0, 1e12)
        if now >= observation['wall_deadline']:
            raise ContractError('aim_mapping_original_host_deadline_expired')
    if status != 'tracking':
        return aim_status_for(observation, status)
    if type(result['command_origin']) is not str or result['command_origin'] != COMMAND_ORIGIN:
        raise ContractError('aim_mapping_requires_actual_capture_command')
    confidence = result['confidence']
    if confidence is not None:
        confidence = finite(confidence, 'aim_confidence', 0, 1)
    factor = math.pi / 180 if mapping.angle_unit == 'deg' else 1.
    yaw = mapping.yaw_sign * finite(result['yaw'], 'aim_yaw', -1e6, 1e6) * factor + mapping.yaw_offset_rad
    pitch = mapping.pitch_sign * finite(result['pitch'], 'aim_pitch', -1e6, 1e6) * factor + mapping.pitch_offset_rad
    try:
        if observation['own']['odom_xyyaw'] is None or observation['own']['odom_vxyw'] is None:
            raise ContractError('aim_mapping_own_pose_unavailable')
        current_yaw = vector(observation['own']['odom_xyyaw'], 3, 'mapping_current_own_pose')[2]
        if mapping.input_frame == 'base_link':
            yaw += vector(metadata['own_odom_at_capture'], 3, 'mapping_capture_own_pose')[2]
        yaw -= current_yaw
    except (KeyError, TypeError):
        raise ContractError('aim_mapping_missing_own_pose') from None
    yaw = math.atan2(math.sin(yaw), math.cos(yaw))
    command = dict(frame='base_link', yaw_rad=yaw, pitch_rad=pitch,
                   active=True, confidence=confidence, fire_permission=False)
    action = action_for(observation, 'aim', 'gimbal_target', command)
    return validate_action(action, observation, dict(kind='aim', output_modes=['gimbal_target']))
