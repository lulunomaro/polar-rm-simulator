"""Single-vehicle deterministic offline/SIL profile; HTTP wall authority stays live.

This profile is explicitly opt-in and cannot consume ordinary live v2 actions.
A wall barrier never holds the control lock or advances simulation time.
"""
from dataclasses import asdict
import copy
import queue
import threading
import time
from .runtime import PlatformRuntime
from .control import ControlPlane,Rejected
from .contracts import ContractError
from .offline_contract import OfflineClock,PROFILE,build_offline_observation,validate_offline_action
from .adapters import Registry,descriptor

class OfflineHalt(RuntimeError):pass

class OfflineControlPlane(ControlPlane):
 def __init__(self,*a,selected_robot,**kw):super().__init__(*a,**kw);self.selected_robot=selected_robot
 def claim(self,token,rid,channels):
  with self.lock:self._session(token,operator=True)
  if rid!=self.selected_robot or channels!=['gimbal']:raise Rejected('offline_gimbal_algorithm_lease_only',403)
  return super().claim(token,rid,channels)
 def control(self,*a,**kw):raise Rejected('offline_wall_manual_input_disabled',403)

class OfflineWorker:
 """One fixed worker, one outstanding request. A hang cannot create new slots."""
 def __init__(self,factory,context,*,host_delay_s=0.,clock=time.monotonic,trace=None):
  self.factory=factory;self.context=context;self.delay=host_delay_s;self.clock=clock;self.trace=trace
  self.jobs=queue.Queue(maxsize=1);self.results=queue.Queue(maxsize=1);self.stop=threading.Event()
  self.thread=threading.Thread(target=self._run,name='offline-native-worker',daemon=True);self.thread.start()
 def _run(self):
  instance=None
  try:
   instance=self.factory();instance.reset(self.context)
   while not self.stop.is_set():
    try:o=self.jobs.get(timeout=.02)
    except queue.Empty:continue
    started=self.clock()
    if self.delay and self.stop.wait(self.delay):return
    try:value=instance.act(copy.deepcopy(o));error=None
    except BaseException as e:value=None;error=type(e).__name__+':'+str(e)
    if self.trace:self.trace(dict(event='offline_worker',wall_start=started,wall_end=self.clock(),host_delay_s=self.delay,observed_seq=o['observed_seq']))
    self.results.put((value,error))
    if error:return
  except BaseException as e:
   try:self.results.put_nowait((None,type(e).__name__+':'+str(e)))
   except queue.Full:pass
  finally:
   if instance is not None:
    try:instance.close()
    except BaseException:pass
 def submit(self,o):self.jobs.put_nowait(o)
 def poll(self):
  try:return self.results.get_nowait()
  except queue.Empty:return None
 def close(self):self.stop.set()

