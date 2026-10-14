"""Measured static transform publication boundary; explicit message fixtures."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from tools.diagnose_pb_humble_sensors import fixture
from rm_match.integrations.pb_navigation_bridge import sensor_bundle
from rm_match.integrations.pb_navigation_transport import HumbleNavigationTransport
from rm_match.integrations.ros2_bridge import BridgeError


class Message:
    def __init__(self,**values):
        self.header=SimpleNamespace(stamp=SimpleNamespace(sec=0,nanosec=0),frame_id='')
        self.transform=SimpleNamespace(translation=SimpleNamespace(x=0.,y=0.,z=0.),rotation=SimpleNamespace(x=0.,y=0.,z=0.,w=0.))
        self.clock=SimpleNamespace(sec=0,nanosec=0)
        self.angular_velocity=SimpleNamespace(x=0.,y=0.,z=0.)
        self.linear_acceleration=SimpleNamespace(x=0.,y=0.,z=0.)
        self.__dict__.update(values)


class StaticTransportTests(unittest.TestCase):
    def transport(self):
        t=HumbleNavigationTransport.__new__(HumbleNavigationTransport)
        t._closed=False;t._extrinsics=None;t._last_imu_ns=-1;t.types=(Message,)*9
        for field in ('tf_pub','cloud_pub','pc_pub','imu_pub','clock_pub','request_pub'):setattr(t,field,Mock())
        return t

    def test_static_mount_zero_stamp_and_single_publication_survive_direct_message_path(self):
        t=self.transport();bundle=sensor_bundle(fixture());t.publish_bundle(bundle,'{}')
        message=t.tf_pub.publish.call_args.args[0];self.assertEqual(len(message.transforms),1)
        tf=message.transforms[0];self.assertEqual((tf.header.frame_id,tf.child_frame_id),('base_link','livox_frame'))
        self.assertEqual((tf.header.stamp.sec,tf.header.stamp.nanosec),(0,0))
        self.assertEqual([getattr(tf.transform.translation,k) for k in ('x','y','z')],bundle['extrinsics']['translation_m'])
        self.assertEqual([getattr(tf.transform.rotation,k) for k in ('x','y','z','w')],bundle['extrinsics']['rotation_xyzw'])
        t.publish_bundle(copy.deepcopy(bundle),'{}');t.tf_pub.publish.assert_called_once()

    def test_changed_mount_stops_before_any_sensor_or_new_static_tf(self):
        t=self.transport();bundle=sensor_bundle(fixture());t.publish_bundle(bundle,'{}')
        for field in ('tf_pub','cloud_pub','pc_pub','imu_pub','clock_pub','request_pub'):getattr(t,field).reset_mock()
        changed=copy.deepcopy(bundle);changed['extrinsics']['translation_m'][0]=.01
        with self.assertRaises(BridgeError):t.publish_bundle(changed,'{}')
        for field in ('tf_pub','cloud_pub','pc_pub','imu_pub','clock_pub','request_pub'):getattr(t,field).publish.assert_not_called()


if __name__=='__main__':unittest.main()
