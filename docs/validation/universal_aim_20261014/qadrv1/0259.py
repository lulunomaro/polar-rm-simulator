"""Producer-only immutable token, cache gates and JSON privacy, without GL."""
import base64
import copy
from dataclasses import FrozenInstanceError
import gc
import json
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch
import weakref
import numpy as np
from .camera import CameraProvider,Capture
from .camera_pixels import VerifiedCameraPixels,encode_camera_pixels


class PixelTokenTests(unittest.TestCase):
    def token(self):
        raw=bytes(range(24))
        data,token=encode_camera_pixels(raw,robot_id='red_sentry',episode=2,frame_id=11,capture_sim_time=.02,
            encoding='rgb8',width=4,height=2,stride_bytes=12)
        camera=dict(frame_id=11,capture_sim_time=.02,image=dict(encoding='rgb8',width=4,height=2,stride_bytes=12,data_base64=data))
        return raw,token,camera

    def test_raw_only_factory_one_canonical_encoding_and_same_immutable_snapshot(self):
        from . import camera
        with patch.object(camera,'encode_raw_base64',wraps=camera.encode_raw_base64) as encoder:
            raw,token,value=self.token()
        self.assertEqual(encoder.call_count,1);self.assertIs(encoder.call_args.args[0],raw)
        self.assertIs(token.raw_bytes,raw);self.assertEqual(base64.b64decode(value['image']['data_base64'],validate=True),raw)
        self.assertTrue(token.matches(value,robot_id='red_sentry',episode=2))
        self.assertIs(copy.deepcopy(token),token)
        with self.assertRaises(FrozenInstanceError):token.frame_id=12
        self.assertNotIn(value['image']['data_base64'],repr(token))

    def test_direct_constructor_and_unminted_object_cannot_pair_raw_and_payload(self):
        raw,token,value=self.token()
        with self.assertRaises(TypeError):VerifiedCameraPixels()
        with self.assertRaises(TypeError):VerifiedCameraPixels(raw_bytes=raw,data_base64='not_real')
        forged=object.__new__(VerifiedCameraPixels)
        self.assertFalse(forged.matches(value,robot_id='red_sentry',episode=2))
        class ForgedSubclass(VerifiedCameraPixels):pass
        self.assertFalse(object.__new__(ForgedSubclass).matches(value,robot_id='red_sentry',episode=2))

    def test_invalid_base64_cannot_be_injected_via_factory_or_reused_token(self):
        raw,token,value=self.token()
        with self.assertRaises(TypeError):
            encode_camera_pixels(raw,robot_id='red_sentry',episode=2,frame_id=11,capture_sim_time=.02,
                encoding='rgb8',width=4,height=2,stride_bytes=12,data_base64='!'*32)
        value['image']['data_base64']='!'*32
        self.assertFalse(token.matches(value,robot_id='red_sentry',episode=2))
        with self.assertRaises(ValueError):base64.b64decode(value['image']['data_base64'],validate=True)

    def test_equal_payload_new_object_or_wrong_metadata_never_matches(self):
        _,token,value=self.token();clone=copy.deepcopy(value)
        clone['image']['data_base64']=value['image']['data_base64'].encode().decode()
        self.assertEqual(clone['image']['data_base64'],token.data_base64);self.assertIsNot(clone['image']['data_base64'],token.data_base64)
        self.assertFalse(token.matches(clone,robot_id='red_sentry',episode=2))
        for key,bad in [('frame_id',12),('frame_id',True),('capture_sim_time',.03),('capture_sim_time',True)]:
            changed=copy.deepcopy(value);changed[key]=bad
            self.assertFalse(token.matches(changed,robot_id='red_sentry',episode=2))
        for key,bad in [('encoding','bgr8'),('width',True),('width',5),('height',3),('stride_bytes',13)]:
            changed=copy.deepcopy(value);changed['image'][key]=bad
            self.assertFalse(token.matches(changed,robot_id='red_sentry',episode=2))
        for rid,episode in [('blue_sentry',2),('red_sentry',3),('red_sentry',True)]:
            self.assertFalse(token.matches(value,robot_id=rid,episode=episode))

    def test_token_registry_has_no_permanent_pixel_or_token_retention(self):
        _,token,value=self.token();reference=weakref.ref(token);del token;gc.collect()
        self.assertIsNone(reference());self.assertTrue(value['image']['data_base64'])

    def provider(self):
        p=CameraProvider.__new__(CameraProvider);p.profile=SimpleNamespace(width=4,height=2)
        p.calibrations={'red_sentry':dict(intrinsics={},extrinsics={})};p.clock=lambda:0.
        p.lock=threading.Lock();p.stopped=threading.Event();p.error=None;p.episode=2;p.ttl=2.5
        key=('adapter','red_sentry','aim','session',7)
        cap=Capture('red_sentry',2,11,0.,0.,frozenset({key}),None,{},())
        rgb=np.arange(24,dtype=np.uint8).reshape(2,4,3)
        value=p._encode(cap,rgb);p.cache={'red_sentry':value};p.display_cache={};p.display_error=None
        return p,key,value,rgb

    def test_cache_token_same_pixels_internal_only_not_camera_json(self):
        p,key,value,rgb=self.provider();expected=rgb.tobytes();rgb[:]=0
        packet=p.sensor_packet('red_sentry',2,key,0.,.08);token=packet['pixel_token']
        self.assertIs(token,value['pixel_token']);self.assertEqual(token.raw_bytes,expected)
        self.assertTrue(token.matches(packet['camera'],robot_id='red_sentry',episode=2))
        dto=p.sensor_camera('red_sentry',2,key,0.,.08)
        self.assertNotIn('pixel_token',dto);self.assertNotIn('raw_bytes',dto);json.dumps(dto)
        self.assertEqual(set(dto['image']),{'encoding','width','height','stride_bytes','data_base64'})

    def test_expired_or_wrong_generation_packet_exposes_no_token(self):
        p,key,_,_=self.provider()
        for rid,episode,consumer,sim_time in [('blue_sentry',2,key,0.),('red_sentry',3,key,0.),('red_sentry',2,('old',),0.),('red_sentry',2,key,.081)]:
            self.assertIsNone(p.sensor_packet(rid,episode,consumer,sim_time,.08)['pixel_token'])
        p.clock=lambda:.081;self.assertIsNone(p.sensor_packet('red_sentry',2,key,0.,.08)['pixel_token'])
        p.clock=lambda:0.;p.stopped.set();self.assertIsNone(p.sensor_packet('red_sentry',2,key,0.,.08)['pixel_token'])


if __name__=='__main__':unittest.main()
