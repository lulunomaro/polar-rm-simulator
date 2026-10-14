"""Pairing and original deadline tests; no renderer, ELF, NN or real control."""
import copy,hashlib,json
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from rm_match.platform_v2.native_camera_snapshot import mint_native_snapshot,NativeCameraSnapshot
from rm_match.platform_v2.native_image import prepare_native_snapshot,PreparedNativeBGR,prepared_native_bgr_matches
from rm_match.integrations.test_wsl_operator_pipe import PipeHostTests as _PipeFixture
from rm_match.integrations.wsl_operator_pipe import IMAGE_BYTES

def fixture(full=False,path='unused/sensor_input.bgr'):
 w,h=(1440,1080) if full else (4,3)
 rgb=np.arange(w*h*3,dtype=np.uint8).reshape(h,w,3)
 source=mint_native_snapshot(rgb.tobytes(),robot_id='red_sentry',episode=0,frame_id=7,
  capture_wall=1000.,capture_sim_time=.410,consumers=frozenset({('adapter','red_sentry','aim','owner',1)}),
  width=w,height=h,stride_bytes=w*3,own=dict(own_qpos_at_capture=[0.]*5,own_qvel_at_capture=[0.]*5,
   own_odom_at_capture=[0.]*3,own_odom_velocity_at_capture=[0.]*3),
  intrinsics=dict(fx=10.,fy=10.,cx=1.,cy=1.,distortion_model='brown_conrady_5',distortion=[0.]*5),
  extrinsics=dict(parent_frame='gimbal_link',translation_m=[.24,0.,.06],rotation_xyzw=[-.5,.5,-.5,.5],calibration_id='fixture'))
 image,_,_,raw,proof=prepare_native_snapshot(source,path,control_time_ns=422000000,host_deadline=1000.08)
 packet=dict(episode=0,control_time_ns=422000000,host_deadline=1000.08,image_bytes=raw,prepared_image=proof,
  frame=dict(schema='rmcs-mujoco-actor-frame-v1',episode=0,frame_id=7,exposure_timestamp_ns=410000000,capture_time_s=.410,
   image=image,camera=dict(fx=10.,fy=10.,cx=1.,cy=1.,distortion=[0.]*5),
   own=dict(joint_positions=[0.]*5,joint_velocities=[0.]*5,base_odom_xyyaw=[0.]*3,base_odom_vxyw=[0.]*3)))
 return source,raw,proof,packet,rgb

class PreparedBgrTests(unittest.TestCase):
 def test_actual_conversion_same_sha_one_immutable_pair(self):
  source,raw,proof,packet,rgb=fixture()
  self.assertEqual(raw,np.ascontiguousarray(rgb[:,:,::-1]).tobytes())
  self.assertEqual(hashlib.sha256(raw).hexdigest(),packet['frame']['image']['sha256'])
  self.assertTrue(prepared_native_bgr_matches(proof,raw,packet))
  self.assertIs(copy.deepcopy(proof),proof);rgb[:]=0
  self.assertTrue(prepared_native_bgr_matches(proof,raw,copy.deepcopy(packet)))
  with self.assertRaises(TypeError):json.dumps(proof)
  with self.assertRaises(TypeError):PreparedNativeBGR()
  with self.assertRaises(AttributeError):object.__setattr__(proof,'raw_bytes',b'forged')
 def test_forged_alias_or_other_conversion_cannot_reuse_proof(self):
  _,raw,proof,packet,_=fixture();_,other_raw,other,_,_=fixture()
  for token,data in ((object.__new__(PreparedNativeBGR),raw),(other,raw),(proof,other_raw),
    (proof,bytearray(raw)),(proof,memoryview(raw))):
   with self.subTest(token=type(token),data=type(data)):
    self.assertFalse(prepared_native_bgr_matches(token,data,packet))
 def test_original_source_fields_types_calibration_and_capture_state_must_match(self):
  _,raw,proof,packet,_=fixture()
  changes=[(('episode',),True),(('control_time_ns',),422000001),(('host_deadline',),1000.09),
   (('frame','episode'),1),(('frame','frame_id'),8),(('frame','exposure_timestamp_ns'),410000001),
   (('frame','capture_time_s'),.411),(('frame','image','sha256'),'0'*64),
   (('frame','image','width'),True),(('frame','image','path'),'other/sensor_input.bgr'),
   (('frame','camera','fx'),11.),(('frame','camera','distortion'),[.1]*5),
   (('frame','own','joint_positions'),[1.]*5)]
  for keys,value in changes:
   candidate=copy.deepcopy(packet);target=candidate
   for key in keys[:-1]:target=target[key]
   target[keys[-1]]=value
   with self.subTest(field=keys):self.assertFalse(prepared_native_bgr_matches(proof,raw,candidate))
 def test_unsealed_source_and_new_deadline_rejected_by_factory(self):
  source,_,_,_,_=fixture()
  with self.assertRaises(ValueError):prepare_native_snapshot(object.__new__(NativeCameraSnapshot),'unused',control_time_ns=422000000,host_deadline=1000.08)
  for ns,deadline in ((True,1000.08),(409000000,1000.08),(491000000,1000.08),(422000000,1000.081)):
   with self.subTest(ns=ns,deadline=deadline),self.assertRaises(ValueError):
    prepare_native_snapshot(source,'unused',control_time_ns=ns,host_deadline=deadline)
 def test_transport_uses_factory_hash_without_serializing_receipt_or_restarting_deadline(self):
  a=_PipeFixture().actor();a.out=Path('unused').absolute()
  _,raw,proof,packet,_=fixture(True,str(a.out/'sensor_input.bgr'))
  a._receive=lambda deadline:dict(event='result',id=1,response=dict(status='ok',runner_identity='rmcs-sim-operator-fov-v1',
   clock_time_ns=422000000,direction_frame='world',tracking=False))
  with patch('rm_match.integrations.wsl_operator_pipe.time.perf_counter',return_value=1000.01),\
    patch('rm_match.integrations.wsl_operator_pipe.hashlib.sha256',side_effect=AssertionError('No second host SHA')):
   a.control(packet)
  header,sent=a._outgoing.get_nowait();self.assertIs(sent,raw);self.assertEqual(len(sent),IMAGE_BYTES)
  value=json.loads(header);self.assertNotIn('prepared_image',value['packet']);self.assertNotIn('image_bytes',value['packet'])
  self.assertEqual(a.diagnostics[0]['original_host_deadline'],1000.08)
  self.assertIn('prepared_bgr_admission_s',a.diagnostics[0]['stages_s']);self.assertNotIn('bgr_hash_s',a.diagnostics[0]['stages_s'])
  b=_PipeFixture().actor();b.out=a.out;candidate=copy.deepcopy(packet);candidate['prepared_image']=object.__new__(PreparedNativeBGR)
  with patch('rm_match.integrations.wsl_operator_pipe.time.perf_counter',return_value=1000.01),self.assertRaises(ValueError):b.control(candidate)
  self.assertTrue(b._stop.is_set());self.assertEqual(b._outgoing.qsize(),0)

if __name__=='__main__':unittest.main()
