"""Versioned JSON-only algorithm boundary. No model, data, judge or roster objects.

wall_deadline is SERVER monotonic seconds, not a client clock. Simulation stamps
are seconds since episode start. Camera pose belongs to exposure, not delivery.
"""
from __future__ import annotations
import base64
import copy
import math

OBS_SCHEMA='polar.sim.observation.v2'
ACTION_SCHEMA='polar.sim.action.v2'
IDENTITY=('robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline')
FRAMES={'world':'right_handed_x_y_z_up_m_rad_ccw','base_link':'x_forward_y_left_z_up','gimbal_link':'relative_yaw_ccw_pitch_up','camera_optical':'x_right_y_down_z_forward'}
MAX_IMAGE_BYTES=8*1024*1024
MAX_INTEGER=2**53-1
class ContractError(ValueError):pass

def exact(value,keys,label):
    if type(value) is not dict or any(type(k) is not str for k in value) or set(value)!=set(keys):raise ContractError('invalid_'+label+'_fields')

def finite(value,label,low=-1e9,high=1e9):
    if type(value) not in (float,int):raise ContractError('invalid_'+label)
    try: f=float(value)
    except (OverflowError,ValueError):raise ContractError('invalid_'+label) from None
    if not math.isfinite(f) or not low<=f<=high:raise ContractError('invalid_'+label)
    return f

def integer(value,label,low=0,high=MAX_INTEGER):
    if type(value) is not int or not low<=value<=high:raise ContractError('invalid_'+label)
    return value

def vector(value,n,label,low=-1e9,high=1e9):
    if type(value) is not list or len(value)!=n:raise ContractError('invalid_'+label)
    return [finite(v,label,low,high) for v in value]

def string(value,label):
    if type(value) is not str or not value or len(value)>256:raise ContractError('invalid_'+label)
    return value

def boolean(value,label):
    if type(value) is not bool:raise ContractError('invalid_'+label)
    return value

def identity(value):
    string(value.get('robot_id'),'robot_id')
    for k in ('episode','binding_epoch','observed_seq'):integer(value.get(k),k)
    for k in ('sim_time','wall_deadline'):finite(value.get(k),k,0,1e12)

def validate_camera(camera,sim_time,*,image_token=None,robot_id=None,episode=None):
    if type(camera) is not dict or type(camera.get('available')) is not bool:raise ContractError('invalid_camera')
    if not camera['available']:
        exact(camera,('available','reason'),'camera_unavailable');string(camera['reason'],'camera_reason');return
    exact(camera,('available','reason','frame_id','capture_sim_time','own_qpos_at_capture','own_qvel_at_capture','own_odom_at_capture','own_odom_velocity_at_capture','image','intrinsics','extrinsics','provenance'),'camera')
    if type(camera['reason']) is not str or camera['reason']!='available':raise ContractError('invalid_camera_reason')
    integer(camera['frame_id'],'camera_frame_id');finite(camera['capture_sim_time'],'capture_sim_time',0,sim_time)
    vector(camera['own_qpos_at_capture'],5,'capture_qpos');vector(camera['own_qvel_at_capture'],5,'capture_qvel');vector(camera['own_odom_at_capture'],3,'capture_odom');vector(camera['own_odom_velocity_at_capture'],3,'capture_odom_velocity')
    if type(camera['provenance']) is not str or camera['provenance']!='simulated_raw_camera':raise ContractError('invalid_camera_provenance')
    image=camera['image'];exact(image,('encoding','width','height','stride_bytes','data_base64'),'image')
    if type(image['encoding']) is not str or image['encoding'] not in ('rgb8','bgr8'):raise ContractError('unsupported_image_encoding')
    w=integer(image['width'],'width',1,4096);h=integer(image['height'],'height',1,4096)
    if integer(image['stride_bytes'],'stride_bytes',3,4096*3)!=w*3:raise ContractError('image_must_be_packed')
    data=image['data_base64']
    if type(data) is not str or len(data)>MAX_IMAGE_BYTES*4//3+8:raise ContractError('image_too_large')
    raw=None
    if image_token is not None:
        from .camera_pixels import VerifiedCameraPixels
        if type(image_token) is VerifiedCameraPixels and image_token.matches(camera,robot_id=robot_id,episode=episode):
            raw=image_token.raw_bytes
    if raw is None:
        try:raw=base64.b64decode(data,validate=True)
        except Exception:raise ContractError('invalid_image_base64') from None
    if len(raw)!=w*h*3 or len(raw)>MAX_IMAGE_BYTES:raise ContractError('image_size_mismatch')
    intr=camera['intrinsics'];exact(intr,('fx','fy','cx','cy','distortion_model','distortion'),'intrinsics')
    for k in ('fx','fy'):finite(intr[k],k,1e-6,1e7)
    for k in ('cx','cy'):finite(intr[k],k,-1e5,1e5)
    if type(intr['distortion_model']) is not str or intr['distortion_model']!='brown_conrady_5':raise ContractError('unsupported_distortion')
    vector(intr['distortion'],5,'distortion')
    ext=camera['extrinsics'];exact(ext,('parent_frame','translation_m','rotation_xyzw','calibration_id'),'extrinsics')
    if type(ext['parent_frame']) is not str or ext['parent_frame']!='gimbal_link':raise ContractError('unsupported_camera_parent')
    vector(ext['translation_m'],3,'camera_translation',-10,10);q=vector(ext['rotation_xyzw'],4,'camera_rotation',-1,1)
    if abs(sum(v*v for v in q)-1)>1e-6:raise ContractError('camera_quaternion_not_unit')
    string(ext['calibration_id'],'calibration_id')
    return raw

