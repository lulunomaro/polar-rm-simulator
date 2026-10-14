"""Explicit offline clock/DTO contract. Never accepted by live v2 action gates."""
from dataclasses import dataclass,asdict
import copy
from .contracts import ContractError,exact,integer,string,validate_observation,validate_action,OBS_SCHEMA,ACTION_SCHEMA,IDENTITY,FRAMES,build_observation
PROFILE='offline_modeled_latency_v1'
OFF_OBS='polar.sim.observation.offline.v1'
OFF_ACTION='polar.sim.action.offline.v1'
SCHEDULE_KEYS=('episode_origin_mj_time_ns','exposure_ns','camera_capture_mj_time_ns','sensor_ready_ns','controller_sample_ns','own_sample_ns','result_available_ns','actuation_ns','sim_expiry_ns')

def ceil_grid(ns,step):return ((ns+step-1)//step)*step

@dataclass(frozen=True)
class OfflineClock:
 physics_step_ns:int
 capture_period_ns:int=40_000_000
 controller_period_ns:int=10_000_000
 sensor_delay_ns:int=10_000_000
 compute_delay_ns:int=10_000_000
 actuation_delay_ns:int=0
 max_age_ns:int=80_000_000
 def __post_init__(self):
  for k,v in asdict(self).items():integer(v,k,0 if k.endswith('delay_ns') else 1)
  if self.max_age_ns!=80_000_000:raise ContractError('native_age_bound_must_remain_80ms')
  if self.capture_period_ns%self.physics_step_ns or self.controller_period_ns%self.physics_step_ns:raise ContractError('period_not_on_physics_grid')
 def schedule(self,index,origin_ns):
  integer(index,'capture_index');integer(origin_ns,'episode_origin')
  exposure=index*self.capture_period_ns;ready=exposure+self.sensor_delay_ns
  sample=ceil_grid(ready,self.controller_period_ns);result=sample+self.compute_delay_ns
  return dict(episode_origin_mj_time_ns=origin_ns,exposure_ns=exposure,camera_capture_mj_time_ns=origin_ns+exposure,
   sensor_ready_ns=ready,controller_sample_ns=sample,own_sample_ns=sample,result_available_ns=result,
   actuation_ns=ceil_grid(result+self.actuation_delay_ns,self.physics_step_ns),sim_expiry_ns=exposure+self.max_age_ns)

def validate_schedule(s):
 exact(s,SCHEDULE_KEYS,'offline_schedule')
 for k,v in s.items():integer(v,k)
 if not s['exposure_ns']<=s['sensor_ready_ns']<=s['controller_sample_ns']<=s['result_available_ns']<=s['actuation_ns']:raise ContractError('nonmonotonic_offline_events')
 if s['own_sample_ns']!=s['controller_sample_ns'] or s['camera_capture_mj_time_ns']!=s['episode_origin_mj_time_ns']+s['exposure_ns']:raise ContractError('offline_sample_identity')
 if s['sim_expiry_ns']!=s['exposure_ns']+80_000_000:raise ContractError('offline_age_bound')
 return copy.deepcopy(s)

def _sensor_validation_view(o):
 # Validation-only projection. This zero is not a deadline, and this temporary
 # envelope is never scheduled or given to the live adapter/runtime.
 return dict(schema=OBS_SCHEMA,robot_id=o['robot_id'],episode=o['episode'],binding_epoch=o['binding_epoch'],observed_seq=o['observed_seq'],
  sim_time=o['schedule']['result_available_ns']/1e9,wall_deadline=0.,frames=o['frames'],own=o['own'],referee=o['referee'],sensors=o['sensors'])

def validate_offline_observation(o):
 exact(o,('schema','clock_profile','robot_id','episode','binding_epoch','observed_seq','schedule','frames','own','referee','sensors'),'offline_observation')
 if o['schema']!=OFF_OBS or o['clock_profile']!=PROFILE:raise ContractError('offline_profile_required')
 s=validate_schedule(o['schedule']);validate_observation(_sensor_validation_view(o))
 cam=o['sensors']['camera']
 if cam['available'] and round(cam['capture_sim_time']*1e9)!=s['exposure_ns']:raise ContractError('offline_camera_timestamp')
 ranges=o['sensors']['ranges']
 if ranges['available'] and round(ranges['capture_sim_time']*1e9)!=s['own_sample_ns']:raise ContractError('offline_own_timestamp')
 return copy.deepcopy(o)

def build_offline_observation(raw,camera,schedule,*,binding_epoch,observed_seq):
 s=validate_schedule(schedule)
 if not camera.get('available') or abs(camera.get('capture_sim_time',-1)*1e9-s['camera_capture_mj_time_ns'])>.5:raise ContractError('actual_camera_not_on_declared_exposure')
 base=build_observation(raw,binding_epoch=binding_epoch,observed_seq=observed_seq,wall_deadline=0.,camera=camera)
 if abs(raw.sim_time*1e9-(s['episode_origin_mj_time_ns']+s['own_sample_ns']))>.5:raise ContractError('actual_own_not_on_declared_tick')
 cam=base['sensors']['camera'];cam['capture_sim_time']=s['exposure_ns']/1e9
 if base['sensors']['ranges']['available']:base['sensors']['ranges']['capture_sim_time']=s['own_sample_ns']/1e9
 return validate_offline_observation(dict(schema=OFF_OBS,clock_profile=PROFILE,robot_id=base['robot_id'],episode=base['episode'],binding_epoch=binding_epoch,observed_seq=observed_seq,schedule=s,frames=base['frames'],own=base['own'],referee=base['referee'],sensors=base['sensors']))

def offline_action(o,command):
 return dict(schema=OFF_ACTION,clock_profile=PROFILE,**{k:o[k] for k in ('robot_id','episode','binding_epoch','observed_seq','schedule')},kind='aim',mode='gimbal_target',command=command)

def validate_offline_action(a,o):
 exact(a,('schema','clock_profile','robot_id','episode','binding_epoch','observed_seq','schedule','kind','mode','command'),'offline_action')
 string(a['robot_id'],'robot_id')
 for key in ('episode','binding_epoch','observed_seq'):integer(a[key],key)
 validate_schedule(a['schedule'])
 if a['schema']!=OFF_ACTION or a['clock_profile']!=PROFILE or any(a[k]!=o[k] for k in ('robot_id','episode','binding_epoch','observed_seq','schedule')):raise ContractError('offline_action_identity')
 if a['kind']!='aim' or a['mode']!='gimbal_target':raise ContractError('offline_aim_only')
 v=_sensor_validation_view(o);legacy=dict(schema=ACTION_SCHEMA,**{k:v[k] for k in IDENTITY},kind=a['kind'],mode=a['mode'],command=a['command'])
 validate_action(legacy,v,dict(kind='aim',output_modes=['gimbal_target']))
 if a['command']['fire_permission']:raise ContractError('offline_fire_disabled')
 return copy.deepcopy(a)
