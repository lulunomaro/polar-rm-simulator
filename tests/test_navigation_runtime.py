"""Sensor-profile scheduling, no-action initialization and original deadlines."""
from copy import deepcopy
import time
import threading
import unittest
from rm_match.platform_v2.runtime import PlatformRuntime
from rm_match.platform_v2.adapters import Registry, descriptor
from rm_match.platform_v2.contracts import action_for, IDENTITY
from rm_match.platform_v2.navigation_contracts import NAV_SCHEMA, NAV_STATUS_SCHEMA, NAV_PROFILE
from rm_match.platform_v2.test_control import Clock
from rm_match.platform_v2.test_runtime import FakeBackend


def packet(clock,end=100000000,frame=0):
    ext=dict(parent_frame='base_link',translation_m=[0.,0.,.5],rotation_xyzw=[0.,0.,0.,1.],calibration_id='unit-fixture')
    return dict(robot_id='alpha',episode=0,sim_time=end*1e-9,capture_wall=clock(),
        own=dict(team='red',role='sentry',hp=100.,ammo=1.,heat=0.,alive=True),
        referee=dict(phase='running',remaining_seconds=300.,emergency_stop=False),
        sensors=dict(pointcloud=dict(available=True,reason='available',frame_id=frame,
            acquisition_start_ns=end-100000000,acquisition_end_ns=end,capture_sim_time=end*1e-9,
            frame='livox_frame',encoding='livox_xyz_offset_reflectivity_tag_line_le_v1',point_count=0,data_base64='',
            range_min_m=.1,range_max_m=40.,time_quantization_ns=2000000,
            provenance='mujoco_ray_cast_nonrepeating_profile_v1',profile_sha256='0'*64,extrinsics=ext),
            imu=dict(available=True,reason='available',frame='livox_frame',capture_sim_time=end*1e-9,
                extrinsics=deepcopy(ext),provenance='mujoco_gyro_accelerometer_v1',
                samples=[dict(sample_sim_ns=stamp,angular_velocity_rps=[0.,0.,0.],linear_acceleration_mps2=[0.,0.,9.81])
                    for stamp in (end-100000000,end)])))


class SensorBackend(FakeBackend):
    def __init__(self,clock):
        super().__init__(('alpha',));self.sim_time=.1;self.packet=packet(clock);self.old_sensor_calls=0
    def sensor_sample(self,rid):
        self.old_sensor_calls+=1;raise AssertionError('Ideal sensor API must not feed this profile')
    def navigation_sensor_packet(self,rid):return deepcopy(self.packet)
    def navigation_capture_valid(self,rid,episode,budget,sim_time):
        return episode==0 and budget['profile_sha256']=='0'*64 and budget['capture_sim_time']<=sim_time<=budget['sim_deadline']


class InitializeThenAct:
    def __init__(self,seen):self.seen=seen;self.calls=0;self.closed=False
    def reset(self,context):self.context=context
    def act(self,o):
        self.seen.append(o);self.calls+=1
        if self.calls==1:return dict(schema=NAV_STATUS_SCHEMA,**{k:o[k] for k in IDENTITY},kind='navigation',status='pending_localization')
        return action_for(o,'navigation','velocity_body',dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=0.))
    def close(self):self.closed=True


class NavigationRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.backend=SensorBackend(self.clock);self.seen=[];self.instances=[]
        registry=Registry()
        def create(config):
            instance=InitializeThenAct(self.seen);self.instances.append(instance);return instance
        registry.register(descriptor('custom_nav_fixture','navigation','Explicit unit fixture',['pointcloud','imu'],
            observation_profile=NAV_PROFILE,test_only=True),create)
        self.runtime=PlatformRuntime(self.backend,registry=registry,clock=self.clock)
        control=self.runtime.control
        self.token=control.open_session('operator')['token'];self.epochs=control.claim(self.token,'alpha',['motion'])['lease_epochs']
        self.runtime.bind(self.token,'alpha','navigation',self.epochs,'custom_nav_fixture',{})
    def tearDown(self):self.runtime.close()
    def tick(self):
        self.runtime.step_once();self.clock.advance(.01);time.sleep(.01)
    def wait_for_response(self,count):
        deadline=time.perf_counter()+1.
        while len(self.seen)<count and time.perf_counter()<deadline:time.sleep(.005)
        self.assertEqual(len(self.seen),count)
        # The fixture reports seen immediately before it returns to the slot.
        deadline=time.perf_counter()+1.
        slot=self.runtime.slots['alpha','navigation']
        while slot.results.empty() and time.perf_counter()<deadline:time.sleep(.005)
        self.assertFalse(slot.results.empty())
    def test_waiting_state_retains_instance_then_consumes_next_actual_scan_action(self):
        self.tick();self.wait_for_response(1);self.tick()
        self.assertEqual(self.runtime.status['alpha','navigation'],'waiting_for_navigation:pending_localization')
        self.assertIsNone(self.backend.targets['alpha']['motion']);self.assertEqual(len(self.instances),1)
        self.assertNotIn(('alpha','navigation'),self.runtime._fault_epochs)
        self.assertEqual(len(self.seen),1);self.assertEqual(self.seen[0]['schema'],NAV_SCHEMA)
        self.backend.sim_time=.2;self.backend.packet=packet(self.clock,200000000,1)
        self.tick();self.wait_for_response(2);self.tick()
        self.assertEqual(len(self.instances),1);self.assertEqual(len(self.seen),2)
        self.assertEqual(self.backend.old_sensor_calls,0)
        self.assertEqual(self.backend.targets['alpha']['motion']['vx_mps'],.2)
        self.assertFalse(self.backend.targets['alpha']['fire'])
        self.clock.advance(.2);self.runtime.step_once()
        self.assertIsNone(self.backend.targets['alpha']['motion'])
    def test_expired_sensor_does_not_gain_a_new_deadline_or_create_adapter(self):
        original=self.backend.packet['capture_wall'];self.clock.advance(.16)
        self.runtime.step_once()
        self.assertEqual(self.runtime.status['alpha','navigation'],'navigation_sensor_expired')
        self.assertEqual(self.backend.packet['capture_wall'],original)
        self.assertEqual(len(self.instances),0);self.assertIsNone(self.backend.targets['alpha']['motion'])

    def test_sensor_preparation_allows_concurrent_control_access(self):
        done=threading.Event();threads=[]
        def prepare():
            def control_access():
                self.runtime.control.snapshot();done.set()
            worker=threading.Thread(target=control_access,daemon=True);threads.append(worker);worker.start()
            self.assertTrue(done.wait(.5),'Sensor work held the lease/control lock')
        self.backend.prepare_navigation_sensors=prepare
        self.runtime.step_once()
        for worker in threads:worker.join(.1)
        self.assertTrue(done.is_set())


if __name__=='__main__':unittest.main()
