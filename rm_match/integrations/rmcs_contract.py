"""Copied, reviewed fixture own-state/angle contract. No target truth."""
import math
import numpy as np

def rotation(yaw,pitch):
 c,s=np.cos(yaw),np.sin(yaw);cp,sp=np.cos(pitch),np.sin(pitch)
 return np.array([[c,-s,0],[s,c,0],[0,0,1.]])@np.array([[cp,0,-sp],[0,1,0],[sp,0,cp]])

def own_state(observation):
 import mujoco
 q=np.array(observation.own_qpos);v=np.array(observation.own_qvel)
 if q.shape!=(5,) or v.shape!=(5,) or observation.odom_xyyaw is None:raise ValueError('Five joint own state and odometry required')
 yaw=observation.odom_xyyaw[2]+q[3];pitch=q[4];R=rotation(yaw,pitch)
 quat=np.zeros(4);mujoco.mju_mat2Quat(quat,R.ravel())
 angular_world=np.array([0.,0.,v[2]+v[3]])+rotation(yaw,0)@np.array([0.,-v[4],0.])
 return dict(joint_positions=q.tolist(),joint_velocities=v.tolist(),base_odom_xyyaw=list(observation.odom_xyyaw),
  base_odom_vxyw=list(observation.odom_vxyw),pitchlink_to_world_quaternion_wxyz=quat.tolist(),
  pitchlink_angular_velocity_world_rad_s=angular_world.tolist(),pitchlink_angular_velocity_local_rad_s=(R.T@angular_world).tolist(),
  yaw_origin_world_m=[*observation.odom_xyyaw[:2],.65],camera_position_pitchlink_m=[.24,0,.06],muzzle_position_pitchlink_m=[.38,0,0],
  camera_optical_from_pitchlink_rotation=[[0,-1,0],[0,0,-1],[1,0,0]],
  hp=observation.own_hp,ammo=observation.ammo,heat=observation.own_heat)

def _direction_pose(observation,label):
 try:
  q=np.asarray(observation.own_qpos);odom=np.asarray(observation.odom_xyyaw)
  if (q.shape!=(5,) or odom.shape!=(3,) or q.dtype.kind not in 'iuf' or odom.dtype.kind not in 'iuf'
      or not np.isfinite(q).all() or not np.isfinite(odom).all()):
   raise ValueError(label+' finite five-joint pose and three-value odometry required')
  q=q.astype(float);odom=odom.astype(float)
  if not np.isfinite(q).all() or not np.isfinite(odom).all():raise ValueError(label+' finite pose conversion required')
  return q,odom
 except (AttributeError,TypeError,OverflowError) as exc:
  raise ValueError(label+' finite five-joint pose and three-value odometry required') from exc

def command_from_direction(output,current_observation,*,capture_observation=None):
 """Map a direction without rebinding its source or claiming moving support.

 pitch_link explicitly means the supplied exposure's pitch frame. The caller
 must associate that exposure with the real algorithm result; this helper only
 validates mechanical pose/time relationships and emits no source/deadline.
 """
 from rm_match.contracts import Command
 if output.get('should_control',False) and output.get('direction_frame')=='pitch_link':
  q,current_odom=_direction_pose(current_observation,'Current');base=float(current_odom[2])
 else:
  q=np.array(current_observation.own_qpos);base=current_observation.odom_xyyaw[2]
 hold=Command(gimbal_yaw=float(q[3]),gimbal_pitch=float(q[4]),fire=False)
 if not output.get('should_control',False):return hold
 direction=np.array(output['direction'],dtype=float)
 if direction.shape!=(3,) or not np.isfinite(direction).all() or np.linalg.norm(direction)<1e-12:raise ValueError('Finite nonzero direction required')
 frame=output.get('direction_frame')
 if frame=='pitch_link':
  if capture_observation is None:raise ValueError('Explicit capture observation required for pitch_link direction')
  try:
   for key in ('robot_id','episode'):
    current=getattr(current_observation,key);captured=getattr(capture_observation,key)
    if type(current) is not type(captured) or current!=captured:raise ValueError('Capture/current identity mismatch')
   if (type(current_observation.robot_id) is not str or not current_observation.robot_id
       or type(current_observation.episode) is not int or current_observation.episode<0):
    raise ValueError('Capture/current robot and episode required')
   now=current_observation.sim_time;exposure=capture_observation.sim_time
   if (type(now) not in (int,float) or type(exposure) not in (int,float)
       or not math.isfinite(now) or not math.isfinite(exposure) or not 0<=exposure<=now):
    raise ValueError('Finite capture time must not follow current time')
  except AttributeError as exc:raise ValueError('Capture/current identity and time required') from exc
  captured_q,captured_odom=_direction_pose(capture_observation,'Capture')
  captured_yaw=float(captured_odom[2])+float(captured_q[3])
  if not math.isfinite(captured_yaw):raise ValueError('Finite capture yaw required')
  direction=rotation(captured_yaw,captured_q[4])@direction
  if not np.isfinite(direction).all():raise ValueError('Finite transformed direction required')
 elif frame!='world':raise ValueError('Direction frame must be explicit world or pitch_link')
 yaw=math.atan2(direction[1],direction[0])-base
 yaw=float(q[3]+math.atan2(math.sin(yaw-q[3]),math.cos(yaw-q[3])))
 pitch=math.atan2(direction[2],math.hypot(direction[0],direction[1]))
 # This fixture uses ideal reference servo, not the user's voltage/current motor loop.
 return Command(gimbal_yaw=yaw,gimbal_pitch=pitch,fire=bool(output.get('should_shoot',False)))
