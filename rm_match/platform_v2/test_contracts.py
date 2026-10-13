import base64
import copy
import math
import unittest
import numpy as np
from ..contracts import Observation
from .contracts import *

def sample(camera=False):
    raw=Observation(episode=1,sim_time=1.,rgb=np.zeros((0,0,3),dtype=np.uint8),fovy_degrees=60.,own_qpos=(0.,0.,0.,0.,0.),own_qvel=(0.,)*5,own_hp=300.,ammo=10,robot_id='red_infantry',odom_xyyaw=(0.,0.,0.),odom_vxyw=(0.,0.,0.),ranges=(8.,)*8,range_angles=tuple(-math.pi+i*math.pi/4 for i in range(8)),team='red',role='infantry',remaining_seconds=299.)
    cam=None
    if camera:
        pixels=np.zeros((12,16,3),dtype=np.uint8);pixels[4:8,6:10,0]=255
        cam=dict(available=True,reason='available',frame_id=1,capture_sim_time=1.,own_qpos_at_capture=list(raw.own_qpos),own_qvel_at_capture=list(raw.own_qvel),own_odom_at_capture=list(raw.odom_xyyaw),own_odom_velocity_at_capture=list(raw.odom_vxyw),image=dict(encoding='rgb8',width=16,height=12,stride_bytes=48,data_base64=base64.b64encode(pixels.tobytes()).decode()),intrinsics=dict(fx=10.,fy=10.,cx=7.5,cy=5.5,distortion_model='brown_conrady_5',distortion=[0.]*5),extrinsics=dict(parent_frame='gimbal_link',translation_m=[.24,0.,.06],rotation_xyzw=[-.5,.5,-.5,.5],calibration_id='synthetic_test_only'),provenance='simulated_raw_camera')
    return build_observation(raw,binding_epoch=1,observed_seq=1,wall_deadline=10.,camera=cam)

class ContractsTests(unittest.TestCase):
    def test_own_only_builder_and_explicit_missing_camera(self):
        o=sample();self.assertFalse(o['sensors']['camera']['available']);self.assertNotIn('robots',o);self.assertNotIn('judge',o)
    def test_builder_normalizes_trusted_numpy_sensors(self):
        from types import SimpleNamespace
        raw=SimpleNamespace(robot_id="red_sentry",episode=np.int64(0),sim_time=np.float64(0),team="red",role="sentry",own_qpos=np.zeros(5),own_qvel=np.zeros(5),odom_xyyaw=np.zeros(3),odom_vxyw=np.zeros(3),own_hp=np.float64(100),ammo=np.int64(10),own_heat=np.float64(0),match_phase="running",remaining_seconds=np.float64(300),emergency_stop=np.bool_(False),ranges=(np.float64(8),),range_angles=(np.float64(0),),range_max=np.float64(8))
        o=build_observation(raw,binding_epoch=0,observed_seq=0,wall_deadline=1.)
        self.assertIs(type(o["sensors"]["ranges"]["angles_rad"][0]),float)
    def test_copy_does_not_share_input_graph(self):
        o=sample();n=validate_observation(o);n['own']['qpos'][0]=3;self.assertEqual(o['own']['qpos'][0],0)
    def test_unknown_truth_and_objects_rejected(self):
        for key,value in [('robots',[]),('model',object()),('enemy_positions',[])]:
            o=sample();o[key]=value
            with self.assertRaises(ContractError):validate_observation(o)
    def test_nonfinite_and_huge_numbers_rejected(self):
        for n in (True,float('nan'),float('inf'),10**400):
            o=sample();o['own']['hp']=n
            with self.assertRaises(ContractError):validate_observation(o)
    def test_camera_encoding_calibration_and_capture(self):
        o=sample(True);validate_observation(o)
        for key,value in [('capture_sim_time',2.),('own_qpos_at_capture',[0.]),('frame_id',True)]:
            n=copy.deepcopy(o);n['sensors']['camera'][key]=value
            with self.assertRaises(ContractError):validate_observation(n)
    def test_image_length_and_quaternion(self):
        for mutate in (lambda c:c['image'].update(data_base64='AA=='),lambda c:c['extrinsics'].update(rotation_xyzw=[0.]*4),lambda c:c['intrinsics'].update(distortion=[])):
            o=sample(True);mutate(o['sensors']['camera'])
            with self.assertRaises(ContractError):validate_observation(o)
    def test_sensor_unavailable_cannot_hide_payload(self):
        o=sample();o['sensors']['camera']['image']={'x':1}
        with self.assertRaises(ContractError):validate_observation(o)
    def test_action_identity_clock_and_binding(self):
        o=sample();cap={'kind':'navigation','output_modes':['velocity_body']};a=action_for(o,'navigation','velocity_body',dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=0.));validate_action(a,o,cap)
        for k in IDENTITY:
            n=copy.deepcopy(a);n[k]= 'blue_infantry' if k=='robot_id' else n[k]+1
            with self.assertRaises(ContractError):validate_action(n,o,cap)
    def test_action_channel_and_norm(self):
        o=sample();cap={'kind':'navigation','output_modes':['velocity_body']}
        for c in (dict(frame='world',vx_mps=0.,vy_mps=0.,wz_rps=0.),dict(frame='base_link',vx_mps=1.,vy_mps=1.,wz_rps=0.),dict(frame='base_link',vx_mps=0.,vy_mps=0.,wz_rps=0.,fire=True)):
            with self.assertRaises(ContractError):validate_action(action_for(o,'navigation','velocity_body',c),o,cap)
    def test_aim_no_invented_confidence_and_no_inactive_fire(self):
        o=sample();cap={'kind':'aim','output_modes':['gimbal_target']};a=action_for(o,'aim','gimbal_target',dict(frame='base_link',yaw_rad=0.,pitch_rad=0.,active=False,confidence=None,fire_permission=False));validate_action(a,o,cap)
        a['command']['fire_permission']=True
        with self.assertRaises(ContractError):validate_action(a,o,cap)
    def test_target_trajectory_not_silently_treated_as_velocity(self):
        o=sample();a=action_for(o,'navigation','trajectory',dict(points=[]))
        with self.assertRaises(ContractError):validate_action(a,o,{'kind':'navigation','output_modes':['velocity_body']})
if __name__=='__main__':unittest.main()
