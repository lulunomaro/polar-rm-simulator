"""Actual rclpy transport. Optional imports fail explicitly; no fake fallback."""
from __future__ import annotations
import os
import time
from .ros2_bridge import BridgeError


class RclpyTransport:
    def __init__(self,settings,receive_action):
        self.node=None;self.executor=None;self.context=None;self._rclpy=None
        self.rejected_actions=0;self._closed=False;self._close_error=False;self._action_topic=settings.action_topic
        # Set only this optional process's environment, never shell/global ROS
        # settings. Static peers could override the local discovery boundary.
        os.environ['ROS_AUTOMATIC_DISCOVERY_RANGE']='LOCALHOST'
        os.environ['ROS_LOCALHOST_ONLY']='1';os.environ['ROS_STATIC_PEERS']=''
        os.environ['ROS_DOMAIN_ID']=str(settings.domain_id)
        os.environ['RCUTILS_LOGGING_USE_STDOUT']='0'
        rmw=os.environ.get('RMW_IMPLEMENTATION','rmw_fastrtps_cpp')
        if rmw not in ('rmw_fastrtps_cpp','rmw_cyclonedds_cpp'):raise BridgeError('ros2_local_dds_rmw_required')
        os.environ['RMW_IMPLEMENTATION']=rmw
        try:
            import rclpy
            from rclpy.context import Context
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.qos import QoSProfile,HistoryPolicy,ReliabilityPolicy,DurabilityPolicy
            from std_msgs.msg import String
        except (ImportError,OSError):raise BridgeError('ros2_rclpy_std_msgs_unavailable') from None
        self._rclpy=rclpy;self._message=String;self.context=Context()
        try:
            rclpy.init(args=[],context=self.context,domain_id=settings.domain_id)
            self.node=rclpy.create_node(settings.node_name,context=self.context,
                use_global_arguments=False,enable_rosout=False,start_parameter_services=False)
            qos=QoSProfile(history=HistoryPolicy.KEEP_LAST,depth=1,
                reliability=ReliabilityPolicy.BEST_EFFORT,durability=DurabilityPolicy.VOLATILE)
            self.publisher=self.node.create_publisher(String,settings.observation_topic,qos)
            def callback(message):
                try:receive_action(message.data)
                except ValueError:self.rejected_actions=min(self.rejected_actions+1,2**53-1)
            self.subscription=self.node.create_subscription(String,settings.action_topic,callback,qos)
            self.executor=SingleThreadedExecutor(context=self.context);self.executor.add_node(self.node)
        except BaseException:
            self.close();raise

    def publish(self,payload):
        if self._closed:raise BridgeError('ros2_transport_closed')
        message=self._message();message.data=payload;self.publisher.publish(message)

    def spin_once(self,timeout):
        if self._closed:raise BridgeError('ros2_transport_closed')
        self.executor.spin_once(timeout_sec=timeout)

    def wait_ready(self,timeout=1.):
        if self._closed:raise BridgeError('ros2_transport_closed')
        deadline=time.monotonic()+timeout
        while not (self.publisher.get_subscription_count()>0 and self.node.count_publishers(self._action_topic)>0):
            remaining=deadline-time.monotonic()
            if remaining<=0:raise BridgeError('ros2_algorithm_graph_unavailable')
            self.spin_once(min(.01,remaining))

    def close(self):
        if self._closed:
            if self._close_error:raise BridgeError('ros2_shutdown_incomplete')
            return
        self._closed=True;errors=[]
        if self.executor is not None:
            try:
                if not self.executor.shutdown(timeout_sec=.15):errors.append('executor')
            except Exception:errors.append('executor')
        if self.node is not None:
            try:self.node.destroy_node()
            except Exception:errors.append('node')
        if self.context is not None and self._rclpy is not None:
            try:self._rclpy.try_shutdown(context=self.context)
            except Exception:errors.append('context')
        if errors:
            self._close_error=True;raise BridgeError('ros2_shutdown_incomplete')
