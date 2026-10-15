#!/usr/bin/env python3
"""Bounded real Point-LIO / SLAM / PB Nav2 to physical sentry evidence."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
import os
import re
from pathlib import Path
import secrets
import signal
import sys
import threading
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
IDENTITY=('robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline')


def identity(value):
    if type(value.get('robot_id')) is not str:raise ValueError('source_robot_type')
    if any(type(value.get(k)) is not int for k in ('episode','binding_epoch','observed_seq')):
        raise ValueError('source_integer_identity_type')
    if any(type(value.get(k)) not in (int,float) or not math.isfinite(value[k]) for k in ('sim_time','wall_deadline')):
        raise ValueError('source_clock_identity_type')
    return tuple((type(value[k]).__name__,value[k]) for k in IDENTITY)


def audit_navigation_consumption(rows,ros_rows,*,result_profile='scan_v1'):
    """Join original controller/LIO provenance with actual actuator receipts."""
    if type(result_profile) is not str or result_profile not in ('scan_v1','follow_path_uuid_v2'):
        raise ValueError('audit_result_profile')
    goal_profile=result_profile=='follow_path_uuid_v2'
    result_schema='polar.sim.pb-navigation-result.v2' if goal_profile else 'polar.sim.pb-navigation-result.v1'
    controller_id='nav2_server_pb_pid_goal_v1' if goal_profile else 'pb_controller_sourced_v1'
    from rm_match.platform_v2.contracts import exact,integer,finite,validate_action
    requests={};localizations={};results={};enqueues={};activations={};errors=[];consumed=set();nonzero=set()
    request_keys=('adapter_id',*IDENTITY,'cloud_frame_id','acquisition_start_ns','acquisition_end_ns')
    def request_checked(value,schema,extra=()):
        exact(value,('schema',*request_keys,*extra),'audit_source')
        if value['schema']!=schema or value['adapter_id']!='custom_pb_navigation':raise ValueError('source_schema_or_adapter')
        key=identity(value)
        if value['robot_id']!='red_sentry' or value['episode']!=0 or value['binding_epoch']!=1:raise ValueError('source_generation')
        for name in ('sim_time','wall_deadline'):finite(value[name],name,0,1e12)
        for name in ('cloud_frame_id','acquisition_start_ns','acquisition_end_ns',*extra):integer(value[name],name)
        if not 0<value['acquisition_end_ns']-value['acquisition_start_ns']<=200000000:raise ValueError('source_scan_window')
        return key
    for row in rows:
        if row.get('event')=='sdk_adapter_activation':
            try:
                window=row['window'];activation=row['activation']
                for name in ('window_id',):integer(window[name],name)
                for name in ('binding_epoch','seq','window_id'):integer(activation[name],name)
                integer(window['lease_epochs']['motion'],'sdk_motion_epoch')
                for value in (window['issued_wall'],window['expires_wall'],window['valid_for_s'],activation['activation_expires'],row['wall_time']):finite(value,'sdk_clock',0,1e12)
                if (window['lease_epochs']!={'motion':1} or activation['binding_epoch']!=1
                    or activation['window_id']!=window['window_id']
                    or activation['activation_expires']!=window['expires_wall']
                    or not 0<window['valid_for_s']<=.15
                    or abs(window['expires_wall']-window['issued_wall']-window['valid_for_s'])>1e-6):raise ValueError('sdk_window_ack_mismatch')
                activations[(activation['binding_epoch'],activation['seq'],activation['window_id'])]=window
            except (KeyError,TypeError,ValueError):errors.append('malformed_actual_sdk_activation')
        if row.get('event')=='adapter_result' and row.get('kind')=='navigation' and row.get('error'):
            errors.append('actual_navigation_adapter_fault:'+str(row['error']))
        if row.get('event')!='adapter_enqueue' or row.get('kind')!='navigation':continue
        try:
            source={k:row['observation_sim_time'] if k=='sim_time' else row[k] for k in IDENTITY}
            cloud=row['cloud_acquisition'];budget=row['sensor_budget']
            exact(cloud,('frame_id','acquisition_start_ns','acquisition_end_ns','profile_sha256'),'audit_cloud')
            for name in ('frame_id','acquisition_start_ns','acquisition_end_ns'):integer(cloud[name],name)
            if (type(cloud['profile_sha256']) is not str or len(cloud['profile_sha256'])!=64
                or any(c not in '0123456789abcdef' for c in cloud['profile_sha256'])):raise ValueError('source_profile_hash')
            if (cloud['frame_id']!=budget['frame_id'] or cloud['profile_sha256']!=budget['profile_sha256']
                or cloud['acquisition_end_ns']!=round(budget['capture_sim_time']*1e9)
                or not 0<cloud['acquisition_end_ns']-cloud['acquisition_start_ns']<=200000000):
                raise ValueError('enqueue_original_cloud_mismatch')
            enqueues.setdefault(identity(source),[]).append((cloud,budget))
        except (KeyError,TypeError,ValueError):errors.append('malformed_original_enqueue')
    for row in ros_rows:
        try:
            if row.get('topic_kind')=='request':
                value=row['value'];key=request_checked(value,'polar.sim.pb-navigation-request.v1')
                requests.setdefault(key,[]).append(value)
            elif row.get('topic_kind')=='localization':
                value=row['value'];key=request_checked(value,'polar.sim.pb-localization-result.v1',('localization_stamp_ns',))
                if not value['acquisition_start_ns']<=value['localization_stamp_ns']<=value['acquisition_end_ns']:raise ValueError('source_localization_window')
                localizations.setdefault(key,[]).append(value)
            elif row.get('topic_kind')=='controller_result':
                value=row['value'];exact(value,('schema','adapter_id','action','source'),'audit_result')
                if type(value['schema']) is not str or value['schema']!=result_schema or value['adapter_id']!='custom_pb_navigation':raise ValueError('result_schema_or_adapter')
                action=value['action'];key=identity(action)
                validate_action(action,action,dict(kind='navigation',output_modes=['velocity_body']))
                source=value['source'];fields=('cloud_frame_id','localization_stamp_ns','controller_stamp_ns','controller_id')
                exact(source,(*fields,'goal_uuid') if goal_profile else fields,'audit_controller_source')
                if goal_profile and (type(source['goal_uuid']) is not str or not re.fullmatch('[0-9a-f]{32}',source['goal_uuid'])):
                    raise ValueError('source_goal_uuid')
                for name in ('cloud_frame_id','localization_stamp_ns','controller_stamp_ns'):integer(source[name],name)
                if type(source['controller_id']) is not str or source['controller_id']!=controller_id:raise ValueError('source_controller')
                results.setdefault(key,[]).append(value)
        except (KeyError,TypeError,ValueError):errors.append('malformed_ros_source_record')
    for row in rows:
        if row.get('event')!='navigation_consumed' or row.get('phase')!='integration_entry':continue
        motion=row['target'].get('motion')
        if row['target'].get('fire') is not False:errors.append('unauthorized_fire')
        if motion is None:continue
        consumed.add(row['consume_sim_time'])
        action=row.get('action');budget=row.get('navigation_budget');authorization=row.get('authorization');output_auth=row.get('output_authorization')
        try:
            if not action or not budget or not authorization or not output_auth:raise ValueError('missing_consumption_authority')
            validate_action(action,action,dict(kind='navigation',output_modes=['velocity_body']))
            key=identity(action)
            if (action['robot_id']!='red_sentry' or action['episode']!=0 or action['binding_epoch']!=1
                or motion!=action['command']):raise ValueError('actuator_identity_or_command')
            wall=row['consume_wall'];sim=row['consume_sim_time']
            for clock in (wall,sim,*[budget[k] for k in ('capture_wall','wall_deadline','capture_sim_time','sim_deadline')]):finite(clock,'audit_clock',0,1e12)
            integer(budget['frame_id'],'budget_frame_id')
            for auth in (authorization,output_auth):
                integer(auth['epoch'],'authority_epoch')
                integer(auth['activation_seq'],'authority_seq');integer(auth['activation_window_id'],'authority_window_id')
                for name in ('activation_expires','activation_window_deadline'):finite(auth[name],name,0,1e12)
                window=activations.get((auth['epoch'],auth['activation_seq'],auth['activation_window_id']))
                if (window is None or window['expires_wall']!=auth['activation_expires']
                    or window['expires_wall']!=auth['activation_window_deadline']
                    or not window['issued_wall']<=wall<window['expires_wall']):raise ValueError('missing_original_sdk_activation_ack')
            if not (budget['source']=='navigation_sensor_v1' and budget['capture_wall']<=wall<budget['wall_deadline']
                and wall<action['wall_deadline'] and budget['capture_sim_time']<=sim<=budget['sim_deadline']
                and budget['wall_deadline']-budget['capture_wall']<=.150001
                and budget['sim_deadline']-budget['capture_sim_time']<=.150001):raise ValueError('original_sensor_deadline')
            if not (authorization['activation_required'] is True and authorization['epoch']==1
                and wall<authorization['activation_expires']<=authorization['activation_window_deadline']):
                raise ValueError('original_sdk_deadman')
            if not (output_auth['activation_required'] is True and output_auth['epoch']==1
                and wall<output_auth['activation_expires']<=output_auth['activation_window_deadline']
                and action['wall_deadline']<=output_auth['activation_expires']):raise ValueError('output_sdk_authority')
            cmd=action['command']
            if (cmd['frame']!='base_link' or not all(math.isfinite(cmd[k]) for k in ('vx_mps','vy_mps','wz_rps'))
                or math.hypot(cmd['vx_mps'],cmd['vy_mps'])>1.0 or abs(cmd['wz_rps'])>2.0):raise ValueError('velocity_limit')
            originals=[cloud for cloud,original in enqueues.get(key,[]) if original==budget
                and type(original['frame_id']) is type(budget['frame_id'])]
            if not originals:raise ValueError('missing_original_sensor_enqueue')
            candidates=results.get(key,[])
            matching=[r for r in candidates if r['action']==action and r['source']['cloud_frame_id']==budget['frame_id']]
            if not matching:raise ValueError('missing_actual_controller_result')
            proven=False
            for result in matching:
                source=result['source']
                for loc in localizations.get(key,[]):
                    for request in requests.get(key,[]):
                        if any(type(loc[k]) is not type(request[k]) or loc[k]!=request[k] for k in request_keys):continue
                        for cloud in originals:
                            if (loc['cloud_frame_id']==cloud['frame_id']==source['cloud_frame_id']
                                and loc['acquisition_start_ns']==cloud['acquisition_start_ns']
                                and loc['acquisition_end_ns']==cloud['acquisition_end_ns']
                                and loc['localization_stamp_ns']==source['localization_stamp_ns']
                                and loc['acquisition_start_ns']<=source['localization_stamp_ns']<=source['controller_stamp_ns']<=loc['acquisition_end_ns']):
                                proven=True
            if not proven:raise ValueError('missing_immutable_lio_source')
            if any(abs(cmd[k])>1e-8 for k in ('vx_mps','vy_mps','wz_rps')):nonzero.add(sim)
        except (KeyError,TypeError,ValueError) as exc:errors.append(str(exc))
    return dict(consumed_steps=len(consumed),nonzero_consumed_steps=len(nonzero),
        actual_sensor_requests=sum(map(len,requests.values())),
        actual_controller_results=sum(map(len,results.values())),actual_localizations=sum(map(len,localizations.values())),
        errors=errors,passed=bool(consumed and nonzero) and not errors)


MAX_RECORDED_PATH_POSES=4096
MAX_ALGORITHM_RECORD_BYTES=2*1024*1024


def _ros_stamp(value):
    sec=value.sec;ns=value.nanosec
    if type(sec) is not int or type(ns) is not int or not 0<=sec<=2147483647 or not 0<=ns<1000000000:
        raise ValueError('algorithm_evidence_stamp')
    return dict(sec=sec,nanosec=ns)


def _ros_header(value):
    frame=value.frame_id
    if type(frame) is not str or len(frame.encode('utf8'))>128 or any(ord(c)<32 for c in frame):
        raise ValueError('algorithm_evidence_frame')
    return dict(stamp=_ros_stamp(value.stamp),frame_id=frame)


def _ros_vector(value,axes):
    values={key:getattr(value,key) for key in axes}
    if any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1e6 for v in values.values()):
        raise ValueError('algorithm_evidence_nonfinite_or_unbounded')
    return values


def recorded_pose(value):
    """Exact ROS message fields, without clock conversion or stamp substitution."""
    return dict(header=_ros_header(value.header),pose=dict(position=_ros_vector(value.pose.position,'xyz'),
        orientation=_ros_vector(value.pose.orientation,'xyzw')))


def recorded_transform(value):
    header=_ros_header(value.header)
    if header['frame_id']!='map' or value.child_frame_id!='base_link':
        raise ValueError('algorithm_evidence_transform_frames')
    return dict(header=header,child_frame_id=value.child_frame_id,
        transform=dict(translation=_ros_vector(value.transform.translation,'xyz'),
                       rotation=_ros_vector(value.transform.rotation,'xyzw')))


def recorded_goal_uuid(handle):
    from array import array
    value=handle.goal_id.uuid
    if type(value) in (bytes,bytearray):
        raw=bytes(value)
    elif type(value) is array and value.typecode=='B':
        raw=value.tobytes()
    elif type(value) in (list,tuple):
        if len(value)!=16 or any(type(v) is not int or not 0<=v<=255 for v in value):
            raise ValueError('algorithm_evidence_goal_uuid')
        raw=bytes(value)
    elif type(value).__module__=='numpy':
        # Humble generated uint8 arrays use ndarray/numpy.uint8, not Python int.
        # Accept only the exact ROS wire dtype/shape, never integer coercion.
        import numpy as np
        if type(value) is not np.ndarray or value.dtype!=np.dtype('uint8') or value.shape!=(16,):
            raise ValueError('algorithm_evidence_goal_uuid')
        raw=value.tobytes(order='C')
    else:raise ValueError('algorithm_evidence_goal_uuid')
    if len(raw)!=16:
        raise ValueError('algorithm_evidence_goal_uuid')
    return raw.hex()


def recorded_path_result(result,handle):
    path=result.result.path
    if type(result.status) is not int or not 0<=result.status<=6:
        raise ValueError('algorithm_evidence_action_status')
    if len(path.poses)>MAX_RECORDED_PATH_POSES:raise ValueError('algorithm_evidence_path_oversized')
    return dict(goal_uuid=recorded_goal_uuid(handle),status=result.status,
        path=dict(header=_ros_header(path.header),poses=[recorded_pose(pose) for pose in path.poses]),
        planning_time=_ros_stamp(result.result.planning_time))


class AlgorithmObserver:
    """Only estimated ROS poses can select the relative test goal."""
    def __init__(self,namespace,domain_id,diagnostics=False,receive_clock='host_perf_counter'):
        from tools.pb_navigation_stack import DDS_ENVIRONMENT,_DDS_INIT_LOCK,namespace_checked
        namespace_checked(namespace)
        if type(domain_id) is not int or domain_id!=84:raise ValueError('observer_domain_84_required')
        if type(diagnostics) is not bool:raise ValueError('observer_diagnostics_boolean_required')
        if type(receive_clock) is not str or receive_clock not in ('host_perf_counter','linux_local_perf_counter'):
            raise ValueError('observer_receive_clock_required')
        self.receive_clock=receive_clock
        import rclpy
        from rclpy.context import Context
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import QoSProfile,ReliabilityPolicy,DurabilityPolicy
        from nav_msgs.msg import Odometry,OccupancyGrid
        from std_msgs.msg import String
        from tf2_ros import Buffer,TransformListener
        self.rclpy=rclpy;self.context=Context();self.rows=[];self.errors=[];self.lock=threading.Lock()
        self.odom_count=0;self.map_count=0;self.goal_report={};self.closed=False
        self.action_request_id=None;self.action_request_seq=0
        with _DDS_INIT_LOCK:
            previous={k:os.environ.get(k) for k in DDS_ENVIRONMENT}
            try:
                os.environ.update(DDS_ENVIRONMENT)
                rclpy.init(args=[],context=self.context,domain_id=domain_id)
            finally:
                for k,v in previous.items():
                    if v is None:os.environ.pop(k,None)
                    else:os.environ[k]=v
        remaps=[]
        for name in ('tf','tf_static','clock'):remaps+=['--remap','/'+name+':='+namespace+'/'+name]
        self.node=rclpy.create_node('polar_sil_observer',namespace=namespace,context=self.context,
            cli_args=['--ros-args',*remaps],use_global_arguments=False,enable_rosout=False,
            parameter_overrides=[rclpy.parameter.Parameter('use_sim_time',value=True)])
        self.buffer=Buffer(node=self.node);self.listener=TransformListener(self.buffer,self.node,spin_thread=False)
        self.executor=SingleThreadedExecutor(context=self.context);self.executor.add_node(self.node)
        sensor=QoSProfile(depth=8,reliability=ReliabilityPolicy.BEST_EFFORT)
        reliable=QoSProfile(depth=64,reliability=ReliabilityPolicy.RELIABLE)
        maps=QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.TRANSIENT_LOCAL)
        def odom(value):self.odom_count+=1
        def map_received(value):
            if value.info.width and value.info.height:self.map_count+=1
        self.subs=[self.node.create_subscription(Odometry,namespace+'/odometry',odom,sensor),
            self.node.create_subscription(OccupancyGrid,namespace+'/map',map_received,maps)]
        def receive(kind):
            def callback(msg):
                try:
                    if len(msg.data)>8192:raise ValueError('observer_message_oversized')
                    value=json.loads(msg.data,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite')))
                    with self.lock:
                        if len(self.rows)>=20000:raise ValueError('observer_queue_full')
                        self.rows.append(dict(topic_kind=kind,receive_wall=time.perf_counter(),
                                              receive_clock=self.receive_clock,value=value))
                except Exception as exc:self.errors.append(type(exc).__name__+':'+str(exc))
            return callback
        for kind,topic in [('request','request'),('localization','localization'),('controller_result','result')]:
            self.subs.append(self.node.create_subscription(String,namespace+'/polar/pb/'+topic,receive(kind),reliable))
        if diagnostics:
            self.subs.append(self.node.create_subscription(String,namespace+'/polar/pb/dispatch',receive('dispatch_diagnostic'),
                QoSProfile(depth=8,reliability=ReliabilityPolicy.RELIABLE)))
        self.namespace=namespace;self.thread=threading.Thread(target=self.executor.spin,name='sil-ros-observer',daemon=True);self.thread.start()

    def wait_future(self,future,stop,timeout=5.):
        end=time.perf_counter()+timeout
        while not future.done():
            if stop.wait(.01) or time.perf_counter()>=end:raise TimeoutError('bounded_algorithm_service')
        return future.result()

    def record_algorithm(self,kind,**fields):
        """Bounded observation only: never publish these records back to ROS."""
        if kind not in ('goal_source_tf','planner_goal_accepted','planner_path_result',
                        'follow_path_goal_accepted','follow_path_result','ending_estimated_tf',
                        'ending_estimated_tf_unavailable'):
            raise ValueError('algorithm_evidence_kind')
        value=dict(schema='polar.pb.algorithm-action-evidence.v1',namespace=self.namespace,
                   action_request_id=self.action_request_id,action_request_seq=self.action_request_seq,**fields)
        if type(self.action_request_seq) is not int or self.action_request_seq<0:
            raise ValueError('algorithm_evidence_request_sequence')
        if self.action_request_id is None:
            if not kind.startswith('ending_estimated_tf') or self.action_request_seq!=0:
                raise ValueError('algorithm_evidence_request_identity')
        elif (type(self.action_request_id) is not str or len(self.action_request_id)!=32 or
              any(c not in '0123456789abcdef' for c in self.action_request_id) or self.action_request_seq<1):
            raise ValueError('algorithm_evidence_request_identity')
        if len(json.dumps(value,allow_nan=False,separators=(',',':')).encode('utf8'))>MAX_ALGORITHM_RECORD_BYTES:
            raise ValueError('algorithm_evidence_record_oversized')
        with self.lock:
            if len(self.rows)>=20000:raise ValueError('observer_queue_full')
            self.rows.append(dict(topic_kind=kind,receive_wall=time.perf_counter(),
                                 receive_clock=self.receive_clock,value=value))

    def record_ending_estimate(self):
        # Lookup is immediate from the actual buffer, with no wait, new input or TF retagging.
        from rclpy.time import Time
        try:
            pose=self.buffer.lookup_transform('map','base_link',Time())
        except Exception as exc:
            self.record_algorithm('ending_estimated_tf_unavailable',error_type=type(exc).__name__,
                                  postprocess_only=True,groundtruth_frame_comparison_qualified=False)
            return
        self.record_algorithm('ending_estimated_tf',source_kind='actual_tf_buffer_lookup',
            transform=recorded_transform(pose),postprocess_only=True,algorithm_input=False,
            groundtruth_frame_comparison_qualified=False)

    def drive_goal(self,stack,stop):
        from geometry_msgs.msg import PoseStamped
        from nav2_msgs.action import ComputePathToPose,FollowPath
        from rclpy.action import ActionClient
        from rclpy.time import Time
        clients=[]
        try:
            end=time.perf_counter()+20.
            pose=None
            while pose is None:
                if stop.wait(.02) or time.perf_counter()>=end:raise TimeoutError('actual_localization_and_map_unavailable')
                stack.poll_health()
                if not self.odom_count or not self.map_count:continue
                try:pose=self.buffer.lookup_transform('map','base_link',Time())
                except Exception:continue
            stack.activate_controller()
            goal=PoseStamped();goal.header.frame_id='map';goal.header.stamp=pose.header.stamp
            goal.pose.position.x=pose.transform.translation.x+1.0
            goal.pose.position.y=pose.transform.translation.y
            goal.pose.orientation=pose.transform.rotation
            self.action_request_id=secrets.token_hex(16)
            self.action_request_seq+=1
            self.record_algorithm('goal_source_tf',source_kind='actual_tf_buffer_lookup',
                transform=recorded_transform(pose),goal=recorded_pose(goal),relative_offset_m=[1.,0.],
                action_name=self.namespace+'/compute_path_to_pose',planner_id='GridBased',use_start=False)
            self.goal_report=dict(source='actual_algorithm_map_to_base_link_tf',frame='map',
                source_stamp_ns=pose.header.stamp.sec*1000000000+pose.header.stamp.nanosec,
                relative_offset_m=[1.,0.],goal_xy=[goal.pose.position.x,goal.pose.position.y])
            planner=ActionClient(self.node,ComputePathToPose,self.namespace+'/compute_path_to_pose');clients.append(planner)
            controller=ActionClient(self.node,FollowPath,self.namespace+'/follow_path');clients.append(controller)
            if not planner.wait_for_server(timeout_sec=2.) or not controller.wait_for_server(timeout_sec=2.):raise TimeoutError('actual_nav2_action_server_unavailable')
            request=ComputePathToPose.Goal();request.goal=goal;request.planner_id='GridBased';request.use_start=False
            handle=self.wait_future(planner.send_goal_async(request),stop)
            planner_uuid=recorded_goal_uuid(handle)
            self.record_algorithm('planner_goal_accepted',action_name=self.namespace+'/compute_path_to_pose',
                goal_uuid=planner_uuid,accepted=handle.accepted)
            if not handle.accepted:raise ValueError('actual_planner_goal_rejected')
            result=self.wait_future(handle.get_result_async(),stop)
            self.record_algorithm('planner_path_result',action_name=self.namespace+'/compute_path_to_pose',
                planner_id=request.planner_id,use_start=request.use_start,**recorded_path_result(result,handle))
            if result.status!=4 or len(result.result.path.poses)<2:raise ValueError('actual_planner_failed_or_empty_path')
            self.goal_report['path_poses']=len(result.result.path.poses);self.goal_report['planner_status']=result.status
            request=FollowPath.Goal();request.path=result.result.path;request.controller_id='FollowPath';request.goal_checker_id='general_goal_checker'
            handle=self.wait_future(controller.send_goal_async(request),stop)
            controller_uuid=recorded_goal_uuid(handle)
            self.record_algorithm('follow_path_goal_accepted',action_name=self.namespace+'/follow_path',
                goal_uuid=controller_uuid,planner_goal_uuid=planner_uuid,accepted=handle.accepted,
                controller_id=request.controller_id,goal_checker_id=request.goal_checker_id)
            if not handle.accepted:raise ValueError('actual_controller_path_rejected')
            self.goal_report['follow_path_accepted']=True
            future=handle.get_result_async()
            while not future.done() and not stop.wait(.02):stack.poll_health()
            if stop.is_set() and not future.done():
                self.wait_future(handle.cancel_goal_async(),threading.Event(),timeout=.5)
                self.goal_report['follow_path_canceled_at_bounded_end']=True
            elif future.done():
                result=future.result()
                if type(result.status) is not int or not 0<=result.status<=6:raise ValueError('algorithm_evidence_action_status')
                self.record_algorithm('follow_path_result',action_name=self.namespace+'/follow_path',
                    goal_uuid=controller_uuid,planner_goal_uuid=planner_uuid,status=result.status)
                self.goal_report['follow_path_status']=result.status
                if result.status!=4:raise ValueError('actual_controller_path_failed')
        except Exception as exc:
            if stop.is_set():self.goal_report['interrupted_at_bounded_end']=type(exc).__name__+':'+str(exc)
            else:self.errors.append(type(exc).__name__+':'+str(exc))
        finally:
            for client in clients:client.destroy()

    def close(self):
        if self.closed:return
        self.closed=True;self.executor.shutdown(timeout_sec=.5);self.thread.join(.5)
        self.node.destroy_node();self.rclpy.try_shutdown(context=self.context)
        if self.thread.is_alive():self.errors.append('observer_thread_not_reaped')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment',type=Path,required=True)
    parser.add_argument('--stack-config',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--seconds',type=float,default=30.)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--diagnostics',action='store_true',help='enable bounded original callback and controller guard metadata')
    args=parser.parse_args(argv)
    if not 5<=args.seconds<=60:parser.error('bounded 5..60 seconds required')
    if not args.run:
        print(json.dumps(dict(status='plan_only',scope=__doc__,control_window_seconds=.15,image_limit_seconds=.08,
            diagnostics=args.diagnostics,truth_input=False,hardware=False,training=False,full_match=False)));return 0
    if sys.platform!='linux':parser.error('actual SIL currently requires the reviewed Ubuntu 22.04 Humble environment')
    env_raw=args.environment.read_bytes();env=json.loads(env_raw)
    env_sha=hashlib.sha256(env_raw).hexdigest()
    # glibc fixes its library search path at process startup. A late environ
    # update cannot make rclpy dependencies visible in this same interpreter.
    # Re-exec before creating evidence or importing ROS/MuJoCo; no data warmup.
    if (os.environ.get('POLAR_PB_SIL_ENV_SHA256')!=env_sha or
        any(os.environ.get(k)!=v for k,v in env['process_environment'].items())):
        child_env=dict(os.environ);child_env.update(env['process_environment'])
        child_env['POLAR_PB_SIL_ENV_SHA256']=env_sha
        os.execve(sys.executable,[sys.executable,str(Path(__file__).absolute()),*(sys.argv[1:] if argv is None else argv)],child_env)
    out=args.out.absolute()
    if any(p.is_symlink() for p in (out,*out.parents)) or out.exists():parser.error('new owned output required')
    out.mkdir(parents=True)
    os.environ.update(env['process_environment'])
    # Child-only bounded startup records, with no protocol or deadline change.
    os.environ['POLAR_PB_BRIDGE_PHASE_FILE']=str(out/'bridge_phase.jsonl')
    from tools.pb_navigation_stack import PBNavigationStack
    from rm_match.navigation_sensors import NavigationSensorConfig
    from rm_match.platform_v2.adapters import Registry
    from rm_match.platform_v2.admission import AdmissionPolicy
    from rm_match.platform_v2.backend import MuJoCoBackend
    from rm_match.platform_v2.client import PlatformClient
    from rm_match.platform_v2.runtime import PlatformRuntime
    from rm_match.platform_v2.server import PlatformHTTPServer,TransportConfig
    from rm_match.integrations.pb_navigation_adapter import register_pb_navigation
    source_names=['tools/qa_pb_navigation_sil.py','tools/pb_navigation_stack.py','rm_match/navigation_sensors.py',
        'rm_match/harness.xml','rm_match/match_model.py','rm_match/match_engine.py',
        'rm_match/platform_v2/navigation_contracts.py','rm_match/platform_v2/runtime.py','rm_match/platform_v2/backend.py',
        'rm_match/integrations/pb_navigation_adapter.py','rm_match/integrations/pb_navigation_bridge.py',
        'rm_match/integrations/pb_navigation_transport.py','rm_match/integrations/pb_controller_context.hpp',
        'rm_match/integrations/pb_navigation_phases.py',
        'tools/pb2025_overlay/pb_scan_source.hpp']
    hashes=lambda:{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in source_names}
    before=hashes();rows=[];errors=[];stop=threading.Event();sdk=None;goal_thread=None;observer=None;server=None;runtime=None;stack=None;cleanup=None
    credential=secrets.token_hex(32)
    policy=AdmissionPolicy([dict(credential_sha256=hashlib.sha256(credential.encode()).hexdigest(),role='operator',allowed_robots=['red_sentry'],audit_authorized=False)])
    def trace(row):
        event=row['event']
        if event in ('adapter_enqueue','adapter_result'):
            rows.append(copy.deepcopy(row));return
        if event!='actuator_consumed' or row['robot_id']!='red_sentry' or row['phase']!='integration_entry':return
        # Actual guard receipts, stripped of other robots and session identifiers.
        output=runtime.outputs.get(('red_sentry','navigation'))
        auth=row['adapter_authorizations']['navigation']
        rows.append(dict(event='navigation_consumed',phase=row['phase'],consume_wall=row['consume_wall'],
            consume_sim_time=row['consume_sim_time'],target=copy.deepcopy(row['target']),action=copy.deepcopy(output),
            navigation_budget=copy.deepcopy(runtime.output_budgets.get(('red_sentry','navigation'))),
            output_authorization=copy.deepcopy(runtime.output_authorizations.get(('red_sentry','navigation'))),
            authorization={k:auth.get(k) for k in ('epoch','activation_required','activation_seq','activation_expires','activation_window_id','activation_window_deadline')}))
        if len(rows)>200000:raise ValueError('bounded_sil_trace_full')
    old_signals={s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM)}
    def requested_stop(*_):
        stop.set()
        if runtime is not None:runtime.request_stop()
    for sig in old_signals:signal.signal(sig,requested_stop)
    try:
        stack=PBNavigationStack(config=json.loads(args.stack_config.read_bytes()),diagnostics=args.diagnostics,
            environment=dict(path=str(args.environment.absolute()),sha256=hashlib.sha256(args.environment.read_bytes()).hexdigest()),
            out=out/'stack',domain_id=84)
        ready=stack.start();observer=AlgorithmObserver(ready['namespace'],84,diagnostics=args.diagnostics)
        registry=Registry();register_pb_navigation(registry,ready['bridge_manifest_path'])
        backend=MuJoCoBackend(navigation_sensors=NavigationSensorConfig())
        initial=backend._sim.data.qpos[backend._sim.qindices['red_sentry'][:3]].copy().tolist()
        runtime=PlatformRuntime(backend,registry=registry,trace=trace)
        server=PlatformHTTPServer(TransportConfig(port=0,admission_policy=policy),runtime)
        http=threading.Thread(target=server.serve_forever,name='sil-http',daemon=True);http.start()
        sdk=PlatformClient('http://127.0.0.1:'+str(server.server_address[1]),control_profile='server_window_v1',admission_credential=credential)
        sdk.open('operator');sdk.claim('red_sentry',['motion']);binding=sdk.bind('red_sentry','navigation','custom_pb_navigation',{})
        if binding['binding_epoch']!=1:raise ValueError('fresh_stack_binding_epoch')
        def deadman():
            renew=time.perf_counter();next_tick=renew;previous_ack=None;previous_issued=None
            try:
                while not stop.is_set():
                    stack.poll_health()
                    if time.perf_counter()-renew>=.25:
                        renewal_started=time.perf_counter()
                        sdk.renew('red_sentry',['motion']);renew=time.perf_counter()
                        rows.append(dict(event='sdk_lease_renewed',started_wall=renewal_started,completed_wall=renew))
                    window=sdk.control_window('red_sentry',['motion'])
                    activation=sdk.adapter_input('red_sentry','navigation',1,window_id=window['window_id'],valid_for_s=.15)
                    ack=time.perf_counter()
                    rows.append(dict(event='sdk_adapter_activation',wall_time=ack,
                        previous_ack_gap_s=None if previous_ack is None else ack-previous_ack,
                        previous_issued_gap_s=None if previous_issued is None else window['issued_wall']-previous_issued,
                        window={k:window[k] for k in ('window_id','issued_wall','expires_wall','valid_for_s','lease_epochs')},
                        activation={k:activation[k] for k in ('binding_epoch','seq','window_id','activation_expires')}))
                    previous_ack=ack;previous_issued=window['issued_wall'];next_tick+=.05
                    # Absolute cadence skips missed ticks; it never catches up by
                    # issuing old windows or extending the original 150 ms TTL.
                    if next_tick<=ack:next_tick+=(math.floor((ack-next_tick)/.05)+1)*.05
                    stop.wait(max(0.,next_tick-time.perf_counter()))
            except Exception as exc:
                if not runtime.stop_event.is_set():
                    errors.append('sdk:'+type(exc).__name__+':'+str(exc))
                    (out/'SDK_FAILURE.txt').write_text(traceback.format_exc(),encoding='utf-8')
                runtime.request_stop();stop.set()
        sdk_thread=threading.Thread(target=deadman,name='sil-sdk-deadman',daemon=True);sdk_thread.start()
        goal_thread=threading.Thread(target=observer.drive_goal,args=(stack,stop),name='sil-algorithm-goal',daemon=True);goal_thread.start()
        started=time.perf_counter()
        runtime.run(max_wall_seconds=args.seconds,real_time_factor=1.)
        elapsed=time.perf_counter()-started
        final=backend._sim.data.qpos[backend._sim.qindices['red_sentry'][:3]].copy().tolist()
        try:observer.record_ending_estimate()
        except Exception as exc:errors.append('ending_estimate_record:'+type(exc).__name__+':'+str(exc))
        stop.set();sdk_thread.join(.5)
        if sdk_thread.is_alive():errors.append('sdk_thread_not_reaped')
    except Exception as exc:
        errors.append(type(exc).__name__+':'+str(exc))
        (out/'FAILURE.txt').write_text(traceback.format_exc(),encoding='utf-8')
    finally:
        stop.set()
        if 'sdk_thread' in locals():
            sdk_thread.join(.5)
            if sdk_thread.is_alive():errors.append('sdk_thread_not_reaped')
        if runtime is not None:
            try:runtime.close()
            except Exception as exc:errors.append('runtime_cleanup:'+type(exc).__name__)
        # Closing the owned stack also interrupts lifecycle waits in the goal
        # thread before its bounded join. No algorithm thread outlives its group.
        try:cleanup=None if stack is None else stack.stop()
        except Exception as exc:errors.append('stack_cleanup:'+type(exc).__name__)
        if goal_thread is not None:goal_thread.join(2.)
        if goal_thread is not None and goal_thread.is_alive():errors.append('goal_thread_not_reaped')
        if sdk is not None:
            try:sdk.close()
            except Exception as exc:errors.append('sdk_close:'+type(exc).__name__)
        if server is not None:
            server.shutdown();server.server_close();http.join(.5)
            if http.is_alive():errors.append('http_thread_not_reaped')
        if observer is not None:
            try:observer.close()
            except Exception as exc:errors.append('observer_cleanup:'+type(exc).__name__)
        for sig,handler in old_signals.items():signal.signal(sig,handler)
    ros_rows=[] if observer is None else observer.rows
    audit=audit_navigation_consumption(rows,ros_rows)
    (out/'TRACE.jsonl').write_text(''.join(json.dumps(r,allow_nan=False,separators=(',',':'))+'\n' for r in rows),encoding='utf-8')
    (out/'ROS_SOURCE.jsonl').write_text(''.join(json.dumps(r,allow_nan=False,separators=(',',':'))+'\n' for r in ros_rows),encoding='utf-8')
    errors+=[] if observer is None else observer.errors
    result=dict(schema='polar.sim.pb-navigation-sil.v1',scope='actual bounded Point-LIO/SLAM/Smac/PB PID and MuJoCo sentry; not full mission/match/hardware',
        requested_seconds=args.seconds,wall_seconds=locals().get('elapsed'),actual_steps=0 if runtime is None else runtime.steps,
        simulation_seconds=None if runtime is None else runtime.steps*runtime.backend.timestep,
        physics_rtf=None if 'elapsed' not in locals() else runtime.steps*runtime.backend.timestep/elapsed,
        source_sha256=before,source_unchanged=before==hashes(),sensor_input_has_truth=False,
        diagnostics=args.diagnostics,environment_ref=dict(path=str(args.environment),sha256=env_sha),
        stack_config_ref=dict(path=str(args.stack_config),sha256=hashlib.sha256(args.stack_config.read_bytes()).hexdigest()),
        image_limit_seconds=.08,control_window_seconds=.15,fire_permission=False,
        observer_goal={} if observer is None else observer.goal_report,
        actual_odometry_messages=0 if observer is None else observer.odom_count,actual_map_messages=0 if observer is None else observer.map_count,
        consumption_audit=audit,shutdown=None if runtime is None else getattr(runtime,'shutdown_status',None),stack_cleanup=cleanup,
        isolated_postrun_groundtruth=dict(initial_qpos=locals().get('initial'),final_qpos=locals().get('final'),algorithm_input=False),errors=errors,
        full_match_qualified=False,hardware_qualified=False)
    goal=result['observer_goal']
    result['relative_goal_completed']=goal.get('follow_path_status')==4
    result['bounded_navigation_consumption_passed']=audit['passed'] and not errors and result['source_unchanged'] and bool(
        result['actual_odometry_messages'] and result['actual_map_messages'] and goal.get('planner_status')==4 and goal.get('follow_path_accepted')
        and
        result['shutdown'] and result['shutdown']['clean'] and cleanup and cleanup['clean'] and cleanup['assets_unchanged'])
    (out/'RESULT.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('bounded_navigation_consumption_passed','actual_steps','actual_odometry_messages','actual_map_messages','consumption_audit','errors')},indent=2))
    return 0 if result['bounded_navigation_consumption_passed'] else 2


if __name__=='__main__':raise SystemExit(main())