def validate_observation(value,*,image_bytes=None,image_token=None):
    if type(value) is dict and value.get('schema') == 'polar.sim.navigation-observation.v1':
        if image_token is not None: raise ContractError('navigation_profile_cannot_carry_camera_token')
        from .navigation_contracts import validate_navigation_observation
        if image_bytes is not None: image_bytes['raw'] = None
        return validate_navigation_observation(value)
    # Validate and decode the SAME detached snapshot. A caller changing its
    # frame while we decode cannot pair copied metadata with older pixel bytes.
    value=copy.deepcopy(value)
    exact(value,('schema',*IDENTITY,'frames','own','referee','sensors'),'observation')
    if type(value['schema']) is not str or value['schema']!=OBS_SCHEMA:raise ContractError('unknown_observation_version_or_frames')
    exact(value['frames'],FRAMES,'frames')
    if any(type(value['frames'][k]) is not str or value['frames'][k]!=v for k,v in FRAMES.items()):raise ContractError('unknown_observation_version_or_frames')
    identity(value)
    own=value['own'];exact(own,('team','role','qpos','qvel','odom_xyyaw','odom_vxyw','hp','ammo','heat','alive'),'own')
    for k in ('team','role'):string(own[k],k)
    vector(own['qpos'],5,'qpos');vector(own['qvel'],5,'qvel')
    for k in ('odom_xyyaw','odom_vxyw'):
        if own[k] is not None:vector(own[k],3,k)
    for k in ('hp','ammo','heat'):finite(own[k],k,0)
    boolean(own['alive'],'alive')
    ref=value['referee'];exact(ref,('phase','remaining_seconds','emergency_stop'),'referee')
    if type(ref['phase']) is not str or ref['phase'] not in ('running','paused','idle','finished','countdown'):raise ContractError('unknown_phase')
    finite(ref['remaining_seconds'],'remaining_seconds',0);boolean(ref['emergency_stop'],'emergency_stop')
    sensors=value['sensors'];exact(sensors,('camera','ranges'),'sensors')
    decoded=(validate_camera(sensors['camera'],value['sim_time']) if image_token is None else
        validate_camera(sensors['camera'],value['sim_time'],image_token=image_token,robot_id=value['robot_id'],episode=value['episode']))
    scan=sensors['ranges']
    if type(scan) is not dict or type(scan.get('available')) is not bool:raise ContractError('invalid_ranges')
    if not scan['available']:
        exact(scan,('available','reason'),'ranges_unavailable');string(scan['reason'],'ranges_reason')
    else:
        exact(scan,('available','reason','ranges_m','angles_rad','range_max_m','capture_sim_time','frame','provenance'),'ranges')
        if any(type(scan[k]) is not str for k in ('reason','frame','provenance')) or scan['reason']!='available' or scan['frame']!='base_link' or scan['provenance']!='ideal_simulated_range':raise ContractError('invalid_range_frame_or_source')
        maximum=finite(scan['range_max_m'],'range_max',1e-6,1e4)
        n=len(scan['ranges_m']) if type(scan['ranges_m']) is list else 0
        if not 1<=n<=4096:raise ContractError('invalid_scan_size')
        vector(scan['ranges_m'],n,'ranges_m',0,maximum);vector(scan['angles_rad'],n,'angles_rad',-2*math.pi,2*math.pi)
        finite(scan['capture_sim_time'],'scan_time',0,value['sim_time'])
    if image_bytes is not None:image_bytes['raw']=decoded
    return value

