"""Actual MuJoCo sensor checks and strict protocol negatives; no ROS navigation."""
from copy import deepcopy
import base64
import json
import math
import unittest

from rm_match.navigation_sensors import NavigationSensorConfig
from rm_match.platform_v2.backend import MuJoCoBackend
from rm_match.platform_v2.contracts import validate_observation, ContractError
from rm_match.platform_v2.navigation_contracts import (
    NAV_SCHEMA, NAV_STATUS_SCHEMA, POINT_STRUCT, build_navigation_observation,
    decode_points, validate_navigation_status)


def capture_scan(*, moving=False, noise=0.):
    config=NavigationSensorConfig(point_rate_hz=4000,range_noise_std_m=noise,
        gyro_noise_std_rps=noise,acceleration_noise_std_mps2=noise)
    backend=MuJoCoBackend(navigation_sensors=config)
    targets={r:dict(motion=None,gimbal=None,fire=False) for r in backend.robot_ids}
    if moving:targets['red_sentry']['motion']=dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=.5)
    try:
        for _ in range(51):backend.step(targets)
        packet=backend.navigation_sensor_packet('red_sentry')
        observation=build_navigation_observation(packet,binding_epoch=2,observed_seq=3,wall_deadline=packet['capture_wall']+.15)
        return backend,packet,observation
    except BaseException:
        backend.close();raise


class ActualNavigationSensorTests(unittest.TestCase):
    def test_actual_scan_times_and_specific_acceleration_without_pose_feed(self):
        backend,packet,o=capture_scan()
        try:
            self.assertEqual(o['schema'],NAV_SCHEMA)
            self.assertEqual(set(o['own']),{'team','role','hp','ammo','heat','alive'})
            self.assertNotIn('odom',json.dumps(o));self.assertNotIn('qpos',json.dumps(o))
            cloud=o['sensors']['pointcloud'];imu=o['sensors']['imu']
            self.assertEqual(cloud['acquisition_start_ns'],0);self.assertEqual(cloud['acquisition_end_ns'],100000000)
            self.assertEqual(cloud['time_quantization_ns'],2000000)
            points=list(POINT_STRUCT.iter_unpack(decode_points(cloud)))
            self.assertGreater(len(points),5)
            self.assertTrue(all(0<=p[3]<100000000 and p[3]%2000000==0 for p in points))
            self.assertEqual([r['sample_sim_ns'] for r in imu['samples']],list(range(0,100000001,2000000)))
            for row in imu['samples']:
                self.assertLess(max(abs(v) for v in row['angular_velocity_rps']),1e-10)
                self.assertAlmostEqual(row['linear_acceleration_mps2'][2],9.81,places=7)
                self.assertNotIn('orientation',row)
            self.assertEqual(validate_observation(o),o)
            packet['own']['hp']=0
            self.assertGreater(backend.navigation_sensor_packet('red_sentry')['own']['hp'],0)
        finally:backend.close()

    def test_physical_velocity_drives_measured_gyro_not_serialized_truth(self):
        backend,packet,o=capture_scan(moving=True)
        try:
            measured=o['sensors']['imu']['samples'][-1]
            self.assertGreater(measured['angular_velocity_rps'][2],.01)
            self.assertGreater(abs(measured['linear_acceleration_mps2'][0]),.01)
            self.assertGreater(backend._sim.data.qvel[backend._sim.vindices['red_sentry'][0]],0)
            self.assertNotIn('orientation',json.dumps(o))
        finally:backend.close()

    def test_seeded_noise_reproduces_sensor_bytes_and_reset_invalidates_capture(self):
        first,p1,o1=capture_scan(noise=.01);second,p2,o2=capture_scan(noise=.01)
        try:
            self.assertEqual(o1['sensors'],o2['sensors'])
            cloud=o1['sensors']['pointcloud']
            budget=dict(frame_id=cloud['frame_id'],profile_sha256=cloud['profile_sha256'],
                capture_sim_time=cloud['capture_sim_time'],capture_wall=p1['capture_wall'],sim_deadline=.25)
            self.assertTrue(first.navigation_capture_valid('red_sentry',p1['episode'],budget,.102))
            wrong=dict(budget,capture_wall=p1['capture_wall']+.001)
            self.assertFalse(first.navigation_capture_valid('red_sentry',p1['episode'],wrong,.102))
            first._sim.reset()
            self.assertIsNone(first.navigation_sensor_packet('red_sentry'))
            self.assertFalse(first.navigation_capture_valid('red_sentry',p1['episode'],budget,.102))
        finally:first.close();second.close()

    def test_wrong_sensor_mount_and_fractional_time_configuration_fail(self):
        with self.assertRaises(ValueError):NavigationSensorConfig(point_rate_hz=True)
        with self.assertRaises(ValueError):MuJoCoBackend(navigation_sensors=NavigationSensorConfig(point_rate_hz=1001))
        from rm_match.match_engine import MatchSimulation
        sim=MatchSimulation(render=False)
        try:
            with self.assertRaises((KeyError,ValueError)):MuJoCoBackend(sim=sim,navigation_sensors=NavigationSensorConfig())
        finally:sim.close()


class NavigationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        backend,packet,cls.observation=capture_scan()
        backend.close()

    def test_hidden_pose_unknown_sensor_clock_and_point_corruption_rejected(self):
        base=self.observation
        mutations=[]
        wrong=deepcopy(base);wrong['own']['qpos']=[0.]*5;mutations.append(wrong)
        wrong=deepcopy(base);wrong['sensors']['imu']['orientation']=[0.,0.,0.,1.];mutations.append(wrong)
        wrong=deepcopy(base);wrong['sensors']['pointcloud']['capture_sim_time']+=.001;mutations.append(wrong)
        wrong=deepcopy(base);wrong['sensors']['imu']['samples'][-1]['sample_sim_ns']+=1;mutations.append(wrong)
        for bad_point in ((float('nan'),1.,1.,0,100,16,0), (1.,1.,1.,100000000,100,16,0),
            (1.,1.,1.,1,100,16,0), (1.,1.,1.,0,100,0,0), (1.,1.,1.,0,100,16,4)):
            wrong=deepcopy(base);cloud=wrong['sensors']['pointcloud'];cloud['point_count']=1
            cloud['data_base64']=base64.b64encode(POINT_STRUCT.pack(*bad_point)).decode();mutations.append(wrong)
        for wrong in mutations:
            with self.subTest(wrong=wrong['sensors']['pointcloud']['point_count']),self.assertRaises(ContractError):validate_observation(wrong)

    def test_pending_localization_has_no_command_and_exact_original_identity(self):
        o=self.observation
        status=dict(schema=NAV_STATUS_SCHEMA,**{k:o[k] for k in ('robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline')},
            kind='navigation',status='pending_localization')
        self.assertEqual(validate_navigation_status(status,o),status)
        for wrong in (dict(status,command={}),dict(status,status='success'),dict(status,observed_seq=999),dict(status,episode=True)):
            with self.assertRaises(ContractError):validate_navigation_status(wrong,o)


if __name__=='__main__':unittest.main()
