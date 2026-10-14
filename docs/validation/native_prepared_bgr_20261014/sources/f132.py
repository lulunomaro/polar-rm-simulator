"""Small CPU fixtures for private decoded pixels and atomic camera identities."""
import base64
from copy import deepcopy
import threading
import unittest
from unittest.mock import patch

from .adapters import BaseAdapter,Registry,descriptor
from .contracts import ContractError,validate_observation
from .native_adapter import NativeSourceAdapter
from .runtime import AdapterSlot,PlatformRuntime
from .test_contracts import sample
from .test_control import Clock
from .test_runtime import FakeBackend


class DecodedRaceTests(unittest.TestCase):
    def test_mutable_caller_cannot_split_decoded_pixels_from_returned_frame(self):
        from . import contracts
        original=sample(True);image=original['sensors']['camera']['image']
        old_pixels=base64.b64decode(image['data_base64']);new_pixels=bytes([19])*len(old_pixels)
        validator=contracts.validate_camera
        def change_caller_after_decode(camera,sim_time):
            decoded=validator(camera,sim_time)
            original['sensors']['camera']['frame_id']=2
            image['data_base64']=base64.b64encode(new_pixels).decode()
            return decoded
        decoded={}
        with patch.object(contracts,'validate_camera',side_effect=change_caller_after_decode):
            checked=validate_observation(original,image_bytes=decoded)
        self.assertEqual(base64.b64decode(checked['sensors']['camera']['image']['data_base64']),decoded['raw'])
        self.assertEqual(checked['sensors']['camera']['frame_id'],1)
        self.assertEqual(original['sensors']['camera']['frame_id'],2)

    def test_non_json_equality_objects_cannot_cross_strict_observation_boundary(self):
        class PretendEqual:
            def __eq__(self,other):return True
            def __ne__(self,other):return False
        cases=[('schema',),('frames',),('frames','world'),('referee','phase'),('sensors','camera','reason'),
            ('sensors','camera','provenance'),('sensors','camera','image','encoding'),
            ('sensors','camera','image','stride_bytes'),
            ('sensors','camera','intrinsics','distortion_model'),('sensors','camera','extrinsics','parent_frame'),
            ('sensors','ranges','reason'),('sensors','ranges','frame'),('sensors','ranges','provenance')]
        for fields in cases:
            o=sample(True);selected=o
            for field in fields[:-1]:selected=selected[field]
            selected[fields[-1]]=PretendEqual()
            with self.subTest(field=fields),self.assertRaises(ContractError):validate_observation(o,image_bytes={})

    def test_slot_private_bytes_are_fresh_per_frame_and_epoch_not_dto_fields(self):
        class Probe(NativeSourceAdapter):
            def __init__(self):
                self._cancelled=threading.Event();self._lifecycle_lock=threading.Lock();self.process=None;self.seen=[]
            def reset(self,context):BaseAdapter.reset(self,context)
            def close(self):pass
            def _act_validated(self,*args):raise AssertionError('An override must not bypass the base trusted entry')
            def _act_sensor(self,o,hold,emit,*,decoded_image=None):
                self.seen.append((deepcopy(o),decoded_image))
                return emit(dict(frame='base_link',yaw_rad=0.,pitch_rad=0.,active=False,confidence=None,fire_permission=False))
        instances=[];registry=Registry()
        def create(_):p=Probe();instances.append(p);return p
        registry.register(descriptor('probe','aim','small fixture',()),create);slot=AdapterSlot(registry,lambda:1.)
        def run(frame,epoch,observed_epoch=None):
            o=sample(True);o.update(wall_deadline=2.,binding_epoch=epoch if observed_epoch is None else observed_epoch,observed_seq=frame)
            c=o['sensors']['camera'];c['frame_id']=frame;c['image']['data_base64']=base64.b64encode(bytes([frame])*576).decode()
            slot.submit(dict(observation=o,kind='aim',binding=dict(epoch=epoch,adapter_id='probe',config={})))
            return slot.results.get(timeout=2.)
        try:
            first=run(1,1);second=run(2,1)
            self.assertIsNone(first['error']);self.assertIsNone(second['error'])
            self.assertEqual([v[1][0] for v in instances[0].seen],[1,2])
            self.assertTrue(all(type(v[1]) is bytes for v in instances[0].seen))
            self.assertEqual(set(instances[0].seen[0][0]),set(sample(True)))
            mismatch=run(3,2,1);self.assertEqual(mismatch['error'],'ContractError')
            self.assertEqual(instances[1].seen,[])
            fresh=run(4,3);self.assertIsNone(fresh['error']);self.assertEqual(instances[2].seen[0][1][0],4)
        finally:slot.close();slot.thread.join(2.)


class CameraSchedulingRaceTests(unittest.TestCase):
    def test_marker_uses_actual_packet_when_frame_publishes_between_reads(self):
        clock=Clock();backend=FakeBackend(ids=('red_sentry',))
        class Camera:
            max_views=1;frame=1
            def sensor_identity(self,*args):return self.frame,1000.,0.
            def sensor_packet(self,*args):
                self.frame=2  # Encode worker publishes after the cheap identity read.
                camera=deepcopy(sample(True)['sensors']['camera']);camera.update(frame_id=2,capture_sim_time=0.)
                return dict(camera=camera,budget=dict(frame_id=2,capture_wall=1000.,capture_sim_time=0.,wall_deadline=1000.2,sim_deadline=.2))
            def stop(self):pass
            def status(self):return {}
        class Slot:
            lifecycle_error=None
            def __init__(self,*args):self.jobs=[]
            def submit(self,job):self.jobs.append(job)
            def close(self):pass
        registry=Registry();registry.register(descriptor('camera','aim','small fixture',('camera',),
            schedule_on_camera_frame=True,max_camera_age_sim_s=.08,max_camera_age_wall_s=.08),lambda _:None)
        runtime=PlatformRuntime(backend,registry=registry,camera=Camera(),clock=clock);runtime._episode=0
        try:
            token=runtime.control.open_session('operator')['token'];epochs=runtime.control.claim(token,'red_sentry',['gimbal'])['lease_epochs']
            runtime.bind(token,'red_sentry','aim',epochs,'camera',{})
            with patch('rm_match.platform_v2.runtime.AdapterSlot',Slot):
                runtime._schedule(runtime.control.snapshot(),0.)
                slot=runtime.slots['red_sentry','aim'];self.assertEqual(slot.jobs[0]['sensor_budget']['frame_id'],2)
                clock.advance(.002);backend.sim_time=.002
                runtime._schedule(runtime.control.snapshot(),.002)
                self.assertEqual(len(slot.jobs),1,'Already enqueued actual frame B must not be enqueued again')
        finally:runtime.close()


if __name__=='__main__':unittest.main()
