"""Exposure-age propagation and explicit clock-rate regressions; no GL/native."""
import copy
import unittest
from .runtime import PlatformRuntime
from .test_runtime import FakeBackend,TestRegistry
from .test_control import Clock
from .backend import MuJoCoBackend
from ..contracts import Command

class BudgetTests(unittest.TestCase):
 def test_budget_does_not_accept_clock_regression_or_boundary(self):
  b=dict(capture_wall=1.,wall_deadline=1.2,capture_sim_time=2.,sim_deadline=2.08)
  self.assertTrue(PlatformRuntime._budget_valid(b,1.199,2.08))
  for wall,sim in [(1.2,2.),(.99,2.),(1.1,1.99),(1.1,2.081)]:
   self.assertFalse(PlatformRuntime._budget_valid(b,wall,sim))
 def test_explicit_rate_rejects_invalid_values_without_advancing(self):
  for rate in (0,-1,1.1,float('inf'),float('nan')):
   b=FakeBackend();r=PlatformRuntime(b,registry=TestRegistry())
   with self.assertRaises(ValueError):r.run(max_wall_seconds=.01,real_time_factor=rate)
   self.assertEqual(b.sim_time,0.)
 def test_engine_guard_none_preserves_default_commands(self):
  b=MuJoCoBackend();rid='red_sentry'
  try:
   targets={r:dict(motion=None,gimbal=None,fire=False) for r in b.robot_ids}
   targets[rid]['gimbal']=dict(yaw_rad=.2,pitch_rad=.1)
   b.step(copy.deepcopy(targets))
   self.assertAlmostEqual(b._sim.data.ctrl[b._sim.aindices[rid][3]],.2)
   self.assertAlmostEqual(b._sim.data.ctrl[b._sim.aindices[rid][4]],.1)
  finally:b.close()
 def test_second_guard_can_revoke_after_first_guard_accepted(self):
  b=MuJoCoBackend();rid='red_sentry';calls=[]
  try:
   targets={r:dict(motion=None,gimbal=None,fire=False) for r in b.robot_ids}
   targets[rid]['gimbal']=dict(yaw_rad=.2,pitch_rad=.1)
   def guard(r,c,phase,sampled_wall=None):
    calls.append((r,phase));old=targets[r]
    if phase in ('integration','integration_entry'):return dict(motion=None,gimbal=None,fire=False)
    return old
   b.guarded_step(targets,guard)
   self.assertEqual(b._sim.data.ctrl[b._sim.aindices[rid][3]],0.)
   self.assertEqual(b._sim.data.ctrl[b._sim.aindices[rid][4]],0.)
   self.assertIn((rid,'actuator'),calls);self.assertIn((rid,'integration'),calls)
  finally:b.close()

class UniformEntryTests(unittest.TestCase):
 def test_uniform_entry_clock_gap_revokes_real_control_and_display(self):
  from .contracts import build_observation,action_for
  clock=Clock();b=MuJoCoBackend();r=PlatformRuntime(b,clock=clock,registry=TestRegistry());r._episode=b.episode;r._schedule=lambda *_:None
  rid='red_sentry';c=r.control;t=c.open_session('operator')['token'];e=c.claim(t,rid,['gimbal'])['lease_epochs'];r.bind(t,rid,'aim',e,'aim',{})
  binding=c.snapshot()['bindings'][rid]['aim'];q=b._sim.data.qpos[b._sim.qindices[rid]].copy()
  o=build_observation(b.sensor_sample(rid),binding_epoch=binding['epoch'],observed_seq=1,wall_deadline=clock()+.03)
  r.outputs[rid,'aim']=action_for(o,'aim','gimbal_target',dict(frame='base_link',yaw_rad=.2,pitch_rad=.1,active=True,confidence=None,fire_permission=False))
  r.output_budgets[rid,'aim']=dict(robot_id=rid,episode=b.episode,frame_id=1,capture_wall=clock()-.17,capture_sim_time=b.sim_time,wall_deadline=clock()+.03,sim_deadline=b.sim_time+.08)
  original=b.guarded_step
  def delayed(targets,guard,**kwargs):
   source=kwargs['clock'];seen=False
   def entry_clock():
    nonlocal seen
    if not seen:clock.advance(.031);seen=True
    return source()
   return original(targets,guard,clock=entry_clock)
  b.guarded_step=delayed
  try:
   r.step_once()
   self.assertAlmostEqual(b._sim.data.ctrl[b._sim.aindices[rid][3]],q[3])
   self.assertIsNone(r.cached['applied_targets'][rid]['gimbal'])
   self.assertAlmostEqual(b.last_commands[rid]['gimbal_yaw'],q[3])
   self.assertGreater(b.last_integration_timing['integration_start_wall'],o['wall_deadline'])
  finally:r.close()

if __name__=='__main__':unittest.main()