def build_observation(raw,*,binding_epoch,observed_seq,wall_deadline,camera=None):
    scan=bool(raw.ranges) and len(raw.ranges)==len(raw.range_angles)
    value=dict(schema=OBS_SCHEMA,robot_id=str(raw.robot_id),episode=int(raw.episode),binding_epoch=binding_epoch,observed_seq=observed_seq,sim_time=float(raw.sim_time),wall_deadline=wall_deadline,frames=dict(FRAMES),
        own=dict(team=str(raw.team),role=str(raw.role),qpos=[float(v) for v in raw.own_qpos],qvel=[float(v) for v in raw.own_qvel],odom_xyyaw=[float(v) for v in raw.odom_xyyaw] if raw.odom_xyyaw is not None else None,odom_vxyw=[float(v) for v in raw.odom_vxyw] if raw.odom_vxyw is not None else None,hp=float(raw.own_hp),ammo=float(raw.ammo),heat=float(raw.own_heat),alive=bool(raw.own_hp>0)),
        referee=dict(phase=str(raw.match_phase),remaining_seconds=float(raw.remaining_seconds),emergency_stop=bool(raw.emergency_stop)),
        sensors=dict(camera=copy.deepcopy(camera) if camera is not None else dict(available=False,reason='calibrated_camera_unavailable'),ranges=dict(available=True,reason='available',ranges_m=[float(v) for v in raw.ranges],angles_rad=[float(v) for v in raw.range_angles],range_max_m=float(raw.range_max),capture_sim_time=float(raw.sim_time),frame='base_link',provenance='ideal_simulated_range') if scan else dict(available=False,reason='range_sensor_unavailable')))
    return validate_observation(value)

def action_for(observation,kind,mode,command):
    return dict(schema=ACTION_SCHEMA,**{k:observation[k] for k in IDENTITY},kind=kind,mode=mode,command=command)

def validate_action(value,observation,capabilities):
    value=copy.deepcopy(value)
    exact(value,('schema',*IDENTITY,'kind','mode','command'),'action');identity(value)
    if type(value['schema']) is not str or value['schema']!=ACTION_SCHEMA or any(value[k]!=observation[k] for k in IDENTITY):raise ContractError('action_observation_mismatch')
    if type(value['kind']) is not str or type(value['mode']) is not str:raise ContractError('unsupported_action_mode')
    if value['kind']!=capabilities['kind'] or value['mode'] not in capabilities['output_modes']:raise ContractError('unsupported_action_mode')
    c=value['command']
    if value['kind']=='navigation' and value['mode']=='velocity_body':
        exact(c,('frame','vx_mps','vy_mps','wz_rps'),'navigation_command')
        if type(c['frame']) is not str or c['frame']!='base_link':raise ContractError('unsupported_navigation_frame')
        for k in ('vx_mps','vy_mps'):finite(c[k],k,-1,1)
        finite(c['wz_rps'],'wz_rps',-2,2)
        if math.hypot(c['vx_mps'],c['vy_mps'])>1+1e-9:raise ContractError('navigation_velocity_exceeds_norm')
    elif value['kind']=='aim' and value['mode']=='gimbal_target':
        exact(c,('frame','yaw_rad','pitch_rad','active','confidence','fire_permission'),'aim_command')
        if type(c['frame']) is not str or c['frame']!='base_link':raise ContractError('unsupported_aim_frame')
        finite(c['yaw_rad'],'yaw_rad',-math.pi,math.pi);finite(c['pitch_rad'],'pitch_rad',-math.pi/2,math.pi/2)
        boolean(c['active'],'aim_active');boolean(c['fire_permission'],'fire_permission')
        if c['confidence'] is not None:finite(c['confidence'],'confidence',0,1)
        if not c['active'] and c['fire_permission']:raise ContractError('inactive_fire_permission')
    else:raise ContractError('action_mode_not_implemented')
    return value
