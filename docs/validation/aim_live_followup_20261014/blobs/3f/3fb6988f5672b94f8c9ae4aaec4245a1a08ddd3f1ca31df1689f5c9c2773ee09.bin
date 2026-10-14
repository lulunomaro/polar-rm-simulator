"""Cumulative mouse-angle lease and physics consumption regressions."""
import unittest
from .protocol import ControlGate
from .test_protocol import Clock
from . import test_source_runtime as source_tests


def angle(gen=0,yaw=.1,pitch=-.02):
    return dict(generation=gen,yaw_total_rad=yaw,pitch_total_rad=pitch)

class MouseGateTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.g=ControlGate(wall=self.clock,monotonic=self.clock);self.seq=0
    def send(self,**changes):
        self.seq+=1;g=self.g
        m=dict(session_id=g.session_id,epoch=g.epoch,robot_id=g.robot_id,seq=self.seq,
            sent_at_ms=self.clock()*1000,focus=True,deadman=True,fire=False,
            vx_mps=0.,vy_mps=0.,yaw_rate_rps=0.,pitch_rate_rps=0.,mouse_angle=angle())
        m.update(changes);return g.accept(m)
    def test_duplicate_total_consumed_once(self):
        self.assertTrue(self.send()['accepted']);self.assertEqual(self.g.consume_mouse_angle(),(.1,-.02))
        self.assertTrue(self.send()['accepted']);self.assertEqual(self.g.consume_mouse_angle(),(0.,0.))
    def test_coalesced_total_and_reverse(self):
        self.send(mouse_angle=angle(yaw=.1));self.send(mouse_angle=angle(yaw=.25))
        self.assertEqual(self.g.consume_mouse_angle(),(.25,-.02))
        self.send(mouse_angle=angle(yaw=.05));self.assertAlmostEqual(self.g.consume_mouse_angle()[0],-.2)
    def test_first_nonzero_total_survives_coalescing(self):
        self.send(mouse_angle=angle(17,.3,.2));self.assertEqual(self.g.consume_mouse_angle(),(.3,.2))
    def test_release_revokes_pending_and_old_generation(self):
        self.send();self.send(focus=False);self.assertEqual(self.g.consume_mouse_angle(),(0.,0.))
        self.assertFalse(self.send()['accepted']);self.assertTrue(self.send(mouse_angle=angle(1))['accepted'])
        self.assertEqual(self.g.consume_mouse_angle(),(.1,-.02))
    def test_elapsed_lease_same_generation_rejected(self):
        self.send();self.clock.advance(.3);self.assertFalse(self.send()['accepted'])
        self.assertEqual(self.g.consume_mouse_angle(),(0.,0.))
    def test_epoch_revokes_pending(self):
        self.send();self.g.new_epoch();self.assertFalse(self.send()['accepted'])
        self.assertTrue(self.send(mouse_angle=angle(1))['accepted'])
    def test_invalid_numbers_and_mixed_rate_fail_closed(self):
        cases=[dict(mouse_angle=None),dict(mouse_angle=angle(True)),dict(mouse_angle=angle(-1)),
               dict(mouse_angle=angle(2**53)),dict(mouse_angle=angle(yaw=float('nan'))),
               dict(mouse_angle=angle(pitch=1e7)),dict(yaw_rate_rps=.1)]
        for bad in cases:
            self.setUp();self.assertFalse(self.send(**bad)['accepted']);self.assertEqual(self.g.consume_mouse_angle(),(0.,0.))
    def test_generation_no_wrap_or_active_change(self):
        self.send(mouse_angle=angle(2**53-1));self.send(deadman=False)
        self.assertFalse(self.send(mouse_angle=angle(0))['accepted'])
        self.assertEqual(self.g.session()['mouse_angle_last_generation'],2**53-1)
        self.setUp();self.send();self.assertFalse(self.send(mouse_angle=angle(1))['accepted'])
    def test_ack_means_consumed_or_discarded(self):
        self.send();self.g.consume_mouse_angle(discard=True)
        a=self.g.status()['mouse_angle_ack'];self.assertEqual(a['reason'],'discarded_by_authority')
        self.assertEqual(a['consumed_control_seq'],1);self.assertEqual(a['consumed_yaw_total_rad'],.1)
    def test_active_missing_angle_rejected(self):
        self.send();m=self.g.input
        self.seq+=1
        r=self.g.accept(dict(session_id=self.g.session_id,epoch=0,robot_id=self.g.robot_id,seq=self.seq,
            sent_at_ms=self.clock()*1000,focus=True,deadman=True,fire=False,vx_mps=0.,vy_mps=0.,yaw_rate_rps=0.,pitch_rate_rps=0.))
        self.assertFalse(r['accepted'])

