"""SIM drive reference frames: protocol, physical-own transforms and safety.

No renderer, detector, hardware or full-match claims. Pose changes below create
named initial test conditions; the direction tests use actual MuJoCo dynamics.
"""
import json
import math
import unittest

import mujoco
import numpy as np

from .protocol import ControlGate, DriveAxes, OperatorInput
from . import test_protocol as protocol_fixtures
from . import test_runtime as runtime_fixtures
from .test_modes import mode
from . import test_source_runtime as source_fixtures
from .source_aim import OperatorSourceAim


def drive_mode(frame='free',**changes):
    return mode(spin_enabled=False,chassis_follow=frame,**changes)


def axes(forward=0.,left=0.):
    return dict(forward_mps=forward,left_mps=left)


class DriveProtocolTests(unittest.TestCase):
    setUp=protocol_fixtures.GateTests.setUp
    message=protocol_fixtures.GateTests.message
    def send(self,**changes):
        value=dict(vx_mps=0.,vy_mps=0.,yaw_rate_rps=0.,pitch_rate_rps=0.,fire=False,
                   drive_axes=axes(),mode_request=drive_mode(),seq=self.gate.last_seq+1)
        value.update(changes)
        return self.gate.accept(self.message(**value))
    def test_advertisement_preserves_legacy_strict_free_client(self):
        s=self.gate.session();c=s['capabilities']
        self.assertEqual(c['chassis_follow_modes'],['free'])
        self.assertEqual(c['chassis_drive_frame_version'],1)
        self.assertEqual(c['chassis_drive_modes'],['free','gimbal','field'])
        self.assertEqual(s['coordinate_frame'],'chassis_body')
        self.assertEqual(s['drive_frame_contract']['yaw_units'],'rad')
        self.assertFalse(s['drive_frame_contract']['automatic_chassis_yaw_follow'])
        self.assertFalse(c['world_stabilized_gimbal'])
        self.assertFalse(c['power_guard']);self.assertFalse(c['buffer_protect'])
    def test_all_three_modes_accept_unambiguous_axes(self):
        for frame in ('free','gimbal','field'):
            with self.subTest(frame=frame):
                self.setUp();self.assertTrue(self.send(mode_request=drive_mode(frame),drive_axes=axes(.5,-.25))['accepted'])
                self.assertEqual(self.gate.input.drive_axes,DriveAxes(.5,-.25))
                self.assertEqual(self.gate.active_mode.chassis_follow,frame)
    def test_mixed_axes_and_old_velocity_rejected_including_tiny_value(self):
        for key in ('vx_mps','vy_mps'):
            for value in (.1,1e-15):
                self.setUp();self.send(fire=True)
                ack=self.send(**{key:value})
                self.assertEqual(ack['reason'],'mixed_drive_axes_and_legacy_velocity')
                self.assertEqual(self.gate.input,OperatorInput())
    def test_bad_shapes_nonfinite_booleans_huge_and_out_of_range_rejected(self):
        bad=[None,{},[],axes(True),axes('1'),axes(math.nan),axes(math.inf),axes(-math.inf),
             axes(10**1000),axes(1.01),axes(0.,-1.01),dict(axes(),yaw=0.)]
        for value in bad:
            with self.subTest(value=str(value)[:70]):
                self.setUp();self.send(fire=True)
                self.assertFalse(self.send(drive_axes=value)['accepted'])
                self.assertEqual(self.gate.input,OperatorInput())
    def test_nonfree_requires_explicit_axes_even_when_legacy_zero(self):
        for frame in ('gimbal','field'):
            self.setUp()
            ack=self.gate.accept(self.message(vx_mps=0.,mode_request=drive_mode(frame)))
            self.assertEqual(ack['reason'],'drive_axes_required_for_mode')
    def test_unsupported_frame_is_neutral(self):
        self.send(fire=True)
        self.assertEqual(self.send(mode_request=drive_mode('target'))['reason'],'unsupported_chassis_follow')
        self.assertEqual(self.gate.input,OperatorInput())
    def test_diagonal_and_negative_axes_normalize_to_one(self):
        for forward,left in ((1.,1.),(-1.,1.),(-1.,-1.)):
            self.setUp();self.send(drive_axes=axes(forward,left));value=self.gate.input.drive_axes
            self.assertAlmostEqual(math.hypot(value.forward_mps,value.left_mps),1.)
            self.assertEqual(math.copysign(1,value.forward_mps),forward)
            self.assertEqual(math.copysign(1,value.left_mps),left)
    def test_mode_change_while_active_latches_release_barrier(self):
        self.send(drive_axes=axes(1.),fire=True)
        rev=self.gate.safety_revision
        ack=self.send(mode_request=drive_mode('field'),drive_axes=axes(1.))
        self.assertEqual(ack['reason'],'drive_frame_release_required')
        self.assertGreater(self.gate.safety_revision,rev)
        self.assertEqual(self.gate.input,OperatorInput())
        self.assertTrue(self.gate.drive_frame_requires_release)
        # Rejecting the first switch must not make a second armed packet safe.
        self.assertFalse(self.send(mode_request=drive_mode('field'))['accepted'])
        self.assertTrue(self.send(deadman=False,mode_request=drive_mode('field'))['accepted'])
        self.assertFalse(self.gate.drive_frame_requires_release)
        self.assertTrue(self.send(mode_request=drive_mode('field'),drive_axes=axes(.2))['accepted'])
    def test_identical_heartbeat_stable_but_axis_change_increments_revision(self):
        self.send(drive_axes=axes(.2));rev=self.gate.safety_revision
        self.send(drive_axes=axes(.2));self.assertEqual(self.gate.safety_revision,rev)
        self.send(drive_axes=axes(0.,.2));self.assertGreater(self.gate.safety_revision,rev)
    def test_focus_timeout_epoch_and_replay_clear_new_axes(self):
        for failure in ('focus','timeout','epoch'):
            with self.subTest(failure=failure):
                self.setUp();self.send(mode_request=drive_mode('gimbal'),drive_axes=axes(1.),fire=True)
                replay=self.message(seq=self.gate.last_seq,mode_request=drive_mode('gimbal'),drive_axes=axes(1.),vx_mps=0.)
                if failure=='focus':self.send(focus=False,mode_request=drive_mode('gimbal'))
                elif failure=='timeout':self.clock.advance(.251);self.gate.sample()
                else:self.gate.new_epoch('blue_infantry')
                self.assertEqual(self.gate.input,OperatorInput())
                self.assertFalse(self.gate.accept(replay)['accepted'])
    def test_any_exact_nonzero_axis_is_movement_request(self):
        for a in (DriveAxes(1e-15,0.),DriveAxes(0.,-1e-15)):
            self.assertTrue(OperatorInput(drive_axes=a).movement_requested())
        self.assertFalse(OperatorInput(drive_axes=DriveAxes()).movement_requested())
    def test_legacy_free_input_remains_body_input(self):
        ack=self.gate.accept(self.message(vx_mps=.5,vy_mps=-.25))
        self.assertTrue(ack['accepted']);self.assertIsNone(self.gate.input.drive_axes)
        self.assertEqual(self.gate.active_mode.chassis_follow,'free')


