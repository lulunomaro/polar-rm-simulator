"""Real MuJoCo, no-GL integration tests. No full match or frozen-run mutation."""
import math
import unittest
import mujoco
import numpy as np
from .protocol import ControlGate
from .server import BridgeState
from .runtime import OperatorRuntime
from .test_protocol import Clock


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock()
        self.state=BridgeState(ControlGate(wall=self.clock,monotonic=self.clock,session_id='runtime-synthetic'))
        self.runtime=OperatorRuntime(self.state,render=False)
        self.seq=0
    def tearDown(self):self.runtime.close()
    def send(self,**changes):
        self.seq+=1;g=self.state.gate
        value=dict(session_id=g.session_id,epoch=g.epoch,robot_id=g.robot_id,seq=self.seq,
            sent_at_ms=self.clock()*1000,focus=True,deadman=True,vx_mps=0.,vy_mps=0.,
            yaw_rate_rps=0.,pitch_rate_rps=0.,fire=False)
        value.update(changes)
        return g.accept(value)
    def tick(self,n=1):
        for _ in range(n):
            self.runtime.step_once();self.clock.advance(self.runtime.sim.model.opt.timestep)
    def test_no_input_never_substitutes_autonomous_drive_or_fire(self):
        self.tick(50)
        command=self.runtime.commands['red_infantry']
        self.assertEqual((command.force_x,command.force_y,command.yaw_torque,command.fire),(0.,0.,0.,False))
        for rid in ('blue_hero','blue_infantry','blue_sentry','red_hero','red_sentry'):
            self.assertIsNotNone(self.runtime.nav[rid].mode)
            nav=self.runtime.nav[rid].last_decision.command
            self.assertEqual(self.runtime.commands[rid].force_x,nav.force_x)
            self.assertEqual(self.runtime.commands[rid].force_y,nav.force_y)
    def test_human_motion_and_gimbal_advance_actual_physics(self):
        start=self.runtime._robot('red_infantry')
        for _ in range(3):self.send(vx_mps=1.,yaw_rate_rps=.5,pitch_rate_rps=.4);self.tick(50)
        final=self.runtime._robot('red_infantry')
        self.assertGreater(final['xy'][0],start['xy'][0]+.01)
        self.assertGreater(final['gimbal_yaw'],start['gimbal_yaw']+.01)
        self.assertGreater(self.runtime.pitch_target,.10)
    def test_stale_command_neutral_before_next_physics_step(self):
        self.send(vx_mps=1.,fire=True);self.tick()
        self.clock.advance(.3);self.tick()
        c=self.runtime.commands['red_infantry']
        self.assertEqual((c.force_x,c.force_y,c.yaw_torque,c.fire),(0.,0.,0.,False))
    def test_focus_loss_zero_drive_and_fire_then_fresh_rearm(self):
        self.send(vx_mps=1.,fire=True);self.tick()
        self.send(focus=False);self.tick()
        self.assertEqual(self.runtime.commands['red_infantry'].force_x,0.)
        self.assertFalse(self.runtime.commands['red_infantry'].fire)
        self.send(vx_mps=.5);self.tick()
        self.assertGreater(self.runtime.commands['red_infantry'].force_x,0.)
    def test_virtual_supply_and_human_shot_use_unmodified_judge(self):
        sim=self.runtime.sim
        self.assertEqual(sim.judge.robots['red_infantry'].ammo,0)
        self.tick(600)
        ammo=sim.judge.robots['red_infantry'].ammo
        self.assertGreater(ammo,0)
        self.assertEqual([p for p in sim.projectiles if p.owner=='red_infantry'],[])
        self.send(fire=True);self.tick()
        self.assertEqual(sim.judge.robots['red_infantry'].ammo,ammo-1)
        self.assertTrue(any(p.owner=='red_infantry' for p in sim.projectiles))
    def test_dead_robot_gates_input(self):
        self.runtime.sim.judge.robots['red_infantry'].hp=0
        self.send(vx_mps=1.,fire=True);self.tick()
        self.assertFalse(self.runtime.commands['red_infantry'].fire)
        self.assertEqual(self.runtime.commands['red_infantry'].force_x,0.)
    def test_camera_uses_separate_data_copy_without_stepping_world(self):
        sim=self.runtime.sim;copy=mujoco.MjData(sim.model)
        self.tick(5);before=sim.data.qpos.copy()
        observation,spheres,epoch=self.runtime._snapshot_for_camera(copy,'red_infantry')
        self.assertIsNot(copy,sim.data)
        np.testing.assert_array_equal(copy.qpos,before)
        copy.qpos[0]+=1
        np.testing.assert_array_equal(sim.data.qpos,before)
        self.assertEqual(observation.robot_id,'red_infantry')
        self.assertEqual(epoch,0)
    def test_telemetry_sources_and_roster_shape(self):
        self.tick(50);t=self.state.snapshot()
        self.assertEqual(t['map_source'],'simulator_truth_display_only')
        self.assertEqual(t['own']['robot_id'],'red_infantry')
        self.assertEqual(len(t['robots']),6)
        self.assertFalse(t['hardware_transport'])
        self.assertFalse(t['camera']['available'])
        self.assertTrue(t['camera']['first_person'])
    def test_epoch_change_drops_old_input(self):
        self.send(vx_mps=1.,fire=True);self.tick()
        self.state.gate.new_epoch('blue_infantry');self.tick()
        c=self.runtime.commands['blue_infantry']
        self.assertEqual((c.force_x,c.force_y,c.fire),(0.,0.,False))
        previous=self.runtime.commands['red_infantry']
        self.assertEqual((previous.force_x,previous.force_y,previous.fire),(0.,0.,False))


if __name__=='__main__':unittest.main()
