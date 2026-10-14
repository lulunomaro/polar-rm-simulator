"""Versioned point-cloud/IMU observation with no ideal pose or odometry feed."""
from __future__ import annotations
import base64
import copy
import math
import re
import struct
from .contracts import ContractError, IDENTITY, exact, identity, finite, integer, vector, string, boolean

NAV_SCHEMA = 'polar.sim.navigation-observation.v1'
NAV_PROFILE = 'pointcloud_imu_v1'
NAV_STATUS_SCHEMA = 'polar.sim.navigation-status.v1'
NAV_FRAMES = {'base_link': 'x_forward_y_left_z_up', 'livox_frame': 'x_forward_y_left_z_up'}
POINT_ENCODING = 'livox_xyz_offset_reflectivity_tag_line_le_v1'
POINT_STRUCT = struct.Struct('<fffIBBBx')
MAX_POINTS = 40000


def extrinsics(value):
    exact(value, ('parent_frame', 'translation_m', 'rotation_xyzw', 'calibration_id'), 'navigation_extrinsics')
    if type(value['parent_frame']) is not str or value['parent_frame'] != 'base_link': raise ContractError('navigation_sensor_parent')
    vector(value['translation_m'], 3, 'navigation_translation', -10, 10)
    q = vector(value['rotation_xyzw'], 4, 'navigation_rotation', -1, 1)
    if abs(sum(x*x for x in q)-1) > 1e-6: raise ContractError('navigation_quaternion_not_unit')
    string(value['calibration_id'], 'navigation_calibration_id')


def decode_points(cloud):
    count = integer(cloud['point_count'], 'point_count', 0, MAX_POINTS)
    text = cloud['data_base64']
    if type(text) is not str or len(text) > (MAX_POINTS*POINT_STRUCT.size+2)//3*4:
        raise ContractError('navigation_cloud_size')
    try: raw = base64.b64decode(text, validate=True)
    except (ValueError, TypeError): raise ContractError('navigation_cloud_base64') from None
    if len(raw) != count*POINT_STRUCT.size or base64.b64encode(raw).decode('ascii') != text:
        raise ContractError('navigation_cloud_packed_size_or_encoding')
    return raw


