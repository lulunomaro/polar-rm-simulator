"""Admission expiry is a discarded exposure, never fabricated native success."""
import unittest
from copy import deepcopy
from unittest.mock import patch
from .adapters import Registry,descriptor
from .contracts import action_for
from .native_adapter import NativeSourceAdapter
from .runtime import AdapterSlot
from .test_control import Clock
from .test_native_early_pixels import fixture,C,RID
from . import test_native_early_pixels as early_fixtures
from .native_camera_snapshot import mint_native_snapshot


def fresh_pixels(p,clock,frame=2):
    m=p.metadata()
    return mint_native_snapshot(p.raw_bytes,robot_id=p.robot_id,episode=p.episode,frame_id=frame,
        capture_wall=clock(),capture_sim_time=p.capture_sim_time,consumers=p.consumers,width=p.width,height=p.height,
        stride_bytes=p.stride_bytes,own={k:m[k] for k in ('own_qpos_at_capture','own_qvel_at_capture','own_odom_at_capture','own_odom_velocity_at_capture')},
        intrinsics=m['intrinsics'],extrinsics=m['extrinsics'])


class AdmissionDeadlineTests(unittest.TestCase):
    def test_create_or_reset_overrun_drops_old_frame_then_same_generation_fresh_frame_executes(self):
        for slow in ('create','reset'):
            clock=Clock();base,p,b=fixture();instance=object.__new__(NativeSourceAdapter);resets=[]
            def reset(context):
                resets.append(context);instance.context=context
                if slow=='reset':clock.advance(.0954625)
            instance.reset=reset;instance.close=lambda:None;instance.cancel=lambda:None
            def create(config):
                if slow=='create':clock.advance(.0954625)
                return instance
            registry=Registry();registry.register(descriptor('aim_native_rmcs_v1','aim','CPU admission fixture',('camera',)),create)
            slot=AdapterSlot(registry,clock)
            def job(obs,pixels,budget):return dict(kind='aim',binding=dict(epoch=1,adapter_id='aim_native_rmcs_v1',config={}),
                observation=obs,native_pixels=pixels,native_consumer=C,sensor_budget=budget,
                native_camera_check=lambda:clock()<obs['wall_deadline'])
            action=action_for(base,'aim','gimbal_target',dict(frame='base_link',yaw_rad=0.,pitch_rad=0.,active=False,confidence=None,fire_permission=False))
            try:
                with patch.object(NativeSourceAdapter,'_act_sensor',side_effect=lambda o,*a,**kw:dict(action,observed_seq=o['observed_seq'],wall_deadline=o['wall_deadline'])) as native:
                    slot.submit(job(base,p,b));old=slot.results.get(timeout=1.)
                    self.assertIsNone(old['error']);self.assertIsNone(old['value'])
                    self.assertEqual(old['discarded_reason'],'original_deadline_expired_after_admission')
                    self.assertEqual(native.call_count,0)
                    self.assertAlmostEqual(old['admission_timings'][slow+'_s'],.0954625)
                    self.assertEqual(base['wall_deadline'],1000.08,'Never refresh old deadline')
                    newer=deepcopy(base);newer['observed_seq']=2;newer['wall_deadline']=clock()+.08
                    pixels=fresh_pixels(p,clock);budget={**b,'frame_id':2,'capture_wall':clock(),'wall_deadline':clock()+.08}
                    slot.submit(job(newer,pixels,budget));new=slot.results.get(timeout=1.)
                    self.assertIsNone(new['error']);self.assertIsNone(new['discarded_reason'])
                    self.assertEqual(native.call_count,1);self.assertEqual(len(resets),1)
                    self.assertEqual(new['value']['observed_seq'],2)
            finally:slot.close();slot.thread.join(1.)

    def test_algorithm_timeout_is_sticky_with_location_only_diagnostic(self):
        class Broken:
            def reset(self,c):pass
            def close(self):pass
            def act(self,o):raise TimeoutError('private-message-must-not-be-logged')
        registry=Registry();registry.register(descriptor('broken','aim','CPU fixture',()),lambda _:Broken())
        clock=Clock();base,p,b=fixture();slot=AdapterSlot(registry,clock)
        try:
            slot.submit(dict(kind='aim',binding=dict(epoch=1,adapter_id='broken',config={}),observation=base))
            result=slot.results.get(timeout=1.)
            self.assertEqual(result['error'],'TimeoutError');self.assertIsNone(result['discarded_reason'])
            diag=result['exception_diagnostic'];self.assertEqual(diag['phase'],'public_act')
            self.assertEqual(diag['frames'][-1]['function'],'act')
            self.assertNotIn('private-message',str(diag));self.assertNotIn('locals',str(diag))
            self.assertEqual(set(diag),{'phase','frames'})
        finally:slot.close();slot.thread.join(1.)

    def test_worker_live_binding_check_rejects_release_even_before_next_capture(self):
        helper=early_fixtures.RuntimePrivateTests();runtime,p,clock,backend,cap,token,epochs=helper.setup_runtime()
        try:
            slot=helper.schedule(runtime,backend);job=slot.jobs[-1]
            self.assertTrue(job['native_camera_check']())
            runtime.control.release(token,RID,epochs)
            # Provider desired still carries the old token: control authority
            # must revoke before its next physics/capture_from_authority tick.
            self.assertTrue(p.desired)
            self.assertFalse(job['native_camera_check']())
        finally:runtime.close()


if __name__=='__main__':unittest.main()
