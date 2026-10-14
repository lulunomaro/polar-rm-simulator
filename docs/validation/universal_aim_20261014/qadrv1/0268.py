"""Strict decoded image handover and original capture wall-budget regressions."""
import base64
from copy import deepcopy
import queue
import unittest
from unittest.mock import patch

from .adapters import raw_observation,Registry,descriptor
from .contracts import validate_observation,ContractError
from .runtime import AdapterSlot,PlatformRuntime
from .test_contracts import sample
from .test_control import Clock
from .test_runtime import FakeBackend
from .native_adapter import NativeSourceAdapter


class DecodedBoundaryTests(unittest.TestCase):
    def test_single_strict_decode_is_private_immutable_and_pixel_exact(self):
        o=sample(True);image=o['sensors']['camera']['image']
        expected=base64.b64decode(image['data_base64']);decoded={}
        with patch('rm_match.platform_v2.contracts.base64.b64decode',wraps=base64.b64decode) as decoder:
            checked=validate_observation(o,image_bytes=decoded)
            raw=raw_observation(checked,decoded_image=decoded['raw'])
            self.assertEqual(decoder.call_count,1)
        self.assertEqual(raw.rgb.tobytes(),expected)
        self.assertFalse(raw.rgb.flags.writeable)
        self.assertEqual(set(checked),set(o))
        image['data_base64']='caller replaced image after validation'
        self.assertEqual(raw.rgb.tobytes(),expected)
        with self.assertRaises(ValueError):raw.rgb[0,0,0]=0

    def test_bad_image_or_private_fields_fail_before_decoded_handover(self):
        for mutate in (lambda o:o['sensors']['camera']['image'].update(data_base64='$$'),
                       lambda o:o['sensors']['camera']['image'].update(data_base64=base64.b64encode(b'x').decode()),
                       lambda o:o['sensors']['camera'].update(world_target=[1,2,3])):
            with self.subTest(mutation=mutate):
                o=sample(True);mutate(o);decoded={}
                with self.assertRaises(ContractError):validate_observation(o,image_bytes=decoded)
                self.assertEqual(decoded,{})

    def test_override_act_is_respected_by_native_worker(self):
        class CustomNative(NativeSourceAdapter):
            def __init__(self):self.called=False
            def reset(self,context):self.context=context
            def close(self):pass
            def cancel(self):pass
            def act(self,o):
                from .contracts import action_for
                self.called=True
                return action_for(o,'aim','gimbal_target',dict(frame='base_link',yaw_rad=0.,pitch_rad=0.,active=False,confidence=None,fire_permission=False))
        instance=CustomNative();r=Registry();r.register(descriptor('custom','aim','fixture',()),lambda _:instance)
        slot=AdapterSlot(r,lambda:1.)
        try:
            o=sample(True);o['wall_deadline']=2.
            slot.submit(dict(observation=o,kind='aim',binding={'epoch':o['binding_epoch'],'adapter_id':'custom','config':{}}))
            result=slot.results.get(timeout=2.)
            self.assertIsNone(result['error']);self.assertTrue(instance.called)
        finally:slot.close();slot.thread.join(2.)

    def test_native_capture_wall_age_is_capped_at_80ms_before_worker(self):
        class Camera:
            max_views=1
            def sensor_packet(self,*args):
                return dict(camera=deepcopy(sample(True)['sensors']['camera']),
                    budget=dict(capture_wall=1000.,wall_deadline=1000.2,capture_sim_time=0.,sim_deadline=.2))
            def stop(self):pass
            def status(self):return {}
        class Slot:
            lifecycle_error=None
            def __init__(self,*args):self.jobs=[]
            def submit(self,job):self.jobs.append(job)
            def close(self):pass
        r=Registry();r.register(descriptor('native','aim','fixture',('camera',),max_camera_age_sim_s=.08,max_camera_age_wall_s=.08),lambda _:None)
        clock=Clock();clock.advance(.03);backend=FakeBackend(ids=('red_sentry',))
        runtime=PlatformRuntime(backend,registry=r,camera=Camera(),clock=clock);runtime._episode=backend.episode
        try:
            token=runtime.control.open_session('operator')['token']
            epochs=runtime.control.claim(token,'red_sentry',['gimbal'])['lease_epochs']
            runtime.bind(token,'red_sentry','aim',epochs,'native',{})
            with patch('rm_match.platform_v2.runtime.AdapterSlot',Slot):runtime._schedule(runtime.control.snapshot(),backend.sim_time)
            job=runtime.slots['red_sentry','aim'].jobs[0]
            self.assertEqual(job['sensor_budget']['wall_deadline'],1000.08)
            self.assertEqual(job['observation']['wall_deadline'],1000.08)
            self.assertEqual(job['sensor_budget']['sim_deadline'],.08)
            self.assertFalse(runtime._budget_valid(job['sensor_budget'],1000.081,0.))
        finally:runtime.close()

    def test_new_camera_frame_wakes_before_period_without_duplicate_or_stale_job(self):
        clock=Clock();backend=FakeBackend(ids=('red_sentry',))
        class Camera:
            max_views=1;frame_id=1;capture_wall=clock();capture_sim=0.
            def sensor_identity(self,*args):return (self.frame_id,self.capture_wall,self.capture_sim)
            def sensor_packet(self,*args):
                c=deepcopy(sample(True)['sensors']['camera']);c.update(frame_id=self.frame_id,capture_sim_time=self.capture_sim)
                return dict(camera=c,budget=dict(frame_id=self.frame_id,capture_wall=self.capture_wall,
                    capture_sim_time=self.capture_sim,wall_deadline=self.capture_wall+.2,sim_deadline=self.capture_sim+.2))
            def stop(self):pass
            def status(self):return {}
        class Slot:
            lifecycle_error=None
            def __init__(self,*args):self.jobs=[]
            def submit(self,job):self.jobs.append(job)
            def close(self):pass
        registry=Registry();registry.register(descriptor('camera_paced','aim','fixture',('camera',),
            max_camera_age_sim_s=.08,max_camera_age_wall_s=.08,schedule_on_camera_frame=True),lambda _:None)
        camera=Camera();runtime=PlatformRuntime(backend,registry=registry,camera=camera,clock=clock);runtime._episode=backend.episode
        try:
            token=runtime.control.open_session('operator')['token'];epochs=runtime.control.claim(token,'red_sentry',['gimbal'])['lease_epochs']
            runtime.bind(token,'red_sentry','aim',epochs,'camera_paced',{})
            with patch('rm_match.platform_v2.runtime.AdapterSlot',Slot):
                runtime._schedule(runtime.control.snapshot(),backend.sim_time)
                slot=runtime.slots['red_sentry','aim'];self.assertEqual(len(slot.jobs),1)
                clock.advance(.004);backend.sim_time=.004;camera.frame_id=2;camera.capture_wall=clock();camera.capture_sim=.004
                runtime._schedule(runtime.control.snapshot(),backend.sim_time)
                self.assertEqual(len(slot.jobs),2)
                self.assertEqual(slot.jobs[-1]['sensor_budget']['frame_id'],2)
                clock.advance(.06);backend.sim_time=.064
                runtime._schedule(runtime.control.snapshot(),backend.sim_time)
                self.assertEqual(len(slot.jobs),2,'Repeated frame must not be revalidated on each control period')
                clock.advance(.03);backend.sim_time=.094;camera.frame_id=3
                runtime._schedule(runtime.control.snapshot(),backend.sim_time)
                self.assertEqual(len(slot.jobs),2,'Late frames retain their original deadline')
                runtime.control.release(token,'red_sentry',epochs)
                runtime._schedule(runtime.control.snapshot(),backend.sim_time)
                self.assertNotIn(('red_sentry','aim'),runtime._camera_samples)
        finally:runtime.close()


if __name__=='__main__':unittest.main()