class MousePhysicsTests(unittest.TestCase):
    setUp=source_tests.SourceArbitrationTests.setUp
    tearDown=source_tests.SourceArbitrationTests.tearDown
    send=source_tests.SourceArbitrationTests.send
    assert_off=source_tests.SourceArbitrationTests.assert_off
    def test_angle_independent_of_physics_dt(self):
        r=self.runtime;r.source.output=None
        for dt in (.0005,.002,.01):
            r.sim.model.opt.timestep=dt
            gen=int(dt*1e6)
            self.send(focus=False);r._operator_command('red_sentry')
            self.send(mouse_angle=angle(gen,0,0));r._operator_command('red_sentry')
            before=(r.yaw_target,r.pitch_target)
            self.send(mouse_angle=angle(gen,.12,-.03));r._operator_command('red_sentry')
            self.assertAlmostEqual(r.yaw_target-before[0],.12)
            self.assertAlmostEqual(r.pitch_target-before[1],-.03)
            hold=(r.yaw_target,r.pitch_target)
            for _ in range(10):r._operator_command('red_sentry')
            self.assertEqual((r.yaw_target,r.pitch_target),hold)
    def test_source_consumes_without_later_backlog(self):
        r=self.runtime;self.send(mouse_angle=angle(0,.7,.2));r.step_once()
        self.assertAlmostEqual(r.yaw_target,.4)
        self.assertEqual(self.gate.status()['mouse_angle_ack']['reason'],'discarded_by_authority')
        r.source.output=None;r.step_once();before=r.yaw_target
        r.step_once();self.assertAlmostEqual(r.yaw_target,before)
    def test_release_during_inference_drops_pending_angle(self):
        self.send(mouse_angle=angle(0,.7,.2));self.runtime.source.hook=lambda:self.send(focus=False)
        self.runtime.step_once();self.assertEqual(self.gate.consume_mouse_angle(),(0.,0.));self.assert_off()

    def test_ordinary_path_expiry_during_consume_clears_manual_fire_drive(self):
        from .runtime import OperatorRuntime
        self.send(mouse_angle=angle(),fire=True,vx_mps=1.)
        original=self.gate.consume_mouse_angle
        def expire(**kwargs):
            self.clock.advance(.3)
            return original(**kwargs)
        self.gate.consume_mouse_angle=expire
        command=OperatorRuntime._operator_command(self.runtime,'red_sentry')
        self.assertEqual(self.gate.reason,'control_timeout')
        self.assertFalse(command.fire);self.assertEqual(command.force_x,0.)
        self.assertEqual(command.force_y,0.);self.assertEqual(command.yaw_torque,0.)
    def test_ordinary_path_expiry_after_consume_clears_manual_fire_drive(self):
        from .runtime import OperatorRuntime
        self.send(mouse_angle=angle(),fire=True,vx_mps=1.)
        original=self.runtime._mode_feedback
        def expire(*args,**kwargs):
            original(*args,**kwargs)
            if kwargs['allowed']:self.clock.advance(.3)
        self.runtime._mode_feedback=expire
        command=OperatorRuntime._operator_command(self.runtime,'red_sentry')
        self.assertFalse(command.fire);self.assertEqual(command.force_x,0.)
