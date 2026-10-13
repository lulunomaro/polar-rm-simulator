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

def command_from_direction(output,observation):
 """Explicit frame required. No synthetic firing when source declines control."""
 from rm_match.contracts import Command
 q=np.array(observation.own_qpos);base=observation.odom_xyyaw[2]
 hold=Command(gimbal_yaw=float(q[3]),gimbal_pitch=float(q[4]),fire=False)
 if not output.get('should_control',False):return hold
 direction=np.array(output['direction'],dtype=float)
 if direction.shape!=(3,) or not np.isfinite(direction).all() or np.linalg.norm(direction)<1e-12:raise ValueError('Finite nonzero direction required')
 frame=output.get('direction_frame')
 if frame=='pitch_link':direction=rotation(base+q[3],q[4])@direction
 elif frame!='world':raise ValueError('Direction frame must be explicit world or pitch_link')
 yaw=math.atan2(direction[1],direction[0])-base
 yaw=float(q[3]+math.atan2(math.sin(yaw-q[3]),math.cos(yaw-q[3])))
 pitch=math.atan2(direction[2],math.hypot(direction[0],direction[1]))
 # This fixture uses ideal reference servo, not the user's voltage/current motor loop.
 return Command(gimbal_yaw=yaw,gimbal_pitch=pitch,fire=bool(output.get('should_shoot',False)))
