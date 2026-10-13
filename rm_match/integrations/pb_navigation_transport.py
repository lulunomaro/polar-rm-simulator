"""Actual ROS 2 Humble/Livox messages; optional dependencies fail explicitly."""
from __future__ import annotations
import os
import time
from .ros2_bridge import BridgeError
from .pb_navigation_phases import PHASES


class HumbleNavigationTransport:
    def __init__(self,settings,core):
        self.node=None;self.executor=None;self.context=None;self._rclpy=None
        self._closed=False;self._close_error=False;self._last_imu_ns=-1;self._extrinsics=None
        self.settings=settings;self.rejected_results=0
        os.environ['ROS_DOMAIN_ID']=str(settings.domain_id)
        os.environ['ROS_LOCALHOST_ONLY']='1';os.environ['ROS_AUTOMATIC_DISCOVERY_RANGE']='LOCALHOST'
        os.environ['ROS_STATIC_PEERS']='';os.environ['RCUTILS_LOGGING_USE_STDOUT']='0'
        rmw=os.environ.get('RMW_IMPLEMENTATION','rmw_fastrtps_cpp')
        if rmw not in ('rmw_fastrtps_cpp','rmw_cyclonedds_cpp'):raise BridgeError('pb_local_dds_rmw_required')
        os.environ['RMW_IMPLEMENTATION']=rmw
        PHASES.mark('ros_import_begin')
        try:
            import rclpy
            from rclpy.context import Context
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.qos import QoSProfile, HistoryPolicy, ReliabilityPolicy, DurabilityPolicy
            from sensor_msgs.msg import PointCloud2, PointField, Imu
            from livox_ros_driver2.msg import CustomMsg, CustomPoint
            from rosgraph_msgs.msg import Clock
            from geometry_msgs.msg import TransformStamped
            from nav_msgs.msg import Odometry
            from std_msgs.msg import String
            from tf2_msgs.msg import TFMessage
        except (ImportError,OSError):
            PHASES.mark('ros_import_failed')
            raise BridgeError('pb_humble_livox_dependencies_unavailable') from None
        PHASES.mark('ros_import_end')
        self._rclpy=rclpy;self.types=(CustomMsg,CustomPoint,PointCloud2,PointField,Imu,Clock,String,TransformStamped,TFMessage)
        self.context=Context()
        try:
            PHASES.mark('rclpy_init_begin')
            rclpy.init(args=[],context=self.context,domain_id=settings.domain_id)
            PHASES.mark('rclpy_init_end');PHASES.mark('node_begin')
            self.node=rclpy.create_node(settings.node_name,context=self.context,use_global_arguments=False,
                cli_args=['--ros-args','--remap','/tf_static:='+settings.tf_static_topic],
                enable_rosout=False,start_parameter_services=False)
            sensor=QoSProfile(history=HistoryPolicy.KEEP_LAST,depth=1,reliability=ReliabilityPolicy.BEST_EFFORT,durability=DurabilityPolicy.VOLATILE)
            imu_qos=QoSProfile(history=HistoryPolicy.KEEP_LAST,depth=1024,reliability=ReliabilityPolicy.BEST_EFFORT,durability=DurabilityPolicy.VOLATILE)
            control=QoSProfile(history=HistoryPolicy.KEEP_LAST,depth=1,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.VOLATILE)
            request_qos=QoSProfile(history=HistoryPolicy.KEEP_LAST,depth=8,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.VOLATILE)
            self.cloud_pub=self.node.create_publisher(CustomMsg,settings.cloud_topic,sensor)
            self.pc_pub=self.node.create_publisher(PointCloud2,settings.pointcloud_topic,sensor)
            self.imu_pub=self.node.create_publisher(Imu,settings.imu_topic,imu_qos)
            self.clock_pub=self.node.create_publisher(Clock,settings.clock_topic,control)
            self.request_pub=self.node.create_publisher(String,settings.request_topic,request_qos)
            def result(message):
                try:core.receive_result(message.data)
                except ValueError:self.rejected_results=min(self.rejected_results+1,2**53-1)
            self.result_sub=self.node.create_subscription(String,settings.result_topic,result,control)
            def odom(message):
                try:core.receive_odom_stamp(message.header.stamp.sec*1000000000+message.header.stamp.nanosec)
                except ValueError:pass
            self.odom_sub=self.node.create_subscription(Odometry,settings.odom_topic,odom,sensor)
            # Same message/QoS as Humble StaticTransformBroadcaster; avoid its
            # package-level buffer/client/listener imports on fresh startup.
            static_qos=QoSProfile(history=HistoryPolicy.KEEP_LAST,depth=1,
                reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.TRANSIENT_LOCAL)
            self.tf_pub=self.node.create_publisher(TFMessage,settings.tf_static_topic,static_qos)
            self.executor=SingleThreadedExecutor(context=self.context);self.executor.add_node(self.node)
            PHASES.mark('node_end');PHASES.mark('transport_ready')
        except BaseException:self.close();raise

    @staticmethod
    def _stamp(target,value):target.sec=value['sec'];target.nanosec=value['nanosec']

    def _header(self,target,value):
        self._stamp(target.stamp,value['stamp']);target.frame_id=value['frame_id']

    def publish_bundle(self,bundle,request):
        if self._closed:raise BridgeError('pb_transport_closed')
        CustomMsg,CustomPoint,PointCloud2,PointField,Imu,Clock,String,TransformStamped,TFMessage=self.types
        ext=bundle['extrinsics']
        if self._extrinsics is not None and self._extrinsics!=ext:raise BridgeError('pb_extrinsics_changed_within_process')
        if self._extrinsics is None:
            tf=TransformStamped();tf.header.frame_id=ext['parent_frame'];tf.child_frame_id=bundle['custom']['header']['frame_id']
            for k,v in zip(('x','y','z'),ext['translation_m']):setattr(tf.transform.translation,k,float(v))
            for k,v in zip(('x','y','z','w'),ext['rotation_xyzw']):setattr(tf.transform.rotation,k,float(v))
            self.tf_pub.publish(TFMessage(transforms=[tf]));self._extrinsics=ext
        clock=Clock();self._stamp(clock.clock,bundle['clock']);self.clock_pub.publish(clock)
        ctx=String();ctx.data=request;self.request_pub.publish(ctx)
        # IMU ends at the cloud end, allowing actual LIO interpolation. Shared
        # boundary samples are emitted once rather than repeated as new IMU.
        for row in bundle['imu']:
            stamp=row['header']['stamp'];ns=stamp['sec']*1000000000+stamp['nanosec']
            if ns<=self._last_imu_ns:continue
            m=Imu();self._header(m.header,row['header'])
            m.orientation_covariance=list(row['orientation_covariance'])
            for k,v in zip(('x','y','z'),row['angular_velocity']):setattr(m.angular_velocity,k,float(v))
            for k,v in zip(('x','y','z'),row['linear_acceleration']):setattr(m.linear_acceleration,k,float(v))
            self.imu_pub.publish(m);self._last_imu_ns=ns
        row=bundle['custom'];m=CustomMsg();self._header(m.header,row['header'])
        m.timebase=row['timebase'];m.point_num=row['point_num'];m.lidar_id=row['lidar_id'];m.rsvd=row['rsvd']
        points=[]
        for point in row['points']:
            p=CustomPoint()
            for k,v in point.items():setattr(p,k,v)
            points.append(p)
        m.points=points;self.cloud_pub.publish(m)
        row=bundle['pointcloud'];m=PointCloud2();self._header(m.header,row['header'])
        fields=[]
        for f in row['fields']:
            p=PointField()
            for k,v in f.items():setattr(p,k,v)
            fields.append(p)
        m.fields=fields
        for k in ('height','width','is_bigendian','point_step','row_step','data','is_dense'):setattr(m,k,row[k])
        self.pc_pub.publish(m)

    def spin_once(self,timeout):
        if self._closed:raise BridgeError('pb_transport_closed')
        self.executor.spin_once(timeout_sec=timeout)

    def wait_ready(self,timeout=1.):
        deadline=time.monotonic()+timeout
        PHASES.mark('graph_wait_enter');last_counts=None
        while True:
            counts=(self.cloud_pub.get_subscription_count(),self.imu_pub.get_subscription_count(),
                self.request_pub.get_subscription_count(),self.node.count_publishers(self.settings.result_topic))
            if counts!=last_counts:PHASES.mark('graph_counts',counts);last_counts=counts
            if all(counts):PHASES.mark('graph_ready');return
            remaining=deadline-time.monotonic()
            if remaining<=0:
                PHASES.mark('graph_timeout');raise BridgeError('pb_navigation_graph_unavailable')
            self.spin_once(min(.01,remaining))

    def close(self):
        if self._closed:
            if self._close_error:raise BridgeError('pb_shutdown_incomplete')
            return
        self._closed=True;errors=[]
        PHASES.mark('transport_cleanup_begin')
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
            PHASES.mark('transport_cleanup_failed');self._close_error=True;raise BridgeError('pb_shutdown_incomplete')
        PHASES.mark('transport_cleanup_end')
