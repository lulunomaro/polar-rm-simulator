"""CPU recording transport only; no ELF, NN, GL or real-time acceptance claim."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from . import test_native_adapter as native_fixtures
from .native_adapter import NativeSourceAdapter
from .wsl_native_adapter import WslNativeSourceAdapter
from .native_camera_snapshot import mint_native_snapshot
from .native_evidence import ActualFrameEvidenceWriter
from .native_image import prepare_native_image


class RecordingTransport:
    def __init__(self):self.calls=[];self.closed=False
    def control(self,packet):
        self.calls.append(packet)
        return dict(should_control=False,observation_shoot_allowed=False,target_age_s=None)
    def close(self):self.closed=True


class DeferredTraceTests(unittest.TestCase):
    def setUp(self):
        self.fixture=native_fixtures.NativeTests();self.fixture.setUp()
        self.o=self.fixture.observation();image=self.o['sensors']['camera']['image']
        # Deliberately distinct channels: black-only fixtures cannot detect a
        # missed/double channel swap. These are explicitly synthetic CPU pixels.
        self.rgb=np.arange(image['width']*image['height']*3,dtype=np.uint8).reshape(image['height'],image['width'],3)
        self.raw=self.rgb.tobytes();image['data_base64']=base64.b64encode(self.raw).decode('ascii')
        self.bgr=self.rgb[:,:,::-1].copy().tobytes()
        self.rgb_sha=hashlib.sha256(self.raw).hexdigest();self.bgr_sha=hashlib.sha256(self.bgr).hexdigest()
    def tearDown(self):self.fixture.tearDown()

    def run_case(self,*,private,inline):
        events=[];a=NativeSourceAdapter({},spec_path=self.fixture.spec,out=self.fixture.root/'out',trace=events.append)
        a.reset(dict(episode=1,robot_id='red_sentry',binding_epoch=1))
        if inline:
            # Exact reviewed class with a recording transport fixture; real WSL
            # startup is intentionally outside this CPU boundary regression.
            a.__class__=WslNativeSourceAdapter;a.transport='wsl_stdio_bgr_v2'
        a.directory=self.fixture.root/('private' if private else 'public');a.directory.mkdir()
        a.process=RecordingTransport();process=a.process
        if inline:a._evidence_writer=ActualFrameEvidenceWriter(a.directory/'actual_frames')
        a.stable_since=.5;a.anchor=[0.,0.]
        o=deepcopy(self.o)
        try:
            with patch('rm_match.platform_v2.native_adapter.prepare_native_image',wraps=prepare_native_image) as prepared:
                if private:
                    cam=o['sensors']['camera'];consumer=('adapter','red_sentry','aim','CPU_fixture_owner',1)
                    pixels=mint_native_snapshot(self.raw,robot_id='red_sentry',episode=1,frame_id=cam['frame_id'],
                        capture_wall=1000.,capture_sim_time=cam['capture_sim_time'],consumers=frozenset((consumer,)),
                        **{k:cam['image'][k] for k in ('width','height','stride_bytes')},
                        own={k:cam[k] for k in ('own_qpos_at_capture','own_qvel_at_capture','own_odom_at_capture','own_odom_velocity_at_capture')},
                        intrinsics=cam['intrinsics'],extrinsics=cam['extrinsics'])
                    o['sensors']['camera']=dict(available=False,reason='calibrated_camera_unavailable');o['wall_deadline']=1000.08
                    budget=dict(robot_id='red_sentry',episode=1,frame_id=1,capture_wall=1000.,capture_sim_time=1.,wall_deadline=1000.08,sim_deadline=1.08)
                    if inline:
                        with patch('rm_match.platform_v2.native_image.np.ascontiguousarray',side_effect=AssertionError('synchronous RGB trace hash forbidden')):
                            action=a._act_native_pixels(o,pixels,consumer=consumer,budget=budget,now=1000.01)
                    else:action=a._act_native_pixels(o,pixels,consumer=consumer,budget=budget,now=1000.01)
                else:action=a.act(o)
                self.assertEqual(prepared.call_args.kwargs['trace_rgb'],not (private and inline))
                actual_rgb=prepared.call_args.args[0]
                self.assertEqual(actual_rgb.tobytes(),self.raw)
                self.assertFalse(actual_rgb.flags.writeable)
            self.assertFalse(action['command']['active'],'Recording fixture never claims a native command')
            self.assertEqual(len(process.calls),1)
            packet=process.calls[0];self.assertEqual(packet['frame']['image']['sha256'],self.bgr_sha)
            if inline:
                self.assertIs(type(packet['image_bytes']),bytes)
                self.assertEqual(packet['image_bytes'],self.bgr)
                self.assertEqual(packet['host_deadline'],o['wall_deadline'])
            else:self.assertEqual(Path(packet['frame']['image']['path']).read_bytes(),self.bgr)
            requests=[e for e in events if e['event']=='native_request'];self.assertEqual(len(requests),1)
            trace=requests[0];self.assertEqual(trace['raw_bgr_sha256'],self.bgr_sha)
            if private and inline:
                self.assertIsNone(trace['raw_rgb_sha256'])
                self.assertEqual(trace['rgb_trace_strategy'],'archived_bgr_postclose_exact_channel_swap')
            else:
                self.assertEqual(trace['raw_rgb_sha256'],self.rgb_sha)
                self.assertEqual(trace['rgb_trace_strategy'],'synchronous_rgb_sha256')
            a.close()
            if inline:
                archived=a.directory/'actual_frames'/'sensor_1.bgr'
                self.assertEqual(archived.read_bytes(),self.bgr)
                manifest=json.loads(archived.with_suffix('.json').read_text())
                self.assertEqual(manifest['sha256'],self.bgr_sha)
                reconstructed=np.frombuffer(archived.read_bytes(),np.uint8).reshape(self.rgb.shape)[:,:,::-1].copy().tobytes()
                self.assertEqual(reconstructed,self.raw)
                self.assertEqual(hashlib.sha256(reconstructed).hexdigest(),self.rgb_sha)
                self.assertTrue(a._last_evidence_status['clean'])
        finally:a.close()

    def test_only_private_v2_defers_rgb_trace_with_exact_immutable_bgr_archive(self):self.run_case(private=True,inline=True)
    def test_public_v2_still_hashes_rgb_synchronously(self):self.run_case(private=False,inline=True)
    def test_private_local_path_without_per_frame_archive_still_hashes_rgb(self):self.run_case(private=True,inline=False)
    def test_public_local_path_retains_original_rgb_sha(self):self.run_case(private=False,inline=False)


if __name__=='__main__':unittest.main()