class DriveHTTPTests(unittest.TestCase):
    setUp=protocol_fixtures.HTTPTests.setUp
    tearDown=protocol_fixtures.HTTPTests.tearDown
    request=protocol_fixtures.HTTPTests.request
    def test_http_extension_and_strict_ambiguity_response(self):
        g=self.state.gate
        command=dict(session_id=g.session_id,epoch=g.epoch,robot_id=g.robot_id,seq=1,
            sent_at_ms=g.wall()*1000,focus=True,deadman=True,fire=False,
            vx_mps=0.,vy_mps=0.,yaw_rate_rps=0.,pitch_rate_rps=0.,
            mode_request=drive_mode('field'),drive_axes=axes(.4,.1))
        code,raw,_=self.request('POST','/control',json.dumps(command),{'Content-Type':'application/json'})
        self.assertEqual(code,200);self.assertTrue(json.loads(raw)['accepted'])
        command.update(seq=2,vx_mps=.2)
        code,raw,_=self.request('POST','/control',json.dumps(command),{'Content-Type':'application/json'})
        self.assertEqual(code,409);self.assertEqual(json.loads(raw)['reason'],'mixed_drive_axes_and_legacy_velocity')


class DrivePhysicsTests(unittest.TestCase):
    setUp=runtime_fixtures.RuntimeTests.setUp
    tearDown=runtime_fixtures.RuntimeTests.tearDown
    send=runtime_fixtures.RuntimeTests.send
    tick=runtime_fixtures.RuntimeTests.tick
    def place(self,chassis=0.,gimbal=0.,velocity=(0.,0.),rid=None):
        rid=rid or self.state.gate.robot_id;sim=self.runtime.sim
        sim.data.qpos[sim.qindices[rid][2]]=chassis
        sim.data.qpos[sim.qindices[rid][3]]=gimbal
        sim.data.qvel[sim.vindices[rid]]=0.
        sim.data.qvel[sim.vindices[rid][0]]=velocity[0]
        sim.data.qvel[sim.vindices[rid][1]]=velocity[1]
        mujoco.mj_forward(sim.model,sim.data)
    def drive(self,frame,forward=0.,left=0.):
        self.send(deadman=False,drive_axes=axes(),mode_request=drive_mode(frame))
        ack=self.send(drive_axes=axes(forward,left),mode_request=drive_mode(frame))
        self.assertTrue(ack['accepted'])
        return self.runtime._operator_command(self.state.gate.robot_id)
    def target(self):return self.runtime.operator_modes['drive']['world_velocity_target_mps']
    def test_free_45_90_180_and_negative_axes(self):
        for angle in (math.pi/4,math.pi/2,math.pi):
            for forward,left in ((.5,0.),(0.,.5),(-.5,0.),(0.,-.5)):
                with self.subTest(angle=angle,forward=forward,left=left):
                    self.place(angle);c=self.drive('free',forward,left)
                    expected=[math.cos(angle)*forward-math.sin(angle)*left,
                              math.sin(angle)*forward+math.cos(angle)*left]
                    np.testing.assert_allclose(self.target(),expected,atol=1e-12)
                    np.testing.assert_allclose([c.force_x,c.force_y],np.array(expected)*36,atol=1e-12)
    def test_field_does_not_mirror_blue_team(self):
        for rid in ('red_infantry','blue_infantry'):
            self.state.gate.new_epoch(rid)
            self.place(math.pi,.8)
            c=self.drive('field',.4,.2)
            np.testing.assert_allclose(self.target(),[.4,.2],atol=1e-12)
            self.assertGreater(c.force_x,0);self.assertGreater(c.force_y,0)
    def test_gimbal_is_world_plus_relative_measured_pose_not_command_target(self):
        self.place(math.pi/4,math.pi/4)
        self.runtime.yaw_target=-1.5
        self.drive('gimbal',.5,0.)
        np.testing.assert_allclose(self.target(),[0.,.5],atol=1e-12)
        self.assertAlmostEqual(self.runtime.operator_modes['drive']['reference_yaw_rad'],math.pi/2)
        # Physical pose changes without any client telemetry or input update.
        self.place(math.pi/2,math.pi/2)
        self.runtime._operator_command(self.state.gate.robot_id)
        np.testing.assert_allclose(self.target(),[-.5,0.],atol=1e-12)
    def test_legacy_vx_vy_still_body_frame(self):
        self.place(math.pi/2)
        self.send(vx_mps=.5,vy_mps=-.2)
        c=self.runtime._operator_command(self.state.gate.robot_id)
        np.testing.assert_allclose(self.target(),[.2,.5],atol=1e-12)
        self.assertEqual(self.runtime.operator_modes['drive']['input_kind'],'legacy_chassis')
    def test_force_saturation_truthful_and_target_not_measured(self):
        self.place(velocity=(-9.,8.));c=self.drive('field',1.,0.)
        self.assertEqual((c.force_x,c.force_y),(60.,-60.))
        d=self.runtime.operator_modes['drive'];self.assertTrue(d['saturated'])
        self.assertEqual(d['world_velocity_target_mps'],[1.,0.])
        self.assertEqual(d['measured_world_velocity_mps'],[-9.,8.])
        self.assertEqual(d['applied_world_force_n'],[60.,-60.])
    def test_nonfinite_actual_own_pose_or_velocity_neutralizes(self):
        sim=self.runtime.sim;rid=self.state.gate.robot_id
        for kind,index in (('qpos',2),('qpos',3),('qvel',0),('qvel',1)):
            for bad in (math.nan,math.inf,-math.inf):
                with self.subTest(kind=kind,index=index,bad=bad):
                    self.place();self.drive('gimbal',.5)
                    array=getattr(sim.data,kind);indices=sim.qindices if kind=='qpos' else sim.vindices
                    array[indices[rid][index]]=bad
                    c=self.runtime._operator_command(rid)
                    self.assertEqual((c.force_x,c.force_y,c.yaw_torque,c.fire),(0.,0.,0.,False))
                    self.assertEqual(self.state.gate.reason,'invalid_physics_state')
                    self.assertFalse(self.runtime.operator_modes['drive']['active'])
    def test_new_axes_timeout_focus_and_epoch_neutral(self):
        for failure in ('focus','timeout','epoch'):
            self.place();self.drive('field',.5)
            if failure=='focus':self.send(focus=False,mode_request=drive_mode('field'),drive_axes=axes())
            elif failure=='timeout':self.clock.advance(.251)
            else:self.state.gate.new_epoch('blue_infantry')
            c=self.runtime._operator_command(self.state.gate.robot_id)
            self.assertEqual((c.force_x,c.force_y,c.fire),(0.,0.,False))
            self.assertFalse(self.runtime.operator_modes['drive']['active'])
    def test_telemetry_reports_actual_poststep_velocity_and_force(self):
        self.place();self.drive('field',.4,.2);self.tick();self.runtime._publish()
        sim=self.runtime.sim;rid=self.state.gate.robot_id
        d=self.state.snapshot()['operator_modes']['drive']
        np.testing.assert_allclose(d['measured_world_velocity_mps'],sim.data.qvel[sim.vindices[rid]][:2])
        np.testing.assert_allclose(d['applied_world_force_n'],sim.data.ctrl[sim.aindices[rid]][:2])
        self.assertFalse(self.state.snapshot()['operator_modes']['supported']['world_stabilized_gimbal'])
    def cached_drive_sample(self):
        self.place();self.drive('field',.4,.2);self.tick();self.runtime._publish()
        before=self.state.snapshot()
        self.assertTrue(before['operator_modes']['drive']['active'])
        self.assertNotEqual(before['operator_modes']['drive']['applied_world_force_n'],[0.,0.])
        return before
    def assert_current_drive_revoked_historical_measurements_preserved(self,before,reason):
        after=self.state.snapshot();drive=after['operator_modes']['drive']
        old=before['operator_modes']['drive']
        self.assertFalse(drive['active']);self.assertEqual(drive['mode'],'free')
        self.assertEqual(drive['reference_yaw_rad'],0.)
        self.assertEqual(drive['world_velocity_target_mps'],[0.,0.])
        self.assertEqual(drive['reason'],reason)
        self.assertEqual(drive['measured_world_velocity_mps'],old['measured_world_velocity_mps'])
        self.assertEqual(drive['applied_world_force_n'],old['applied_world_force_n'])
        self.assertEqual(drive['measurement_sim_time'],before['sim_time'])
        self.assertEqual(drive['input_revision'],old['input_revision'])
        self.assertEqual(after['operator_modes']['effective']['chassis_follow'],'free')
        self.assertIsNone(after['operator_modes']['effective_seq'])
        # Snapshot reads cannot modify the stored physical sample.
        self.assertTrue(self.state.telemetry['operator_modes']['drive']['active'])
    def test_cached_drive_focus_loss_revokes_without_claiming_zero_actual_force(self):
        before=self.cached_drive_sample()
        self.send(focus=False,mode_request=drive_mode('field'),drive_axes=axes())
        self.assert_current_drive_revoked_historical_measurements_preserved(before,'focus_lost')
    def test_cached_drive_timeout_revokes_without_physics_tick(self):
        before=self.cached_drive_sample();self.clock.advance(.251)
        self.assert_current_drive_revoked_historical_measurements_preserved(before,'control_timeout')
    def test_cached_drive_new_axes_revision_is_pending_until_sampled(self):
        before=self.cached_drive_sample()
        self.send(mode_request=drive_mode('field'),drive_axes=axes(0.,.4))
        self.assert_current_drive_revoked_historical_measurements_preserved(before,'new_input_pending')
        self.tick();self.runtime._publish()
        d=self.state.snapshot()['operator_modes']['drive']
        self.assertTrue(d['active']);self.assertEqual(d['world_velocity_target_mps'],[0.,.4])
    def test_cached_drive_release_rearm_cannot_resurrect_old_reference(self):
        before=self.cached_drive_sample()
        self.send(deadman=False,mode_request=drive_mode('gimbal'),drive_axes=axes())
        self.send(mode_request=drive_mode('gimbal'),drive_axes=axes(.4,.2))
        self.assert_current_drive_revoked_historical_measurements_preserved(before,'new_input_pending')
    def test_cached_drive_identical_heartbeat_keeps_same_revision_sample(self):
        before=self.cached_drive_sample()
        self.send(mode_request=drive_mode('field'),drive_axes=axes(.4,.2))
        after=self.state.snapshot()['operator_modes']['drive']
        self.assertTrue(after['active'])
        self.assertEqual(after['input_revision'],before['operator_modes']['drive']['input_revision'])
    def test_all_role_profiles_expose_bounded_drive_reference_capability(self):
        profiles=self.state.session()['robot_profiles'];self.assertEqual(len(profiles),6)
        for profile in profiles:
            c=profile['capabilities'];self.assertEqual(c['chassis_drive_frame_version'],1)
            self.assertEqual(c['chassis_drive_modes'],['free','gimbal','field'])
            self.assertEqual(c['chassis_follow_modes'],['free'])
            self.assertFalse(c['power_guard']);self.assertFalse(c['buffer_protect'])


