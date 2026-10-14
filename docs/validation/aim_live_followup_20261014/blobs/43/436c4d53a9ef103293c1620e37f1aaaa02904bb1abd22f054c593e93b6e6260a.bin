"""JSONL peer for the pinned PB detector->tracker->projectile source overlay.

Optional ROS imports occur only in the real transport constructor. No algorithm
replacement, inference warmup, world TF or automatic software fire.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from .aim_camera_codec import camera_sensor_bundle,ros_camera_messages
from .pb_aim_contract import convert_pb_result
from .pb_aim_configure import ConfigureOnce
from .ros2_bridge import (EnvelopeBridge,BridgeSettings,BridgeError,parse_json,encode_json,
                         ENVELOPE_SCHEMA,MAX_RESPONSE,MAX_REQUEST,serve)
from ..deployment.profile import read_json_snapshot
from ..platform_v2.contracts import ContractError,exact
from ..platform_v2.aim_contracts import aim_status_for,AIM_STATUS_SCHEMA

MOUNT_SCHEMA='polar.sim.aim-mount-calibration.v2'

def checked_mount(ref,expected_sha,robot):
    ref=Path(ref).absolute()
    if ref.is_symlink():raise ContractError('pb_aim_mount_symlink')
    value,sha=read_json_snapshot(ref)
    if type(expected_sha) is not str or sha!=expected_sha:raise ContractError('pb_aim_mount_hash_changed')
    if (type(value) is not dict or value.get('schema')!=MOUNT_SCHEMA
        or value.get('origin')!='static_simulation_model_design_not_hardware_calibration'
        or type(value.get('robots')) is not dict or robot not in value['robots']):
        raise ContractError('pb_aim_simulated_mount_required')
    mount=copy.deepcopy(value['robots'][robot])
    exact(mount,('parent_frame','child_frame','translation_m','rotation_xyzw','source_site','source_body',
        'pitch_positive','pitch_joint_axis','kinematics'),'pb_aim_mount')
    if (mount['parent_frame']!='gimbal_link' or mount['child_frame']!='shooter_link'
        or mount['pitch_positive']!='up' or mount['pitch_joint_axis']!=[0,-1,0]):
        raise ContractError('pb_aim_mount_frame_convention')
    def vector(values,size):
        if type(values) is not list or len(values)!=size or any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
            raise ContractError('pb_aim_mount_finite')
    for key,size in (('translation_m',3),('rotation_xyzw',4),('pitch_joint_axis',3)):vector(mount[key],size)
    # This source adapter expects the real fixture's co-aligned muzzle axes.
    # A differently mounted robot requires a reviewed coordinate conversion.
    if mount['rotation_xyzw']!=[0,0,0,1]:raise ContractError('pb_aim_muzzle_axis_unsupported')
    k=mount['kinematics']
    fields=('origin_frame','origin_definition','yaw_frame','pitch_frame','chassis_to_origin_translation_m',
        'chassis_to_origin_rotation_xyzw','origin_to_yaw_translation_m','origin_to_yaw_rotation_xyzw',
        'yaw_to_pitch_translation_m','yaw_to_pitch_rotation_xyzw','yaw_joint_axis','pitch_joint_pivot_m',
        'source_yaw_body','source_yaw_joint','source_pitch_joint')
    exact(k,fields,'pb_aim_kinematics')
    if (k['origin_frame']!='gimbal_aim_origin' or k['origin_definition']!='chassis_fixed_frame_at_zero_yaw_joint_origin'
        or k['yaw_frame']!='gimbal_yaw' or k['pitch_frame']!='gimbal_link'
        or k['yaw_joint_axis']!=[0,0,1] or k['pitch_joint_pivot_m']!=[0,0,0]):
        raise ContractError('pb_aim_kinematics_convention')
    for name in fields:
        if name.endswith('_xyzw'):vector(k[name],4)
        elif name.endswith('_m') or name.endswith('_axis'):vector(k[name],3)
    for name in ('chassis_to_origin_rotation_xyzw','origin_to_yaw_rotation_xyzw','yaw_to_pitch_rotation_xyzw'):
        if k[name]!=[0,0,0,1]:raise ContractError('pb_aim_kinematics_rotation_unsupported')
    for key,suffix in (('source_site','__muzzle'),('source_body','__pitch')):
        if mount[key]!=robot+suffix:raise ContractError('pb_aim_mount_source_robot')
    for key,suffix in (('source_yaw_body','__yaw'),('source_yaw_joint','__gimbal_yaw'),('source_pitch_joint','__gimbal_pitch')):
        if k[key]!=robot+suffix:raise ContractError('pb_aim_kinematics_source_robot')
    sources=value.get('source_sha256')
    wanted={'rm_match/harness.xml','rm_match/match_model.py','rm_match/platform_v2/camera.py'}
    if type(sources) is not dict or set(sources)!=wanted:raise ContractError('pb_aim_mount_source_identity')
    root=Path(__file__).resolve().parents[2]
    for rel,expected in sources.items():
        if type(expected) is not str or hashlib.sha256((root/rel).read_bytes()).hexdigest()!=expected:
            raise ContractError('pb_aim_mount_source_changed')
    return mount,sha

def capture_feedback(bundle,mount):
    camera=bundle.camera
    if camera['extrinsics']['parent_frame']!='gimbal_link':raise ContractError('pb_aim_camera_mount_frame')
    q=camera['own_qpos_at_capture'];vel=camera['own_odom_velocity_at_capture']
    if math.hypot(vel[0],vel[1])>.06 or abs(vel[2])>.25:
        raise ContractError('pb_aim_stationary_first_required')
    return dict(stamp_ns=bundle.capture_stamp_ns,
        yaw_rotation_xyzw=[0.,0.,math.sin(q[3]/2),math.cos(q[3]/2)],
        pitch_rotation_xyzw=[0.,-math.sin(q[4]/2),0.,math.cos(q[4]/2)],
        muzzle=copy.deepcopy(mount),origin_scope='local_chassis_aligned_yaw_joint_origin_not_world_pose')

class PBAimBridge(EnvelopeBridge):
    def __init__(self,settings,*,clock=time.monotonic):
        if settings.kind!='aim':raise BridgeError('pb_aim_kind_required')
        super().__init__(settings,clock=clock);self.bundle=None

    def begin(self,observation):
        payload=super().begin(observation)
        self.bundle=camera_sensor_bundle(self._pending)
        return payload

    def receive_pb_result(self,raw):
        if self._pending is None or self.bundle is None:raise BridgeError('pb_aim_no_pending_source')
        if self.clock()>=self._deadline:raise BridgeError('ros2_response_timeout')
        value=convert_pb_result(parse_json(raw,MAX_RESPONSE),self._pending,self.bundle)
        field='status' if value['schema']==AIM_STATUS_SCHEMA else 'action'
        super().receive_action(encode_json(dict(schema=ENVELOPE_SCHEMA,type=field,
            adapter_id=self.settings.adapter_id,**{field:value}),MAX_RESPONSE))

    def close(self):self.bundle=None;super().close()

class PBAimRosTransport:
    def __init__(self,core,namespace,mount,*,run_uuid,calibration_id):
        self.node=None;self.rclpy=None;self._ros_started=False
        # No substitute message classes when optional interfaces are missing.
        import rclpy
        from rclpy.parameter import Parameter
        from sensor_msgs.msg import Image,CameraInfo
        from std_msgs.msg import String
        from rosgraph_msgs.msg import Clock
        from tf2_msgs.msg import TFMessage
        from geometry_msgs.msg import TransformStamped
        from polar_pb_aim_interfaces.msg import SourceImage
        from rclpy.qos import QoSProfile,ReliabilityPolicy,DurabilityPolicy,qos_profile_sensor_data
        self.core=core;self.rclpy=rclpy;self.mount=copy.deepcopy(mount);self.namespace=namespace
        self.configure_once=ConfigureOnce(run_uuid,calibration_id)
        self.SourceImage=SourceImage;self.Transform=TransformStamped;self.TFMessage=TFMessage;self.Clock=Clock
        rclpy.init();self._ros_started=True;self.node=rclpy.create_node(core.settings.node_name,namespace=namespace)
        self.node.set_parameters([Parameter('use_sim_time',Parameter.Type.BOOL,True)])
        self.image=self.node.create_publisher(SourceImage,'front_industrial_camera/image',qos_profile_sensor_data)
        self.tf=self.node.create_publisher(TFMessage,'tf',QoSProfile(depth=16,reliability=ReliabilityPolicy.RELIABLE))
        self.static=self.node.create_publisher(TFMessage,'tf_static',QoSProfile(depth=1,
            reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.clock=self.node.create_publisher(Clock,'clock',QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE))
        self.result=self.node.create_subscription(String,'polar/pb/aim_result',lambda msg:core.receive_pb_result(msg.data),
            QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE))
        self.configure_pub=self.node.create_publisher(String,'polar/pb/aim_configure',QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE))
        self.configure_sub=self.node.create_subscription(String,'polar/pb/aim_configured',
            lambda msg:self.configure_once.receive(msg.data),QoSProfile(depth=3,reliability=ReliabilityPolicy.RELIABLE))
        self.String=String
        self._static_signature=None

    def _transform(self,stamp,parent,child,translation,rotation):
        result=self.Transform();result.header.frame_id=parent;result.child_frame_id=child
        result.header.stamp.sec=stamp//1_000_000_000;result.header.stamp.nanosec=stamp%1_000_000_000
        for key,value in zip(('x','y','z'),translation):setattr(result.transform.translation,key,float(value))
        for key,value in zip(('x','y','z','w'),rotation):setattr(result.transform.rotation,key,float(value))
        return result

    def publish(self,payload):
        if not self.configure_once.ready:raise BridgeError('pb_aim_source_nodes_not_configured')
        request=parse_json(payload,MAX_REQUEST)
        bundle=self.core.bundle
        if bundle is None or request['observation']!=self.core._pending:raise BridgeError('pb_aim_publish_source_changed')
        if bundle.source_context['calibration_id']!=self.configure_once.calibration_id:
            raise BridgeError('pb_aim_configured_calibration_mismatch')
        try:feedback=capture_feedback(bundle,self.mount)
        except ContractError as exc:
            if str(exc)!='pb_aim_stationary_first_required':raise
            value=aim_status_for(self.core._pending,'pending_result')
            self.core.receive_action(encode_json(dict(schema=ENVELOPE_SCHEMA,type='status',
                adapter_id=self.core.settings.adapter_id,status=value),MAX_RESPONSE));return
        image,info,optical=ros_camera_messages(bundle)
        mount=self.mount
        static=[optical,self._transform(0,mount['parent_frame'],mount['child_frame'],mount['translation_m'],mount['rotation_xyzw'])]
        signature=json.dumps(bundle.camera['extrinsics'],sort_keys=True)
        if self._static_signature is not None and self._static_signature!=signature:
            raise BridgeError('pb_aim_camera_calibration_changed')
        if self._static_signature is None:
            self.static.publish(self.TFMessage(transforms=static));self._static_signature=signature
        stamp=bundle.capture_stamp_ns
        k=mount['kinematics']
        dynamic=[self._transform(stamp,k['origin_frame'],k['yaw_frame'],k['origin_to_yaw_translation_m'],feedback['yaw_rotation_xyzw']),
            self._transform(stamp,k['yaw_frame'],k['pitch_frame'],k['yaw_to_pitch_translation_m'],feedback['pitch_rotation_xyzw'])]
        self.tf.publish(self.TFMessage(transforms=dynamic))
        clock=self.Clock();clock.clock=image.header.stamp;self.clock.publish(clock)
        carrier=self.SourceImage();carrier.header=image.header;carrier.image=image;carrier.camera_info=info
        carrier.source_context=json.dumps(bundle.source_context,allow_nan=False,separators=(',',':'))
        self.image.publish(carrier)

    def wait_ready(self,timeout):
        deadline=self.core.clock()+timeout
        while self.core.clock()<deadline:
            if (self.image.get_subscription_count()>0
                and self.node.count_publishers(self.namespace+'/polar/pb/aim_result')>0
                and self.node.count_subscribers(self.namespace+'/tracker/target')>0
                and self.configure_pub.get_subscription_count()==3):return
            self.spin_once(min(.005,max(0.,deadline-self.core.clock())))
        raise BridgeError('pb_aim_actual_pipeline_not_ready')

    def configure(self,context,mount,timeout=1.):
        self.mount=copy.deepcopy(mount)
        raw=self.configure_once.begin(context)
        msg=self.String();msg.data=raw;self.configure_pub.publish(msg)
        deadline=self.core.clock()+timeout
        while not self.configure_once.ready:
            if self.core.clock()>=deadline:raise BridgeError('pb_aim_original_reset_configure_timeout')
            self.spin_once(min(.005,max(0.,deadline-self.core.clock())))

    def spin_once(self,timeout):self.rclpy.spin_once(self.node,timeout_sec=timeout)
    def close(self):
        errors=[]
        if self.node is not None:
            try:self.node.destroy_node();self.node=None
            except BaseException as exc:errors.append(exc)
        if self._ros_started:
            try:self.rclpy.shutdown();self._ros_started=False
            except BaseException as exc:errors.append(exc)
        if errors:raise BridgeError('pb_aim_ros_cleanup_failed') from errors[0]

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adapter-id',required=True);parser.add_argument('--robot-id',required=True)
    parser.add_argument('--episode',type=int,required=True);parser.add_argument('--binding-epoch',type=int,required=True)
    parser.add_argument('--namespace',required=True);parser.add_argument('--domain-id',type=int,required=True)
    parser.add_argument('--run-uuid',required=True);parser.add_argument('--calibration-id',required=True)
    parser.add_argument('--mount-ref',type=Path,required=True);parser.add_argument('--mount-sha256',required=True)
    args=parser.parse_args(argv)
    settings=BridgeSettings(args.adapter_id,'aim','pb_aim_jsonl_peer',args.namespace+'/input',args.namespace+'/result',args.domain_id,.08)
    mount,_=checked_mount(args.mount_ref,args.mount_sha256,args.robot_id)
    os.environ['ROS_DOMAIN_ID']=str(args.domain_id)
    # ROS logging is stderr; this duplicated stream alone carries the protocol.
    sys.stdout.flush();protocol=os.fdopen(os.dup(sys.stdout.fileno()),'wb',buffering=0)
    os.dup2(sys.stderr.fileno(),sys.stdout.fileno())
    core=PBAimBridge(settings);transport=None
    expected=dict(robot_id=args.robot_id,episode=args.episode,binding_epoch=args.binding_epoch)
    original_reset=core.reset
    def reset(context,config):
        if any(type(context.get(k)) is not type(v) or context[k]!=v for k,v in expected.items()):
            raise BridgeError('pb_aim_fresh_process_generation_mismatch')
        return original_reset(context,config)
    core.reset=reset
    try:
        # Hold the object before optional ROS setup so partial-constructor
        # failures also destroy the real node/context rather than leak them.
        transport=PBAimRosTransport.__new__(PBAimRosTransport)
        transport.__init__(core,args.namespace,mount,run_uuid=args.run_uuid,calibration_id=args.calibration_id)
        transport.wait_ready(1.)
        def configured_reset(context,config):
            reset(context,config);transport.configure(context,mount,1.)
        core.reset=configured_reset
        serve(core,transport,sys.stdin.buffer,protocol)
        return 0
    finally:
        core.close()
        if transport is not None:transport.close()
        protocol.close()
if __name__=='__main__':raise SystemExit(main())
