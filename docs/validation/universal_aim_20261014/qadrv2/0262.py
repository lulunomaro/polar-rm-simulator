"""Independent strict JSON/token/worker checks, with 576-byte CPU images only."""
import base64
from copy import deepcopy
from dataclasses import fields
import json
import threading
import unittest
from unittest.mock import patch
from .adapters import BaseAdapter,Registry,descriptor
from .camera_pixels import VerifiedCameraPixels,encode_camera_pixels
from .contracts import ContractError,action_for,validate_observation
from .native_adapter import NativeSourceAdapter
from .runtime import AdapterSlot
from .test_contracts import sample


def observation():
    o=sample(True);raw=bytes([7])*576
    data,token=encode_camera_pixels(raw,robot_id=o['robot_id'],episode=o['episode'],frame_id=1,
        capture_sim_time=1.,encoding='rgb8',width=16,height=12,stride_bytes=48)
    o['sensors']['camera']['image']['data_base64']=data
    return o,token,raw


class PixelBoundaryTests(unittest.TestCase):
    def test_same_sealed_payload_skips_decode_but_token_never_enters_json_dto(self):
        o,token,raw=observation();decoded={};decoder=base64.b64decode
        with patch('rm_match.platform_v2.contracts.base64.b64decode',wraps=decoder) as decode:
            result=validate_observation(o,image_bytes=decoded,image_token=token)
            self.assertEqual(decode.call_count,0)
        self.assertIs(decoded['raw'],raw);self.assertEqual(set(result),set(o))
        self.assertNotIn('pixel_token',json.dumps(result));self.assertNotIn('raw_bytes',json.dumps(result))
        o['sensors']['camera']['image']['data_base64']='caller mutated after validation'
        self.assertIs(result['sensors']['camera']['image']['data_base64'],token.data_base64)

    def test_equal_new_string_and_wrong_context_frame_shape_encoding_time_fall_back(self):
        original,token,raw=observation();decoder=base64.b64decode
        def payload(o):o['sensors']['camera']['image']['data_base64']=('!'+token.data_base64)[1:]
        def shape(o):o['sensors']['camera']['image'].update(width=2,height=96,stride_bytes=6)
        mutations=[payload,shape,lambda o:o.update(robot_id='other'),lambda o:o.update(episode=2),
            lambda o:o['sensors']['camera'].update(frame_id=2),lambda o:o['sensors']['camera'].update(capture_sim_time=.99),
            lambda o:o['sensors']['camera']['image'].update(encoding='bgr8')]
        for mutate in mutations:
            o=deepcopy(original);mutate(o);decoded={}
            with self.subTest(mutation=mutate),patch('rm_match.platform_v2.contracts.base64.b64decode',wraps=decoder) as decode:
                validate_observation(o,image_bytes=decoded,image_token=token)
                self.assertEqual(decode.call_count,1);self.assertEqual(decoded['raw'],raw)

    def test_unminted_exact_type_cannot_supply_wrong_pixel_pair_or_invalid_payload(self):
        o,token,raw=observation();forged=object.__new__(VerifiedCameraPixels)
        for field in fields(token):object.__setattr__(forged,field.name,getattr(token,field.name))
        object.__setattr__(forged,'raw_bytes',bytes([23])*len(raw))
        decoded={};validate_observation(o,image_bytes=decoded,image_token=forged)
        self.assertEqual(decoded['raw'],raw)
        o['sensors']['camera']['image']['data_base64']='!'*len(token.data_base64)
        object.__setattr__(forged,'data_base64',o['sensors']['camera']['image']['data_base64'])
        with self.assertRaisesRegex(ContractError,'invalid_image_base64'):validate_observation(o,image_token=forged)
        with self.assertRaises(TypeError):VerifiedCameraPixels(raw_bytes=raw,data_base64=o['sensors']['camera']['image']['data_base64'])

    def test_cache_hit_does_not_bypass_other_scalar_metadata_or_unknown_fields(self):
        o,token,_=observation()
        mutations=[lambda v:v['sensors']['camera']['intrinsics'].update(fx=float('nan')),
            lambda v:v['sensors']['camera']['extrinsics'].update(rotation_xyzw=[0.]*4),
            lambda v:v['sensors']['ranges'].update(frame='world'),lambda v:v['own'].update(hp=-1),
            lambda v:v['sensors']['camera']['image'].update(stride_bytes=True),
            lambda v:v['sensors']['camera'].update(pixel_token=token),lambda v:v.update(pixel_token=token)]
        for mutate in mutations:
            bad=deepcopy(o);mutate(bad);decoded={}
            with self.subTest(mutation=mutate),self.assertRaises(ContractError):validate_observation(bad,image_bytes=decoded,image_token=token)
            self.assertEqual(decoded,{})

    def test_old_token_on_new_frame_uses_new_actual_base64_pixels(self):
        o,old,_=observation();new_raw=bytes([31])*576
        data,_=encode_camera_pixels(new_raw,robot_id=o['robot_id'],episode=2,frame_id=2,capture_sim_time=1.,
            encoding='rgb8',width=16,height=12,stride_bytes=48)
        o['episode']=2;o['sensors']['camera']['frame_id']=2;o['sensors']['camera']['image']['data_base64']=data
        decoded={};validate_observation(o,image_bytes=decoded,image_token=old)
        self.assertEqual(decoded['raw'],new_raw)

    def test_direct_default_caller_always_performs_strict_decode(self):
        o,_,_=observation();decoder=base64.b64decode
        with patch('rm_match.platform_v2.contracts.base64.b64decode',wraps=decoder) as decode:
            validate_observation(o);self.assertEqual(decode.call_count,1)
        o['sensors']['camera']['image']['data_base64']='invalid'
        with self.assertRaises(ContractError):validate_observation(o)

    def test_only_inherited_native_act_uses_private_token_generic_and_override_decode(self):
        class Probe(NativeSourceAdapter):
            def __init__(self):
                self.process=None;self._cancelled=threading.Event();self._lifecycle_lock=threading.Lock();self.received=None
            def reset(self,context):BaseAdapter.reset(self,context)
            def close(self):pass
            def _act_sensor(self,o,hold,emit,*,decoded_image=None):
                self.received=(o,decoded_image)
                return emit(dict(frame='base_link',yaw_rad=0.,pitch_rad=0.,active=False,confidence=None,fire_permission=False))
        class Override(Probe):
            def act(self,o):
                self.received=(o,None)
                return action_for(o,'aim','gimbal_target',dict(frame='base_link',yaw_rad=0.,pitch_rad=0.,active=False,confidence=None,fire_permission=False))
        class Generic(BaseAdapter):
            def act(self,o):
                self.received=(o,None)
                return action_for(o,'aim','gimbal_target',dict(frame='base_link',yaw_rad=0.,pitch_rad=0.,active=False,confidence=None,fire_permission=False))
        for kind,expected_decode in ((Probe,0),(Override,1),(Generic,1)):
            o,token,raw=observation();o['wall_deadline']=2.;instance=kind();registry=Registry()
            registry.register(descriptor('test','aim','tiny fixture',()),lambda _:instance)
            slot=AdapterSlot(registry,lambda:1.);decoder=base64.b64decode
            try:
                with self.subTest(adapter=kind),patch('rm_match.platform_v2.contracts.base64.b64decode',wraps=decoder) as decode:
                    slot.submit(dict(kind='aim',binding=dict(epoch=1,adapter_id='test',config={}),observation=o,pixel_token=token))
                    result=slot.results.get(timeout=2.)
                    self.assertIsNone(result['error']);self.assertEqual(decode.call_count,expected_decode)
                    self.assertEqual(set(instance.received[0]),set(o));json.dumps(instance.received[0])
                    if kind is Probe:self.assertIs(instance.received[1],raw)
                    else:self.assertIsNone(instance.received[1])
            finally:slot.close();slot.thread.join(2.)


if __name__=='__main__':unittest.main()
