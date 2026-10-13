"""Explicit local codec enum and scalar publication-rejection evidence."""
import base64
from dataclasses import replace
import unittest
from unittest.mock import patch
from .camera import CameraProvider
from .camera_pixels import encode_camera_pixels
from .test_native_early_pixels import provider_fixture,fixture,RID


class CameraCodecBoundaryTests(unittest.TestCase):
    def factory(self,raw,**extra):
        return encode_camera_pixels(raw,robot_id=RID,episode=1,frame_id=1,capture_sim_time=1.,
            encoding='rgb8',width=16,height=12,stride_bytes=48,**extra)

    def test_default_factory_encoder_call_remains_original_positional(self):
        base,p,b=fixture();expected=base64.b64encode(p.raw_bytes).decode('ascii')
        with patch('rm_match.platform_v2.camera.encode_raw_base64',return_value=expected) as encoder:
            data,token=self.factory(p.raw_bytes)
            encoder.assert_called_once_with(p.raw_bytes)
        self.assertEqual(data,expected);self.assertIs(token.raw_bytes,p.raw_bytes)

    def test_no_callback_unknown_enum_or_mutable_bytes(self):
        base,p,b=fixture()
        for codec in (lambda raw:'',None,True,'auto','pybase64','pybase64_1_5_0'):
            with self.subTest(codec=codec),self.assertRaises(ValueError):self.factory(p.raw_bytes,raw_base64_codec=codec)
        with self.assertRaises(ValueError):self.factory(bytearray(p.raw_bytes))

    def test_explicit_verified_c_codec_exact_payload_and_token_pair(self):
        from .base64_codec import load_raw_encoder,raw_encoder_metadata
        base,p,b=fixture();encoder=load_raw_encoder('pybase64_1_5_1')
        data,token=self.factory(p.raw_bytes,raw_base64_codec='pybase64_1_5_1')
        self.assertEqual(data,base64.b64encode(p.raw_bytes).decode('ascii'))
        self.assertIs(token.raw_bytes,p.raw_bytes)
        self.assertIs(encoder,load_raw_encoder('pybase64_1_5_1'))
        metadata=raw_encoder_metadata('pybase64_1_5_1')
        self.assertEqual(metadata['version'],'1.5.1');self.assertEqual(len(metadata['extension_sha256']),64)

    def test_provider_setup_keeps_extension_identity_private_and_status_scalar(self):
        from .backend import MuJoCoBackend
        backend=MuJoCoBackend(camera=True)
        try:
            p=CameraProvider(backend._sim,raw_base64_codec='pybase64_1_5_1')
            self.assertIsNotNone(p._raw_encoder)
            self.assertEqual(p._raw_encoder_metadata['version'],'1.5.1')
            status=p.status()
            self.assertEqual(status['raw_base64_codec'],'pybase64_1_5_1')
            self.assertNotIn('extension_path',status);self.assertNotIn('extension_sha256',status)
            self.assertIsNone(p.thread,'Setup must not start a renderer or capture')
            p.stop()
        finally:backend.close()

    def test_private_reject_reasons_are_actual_scalar_guard_results(self):
        for mode,expected in [('stop','runtime_stopped'),('fault','camera_fault'),('episode','episode_changed'),
                              ('release','capture_revoked'),('expire','native_80ms_expired'),('watch_only','no_native_consumer')]:
            p,clock,base,b=provider_fixture();events=[];p.native_pixels_hook=events.append;cap=p.pending[RID]
            if mode=='stop':p.stopped.set()
            elif mode=='fault':p.error='internal-details-not-published'
            elif mode=='episode':p.episode=2
            elif mode=='release':p.desired={}
            elif mode=='expire':clock.advance(.081)
            else:cap=replace(cap,consumers=frozenset((('watch','fixture_owner',1),)))
            with self.subTest(mode=mode):
                raw=p._publish_native_pixels(cap,p.rgb)
                self.assertEqual(len(raw),16*12*3);self.assertEqual(p.native_cache,{})
                self.assertEqual(len(events),1);self.assertEqual(events[0]['event'],'private_publish_rejected')
                self.assertEqual(events[0]['reason'],expected)
                self.assertEqual(events[0]['capture_wall'],1000.)
                self.assertNotIn('raw_bytes',events[0]);self.assertNotIn('internal-details',str(events[0]))


if __name__=='__main__':unittest.main()
