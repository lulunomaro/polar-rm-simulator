"""Typed manual-spin contract; model capability is trusted cached metadata."""
import copy,math
from .control import Rejected,exact,finite

def parse_spin(value,capability):
 exact(value,('mode','frame','vx_mps','vy_mps','direction','speed_dps'))
 if value['mode']!='spin_v1' or value['frame']!='base_link':raise Rejected('invalid_spin_mode',400)
 if type(capability) is not dict or capability.get('available') is not True or type(capability.get('version')) is not int or capability['version']!=1:raise Rejected('spin_unavailable')
 if type(value['direction']) is not str or value['direction'] not in ('auto','cw','ccw'):raise Rejected('invalid_spin_direction',400)
 speed=finite(value['speed_dps'],'spin_speed')
 if not 120<=speed<=720:raise Rejected('spin_speed_limit',400)
 vx=finite(value['vx_mps'],'vx');vy=finite(value['vy_mps'],'vy')
 if abs(vx)>1 or abs(vy)>1:raise Rejected('spin_translation_limit',400)
 n=max(1.,math.hypot(vx,vy))
 return dict(mode='spin_v1',frame='base_link',vx_mps=vx/n,vy_mps=vy/n,direction=value['direction'],speed_dps=speed)

def motion_signature(value):
 return ('spin_v1',value['direction'],value['speed_dps']) if value.get('mode')=='spin_v1' else ('manual',)

def requested_yaw(value):
 if value.get('mode')=='spin_v1':return (-1. if value['direction']=='cw' else 1.)*value['speed_dps']*math.pi/180.
 return value['wz_rps']

def validate_mapping(value):
 """Only the currently supported unit-gain, unbounded-force hinge motor qualifies."""
 if type(value) is not dict:return False
 required=('joint_transmission','hinge_joint','own_qpos','own_dof','axis_positive_z','unit_gear','fixed_unit_gain','no_bias','no_dynamics','control_limited','no_force_limit')
 if any(value.get(k) is not True for k in required):return False
 try:lo=finite(value['ctrl_min'],'ctrl_min');hi=finite(value['ctrl_max'],'ctrl_max')
 except (Rejected,KeyError):return False
 return lo<0<hi

def capability(mapping):
 valid=validate_mapping(mapping)
 return dict(version=1,available=valid,directions=['auto','cw','ccw'],resolved_auto_direction='ccw',speed_min_dps=120.,speed_max_dps=720.,simulation_only=True,power_guard=False,world_stabilized_gimbal=False,reason='verified_loaded_yaw_motor' if valid else 'unsupported_yaw_actuator_mapping',yaw_torque_ctrlrange=[mapping['ctrl_min'],mapping['ctrl_max']] if valid else None)

def validate_capabilities(values,robot_ids):
 if type(values) is not dict or any(r not in robot_ids for r in values):raise ValueError('Invalid spin capability roster')
 result={}
 for rid,c in values.items():
  if type(c) is not dict or type(c.get('available')) is not bool or type(c.get('version')) is not int or c['version']!=1:raise ValueError('Invalid spin capability')
  if c['available']:
   if c.get('directions')!=['auto','cw','ccw'] or c.get('resolved_auto_direction')!='ccw' or c.get('simulation_only') is not True or c.get('power_guard') is not False or c.get('world_stabilized_gimbal') is not False:raise ValueError('Invalid spin semantics')
   if finite(c.get('speed_min_dps'),'speed_min')!=120 or finite(c.get('speed_max_dps'),'speed_max')!=720:raise ValueError('Invalid spin range')
   limits=c.get('yaw_torque_ctrlrange')
   if type(limits) is not list or len(limits)!=2 or not finite(limits[0],'torque_min')<0<finite(limits[1],'torque_max'):raise ValueError('Invalid spin actuator range')
  result[rid]=copy.deepcopy(c)
 return result
