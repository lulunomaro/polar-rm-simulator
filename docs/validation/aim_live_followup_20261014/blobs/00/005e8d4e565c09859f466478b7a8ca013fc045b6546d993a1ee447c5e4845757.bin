"""CPU-only source-result arbitration tests, with a named injected test double.

These tests do NOT claim detector execution. Separate native/HTTP QA does that.
"""
import dataclasses
import threading
import unittest
from types import SimpleNamespace

from ..contracts import Command
from .autoaim import AutoAimRequest
from .protocol import ControlGate
from .server import BridgeState
from .source_runtime import SourceOperatorRuntime
from .test_protocol import Clock

class FakeSource:
    def __init__(self,*args):
        self.error=None;self.feedback={};self.source_calls=0;self.captured_frames=0;self.delivered_frames=0
        self.hook=None;self.output=Command(gimbal_yaw=.4,gimbal_pitch=.1,fire=True)
        self.disengaged=[]
    def act_operator(self,o,request,**kwargs):
        if self.hook:self.hook()
        self.feedback=dict(available=True,active=self.output is not None,reason='test_double',authority='source_autoaim')
        return self.output
    def disengage(self,o,reason):
        self.disengaged.append(reason);self.feedback=dict(available=True,active=False,reason=reason,authority='manual')
    def close(self):pass

class SourceArbitrationTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.gate=ControlGate('red_sentry',wall=self.clock,monotonic=self.clock)
        self.state=BridgeState(self.gate);self.seq=0
        self.runtime=SourceOperatorRuntime(self.state,source_spec='test-double',source_out='unused',
            source_factory=FakeSource,display_renderer_factory=lambda *a:None)
        self.runtime._render_display_tick=lambda:None
        self.request=dataclasses.asdict(AutoAimRequest(True,True,85,.25,.25))
        self.send()
    def tearDown(self):self.runtime.close()
    def send(self,**changes):
        self.seq+=1;g=self.gate
        value=dict(session_id=g.session_id,epoch=g.epoch,robot_id=g.robot_id,seq=self.seq,
            sent_at_ms=self.clock()*1000,focus=True,deadman=True,vx_mps=0.,vy_mps=0.,
            yaw_rate_rps=0.,pitch_rate_rps=0.,fire=False,aim_request=self.request)
        value.update(changes);self.assertTrue(g.accept(value)['accepted'])
    def assert_off(self):
        self.assertFalse(self.runtime.autoaim_status['active'])
        self.assertFalse(self.runtime.commands[self.gate.robot_id].fire)
        self.assertNotAlmostEqual(self.runtime.commands[self.gate.robot_id].gimbal_yaw,.4)
    def test_valid_source_controls_only_gimbal(self):
        self.runtime.step_once();c=self.runtime.commands['red_sentry']
        self.assertAlmostEqual(c.gimbal_yaw,.4);self.assertAlmostEqual(c.gimbal_pitch,.1)
        self.assertFalse(c.fire,'Even fire=True from source must not authorize firing')
    def test_heartbeat_does_not_discard_identical_request(self):
        rev=self.gate.safety_revision;self.runtime.source.hook=lambda:self.send()
        self.runtime.step_once();self.assertEqual(rev,self.gate.safety_revision)
        self.assertAlmostEqual(self.runtime.commands['red_sentry'].gimbal_yaw,.4)
    def test_http_thread_can_release_during_source(self):
        def release():
            done=threading.Event()
            def work():self.send(focus=False);done.set()
            thread=threading.Thread(target=work);thread.start()
            self.assertTrue(done.wait(.5),'Input gate lock held over source inference')
            thread.join()
        self.runtime.source.hook=release;self.runtime.step_once();self.assert_off()
    def test_release_then_repress_invalidates_same_value_result(self):
        def toggle():
            self.send(aim_request=dict(self.request,hold=False));self.send()
        self.runtime.source.hook=toggle;self.runtime.step_once();self.assert_off()
    def test_fov_change_discards_old_result(self):
        self.runtime.source.hook=lambda:self.send(aim_request=dict(self.request,fov_degrees=20))
        self.runtime.step_once();self.assert_off()
    def test_movement_change_discards_old_result(self):
        self.runtime.source.hook=lambda:self.send(vx_mps=.5)
        self.runtime.step_once();self.assert_off()
    def test_elapsed_lease_then_identical_renewal_discards_result(self):
        def gap():self.clock.advance(.3);self.send()
        self.runtime.source.hook=gap;self.runtime.step_once();self.assert_off()
    def test_lease_expiring_during_manual_build_discards_result(self):
        from unittest.mock import patch
        from .runtime import OperatorRuntime
        original=OperatorRuntime._operator_command
        def expire(runtime,rid):self.clock.advance(.3);return original(runtime,rid)
        with patch.object(OperatorRuntime,'_operator_command',expire):self.runtime.step_once()
        self.assert_off()
    def test_lease_expiring_after_manual_build_clears_drive_and_fire(self):
        from unittest.mock import patch
        from .runtime import OperatorRuntime
        original=OperatorRuntime._operator_command
        def expire(runtime,rid):
            command=original(runtime,rid);self.clock.advance(.3);return command
        self.send(fire=True,vx_mps=.5)
        with patch.object(OperatorRuntime,'_operator_command',expire):self.runtime.step_once()
        self.assert_off()
        self.assertEqual(self.runtime.commands[self.gate.robot_id].force_x,0.)
    def test_lease_expiry_discards_result(self):
        self.runtime.source.hook=lambda:self.clock.advance(.3)
        self.runtime.step_once();self.assert_off()
    def test_epoch_switch_discards_result(self):
        self.runtime.source.hook=lambda:self.gate.new_epoch('blue_sentry')
        self.runtime.step_once();self.assert_off()
    def test_nonfinite_source_result_neutralizes(self):
        self.runtime.source.output=Command(gimbal_yaw=float('nan'))
        self.runtime.step_once();self.assert_off();self.assertEqual(self.runtime.autoaim_status['reason'],'source_error')
    def test_source_exception_neutralizes(self):
        def boom():raise RuntimeError('Injected source failure')
        self.runtime.source.hook=boom;self.runtime.step_once();self.assert_off()
        self.assertFalse(self.gate.source_autoaim_ready)
    def test_inactive_hold_latches_command_instead_of_following_gravity(self):
        self.runtime.step_once();self.send(focus=False);self.runtime.step_once()
        held=self.runtime.pitch_target
        for _ in range(100):
            self.runtime.step_once()
            self.assertAlmostEqual(self.runtime.pitch_target,held,places=12)
        self.assertFalse(self.runtime.commands['red_sentry'].fire)
    def test_repeated_neutral_rearm_does_not_accumulate_gravity_offset(self):
        import mujoco
        self.runtime.source.output=None
        index=self.runtime.sim.qindices['red_sentry'][4]
        self.runtime.sim.data.qpos[index]=.15
        mujoco.mj_forward(self.runtime.sim.model,self.runtime.sim.data)
        self.runtime.last_identity=None
        before=float(self.runtime.sim.data.qpos[index])
        for _ in range(6):
            for focused in (True,False):
                self.send(focus=focused)
                for _ in range(50):
                    self.runtime.step_once();self.clock.advance(.0005)
                    self.assertFalse(self.runtime.commands['red_sentry'].fire)
        after=float(self.runtime.sim.data.qpos[index])
        self.assertLess(abs(after-before),.001)
        self.assertIsNotNone(self.runtime.manual_gravity_audit)
    def test_plain_bridge_unavailable_reason_is_not_masked_as_pending(self):
        self.runtime.step_once()
        with self.state.lock:
            self.state.telemetry['autoaim']=dict(algorithm='unavailable',available=False,active=False,reason='source_adapter_unavailable')
        self.assertEqual(self.state.snapshot()['autoaim']['reason'],'source_adapter_unavailable')
    def test_manual_fire_is_not_replaced_by_source_permission(self):
        self.runtime.source.output=Command(gimbal_yaw=.4,gimbal_pitch=.1,fire=False)
        self.send(fire=True);self.runtime.step_once()
        self.assertTrue(self.runtime.commands['red_sentry'].fire)

if __name__=='__main__':unittest.main()
