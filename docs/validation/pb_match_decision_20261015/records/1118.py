"""PB algorithm output conversion, exact original camera source, no target math."""
from __future__ import annotations
import copy
import math
from .aim_camera_codec import CameraSensorBundle,validate_source_echo
from ..platform_v2.contracts import ContractError,exact,action_for,validate_action
from ..platform_v2.aim_contracts import aim_status_for

RESULT_SCHEMA='polar.sim.pb-aim-result.v1'

def convert_pb_result(value,observation,bundle):
    if type(bundle) is not CameraSensorBundle:raise ContractError('pb_aim_bundle_type')
    exact(value,('schema','source_context','capture_stamp_ns','status','output_frame','yaw','pitch'),'pb_aim_result')
    value=copy.deepcopy(value)
    if (type(value['schema']) is not str or value['schema']!=RESULT_SCHEMA
        or type(value['output_frame']) is not str or value['output_frame']!='chassis_relative_ros_rpy'):
        raise ContractError('pb_aim_output_schema_or_frame')
    validate_source_echo(value['source_context'],bundle)
    if type(value['capture_stamp_ns']) is not int or value['capture_stamp_ns']!=bundle.capture_stamp_ns:
        raise ContractError('pb_aim_original_capture_stamp')
    # Check against the very same observation, not a newer alias or latest TF.
    if any(type(observation.get(k)) is not type(v) or observation[k]!=v
           for k,v in bundle.source_context.items() if k in observation and k!='schema'):
        raise ContractError('pb_aim_observation_source_mismatch')
    if value['status'] in ('no_target','pending_result') and type(value['status']) is str:
        if value['yaw'] is not None or value['pitch'] is not None:raise ContractError('pb_aim_status_with_angles')
        return aim_status_for(observation,value['status'])
    if type(value['status']) is not str or value['status']!='gimbal_target':raise ContractError('pb_aim_output_status')
    for name in ('yaw','pitch'):
        if type(value[name]) not in (int,float) or not math.isfinite(value[name]):raise ContractError('pb_aim_finite_angle')
    # PB's projectile solver publishes ROS +Y pitch (positive down). The
    # simulator servo is positive up; this changes coordinates, not its solver.
    yaw=math.atan2(math.sin(value['yaw']),math.cos(value['yaw']))
    pitch=-float(value['pitch'])
    action=action_for(observation,'aim','gimbal_target',dict(frame='base_link',yaw_rad=yaw,
        pitch_rad=pitch,active=True,confidence=None,fire_permission=False))
    return validate_action(action,observation,dict(kind='aim',output_modes=['gimbal_target']))
