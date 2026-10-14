"""CPU regressions for rejected requests and cached physical sample identity."""
from dataclasses import asdict
import json
import math
import unittest
import numpy as np
from . import test_runtime as runtime_fixture
from . import test_protocol as http_fixture
from .test_modes import mode
from .protocol import OperatorInput
from .server import start_server

class ModeSafetyTests(unittest.TestCase):
    setUp=runtime_fixture.RuntimeTests.setUp
    tearDown=runtime_fixture.RuntimeTests.tearDown
    send=runtime_fixture.RuntimeTests.send
    tick=runtime_fixture.RuntimeTests.tick
    def active_sample(self):
        self.assertTrue(self.send(mode_request=mode(), fire=True)['accepted'])
        self.tick()
        self.runtime._publish()
        self.assertTrue(self.state.snapshot()['operator_modes']['effective']['spin_enabled'])
    def test_explicit_null_aim_clears_fire_spin_and_motion(self):
        self.active_sample()
        ack=self.send(aim_request=None, mode_request=mode(), fire=True, vx_mps=1.)
        self.assertFalse(ack['accepted'])
        self.assertEqual(self.state.gate.sample(),OperatorInput())
        self.assertFalse(self.state.gate.active_mode.spin_enabled)
    def test_absent_aim_preserves_legacy_manual_input(self):
        self.assertTrue(self.send(fire=True)['accepted'])
        self.assertTrue(self.state.gate.sample().fire)
    def test_timeout_clears_effective_but_preserves_measured_sample(self):
        self.active_sample();before=self.state.snapshot()
        cached=self.state.telemetry['operator_modes']['effective']['spin_enabled']
        self.clock.advance(.3);after=self.state.snapshot()
        self.assertFalse(after['operator_modes']['effective']['spin_enabled'])
        self.assertIsNone(after['operator_modes']['effective_seq'])
        self.assertEqual(after['operator_modes']['reason'],'control_timeout')
        self.assertEqual(after['operator_modes']['measured'],before['operator_modes']['measured'])
        self.assertEqual(after['operator_modes']['measurement_sim_time'],before['sim_time'])
        self.assertEqual(after['applied_command_sim_time'],before['sim_time'])
        self.assertEqual(self.state.telemetry['operator_modes']['effective']['spin_enabled'],cached)
    def test_blur_clears_effective_before_next_physics_tick(self):
        self.active_sample();self.send(mode_request=mode(), focus=False)
        self.assertFalse(self.state.snapshot()['operator_modes']['effective']['spin_enabled'])
    def test_epoch_robot_change_never_relabels_old_physical_sample(self):
        self.active_sample();self.state.gate.new_epoch('blue_infantry')
        self.runtime.next_publish_time = self.runtime.sim.time + 10.
        self.runtime.next_publish_wall = float('inf')
        self.runtime._publish()  # A publish alone is not a current control sample.
        t=self.state.snapshot();self.assertFalse(t['telemetry_available'])
        self.assertEqual(t['robot_id'],'blue_infantry');self.assertEqual(t['epoch'],1)
        self.assertIsNone(t['own']);self.assertIsNone(t['operator_modes'])
        self.tick();t=self.state.snapshot()
        self.assertFalse(t['telemetry_available'])  # Before the next due publish.
        self.runtime._publish();t=self.state.snapshot()
        self.assertTrue(t['telemetry_available']);self.assertEqual(t['own']['robot_id'],'blue_infantry')
        self.assertFalse(t['operator_modes']['effective']['spin_enabled'])
    def test_same_robot_new_epoch_is_also_not_ready(self):
        self.active_sample();self.state.gate.new_epoch()
        t=self.state.snapshot();self.assertEqual(t['epoch'],1);self.assertFalse(t['telemetry_available'])
    def test_nonfinite_own_qpos_qvel_yields_finite_zero_command(self):
        sim=self.runtime.sim;rid=self.state.gate.robot_id
        for array,indices in ((sim.data.qpos,sim.qindices[rid]),(sim.data.qvel,sim.vindices[rid])):
            for index in indices:
                for bad in (math.nan,math.inf,-math.inf):
                    with self.subTest(array='qpos' if array is sim.data.qpos else 'qvel',index=int(index),bad=str(bad)):
                        self.send(mode_request=mode(),fire=True,vx_mps=1.)
                        old=float(array[index]);array[index]=bad
                        try:
                            cmd=self.runtime._operator_command(rid)
                            values=asdict(cmd);self.assertFalse(cmd.fire)
                            self.assertTrue(all(math.isfinite(v) for v in values.values()))
                            self.assertEqual((cmd.force_x,cmd.force_y,cmd.yaw_torque),(0.,0.,0.))
                            self.assertEqual(self.state.gate.reason,'invalid_physics_state')
                            self.assertFalse(self.runtime.operator_modes['effective']['spin_enabled'])
                        finally:array[index]=old
        self.send(mode_request=mode(),fire=False);cmd=self.runtime._operator_command(rid)
        self.assertTrue(math.isfinite(cmd.yaw_torque));self.assertGreater(cmd.yaw_torque,0.)

class ModeSafetyHTTPTests(unittest.TestCase):
    setUp=http_fixture.HTTPTests.setUp
    tearDown=http_fixture.HTTPTests.tearDown
    request=http_fixture.HTTPTests.request
    def test_http_null_aim_rejects_and_immediately_neutralizes(self):
        g=self.state.gate
        data=dict(session_id=g.session_id,epoch=0,robot_id=g.robot_id,seq=1,
                  sent_at_ms=g.wall()*1000,focus=True,deadman=True,vx_mps=0.,vy_mps=0.,
                  yaw_rate_rps=0.,pitch_rate_rps=0.,fire=True,mode_request=mode())
        code,_,_=self.request('POST','/control',json.dumps(data),{'Content-Type':'application/json'})
        self.assertEqual(code,200)
        data.update(seq=2,aim_request=None)
        code,raw,_=self.request('POST','/control',json.dumps(data),{'Content-Type':'application/json'})
        self.assertEqual(code,409);self.assertFalse(json.loads(raw)['accepted'])
        self.assertFalse(g.sample().fire);self.assertFalse(g.active_mode.spin_enabled)
    def test_http_new_identity_has_no_old_own(self):
        g=self.state.gate
        self.state.publish(dict(schema='polar.sim.operator.v1',session_id=g.session_id,
            epoch=g.epoch,robot_id=g.robot_id,own={'robot_id':g.robot_id},phase='running'))
        g.new_epoch('blue_infantry')
        code,raw,_=self.request('GET','/telemetry');t=json.loads(raw)
        self.assertEqual(code,200);self.assertFalse(t['telemetry_available'])
        self.assertEqual(t['robot_id'],'blue_infantry');self.assertIsNone(t['own'])

if __name__=='__main__':unittest.main()
