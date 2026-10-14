"""Spin mode protocol and real MuJoCo actuator/lease regressions. No GL."""
import math
import unittest
from .protocol import ModeRequest, OperatorInput
from . import test_protocol as protocol_fixtures
from . import test_runtime as runtime_fixtures
import json
from .autoaim import AutoAimRequest
from dataclasses import asdict


def mode(**changes):
    result=dict(spin_enabled=True,spin_direction='ccw',spin_speed_dps=120.,chassis_follow='free')
    result.update(changes)
    return result


class SpinProtocolTests(unittest.TestCase):
    setUp=protocol_fixtures.GateTests.setUp
    message=protocol_fixtures.GateTests.message
    def test_mode_defaults_preserve_legacy_command(self):
        self.gate.accept(self.message())
        self.assertEqual(self.gate.active_mode,ModeRequest())
        self.assertFalse(self.gate.mode_request_explicit)
    def test_mode_fields_accept_and_lease_clears_effective(self):
        self.gate.accept(self.message(mode_request=mode()))
        self.assertTrue(self.gate.active_mode.spin_enabled)
        self.assertEqual(self.gate.mode_request_seq,1)
        self.clock.advance(.251)
        self.gate.sample()
        self.assertFalse(self.gate.active_mode.spin_enabled)
        self.assertTrue(self.gate.requested_mode.spin_enabled)
        self.assertEqual(self.gate.reason,'control_timeout')
    def test_invalid_or_unsupported_mode_neutral(self):
        bad=[None,{},mode(spin_enabled=1),mode(spin_direction='CW'),mode(spin_speed_dps=119),
             mode(spin_speed_dps=721),mode(spin_speed_dps=math.nan),mode(spin_speed_dps=10**1000),
             mode(chassis_follow='target'),mode(chassis_follow='FIELD'),dict(mode(),power_guard=True)]
        for value in bad:
            with self.subTest(value=str(value)[:70]):
                self.setUp();self.gate.accept(self.message(mode_request=mode()))
                ack=self.gate.accept(self.message(seq=2,mode_request=value))
                self.assertFalse(ack['accepted'])
                self.assertEqual(self.gate.sample(),OperatorInput())
                self.assertFalse(self.gate.active_mode.spin_enabled)
    def test_mode_cannot_survive_epoch_or_new_legacy_packet(self):
        self.gate.accept(self.message(mode_request=mode()))
        self.gate.new_epoch()
        self.assertEqual(self.gate.active_mode,ModeRequest())
        self.assertEqual(self.gate.requested_mode,ModeRequest())
        self.gate.accept(self.message(seq=2,mode_request=mode()))
        self.gate.accept(self.message(seq=3))
        self.assertFalse(self.gate.active_mode.spin_enabled)
    def test_no_default_spin_from_saved_module_state(self):
        caps=self.gate.session()['capabilities']
        self.assertEqual(caps['operator_modes_version'],1)
        self.assertTrue(caps['spin_mode'])
        self.assertEqual(caps['chassis_follow_modes'],['free'])
        self.assertFalse(caps['power_guard'])
        self.assertFalse(self.gate.active_mode.spin_enabled)


