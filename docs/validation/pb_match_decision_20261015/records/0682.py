"""Pixel-byte preservation at every base64 chunk/padding boundary."""
import base64
import unittest
from unittest.mock import patch
from .camera import encode_raw_base64, RAW_BASE64_CHUNK_BYTES


class RawEncodingTests(unittest.TestCase):
    def test_equal_to_single_encode_including_all_padding_remainders(self):
        chunk=RAW_BASE64_CHUNK_BYTES
        for size in (0,1,2,3,4,5,chunk-2,chunk-1,chunk,chunk+1,chunk+2,
                     2*chunk-1,2*chunk,2*chunk+1,1440*1080*3):
            with self.subTest(size=size):
                raw=(bytes(range(256))*((size+255)//256))[:size]
                result=encode_raw_base64(raw)
                self.assertEqual(result,base64.b64encode(raw).decode('ascii'))
                self.assertEqual(base64.b64decode(result,validate=True),raw)
                self.assertEqual(len(result),4*((size+2)//3))

    def test_working_chunk_size_is_bounded_and_yielded(self):
        original=base64.b64encode
        sizes=[]
        def encode(value):
            sizes.append(len(value));return original(value)
        with patch('rm_match.platform_v2.camera.base64.b64encode',side_effect=encode), \
             patch('rm_match.platform_v2.camera.time.sleep') as yield_thread:
            encode_raw_base64(b'x'*(2*RAW_BASE64_CHUNK_BYTES+1))
        self.assertEqual(sizes,[RAW_BASE64_CHUNK_BYTES,RAW_BASE64_CHUNK_BYTES,1])
        self.assertEqual(yield_thread.call_count,2)
        yield_thread.assert_called_with(0)


if __name__=='__main__':unittest.main()
