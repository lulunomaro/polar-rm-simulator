"""Synthetic engine/backend guards and cached metadata, no MuJoCo integration."""
import copy,math,threading,unittest
from types import SimpleNamespace
from .runtime import PlatformRuntime
from .backend import MuJoCoBackend
from .test_runtime import FakeBackend,TestRegistry
from .test_control import Clock
from .test_spin import cap,spin

class GuardBackend(FakeBackend):
 def __init__(self,clock,expire=False):super().__init__(('alpha',));self.clock=clock;self.expire=expire
 def declared_spin_capabilities(self):return {'alpha':cap()}
 def guarded_step(self,targets,guard,clock):
  guard('alpha',None,'actuator');guard('alpha',None,'integration_entry',clock())
  if self.expire:self.clock.advance(.151)
  guard('alpha',None,'fire');self.targets=copy.deepcopy(targets);start=self.sim_time;self.sim_time+=self.timestep
  self.last_motion_feedback={'alpha':dict(integration_sim_time=start,timestep_seconds=self.timestep,sample_sim_time=self.sim_time,measurement_valid=True,spin_requested=targets['alpha']['motion'] is not None)}

class ReceiptTests(unittest.TestCase):
 def make(self,expire=False):
  clock=Clock();backend=GuardBackend(clock,expire);runtime=PlatformRuntime(backend,registry=TestRegistry(),clock=clock)
  token=runtime.control.open_session('operator','server_window_v1')['token'];epochs=runtime.control.claim(token,'alpha',['motion'])['lease_epochs'];window=runtime.control.control_window(token,'alpha',epochs)
  runtime.control.control(token,'alpha','motion',epochs['motion'],0,spin(),.15,window['window_id']);return runtime,token
 def test_entry_and_final_receipts_separate_on_late_fire_gate(self):
  r,t=self.make(True)
  try:
   r.step_once();audit=r.control.open_session('spectator')['token'];s=r.snapshot(audit);receipt=s['spin_consumption_receipts']['alpha']
   self.assertEqual(receipt['entry']['phase'],'integration_entry');self.assertEqual(receipt['entry']['target']['motion']['mode'],'spin_v1')
   self.assertEqual(receipt['final']['phase'],'fire');self.assertIsNone(receipt['final']['target']['motion']);self.assertIsNone(s['applied_targets']['alpha']['motion']);self.assertFalse(s['motion_feedback']['alpha']['spin_requested'])
  finally:r.close()
 def test_fresh_receipts_share_same_step_identity(self):
  r,t=self.make()
  try:
   r.step_once();audit=r.control.open_session('spectator')['token'];s=r.snapshot(audit);q=s['spin_consumption_receipts']['alpha'];self.assertEqual(q['entry']['target'],q['final']['target']);self.assertEqual(q['entry']['consume_sim_time'],q['final']['consume_sim_time']);self.assertEqual(s['motion_feedback']['alpha']['sample_sim_time'],s['sim_time'])
  finally:r.close()
 def test_http_capability_path_never_reenters_backend(self):
  r,t=self.make()
  try:
   r.backend.declared_spin_capabilities=lambda:(_ for _ in ()).throw(AssertionError('HTTP backend read'))
   values=[];th=threading.Thread(target=lambda:values.append(r.capabilities(t)));th.start();th.join(1)
   self.assertFalse(th.is_alive());self.assertTrue(values[0]['robots'][0]['spin_control']['available'])
   values[0]['robots'][0]['spin_control']['available']=False;self.assertTrue(r.capabilities(t)['robots'][0]['spin_control']['available'])
  finally:r.close()

class BackendTests(unittest.TestCase):
 def test_torque_formula_and_poststep_metadata_with_synthetic_engine(self):
  import numpy as np
  from ..contracts import Command
  b=MuJoCoBackend.__new__(MuJoCoBackend);b.robot_ids=('a',);b.timestep=.002;b._authority=None;b._resupply=SimpleNamespace(apply=lambda *_:None);b._gimbal_hold={};b._gimbal_was_active={'a':False}
  q=np.zeros(5);v=np.zeros(5);s=SimpleNamespace(time=1.,episode=0,model=SimpleNamespace(actuator_ctrlrange=np.array([[-60,60],[-60,60],[-20,20],[-3,3],[-1,1]])),data=SimpleNamespace(qpos=q,qvel=v,actuator_force=np.zeros(5)),qindices={'a':list(range(5))},vindices={'a':list(range(5))},aindices={'a':list(range(5))},commands={})
  def step(commands,command_guard=None,integration_clock=None):
   s.commands=commands;s.data.actuator_force[2]=commands['a'].yaw_torque;s.data.qvel[2]=.123;s.time+=.002
  s.step=step;b._sim=s;b.allowed=lambda _:True
  b.step({'a':dict(motion=spin(),gimbal=None,fire=False)})
  self.assertEqual(s.commands['a'].yaw_torque,20.);m=b.last_motion_feedback['a'];self.assertEqual(m['integration_sim_time'],1.);self.assertEqual(m['sample_sim_time'],1.002);self.assertEqual(m['measured_yaw_rate_rps'],.123);self.assertEqual(m['applied_yaw_torque_nm'],20.);self.assertTrue(m['saturated']);self.assertAlmostEqual(m['target_yaw_rate_rps'],420*math.pi/180)
if __name__=='__main__':unittest.main()