class ModeHTTPTests(unittest.TestCase):
    setUp=protocol_fixtures.HTTPTests.setUp
    tearDown=protocol_fixtures.HTTPTests.tearDown
    request=protocol_fixtures.HTTPTests.request
    def test_mode_request_ack_then_invalid_mode_neutral(self):
        s=self.state.gate.session()
        command=dict(session_id=s['session_id'],epoch=0,robot_id='red_infantry',seq=1,
            sent_at_ms=s['server_time_ms'],focus=True,deadman=True,vx_mps=0.,vy_mps=0.,
            yaw_rate_rps=0.,pitch_rate_rps=0.,fire=False,mode_request=mode())
        code,raw,_=self.request('POST','/control',json.dumps(command),{'Content-Type':'application/json'})
        self.assertEqual(code,200);self.assertTrue(json.loads(raw)['accepted'])
        self.assertTrue(self.state.gate.active_mode.spin_enabled)
        command.update(seq=2,mode_request=mode(chassis_follow='target'))
        code,raw,_=self.request('POST','/control',json.dumps(command),{'Content-Type':'application/json'})
        self.assertEqual(code,409);self.assertEqual(json.loads(raw)['reason'],'unsupported_chassis_follow')
        self.assertFalse(self.state.gate.active_mode.spin_enabled)
    def test_invalid_aim_request_neutralizes_spin_and_manual_fire(self):
        g=self.state.gate
        base=dict(session_id=g.session_id,epoch=0,robot_id=g.robot_id,seq=1,
            sent_at_ms=g.wall()*1000,focus=True,deadman=True,vx_mps=0.,vy_mps=0.,
            yaw_rate_rps=0.,pitch_rate_rps=0.,fire=True,mode_request=mode())
        self.assertTrue(g.accept(base)['accepted'])
        base.update(seq=2,aim_request=dict(asdict(AutoAimRequest()),fov_degrees=10**1000))
        code,raw,_=self.request('POST','/control',json.dumps(base),{'Content-Type':'application/json'})
        self.assertEqual(code,409);self.assertFalse(json.loads(raw)['accepted'])
        self.assertFalse(g.sample().fire);self.assertFalse(g.active_mode.spin_enabled)


