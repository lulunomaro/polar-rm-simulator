"""CPU/noGL offline tests. Fake images/adapters are not live qualification."""
import copy
import threading
import time
import unittest
from .offline_contract import *
from .offline_runtime import OfflineRuntime,OfflineHalt
from .backend import MuJoCoBackend
from .camera import CameraProvider
from .test_camera import FakeRenderer
from .test_control import Clock
from .control import Rejected
from .test_contracts import sample

class SchedulingTests(unittest.TestCase):
 def test_exact_first_and_second(self):
  c=OfflineClock(2_000_000);a=c.schedule(0,18_000_000_000);b=c.schedule(1,18_000_000_000)
  self.assertEqual((a['exposure_ns'],a['own_sample_ns'],a['result_available_ns'],a['actuation_ns']),(0,10_000_000,20_000_000,20_000_000))
  self.assertEqual(a['camera_capture_mj_time_ns'],18_000_000_000);self.assertEqual(b['actuation_ns'],60_000_000)
 def test_no_fractional_steps_or_changed_age(self):
  for kw in ({'capture_period_ns':3},{'max_age_ns':100_000_000},{'compute_delay_ns':-1},{'sensor_delay_ns':True}):
   with self.assertRaises(ValueError):OfflineClock(2_000_000,**kw)
 def observation(self):
  o=sample(True);s=OfflineClock(2_000_000).schedule(0,0);cam=o['sensors']['camera'];cam['capture_sim_time']=0
  o['sensors']['ranges']['capture_sim_time']=.01
  return dict(schema=OFF_OBS,clock_profile=PROFILE,robot_id=o['robot_id'],episode=o['episode'],binding_epoch=o['binding_epoch'],observed_seq=o['observed_seq'],schedule=s,frames=o['frames'],own=o['own'],referee=o['referee'],sensors=o['sensors'])
 def test_live_and_offline_envelopes_not_interchangeable(self):
  o=self.observation();validate_offline_observation(o)
  with self.assertRaises(ValueError):validate_observation(o)
  with self.assertRaises(ValueError):validate_offline_observation(sample(True))
 def test_own_pose_must_not_be_restamped_at_result(self):
  o=self.observation();o['schedule']['own_sample_ns']=o['schedule']['result_available_ns']
  with self.assertRaises(ValueError):validate_offline_observation(o)
 def test_output_identity_and_fire_cannot_bypass(self):
  o=self.observation();a=offline_action(o,dict(frame='base_link',yaw_rad=.1,pitch_rad=.1,active=True,confidence=None,fire_permission=False));validate_offline_action(a,o)
  a['command']['fire_permission']=True
  with self.assertRaises(ValueError):validate_offline_action(a,o)
  a['command']['fire_permission']=False;a['schedule']=dict(a['schedule'],actuation_ns=40_000_000)
  with self.assertRaises(ValueError):validate_offline_action(a,o)


 def test_action_identity_rejects_python_equal_wrong_types(self):
  o=self.observation();good=offline_action(o,dict(frame='base_link',yaw_rad=.1,pitch_rad=.1,active=True,confidence=None,fire_permission=False))
  cases=[('episode',bool(o['episode'])),('binding_epoch',bool(o['binding_epoch'])),('observed_seq',float(o['observed_seq']))]
  for key,value in cases:
   a=copy.deepcopy(good);a[key]=value
   with self.subTest(key=key),self.assertRaises(ValueError):validate_offline_action(a,o)
  for key,value in [('exposure_ns',False),('result_available_ns',float(good['schedule']['result_available_ns']))]:
   a=copy.deepcopy(good);a['schedule'][key]=value
   with self.subTest(key=key),self.assertRaises(ValueError):validate_offline_action(a,o)
 def test_builder_rejects_camera_timestamp_relabel(self):
  from types import SimpleNamespace
  o=self.observation();camera=o['sensors']['camera'];s=OfflineClock(2_000_000).schedule(1,0)
  with self.assertRaisesRegex(ValueError,'actual_camera_not_on_declared_exposure'):
   build_offline_observation(SimpleNamespace(sim_time=.05),camera,s,binding_epoch=1,observed_seq=1)

