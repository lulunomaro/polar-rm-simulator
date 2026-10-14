"""Real MuJoCo without rendering: selected manual packets can expire in preparation."""
import unittest
from .backend import MuJoCoBackend
from .runtime import PlatformRuntime
from .test_control import Clock

class ConsumptionTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.b=MuJoCoBackend(camera=False);self.r=PlatformRuntime(self.b,clock=self.clock)
        self.r.step_once();self.rid='red_sentry';self.s=self.r.control.open_session('operator','server_window_v1');self.t=self.s['token'];self.e=self.r.control.claim(self.t,self.rid,['motion','gimbal','fire'])['lease_epochs'];self.w=self.r.control.control_window(self.t,self.rid,self.e)
        for c,v in [('motion',dict(frame='base_link',vx_mps=.5,vy_mps=0.,wz_rps=0.)),('gimbal',dict(frame='base_link',yaw_rad=.2,pitch_rad=.1)),('fire',dict(fire=True))]:self.r.control.control(self.t,self.rid,c,self.e[c],0,v,.25,self.w['window_id'])
        self.q=self.b._sim.data.qpos[self.b._sim.qindices[self.rid]].copy();self.ammo=self.b._sim.judge.robots[self.rid].ammo;self.heat=self.b._sim.judge.robots[self.rid].heat;self.shots=self.b._sim.projectile_counter
    def tearDown(self):self.r.close()
    def assert_neutral(self):
        s=self.b._sim;self.assertTrue(all(s.data.ctrl[s.aindices[self.rid][i]]==0. for i in range(3)));self.assertAlmostEqual(float(s.data.ctrl[s.aindices[self.rid][3]]),self.q[3]);self.assertFalse(self.b.last_commands[self.rid]['fire']);self.assertEqual(s.judge.robots[self.rid].ammo,self.ammo);self.assertEqual(s.judge.robots[self.rid].heat,self.heat);self.assertEqual(s.projectile_counter,self.shots);self.assertIsNone(self.r.cached['applied_targets'][self.rid]['motion'])
    def test_fresh_reaches_actuator_with_original_window_receipt(self):
        self.r.step_once();s=self.b._sim;self.assertGreater(float(s.data.ctrl[s.aindices[self.rid][0]]),0.);self.assertAlmostEqual(float(s.data.ctrl[s.aindices[self.rid][3]]),.2)
        receipt=self.r.cached['manual_consumption_receipts'][self.rid];self.assertEqual(receipt['phase'],'fire');self.assertEqual(receipt['manual_inputs']['gimbal']['input_window_deadline'],self.w['expires_wall']);self.assertLess(receipt['consume_wall'],self.w['expires_wall'])
    def test_after_selection_before_backend_consumption(self):
        real=self.b._resupply.apply
        def delay(*a,**kw):self.clock.now=self.w['expires_wall'];return real(*a,**kw)
        self.b._resupply.apply=delay;self.r.step_once();self.assert_neutral()
    def test_after_actuator_write_before_integration(self):
        real=self.b.guarded_step
        def delayed(targets,guard,**kwargs):
            def wrapped(rid,command,phase,sampled_wall=None):
                result=guard(rid,command,phase,sampled_wall)
                if rid==self.rid and phase=='actuator':self.clock.now=self.w['expires_wall']
                return result
            return real(targets,wrapped,**kwargs)
        self.b.guarded_step=delayed;self.r.step_once();self.assert_neutral()
    def test_final_uniform_entry_rechecks_deadline(self):
        real=self.b.guarded_step
        def delayed(targets,guard,**kwargs):
            calls=[0]
            def wrapped(rid,command,phase,sampled_wall=None):
                result=guard(rid,command,phase,sampled_wall)
                if phase=='integration':calls[0]+=1
                return result
            def clock():
                if calls[0]>=len(self.b.robot_ids):self.clock.now=self.w['expires_wall']
                return self.clock()
            return real(targets,wrapped,clock=clock)
        self.b.guarded_step=delayed;self.r.step_once();self.assert_neutral()

    def test_release_after_uniform_entry_before_fire(self):
        real=self.b.guarded_step
        def delayed(targets,guard,**kwargs):
            def wrapped(rid,command,phase,sampled_wall=None):
                result=guard(rid,command,phase,sampled_wall)
                if rid==self.rid and phase=='integration_entry':self.r.control.release(self.t,self.rid,self.e)
                return result
            return real(targets,wrapped,**kwargs)
        self.b.guarded_step=delayed;self.r.step_once();self.assert_neutral()
    def test_epoch_change_after_uniform_entry_before_fire(self):
        real=self.b.guarded_step
        def delayed(targets,guard,**kwargs):
            def wrapped(rid,command,phase,sampled_wall=None):
                result=guard(rid,command,phase,sampled_wall)
                if rid==self.rid and phase=='integration_entry':self.r.control.reset_episode()
                return result
            return real(targets,wrapped,**kwargs)
        self.b.guarded_step=delayed;self.r.step_once();self.assert_neutral()
    def test_held_fire_does_not_duplicate_discrete_projectile(self):
        self.r.step_once();self.assertEqual(self.b._sim.projectile_counter,self.shots+1)
        self.r.step_once();self.assertEqual(self.b._sim.projectile_counter,self.shots+1)
        self.clock.now=self.w['expires_wall'];self.r.step_once()
        self.assertEqual(self.b._sim.projectile_counter,self.shots+1);self.assertFalse(self.b.last_commands[self.rid]['fire'])
    def test_final_fire_consumption_expiry_has_no_discrete_side_effect(self):
        real=self.b.guarded_step
        def delayed(targets,guard,**kwargs):
            def wrapped(rid,command,phase,sampled_wall=None):
                if rid==self.rid and phase=='fire':self.clock.now=self.w['expires_wall']
                return guard(rid,command,phase,sampled_wall)
            return real(targets,wrapped,**kwargs)
        self.b.guarded_step=delayed;self.r.step_once();self.assert_neutral()

class LegacyNumericalEquivalence(unittest.TestCase):
    def test_fresh_guard_matches_unguarded_physics_and_fire(self):
        import numpy as np
        from ..match_engine import MatchSimulation
        from ..contracts import Command
        a=MatchSimulation(render=False);b=MatchSimulation(render=False)
        try:
            commands={r:Command(force_x=3.,gimbal_yaw=.1,gimbal_pitch=.02,fire=r=='red_sentry') for r in a.robot_ids}
            for _ in range(5):
                a.step(commands);b.step(commands,command_guard=lambda rid,c,phase,sampled_wall=None:c,integration_clock=lambda:1000.)
                np.testing.assert_array_equal(a.data.qpos,b.data.qpos);np.testing.assert_array_equal(a.data.qvel,b.data.qvel);np.testing.assert_array_equal(a.data.ctrl,b.data.ctrl)
                self.assertEqual(a.projectile_counter,b.projectile_counter)
                for rid in a.robot_ids:
                    self.assertEqual(a.judge.robots[rid].hp,b.judge.robots[rid].hp);self.assertEqual(a.judge.robots[rid].ammo,b.judge.robots[rid].ammo);self.assertEqual(a.judge.robots[rid].heat,b.judge.robots[rid].heat)
                self.assertEqual(len(a.projectiles),len(b.projectiles))
                for x,y in zip(a.projectiles,b.projectiles):
                    self.assertEqual(x.uid,y.uid);np.testing.assert_array_equal(x.position,y.position);np.testing.assert_array_equal(x.velocity,y.velocity)
        finally:a.close();b.close()

if __name__=='__main__':unittest.main()
