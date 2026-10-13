"""Explicit fake rclpy lifecycle tests; not actual ROS middleware validation."""
import os
from types import SimpleNamespace,ModuleType
import unittest
from unittest.mock import patch

from rm_match.integrations.ros2_bridge import BridgeSettings,BridgeError
from rm_match.integrations.ros2_bridge_transport import RclpyTransport


def settings():return BridgeSettings('custom_ros2_transport','navigation','polar_transport','/polar/transport/observation','/polar/transport/action',78)


class FakeRos:
    def __init__(self,*,startup_error=False,clean=True):
        self.calls=[];self.published=[];self.startup_error=startup_error;self.clean=clean;self.ready=True
        self.context=object();self.node=SimpleNamespace(
            create_publisher=self.create_publisher,create_subscription=self.create_subscription,
            count_publishers=lambda topic:int(self.ready),destroy_node=lambda:self.calls.append('destroy_node'))
        self.executor=SimpleNamespace(add_node=lambda node:self.calls.append('add_node'),
            spin_once=lambda **kw:self.calls.append(('spin',kw)),shutdown=self.shutdown)
        self.modules={}
        for name in ('rclpy','rclpy.context','rclpy.executors','rclpy.qos','std_msgs','std_msgs.msg'):self.modules[name]=ModuleType(name)
        rclpy=self.modules['rclpy'];rclpy.init=lambda **kw:self.calls.append(('init',kw))
        rclpy.create_node=self.create_node;rclpy.try_shutdown=lambda **kw:self.calls.append(('try_shutdown',kw))
        self.modules['rclpy.context'].Context=lambda:self.context
        self.modules['rclpy.executors'].SingleThreadedExecutor=lambda **kw:self.executor
        qos=self.modules['rclpy.qos'];qos.QoSProfile=lambda **kw:SimpleNamespace(**kw)
        qos.HistoryPolicy=SimpleNamespace(KEEP_LAST='keep_last');qos.ReliabilityPolicy=SimpleNamespace(BEST_EFFORT='best_effort');qos.DurabilityPolicy=SimpleNamespace(VOLATILE='volatile')
        self.modules['std_msgs.msg'].String=lambda:SimpleNamespace(data='')
    def create_node(self,name,**kw):self.calls.append(('create_node',name,kw));return self.node
    def create_publisher(self,typ,topic,qos):
        self.calls.append(('publisher',topic,qos))
        return SimpleNamespace(publish=lambda message:self.published.append(message.data),get_subscription_count=lambda:int(self.ready))
    def create_subscription(self,typ,topic,callback,qos):
        self.callback=callback;self.calls.append(('subscription',topic,qos))
        if self.startup_error:raise RuntimeError('fake partial startup failed')
        return object()
    def shutdown(self,**kw):self.calls.append(('shutdown',kw));return self.clean


class TransportUnitTests(unittest.TestCase):
    def test_fixed_local_domain_qos_no_remapping_and_lifecycle_cleanup(self):
        fake=FakeRos();received=[]
        with patch.dict('sys.modules',fake.modules),patch.dict(os.environ,{},clear=True):
            transport=RclpyTransport(settings(),received.append)
            self.assertEqual(os.environ['ROS_AUTOMATIC_DISCOVERY_RANGE'],'LOCALHOST')
            self.assertEqual(os.environ['ROS_STATIC_PEERS'],'');self.assertEqual(os.environ['ROS_DOMAIN_ID'],'78')
            self.assertEqual(os.environ['RMW_IMPLEMENTATION'],'rmw_fastrtps_cpp')
            init=next(v for v in fake.calls if type(v) is tuple and v[0]=='init')
            self.assertEqual(init[1],dict(args=[],context=fake.context,domain_id=78))
            created=next(v for v in fake.calls if type(v) is tuple and v[0]=='create_node')
            self.assertFalse(created[2]['use_global_arguments']);self.assertFalse(created[2]['enable_rosout'])
            for entry in [v for v in fake.calls if type(v) is tuple and v[0] in ('publisher','subscription')]:
                self.assertEqual(vars(entry[2]),dict(history='keep_last',depth=1,reliability='best_effort',durability='volatile'))
            transport.wait_ready();transport.publish('exact envelope');fake.callback(SimpleNamespace(data='received action'))
            self.assertEqual(fake.published,['exact envelope']);self.assertEqual(received,['received action'])
            transport.close();transport.close();self.assertEqual(fake.calls.count('destroy_node'),1)
            self.assertIn(('shutdown',dict(timeout_sec=.15)),fake.calls)
            for call in (lambda:transport.publish('late'),lambda:transport.spin_once(0),lambda:transport.wait_ready()):
                with self.assertRaisesRegex(BridgeError,'closed'):call()

    def test_rejected_callback_is_counted_without_untrusted_payload_logging(self):
        fake=FakeRos()
        def reject(_):raise BridgeError('ros2_action_identity_mismatch')
        with patch.dict('sys.modules',fake.modules),patch.dict(os.environ,{},clear=True):
            transport=RclpyTransport(settings(),reject);fake.callback(SimpleNamespace(data='untrusted action'))
            self.assertEqual(transport.rejected_actions,1);transport.close()

    def test_partial_startup_and_unclean_executor_are_explicit(self):
        fake=FakeRos(startup_error=True)
        with patch.dict('sys.modules',fake.modules),patch.dict(os.environ,{},clear=True),self.assertRaisesRegex(RuntimeError,'partial startup'):
            RclpyTransport(settings(),lambda _:None)
        self.assertIn('destroy_node',fake.calls)
        fake=FakeRos(clean=False)
        with patch.dict('sys.modules',fake.modules),patch.dict(os.environ,{},clear=True):
            transport=RclpyTransport(settings(),lambda _:None)
            with self.assertRaisesRegex(BridgeError,'shutdown_incomplete'):transport.close()
            with self.assertRaisesRegex(BridgeError,'shutdown_incomplete'):transport.close()
        self.assertIn('destroy_node',fake.calls);self.assertTrue(any(type(v) is tuple and v[0]=='try_shutdown' for v in fake.calls))

    def test_graph_timeout_and_unsupported_discovery_middleware_fail_closed(self):
        fake=FakeRos();fake.ready=False
        with patch.dict('sys.modules',fake.modules),patch.dict(os.environ,{},clear=True):
            transport=RclpyTransport(settings(),lambda _:None)
            with self.assertRaisesRegex(BridgeError,'graph_unavailable'):transport.wait_ready(0.)
            transport.close()
        with patch.dict(os.environ,{'RMW_IMPLEMENTATION':'rmw_zenoh_cpp'},clear=True),self.assertRaisesRegex(BridgeError,'local_dds_rmw_required'):
            RclpyTransport(settings(),lambda _:None)


if __name__=='__main__':unittest.main()