class DriveSourceSafetyTests(unittest.TestCase):
    setUp=source_fixtures.SourceArbitrationTests.setUp
    tearDown=source_fixtures.SourceArbitrationTests.tearDown
    send=source_fixtures.SourceArbitrationTests.send
    assert_off=source_fixtures.SourceArbitrationTests.assert_off
    def test_new_axes_are_passed_as_motion_and_cannot_apply_fake_source(self):
        seen=[]
        original=self.runtime.source.act_operator
        def spy(*args,**kwargs):seen.append(kwargs);return original(*args,**kwargs)
        self.runtime.source.act_operator=spy
        self.send(drive_axes=axes(1e-15))
        self.runtime.step_once()
        self.assertTrue(seen[-1]['move_requested']);self.assert_off()
    def test_new_axis_change_discards_inflight_old_source_result(self):
        self.runtime.source.hook=lambda:self.send(drive_axes=axes(.3))
        self.runtime.step_once();self.assert_off()
        self.assertEqual(self.runtime.source_results_discarded,1)
    def test_frame_change_discards_inflight_source_and_requires_release(self):
        def switch():
            self.seq+=1;g=self.gate
            ack=g.accept(dict(session_id=g.session_id,epoch=g.epoch,robot_id=g.robot_id,seq=self.seq,
                sent_at_ms=self.clock()*1000,focus=True,deadman=True,fire=True,
                vx_mps=0.,vy_mps=0.,yaw_rate_rps=0.,pitch_rate_rps=0.,
                mode_request=drive_mode('gimbal'),drive_axes=axes()))
            self.assertEqual(ack['reason'],'drive_frame_release_required')
        self.runtime.source.hook=switch
        self.runtime.step_once();self.assert_off();self.assertTrue(self.gate.drive_frame_requires_release)
    def test_expiry_after_manual_build_clears_drive_feedback(self):
        from unittest.mock import patch
        from .runtime import OperatorRuntime
        original=OperatorRuntime._operator_command
        def expire(runtime,rid):
            command=original(runtime,rid);self.clock.advance(.3);return command
        self.send(drive_axes=axes(.5))
        with patch.object(OperatorRuntime,'_operator_command',expire):self.runtime.step_once()
        d=self.runtime.operator_modes['drive']
        self.assertFalse(d['active']);self.assertEqual(d['world_velocity_target_mps'],[0.,0.])
        self.assertEqual(d['applied_world_force_n'],[0.,0.])
    def test_real_source_boundary_rejects_motion_before_inference(self):
        aim=object.__new__(OperatorSourceAim);aim.error=None;reasons=[]
        aim.disengage=lambda o,reason:reasons.append(reason)
        from types import SimpleNamespace
        result=aim.act_operator(SimpleNamespace(robot_id='red_sentry'),
            self.gate.input.aim_request,identity=('test',),allowed=True,move_requested=True)
        self.assertIsNone(result);self.assertEqual(reasons,['own_motion_requested'])



class QualificationEntryGuardTests(unittest.TestCase):
    def _reject_optimized(self, flags, optimize=None):
        import os, subprocess, sys, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'must_not_be_created'
            env=dict(os.environ)
            env.pop('PYTHONOPTIMIZE',None)
            if optimize is not None:env['PYTHONOPTIMIZE']=optimize
            script=Path(__file__).with_name('qa_drive_frames.py')
            p=subprocess.run([sys.executable,*flags,str(script),'--out',str(output)],
                             env=env,capture_output=True,text=True,timeout=10)
            self.assertNotEqual(p.returncode,0)
            self.assertIn('qualification assertions are required',p.stderr)
            self.assertFalse(output.exists())
    def test_qualification_rejects_optimized_python(self):self._reject_optimized(['-O'])
    def test_qualification_rejects_double_optimized_python(self):self._reject_optimized(['-OO'])
    def test_qualification_rejects_optimized_environment(self):self._reject_optimized([], '1')

if __name__=='__main__':unittest.main()