class OfflineNativeTests(unittest.TestCase):
 def test_native_clock_exposure_and_delayed_own_are_distinct(self):
  from .test_native_adapter import NativeTests,FakeProcess
  from .offline_native import OfflineNativeAdapter
  from unittest.mock import patch
  helper=NativeTests();helper.setUp()
  try:
   a=OfflineNativeAdapter({},spec_path=helper.spec,out=helper.root/'offline')
   a.reset(dict(episode=1,robot_id='red_sentry',binding_epoch=1));FakeProcess.calls=[]
   def observation(index):
    live=helper.observation();s=OfflineClock(2_000_000).schedule(index,0);live['sensors']['camera'].update(capture_sim_time=s['exposure_ns']/1e9,frame_id=index+1)
    live['sensors']['ranges']['capture_sim_time']=s['own_sample_ns']/1e9
    return dict(schema=OFF_OBS,clock_profile=PROFILE,**{k:live[k] for k in ('robot_id','episode','binding_epoch','frames','own','referee','sensors')},observed_seq=index+1,schedule=s)
   with patch('rm_match.operator.source_aim.OperatorFovProcess',FakeProcess):
    a.act(observation(0));o=observation(11);v=a.act(o)
    self.assertTrue(v['command']['active']);self.assertFalse(v['command']['fire_permission'])
    packet=FakeProcess.calls[-1];self.assertEqual(packet['frame']['exposure_timestamp_ns'],440_000_000)
    self.assertEqual(v['schedule']['own_sample_ns'],450_000_000);self.assertEqual(v['schedule']['result_available_ns'],460_000_000)
    a.close()
  finally:helper.tearDown()

class TestAim:
 def reset(self,c):self.c=c
 def act(self,o):return offline_action(o,dict(frame='base_link',yaw_rad=.1,pitch_rad=.05,active=True,confidence=None,fire_permission=False))
 def close(self):pass

class OfflineRuntimeTests(unittest.TestCase):
 def make(self,**kw):
  clock=kw.pop('clock',time.monotonic);b=MuJoCoBackend(camera=True);cam=CameraProvider(b._sim,clock=clock,renderer_factory=FakeRenderer)
  r=OfflineRuntime(b,camera=cam,native_factory=TestAim,clock=clock,captures=2,**kw)
  t=r.control.open_session('operator')['token'];e=r.control.claim(t,'red_sentry',['gimbal'])['lease_epochs'];r.bind(t,'red_sentry','aim',e,'aim_native_rmcs_offline_v1',{})
  return r,b,cam,t,e
 def test_two_actual_physics_captures_complete_without_fire(self):
  rows=[];r,b,cam,t,e=self.make(trace=rows.append)
  try:
   r.run();self.assertEqual(r.state,'COMPLETED');self.assertEqual(r.completed_captures,2)
   events=[v for v in rows if v['event']=='offline_physics'];self.assertTrue(any(v['target']['gimbal'] for v in events));self.assertTrue(all(not v['target']['fire'] for v in events))
   self.assertAlmostEqual(b._sim.time,.062);self.assertEqual(r.tick,31);self.assertEqual(r.cached['clock_profile']['kind'],PROFILE);self.assertEqual(r.cached['offline_final_state'],'COMPLETED')
  finally:cam.wait_closed()
 def test_manual_fire_and_motion_not_admitted(self):
  r,b,cam,t,e=self.make()
  try:
   with self.assertRaises(Rejected):r.control.claim(t,'red_sentry',['motion'])
   with self.assertRaises(Rejected):r.control.control(t,'red_sentry','gimbal',e['gimbal'],1,{},.2)
  finally:r.close();cam.wait_closed()
 def test_modeled_delay_over_budget_halts_before_exposure_or_motion(self):
  r,b,cam,t,e=self.make(delays=OfflineClock(2_000_000,compute_delay_ns=100_000_000))
  try:r.run();self.assertEqual(r.state,'HALTED');self.assertEqual(r.halt_reason,'modeled_age_exceeded');self.assertEqual(r.tick,0);self.assertEqual(cam.sequence,0)
  finally:cam.wait_closed()
 def test_watchdog_while_waiting_does_not_advance_physics(self):
  clock=Clock()
  class Hung:
   def __init__(self,*a,**kw):pass
   def submit(self,o):pass
   def poll(self):clock.advance(.11);return None
   def close(self):pass
  r,b,cam,t,e=self.make(clock=clock,worker_factory=Hung,watchdog_s=.2)
  try:r.run();self.assertEqual(r.state,'HALTED');self.assertEqual(r.halt_reason,'native_barrier_wall_watchdog');self.assertEqual(r._ns(),10_000_000);self.assertEqual(r.cached['offline_halt_reason'],r.halt_reason)
  finally:cam.wait_closed()
 def test_wall_lease_expiry_while_barrier_halts(self):
  clock=Clock()
  class Hung:
   def __init__(self,*a,**kw):pass
   def submit(self,o):pass
   def poll(self):clock.advance(1.01);return None
   def close(self):pass
  r,b,cam,t,e=self.make(clock=clock,worker_factory=Hung)
  try:r.run();self.assertEqual(r.state,'HALTED');self.assertEqual(r.halt_reason,'lease_or_binding_changed');self.assertEqual(r._ns(),10_000_000)
  finally:cam.wait_closed()

if __name__=='__main__':unittest.main()
