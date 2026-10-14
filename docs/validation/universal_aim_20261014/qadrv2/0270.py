import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from .native_adapter import NativeSourceAdapter
from .contracts import ContractError,validate_action
from .adapters import default_registry
from .test_contracts import sample

class FakeProcess:
    calls=[]
    def __init__(self,*args,**kwargs):self.closed=False
    def reset(self,message):pass
    def close(self):self.closed=True
    def control(self,packet):
        self.calls.append(packet)
        return dict(should_control=True,observation_shoot_allowed=True,target_age_s=.01,direction_frame='world',direction=[1.,0.,.1],should_shoot=True)

class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);binary=self.root/'not_executed';binary.write_bytes(b'synthetic unit fixture')
        self.config=self.root/'dummy';self.config.write_bytes(b'synthetic config')
        self.model=self.root/'shenzhen-0526.onnx';self.model.write_bytes(b'synthetic model')
        bsha=hashlib.sha256(binary.read_bytes()).hexdigest();csha=hashlib.sha256(self.config.read_bytes()).hexdigest();msha=hashlib.sha256(self.model.read_bytes()).hexdigest();mode_sha=hashlib.sha256(b'multi_ekf\n').hexdigest()
        self.spec=self.root/'spec.json';self.spec.write_text(json.dumps(dict(operator_identity='rmcs-sim-operator-fov-v1',binary=str(binary),frozen_build={'binary_sha256':bsha},executor_yaml=str(self.config),autoaim_config=str(self.config),model_share=str(self.root),sha256=dict(binary=bsha,executor_yaml=csha,autoaim_config=csha,runtime_mode=mode_sha),model_sha256=msha,runtime_mode_contents='multi_ekf\n',runtime_mode_sha256=mode_sha)))
    def tearDown(self):self.temp.cleanup()
    def observation(self):
        from ..camera_profile import SourceCameraProfile
        p=SourceCameraProfile();o=sample(True);o.update(robot_id='red_sentry');o['own'].update(role='sentry');c=o['sensors']['camera']
        c['image'].update(width=p.width,height=p.height,stride_bytes=p.width*3,data_base64=base64.b64encode(bytes(p.width*p.height*3)).decode());c['intrinsics'].update(fx=p.fx,fy=p.fy,cx=p.cx,cy=p.cy,distortion=list(p.distortion));return o
    def adapter(self):
        a=NativeSourceAdapter({},spec_path=self.spec,out=self.root/'out');a.reset(dict(episode=1,robot_id='red_sentry',binding_epoch=1));return a
    def test_network_config_cannot_select_binary(self):
        with self.assertRaises(ContractError):NativeSourceAdapter({'binary':'bad'},spec_path=self.spec,out=self.root/'out')
    def test_binary_identity_mismatch_rejected(self):
        v=json.loads(self.spec.read_text());v['frozen_build']['binary_sha256']='0'*64;self.spec.write_text(json.dumps(v))
        with self.assertRaises(ContractError):self.adapter()
    def test_config_or_model_tampering_rejected_before_registration(self):
        from .adapters import default_registry
        for path in (self.config,self.model):
            original=path.read_bytes();path.write_bytes(b'tampered')
            with self.assertRaises(ContractError):default_registry(native_spec=self.spec,native_out=self.root/'out')
            path.write_bytes(original)
    def test_spec_cannot_change_after_registration(self):
        registry=default_registry(native_spec=self.spec,native_out=self.root/'out')
        self.spec.write_text(self.spec.read_text()+' ')
        with self.assertRaisesRegex(ContractError,'changed_after_registration'):registry.create('aim_native_rmcs_v1',{})
    def test_hashes_rechecked_before_process_start(self):
        o=self.observation();a=self.adapter();a.act(o);self.model.write_bytes(b'tamper after constructor')
        o['sim_time']=1.5;o['sensors']['camera']['capture_sim_time']=1.5;o['sensors']['camera']['frame_id']=2
        with patch('rm_match.operator.source_aim.OperatorFovProcess') as process:
            with self.assertRaises(ContractError):a.act(o)
            process.assert_not_called()
    def test_reserved_environment_cannot_redirect_verified_artifacts(self):
        from .native_adapter import validate_native_spec
        original=json.loads(self.spec.read_text())
        for key in ('AUTOAIM_CONFIG','RMCS_HEADLESS_SHARE','ORT_DISABLE_TELEMETRY'):
            value=dict(original,environment={key:'unverified override'});self.spec.write_text(json.dumps(value))
            with self.assertRaisesRegex(ContractError,'reserved_environment_override'):validate_native_spec(self.spec)
    def test_environment_types_are_explicit(self):
        from .native_adapter import validate_native_spec
        original=json.loads(self.spec.read_text())
        for environment in ([],{'OMP_NUM_THREADS':True}):
            self.spec.write_text(json.dumps(dict(original,environment=environment)))
            with self.assertRaises(ContractError):validate_native_spec(self.spec)
    def test_wrong_K_before_native_process(self):
        o=self.observation();o['sensors']['camera']['intrinsics']['fx']+=1;a=self.adapter()
        with patch('rm_match.operator.source_aim.OperatorFovProcess') as process:
            with self.assertRaises(ContractError):a.act(o)
            process.assert_not_called()
    def test_sensor_packet_exposure_pose_and_fire_authority(self):
        o=self.observation();a=self.adapter();FakeProcess.calls=[]
        with patch('rm_match.operator.source_aim.OperatorFovProcess',FakeProcess):
            a.act(o);o['sim_time']=1.5;o['observed_seq']=2;c=o['sensors']['camera'];c['frame_id']=2;c['capture_sim_time']=1.49;c['own_qvel_at_capture'][3]=.7;c['own_odom_velocity_at_capture'][2]=.02
            v=a.act(o);self.assertTrue(v['command']['active']);self.assertFalse(v['command']['fire_permission'])
            packet=FakeProcess.calls[0];self.assertEqual(packet['frame']['exposure_timestamp_ns'],1490000000);self.assertEqual(packet['frame']['own']['joint_velocities'][3],.7);self.assertEqual(packet['frame']['own']['base_odom_vxyw'][2],.02)
            self.assertNotIn('robots',packet);self.assertNotIn('sim',packet);a.close()
    def test_motion_and_repeated_capture_do_not_start_process(self):
        o=self.observation();o['own']['odom_vxyw'][0]=.1;a=self.adapter()
        with patch('rm_match.operator.source_aim.OperatorFovProcess') as process:
            self.assertFalse(a.act(o)['command']['active']);process.assert_not_called()
if __name__=='__main__':unittest.main()