class SpinPhysicsTests(unittest.TestCase):
    setUp=runtime_fixtures.RuntimeTests.setUp
    tearDown=runtime_fixtures.RuntimeTests.tearDown
    send=runtime_fixtures.RuntimeTests.send
    tick=runtime_fixtures.RuntimeTests.tick
    def spin_for(self,seconds=1.0,**changes):
        for _ in range(round(seconds/.1)):
            self.send(mode_request=mode(**changes));self.tick(50)
    def test_ccw_actual_chassis_angle_and_velocity_increase(self):
        before=self.runtime._robot('red_infantry')
        self.spin_for()
        after=self.runtime._robot('red_infantry')
        self.assertGreater(after['chassis_yaw'],before['chassis_yaw']+.5)
        self.assertGreater(after['chassis_yaw_rate_rps'],1.)
        feedback=self.runtime.operator_modes
        self.assertTrue(feedback['effective']['spin_enabled'])
        self.assertEqual(feedback['effective']['direction_resolved'],'ccw')
        self.assertAlmostEqual(feedback['effective']['target_yaw_rate_rps'],math.radians(120))
        self.assertAlmostEqual(after['world_gimbal_yaw'],after['chassis_yaw']+after['gimbal_yaw'])
        self.assertFalse(self.runtime.commands['red_infantry'].fire)
    def test_cw_actual_chassis_angle_is_negative(self):
        self.spin_for(spin_direction='cw')
        own=self.runtime._robot('red_infantry')
        self.assertLess(own['chassis_yaw'],-.5)
        self.assertLess(own['chassis_yaw_rate_rps'],-1.)
    def test_auto_resolves_to_ccw_without_target_truth(self):
        self.spin_for(.2,spin_direction='auto')
        self.assertEqual(self.runtime.operator_modes['effective']['direction_resolved'],'ccw')
        self.assertGreater(self.runtime._robot('red_infantry')['chassis_yaw_rate_rps'],0.)
    def test_speed_request_changes_actual_angular_velocity(self):
        self.spin_for(.8,spin_speed_dps=120)
        slow=self.runtime._robot('red_infantry')['chassis_yaw_rate_rps']
        self.spin_for(.8,spin_speed_dps=420)
        fast=self.runtime._robot('red_infantry')['chassis_yaw_rate_rps']
        self.assertGreater(fast,slow+1.)
    def test_turn_off_brakes_physics_then_retains_off_state(self):
        self.spin_for(.7)
        before=abs(self.runtime._robot('red_infantry')['chassis_yaw_rate_rps'])
        self.spin_for(.6,spin_enabled=False)
        after=abs(self.runtime._robot('red_infantry')['chassis_yaw_rate_rps'])
        self.assertLess(after,before*.4)
        self.assertFalse(self.runtime.operator_modes['effective']['spin_enabled'])
        self.assertEqual(self.runtime.operator_modes['effective']['target_yaw_rate_rps'],0.)
    def test_timeout_focus_and_unsupported_mode_remove_spin_torque(self):
        for failure in ('timeout','blur','invalid','epoch'):
            with self.subTest(failure=failure):
                self.send(mode_request=mode());self.tick(10)
                if failure=='timeout':self.clock.advance(.251)
                elif failure=='blur':self.send(mode_request=mode(),focus=False)
                elif failure=='invalid':self.send(mode_request=mode(chassis_follow='target'))
                else:self.state.gate.new_epoch()
                self.tick()
                self.assertEqual(self.runtime.commands[self.state.gate.robot_id].yaw_torque,0.)
                self.assertFalse(self.runtime.operator_modes['effective']['spin_enabled'])
                self.assertIsNone(self.runtime.operator_modes['effective_seq'])
                self.assertFalse(self.runtime.commands[self.state.gate.robot_id].fire)
    def test_saturation_is_feedback_not_false_speed_achievement(self):
        self.send(mode_request=mode(spin_speed_dps=720));self.tick()
        feedback=self.runtime.operator_modes
        self.assertTrue(feedback['saturated'])
        self.assertEqual(feedback['reason'],'torque_saturated')
        self.assertEqual(feedback['measured']['yaw_torque'],20.)
        self.assertLess(abs(feedback['measured']['chassis_yaw_rate_rps']),
                        abs(feedback['effective']['target_yaw_rate_rps']))
    def test_spin_preserves_chassis_body_translation_contract(self):
        sim=self.runtime.sim;rid='red_infantry'
        self.spin_for(.5)
        q=sim.data.qpos[sim.qindices[rid]];v=sim.data.qvel[sim.vindices[rid]]
        self.send(vx_mps=.4,mode_request=mode())
        command=self.runtime._operator_command(rid)
        expected_x=28*(.4*math.cos(float(q[2]))-float(v[0]))+8*.4*math.cos(float(q[2]))
        expected_y=28*(.4*math.sin(float(q[2]))-float(v[1]))+8*.4*math.sin(float(q[2]))
        self.assertAlmostEqual(command.force_x,max(-60,min(60,expected_x)))
        self.assertAlmostEqual(command.force_y,max(-60,min(60,expected_y)))
    def test_autoaim_request_stays_unavailable_and_never_takes_control(self):
        requested=asdict(AutoAimRequest(enabled=True,hold=True))
        self.send(mode_request=mode(),aim_request=requested,fire=False,yaw_rate_rps=.2)
        self.tick()
        status=self.runtime.autoaim_status
        self.assertTrue(status['requested']);self.assertTrue(status['held'])
        self.assertFalse(status['available']);self.assertFalse(status['active'])
        self.assertEqual(status['reason'],'source_adapter_unavailable')
        self.assertEqual(status['fire_authority'],'manual_only')
        self.assertFalse(self.runtime.commands['red_infantry'].fire)
    def test_telemetry_measured_is_actual_physics_state(self):
        self.spin_for(.2)
        self.runtime._publish()
        telemetry=self.state.snapshot();sim=self.runtime.sim;rid='red_infantry'
        self.assertEqual(telemetry['operator_modes']['measured']['chassis_yaw_rate_rps'],
                         float(sim.data.qvel[sim.vindices[rid][2]]))
        self.assertEqual(telemetry['operator_modes']['measured']['yaw_torque'],
                         float(sim.data.ctrl[sim.aindices[rid][2]]))
    def test_dead_robot_and_paused_phase_remove_spin_torque(self):
        self.spin_for(.1)
        self.runtime.sim.paused=True
        self.tick()
        self.assertEqual(self.runtime.commands['red_infantry'].yaw_torque,0.)
        self.assertFalse(self.runtime.operator_modes['effective']['spin_enabled'])
        self.runtime.sim.paused=False
        self.runtime.sim.judge.robots['red_infantry'].hp=0
        self.tick()
        self.assertEqual(self.runtime.commands['red_infantry'].yaw_torque,0.)


if __name__=='__main__':unittest.main()
