"""Exact raw-pixel serialization regressions; no GL/native process or NN."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from .native_image import prepare_native_image


class NativeImageTests(unittest.TestCase):
    def verify(self,rgb,fallback=False):
        before=rgb.copy()
        expected=np.ascontiguousarray(rgb[:,:,::-1]).tobytes()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input.bgr'
            if fallback:
                with patch('rm_match.platform_v2.native_image._opencv',None):result=prepare_native_image(rgb,path,trace_rgb=True)
            else:result=prepare_native_image(rgb,path,trace_rgb=True)
            image,rgb_sha,stages=result
            self.assertEqual(path.read_bytes(),expected)
            self.assertEqual(image['sha256'],hashlib.sha256(expected).hexdigest())
            self.assertEqual(rgb_sha,hashlib.sha256(rgb.tobytes()).hexdigest())
            self.assertEqual(image['bytes'],rgb.size);self.assertEqual(image['stride_bytes'],rgb.shape[1]*3)
            self.assertEqual(set(image),{'encoding','width','height','stride_bytes','bytes','sha256','path'})
            self.assertEqual(stages['clock_domain'],'host_perf_counter')
            self.assertTrue(all(v>=0 for k,v in stages.items() if k.endswith('_s')))
            np.testing.assert_array_equal(rgb,before)

    def test_full_native_resolution_exact_channel_bytes_and_sha(self):
        rgb=np.random.default_rng(729).integers(0,256,(1080,1440,3),dtype=np.uint8)
        self.verify(rgb);self.verify(rgb,True)

    def test_known_rgb_channel_order(self):
        self.verify(np.array([[[255,0,0],[0,255,0],[0,0,255],[3,2,1]]],dtype=np.uint8))

    def test_strided_reversed_and_readonly_pixels_remain_exact(self):
        rgb=np.arange(8*9*3,dtype=np.uint8).reshape(8,9,3)[::2,::-1,:]
        rgb.setflags(write=False)
        self.verify(rgb);self.verify(rgb,True)

    def test_invalid_pixels_rejected_before_file_creation(self):
        for value in (np.zeros((2,3,3),dtype=float),np.zeros((2,3),dtype=np.uint8),np.zeros((0,3,3),dtype=np.uint8),np.zeros((2,3,4),dtype=np.uint8)):
            with self.assertRaises(ValueError):prepare_native_image(value,'must_not_create.bgr')

    def test_trace_off_does_not_compute_or_return_rgb_sha(self):
        with tempfile.TemporaryDirectory() as directory:
            _,rgb_sha,stages=prepare_native_image(np.zeros((2,2,3),dtype=np.uint8),Path(directory)/'input.bgr')
            self.assertIsNone(rgb_sha);self.assertGreaterEqual(stages['rgb_trace_sha256_s'],0)

    def test_private_immutable_snapshot_exact_and_no_artifact_open(self):
        rgb=np.array([[[1,2,3],[4,5,6]]],dtype=np.uint8)
        with patch.object(Path,'open',side_effect=AssertionError('No artifact I/O permitted')):
            image,_,_,raw=prepare_native_image(rgb,'record_only/sensor_input.bgr',return_bytes=True,write_artifact=False)
        self.assertIs(type(raw),bytes);self.assertEqual(raw,b'\x03\x02\x01\x06\x05\x04')
        self.assertEqual(image['sha256'],hashlib.sha256(raw).hexdigest())
        rgb[:]=0;self.assertEqual(raw,b'\x03\x02\x01\x06\x05\x04')
        with self.assertRaises(TypeError):raw[0]=1

    def test_no_artifact_without_private_byte_snapshot_rejected(self):
        with self.assertRaises(ValueError):prepare_native_image(np.zeros((1,1,3),dtype=np.uint8),'unused',write_artifact=False)