class OfflineRuntime(PlatformRuntime):
 def __init__(self,backend,*,camera,selected_robot='red_sentry',native_factory,clock=time.monotonic,
              delays=None,captures=24,host_delay_s=0.,watchdog_s=5.,trace=None,worker_factory=OfflineWorker):
  if selected_robot not in backend.robot_ids:raise ValueError('Unknown selected vehicle')
  if type(captures) is not int or not 1<=captures<=1000:raise ValueError('Bounded capture count required')
  if not 0<=host_delay_s<=1 or not 0<watchdog_s<=5:raise ValueError('Bounded wall delay/watchdog required')
  step_ns=round(backend.timestep*1e9)
  if step_ns<=0 or abs(step_ns/1e9-backend.timestep)>1e-15:raise ValueError('Timestep not representable in integer ns')
  self.timeline=delays or OfflineClock(step_ns)
  if self.timeline.physics_step_ns!=step_ns:raise ValueError('Offline grid must match actual model')
  reg=Registry();reg.register(descriptor('aim_native_rmcs_offline_v1','aim','OFFLINE/SIL native source; separate modeled clock',('camera','odometry'),clock_profile=PROFILE,supported_robots=[selected_robot],stationary_only=True,max_camera_age_sim_s=.08),lambda config:None)
  control=OfflineControlPlane(backend.robot_ids,selected_robot=selected_robot,clock=clock)
  super().__init__(backend,registry=reg,control=control,clock=clock,camera=camera,trace=trace)
  self.selected_robot=selected_robot;self.native_factory=native_factory;self.capture_limit=captures;self.host_delay=host_delay_s;self.watchdog=watchdog_s;self.worker_factory=worker_factory
  self.attempt_deadline=None;self.worker=None;self.tick=0;self.origin_ns=None;self.binding=None;self.offline_output=None;self.state='waiting_for_binding';self.halt_reason=None;self.capture_index=-1;self.completed_captures=0
 def bind(self,token,robot_id,kind,lease_epochs,adapter_id,config):
  if kind!='aim' or adapter_id!='aim_native_rmcs_offline_v1' or robot_id!=self.selected_robot or config!={}:raise Rejected('offline_fixed_native_binding_only',400)
  return super().bind(token,robot_id,kind,lease_epochs,adapter_id,config)
 def watch(self,token,rid):
  if rid is not None and rid!=self.selected_robot:raise Rejected('offline_single_camera_qualification',409)
  return super().watch(token,rid)
 def _ns(self):
  expected=self.origin_ns+self.tick*self.timeline.physics_step_ns
  # Tick is authoritative; floating mjData.time is cross-checked within half ns.
  if abs(self.backend.sim_time*1e9-expected)>.5:raise OfflineHalt('physics_tick_clock_mismatch')
  return self.tick*self.timeline.physics_step_ns
 def _same_binding(self):
  if self.stop_event.is_set() or self.control.stopped:raise OfflineHalt('stop_requested')
  if self.attempt_deadline is not None and self.clock()>=self.attempt_deadline:raise OfflineHalt('attempt_wall_watchdog')
  if self.backend.episode!=self._episode:raise OfflineHalt('episode_changed')
  snap=self.control.snapshot();b=snap['bindings'][self.selected_robot]['aim']
  if self.binding is None:return snap
  if (b['owner'],b['epoch'],b['lease_epochs'])!=(self.binding['owner'],self.binding['epoch'],self.binding['lease_epochs']):raise OfflineHalt('lease_or_binding_changed')
  if not self.backend.allowed(self.selected_robot):raise OfflineHalt('referee_or_alive_gate')
  pose=self.backend.own_pose(self.selected_robot)
  if abs(pose['wz'])>.03 or (pose['vx']**2+pose['vy']**2)**.5>.03:raise OfflineHalt('stationary_required')
  return snap
 def _targets_offline(self):
  snap=self._same_binding();lease=snap['leases'][self.selected_robot]['gimbal']
  self.last_authority_receipt=dict(checked_wall=snap['server_monotonic_s'],owner_present=lease['owner'] is not None,lease_epoch=lease['epoch'],expires_wall=lease['expires'],binding_epoch=self.binding['epoch'],observed_seq=self.offline_output['observed_seq'] if self.offline_output else None)
  result={r:dict(motion=None,gimbal=None,fire=False) for r in self.backend.robot_ids}
  a=self.offline_output
  if a is not None:
   ns=self._ns();s=a['schedule']
   if a['episode']!=self._episode or a['binding_epoch']!=self.binding['epoch']:raise OfflineHalt('output_generation_changed')
   if s['actuation_ns']<=ns<=s['sim_expiry_ns'] and a['command']['active']:
    if not self.backend.validate_target(self.selected_robot,'gimbal',a['command']):raise OfflineHalt('robot_limit_rejected')
    result[self.selected_robot]['gimbal']=a['command']
  return result
 def _publish(self,targets=None):
  value=self.backend.display_snapshot();self._ns()
  value.update(runtime_state='running' if self.state!='HALTED' else 'halted',telemetry_available=True,
   clock_profile=dict(kind=PROFILE,label='OFFLINE / SIL',barrier_state=self.state,episode_origin_mj_time_ns=self.origin_ns,simulation_tick=self.tick,simulation_ns=self._ns(),delays=asdict(self.timeline),delays_are_engineering_configuration_not_device_calibration=True,host_delay_s=self.host_delay,wall_elapsed_s=self.clock()-self._started),
   applied_targets=copy.deepcopy(targets or {r:dict(motion=None,gimbal=None,fire=False) for r in self.backend.robot_ids}),
   algorithm_status={r:{'navigation':'unsupported_offline','aim':self.state if r==self.selected_robot else 'unbound'} for r in self.backend.robot_ids},
   offline_halt_reason=self.halt_reason,completed_captures=self.completed_captures)
  if self.camera is not None:value['camera']=self.camera.status()
  with self.cache_lock:self.cached=value
 def _advance_to(self,ns):
  if ns%self.timeline.physics_step_ns or ns<self._ns():raise OfflineHalt('invalid_event_grid')
  while self._ns()<ns:
   targets=self._targets_offline();receipt={};before=self._ns();q0=self.backend._sim.data.qpos[self.backend._sim.qindices[self.selected_robot]].tolist()
   def guard(rid,command,phase,sampled_wall=None):
    checked=self._targets_offline()[rid];targets[rid]=checked
    if rid==self.selected_robot and phase=='integration_entry':receipt.update(self.last_authority_receipt,sampled_integration_wall=sampled_wall)
    return checked
   self.backend.guarded_step(targets,guard,clock=self.clock);self.tick+=1;self.steps+=1;self._ns()
   self._trace('offline_physics',sim_apply_ns=before,episode=self._episode,robot_id=self.selected_robot,binding_epoch=self.binding['epoch'],target=targets[self.selected_robot],source_schedule=self.offline_output['schedule'] if self.offline_output else None,
    authority_receipt=receipt,qpos_before=q0,qpos_after=self.backend._sim.data.qpos[self.backend._sim.qindices[self.selected_robot]].tolist(),actuator_ctrl=self.backend._sim.data.ctrl[self.backend._sim.aindices[self.selected_robot]].tolist(),**self.backend.last_integration_timing)
   self._publish(targets)
 def _wait(self,poll,stage):
  start=self.clock();self.state=stage;self._publish()
  while True:
   self._same_binding()
   if self.clock()-start>=self.watchdog:raise OfflineHalt(stage+'_wall_watchdog')
   value=poll()
   if value is not None:
    if self.clock()-start>=self.watchdog:raise OfflineHalt(stage+'_wall_watchdog')
    self._same_binding();return value
   self.stop_event.wait(.005)
 def _camera_event(self,s):
  sim=self.backend._sim;rid=self.selected_robot;consumer=self._camera_binding(rid,'aim',self.binding)
  desired=self._camera_desired(self.control.snapshot());desired={rid:desired.get(rid,{consumer})}
  # Explicit scheduled capture, only in this offline authority. Provider clock
  # remains real monotonic; image timestamps and cache ages are never refreshed.
  with self.camera.lock:self.camera.next_capture=0.;before=self.camera.sequence
  self.camera.capture_from_authority(sim,desired)
  with self.camera.lock:expected=self.camera.sequence
  if expected!=before+1:raise OfflineHalt('scheduled_capture_not_created')
  self._trace('offline_capture',robot_id=rid,episode=self._episode,frame_id=expected,schedule=s)
  def poll():
   with self.camera.lock:
    if self.camera.error:raise OfflineHalt('camera_error:'+self.camera.error)
    v=self.camera.cache.get(rid)
    if v is None or v['capture'].frame_seq!=expected:return None
    cap=v['capture']
    if cap.robot_id!=rid or cap.episode!=self._episode or consumer not in cap.consumers:raise OfflineHalt('camera_identity_changed')
    if abs(cap.sim_time*1e9-s['camera_capture_mj_time_ns'])>.5:raise OfflineHalt('exposure_tick_mismatch')
    camera=v['camera']
    if camera['frame_id']!=cap.frame_seq or abs(camera['capture_sim_time']-cap.sim_time)>5e-10 or any(camera[k]!=val for k,val in cap.own.items()):raise OfflineHalt('camera_payload_capture_mismatch')
    return copy.deepcopy(camera)
  return self._wait(poll,'camera_barrier')
 def run(self,*,max_wall_seconds=90.):
  if type(max_wall_seconds) not in (int,float) or not 0<max_wall_seconds<=90:raise ValueError('Attempt wall bound must be within (0,90]')
  self.attempt_deadline=self.clock()+max_wall_seconds
  self._check_authority();self._episode=self.backend.episode;self.origin_ns=round(self.backend.sim_time*1e9);self._started=self.clock();self._ns();self._publish()
  try:
   while self.binding is None:
    self._same_binding()
    if self.clock()-self._started>self.watchdog:raise OfflineHalt('initial_binding_wall_watchdog')
    b=self.control.snapshot()['bindings'][self.selected_robot]['aim']
    if b['owner'] is not None:self.binding=copy.deepcopy(b);break
    self.stop_event.wait(.005)
   context=dict(robot_id=self.selected_robot,episode=self._episode,binding_epoch=self.binding['epoch'])
   self.worker=self.worker_factory(self.native_factory,context,host_delay_s=self.host_delay,clock=self.clock,trace=self.trace)
   for index in range(self.capture_limit):
    if self.clock()-self._started>=max_wall_seconds:raise OfflineHalt('attempt_wall_watchdog')
    self.capture_index=index;s=self.timeline.schedule(index,self.origin_ns)
    if s['actuation_ns']>s['sim_expiry_ns']:raise OfflineHalt('modeled_age_exceeded')
    self.state='advancing_to_capture';self._advance_to(s['exposure_ns'])
    camera=self._camera_event(s)
    self.state='advancing_to_controller_sample';self._advance_to(s['controller_sample_ns'])
    raw=self.backend.sensor_sample(self.selected_robot)
    o=build_offline_observation(raw,camera,s,binding_epoch=self.binding['epoch'],observed_seq=index+1)
    self._trace('offline_observation',robot_id=self.selected_robot,episode=self._episode,binding_epoch=self.binding['epoch'],observed_seq=index+1,schedule=s,frame_id=camera['frame_id'],own=o['own'])
    self.worker.submit(o);value,error=self._wait(self.worker.poll,'native_barrier')
    if error:raise OfflineHalt('native_error:'+error)
    action=validate_offline_action(value,o);self._same_binding()
    self.state='advancing_to_actuation';self._advance_to(s['actuation_ns']);self.offline_output=action
    self._trace('offline_action_available',action=action)
    self.state='applying';self._advance_to(s['actuation_ns']+self.timeline.physics_step_ns)
    self.completed_captures+=1;self._publish()
   self.state='COMPLETED';self._publish()
  except BaseException as e:
   self.halt_reason=str(e) if isinstance(e,OfflineHalt) else type(e).__name__+':'+str(e);self.state='HALTED';self.backend.neutralize();self.offline_output=None;self._publish()
   self._trace('offline_halt',reason=str(e),simulation_ns=self._ns())
  finally:
   if self.worker is not None:self.worker.close()
   self.close()
 def close(self):
  # Preserve the immutable offline label and terminal reason for observers;
  # base close still revokes all rights and neutralizes without advancing time.
  super().close()
  with self.cache_lock:
   self.cached.update(clock_profile=dict(kind=PROFILE,label='OFFLINE / SIL',barrier_state=self.state,
    episode_origin_mj_time_ns=self.origin_ns,simulation_tick=self.tick,
    simulation_ns=self.tick*self.timeline.physics_step_ns,delays=asdict(self.timeline),
    delays_are_engineering_configuration_not_device_calibration=True,host_delay_s=self.host_delay,
    wall_elapsed_s=self.clock()-self._started),offline_halt_reason=self.halt_reason,
    offline_final_state=self.state,completed_captures=self.completed_captures)