def validate_navigation_observation(value):
    value = copy.deepcopy(value)
    exact(value, ('schema', *IDENTITY, 'frames', 'own', 'referee', 'sensors'), 'navigation_observation')
    if type(value['schema']) is not str or value['schema'] != NAV_SCHEMA:
        raise ContractError('navigation_observation_version')
    identity(value)
    exact(value['frames'], NAV_FRAMES, 'navigation_frames')
    if any(type(value['frames'][k]) is not str or value['frames'][k] != v for k,v in NAV_FRAMES.items()):
        raise ContractError('navigation_frames')
    own = value['own']
    exact(own, ('team', 'role', 'hp', 'ammo', 'heat', 'alive'), 'navigation_own')
    for k in ('team', 'role'): string(own[k], k)
    for k in ('hp', 'ammo', 'heat'): finite(own[k], k, 0)
    boolean(own['alive'], 'alive')
    ref = value['referee']
    exact(ref, ('phase', 'remaining_seconds', 'emergency_stop'), 'navigation_referee')
    if type(ref['phase']) is not str or ref['phase'] not in ('running', 'paused', 'idle', 'finished', 'countdown'):
        raise ContractError('navigation_referee_phase')
    finite(ref['remaining_seconds'], 'remaining_seconds', 0)
    boolean(ref['emergency_stop'], 'emergency_stop')
    exact(value['sensors'], ('pointcloud', 'imu'), 'navigation_sensors')
    cloud = value['sensors']['pointcloud']; imu = value['sensors']['imu']
    exact(cloud, ('available', 'reason', 'frame_id', 'acquisition_start_ns', 'acquisition_end_ns',
        'capture_sim_time', 'frame', 'encoding', 'point_count', 'data_base64', 'range_min_m',
        'range_max_m', 'time_quantization_ns', 'provenance', 'profile_sha256', 'extrinsics'), 'navigation_cloud')
    if (cloud['available'] is not True or type(cloud['reason']) is not str or cloud['reason'] != 'available'
        or any(type(cloud[k]) is not str for k in ('frame','encoding','provenance'))
        or cloud['frame'] != 'livox_frame' or cloud['encoding'] != POINT_ENCODING
        or cloud['provenance'] != 'mujoco_ray_cast_nonrepeating_profile_v1'):
        raise ContractError('navigation_cloud_source')
    integer(cloud['frame_id'], 'navigation_frame_id')
    start = integer(cloud['acquisition_start_ns'], 'acquisition_start_ns')
    end = integer(cloud['acquisition_end_ns'], 'acquisition_end_ns')
    quantum = integer(cloud['time_quantization_ns'], 'time_quantization_ns', 1, 10000000)
    if not 0 < end-start <= 200000000 or (end-start)%quantum:
        raise ContractError('navigation_cloud_acquisition_window')
    capture = finite(cloud['capture_sim_time'], 'navigation_capture_time', 0, value['sim_time'])
    if abs(capture-end*1e-9) > .5e-9: raise ContractError('navigation_cloud_clock_mismatch')
    minimum = finite(cloud['range_min_m'], 'navigation_range_min', 0, 10)
    maximum = finite(cloud['range_max_m'], 'navigation_range_max', minimum+1e-6, 200)
    if type(cloud['profile_sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', cloud['profile_sha256']):
        raise ContractError('navigation_profile_identity')
    extrinsics(cloud['extrinsics'])
    previous = -1
    raw = decode_points(cloud)
    for i, point in enumerate(POINT_STRUCT.iter_unpack(raw)):
        x,y,z,offset,reflectivity,tag,line = point
        distance = math.sqrt(x*x+y*y+z*z)
        if (not all(math.isfinite(v) for v in (x,y,z)) or not minimum-1e-5 <= distance <= maximum+1e-5
            or not previous <= offset < end-start or offset%quantum or line >= 4 or tag != 0x10
            or raw[i*POINT_STRUCT.size+19] != 0):
            raise ContractError('navigation_point_value_or_time')
        previous = offset
    exact(imu, ('available', 'reason', 'frame', 'capture_sim_time', 'extrinsics', 'provenance', 'samples'), 'navigation_imu')
    if (imu['available'] is not True or imu['reason'] != 'available' or imu['frame'] != 'livox_frame'
        or any(type(imu[k]) is not str for k in ('reason','frame','provenance'))
        or imu['provenance'] != 'mujoco_gyro_accelerometer_v1' or imu['extrinsics'] != cloud['extrinsics']):
        raise ContractError('navigation_imu_source')
    if finite(imu['capture_sim_time'], 'imu_capture_time', 0, value['sim_time']) != capture:
        raise ContractError('navigation_imu_clock_mismatch')
    samples = imu['samples']
    if type(samples) is not list or not 2 <= len(samples) <= 1024: raise ContractError('navigation_imu_count')
    previous = -1
    for row in samples:
        exact(row, ('sample_sim_ns', 'angular_velocity_rps', 'linear_acceleration_mps2'), 'navigation_imu_sample')
        stamp = integer(row['sample_sim_ns'], 'imu_sample_sim_ns')
        if not start <= stamp <= end or stamp <= previous: raise ContractError('navigation_imu_sequence')
        vector(row['angular_velocity_rps'], 3, 'imu_angular_velocity', -1000, 1000)
        vector(row['linear_acceleration_mps2'], 3, 'imu_acceleration', -10000, 10000)
        previous = stamp
    if samples[0]['sample_sim_ns'] != start or samples[-1]['sample_sim_ns'] != end:
        raise ContractError('navigation_imu_does_not_bracket_cloud')
    return value


def build_navigation_observation(packet, *, binding_epoch, observed_seq, wall_deadline):
    return validate_navigation_observation(dict(schema=NAV_SCHEMA, robot_id=packet['robot_id'],
        episode=packet['episode'], binding_epoch=binding_epoch, observed_seq=observed_seq,
        sim_time=packet['sim_time'], wall_deadline=wall_deadline, frames=dict(NAV_FRAMES),
        own=packet['own'], referee=packet['referee'], sensors=packet['sensors']))


def validate_navigation_status(value, observation):
    value = copy.deepcopy(value)
    exact(value, ('schema', *IDENTITY, 'kind', 'status'), 'navigation_status')
    identity(value)
    if (observation.get('schema') != NAV_SCHEMA or type(value['schema']) is not str or value['schema'] != NAV_STATUS_SCHEMA
        or type(value['kind']) is not str or value['kind'] != 'navigation' or type(value['status']) is not str
        or value['status'] not in ('pending_localization', 'no_associated_command')
        or any(type(value[k]) is not type(observation[k]) or value[k] != observation[k] for k in IDENTITY)):
        raise ContractError('navigation_status_identity_or_state')
    return value
