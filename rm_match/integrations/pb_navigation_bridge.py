"""Optional Humble sensor bridge. Bare Twist is deliberately not an action input."""
from __future__ import annotations
from .pb_navigation_phases import PHASES
PHASES.mark('module')
from dataclasses import dataclass
import argparse
import copy
import os
import re
import sys
import time
from .ros2_bridge import BridgeError, JSONL_SCHEMA, MAX_REQUEST, MAX_RESPONSE, parse_json, encode_json
from ..platform_v2.contracts import IDENTITY, exact, integer, string, validate_action
from ..platform_v2.navigation_contracts import (NAV_STATUS_SCHEMA, POINT_STRUCT,
    decode_points, validate_navigation_observation, validate_navigation_status)

REQUEST_SCHEMA = 'polar.sim.pb-navigation-request.v1'
RESULT_SCHEMA = 'polar.sim.pb-navigation-result.v1'
GOAL_RESULT_SCHEMA = 'polar.sim.pb-navigation-result.v2'


@dataclass(frozen=True)
class NavigationSettings:
    adapter_id: str = 'custom_pb_navigation'
    node_name: str = 'polar_pb_sensor_bridge'
    cloud_topic: str = '/livox/lidar'
    pointcloud_topic: str = '/livox/lidar/pointcloud'
    imu_topic: str = '/livox/imu'
    request_topic: str = '/polar/pb/request'
    result_topic: str = '/polar/pb/result'
    odom_topic: str = '/Odometry'
    clock_topic: str = '/clock'
    tf_static_topic: str = '/tf_static'
    domain_id: int = 81
    response_timeout: float = .05
    controller_id: str = 'pb_controller_sourced_v1'
    result_profile: str = 'scan_v1'
    expected_robot_id: str = 'red_sentry'
    expected_episode: int = 0
    expected_binding_epoch: int = 1

    def __post_init__(self):
        if type(self.adapter_id) is not str or not re.fullmatch('custom_[a-z0-9_]{1,100}', self.adapter_id): raise BridgeError('pb_invalid_adapter_id')
        for key in ('node_name', 'controller_id'):
            if type(getattr(self,key)) is not str or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,127}',getattr(self,key)): raise BridgeError('pb_invalid_node_or_controller')
        if type(self.result_profile) is not str or self.result_profile not in ('scan_v1','follow_path_uuid_v2'):
            raise BridgeError('pb_invalid_result_profile')
        topics=[getattr(self,k) for k in ('cloud_topic','pointcloud_topic','imu_topic','request_topic','result_topic','odom_topic','clock_topic','tf_static_topic')]
        if len(set(topics))!=len(topics) or any(type(t) is not str or len(t)>256 or not re.fullmatch('(?:/[A-Za-z_][A-Za-z0-9_]*)+',t) for t in topics): raise BridgeError('pb_invalid_topics')
        if type(self.domain_id) is not int or not 0<=self.domain_id<=101: raise BridgeError('pb_invalid_domain')
        if type(self.response_timeout) not in (int,float) or not 0<self.response_timeout<=.1: raise BridgeError('pb_invalid_response_budget')
        string(self.expected_robot_id,'pb_expected_robot')
        integer(self.expected_episode,'pb_expected_episode');integer(self.expected_binding_epoch,'pb_expected_epoch')


def stamp_ns(ns):
    integer(ns,'ros_sim_stamp_ns',0,2147483647*1000000000+999999999)
    return dict(sec=ns//1000000000,nanosec=ns%1000000000)


def sensor_bundle(observation):
    """Detached plain data; transport constructs actual generated ROS messages."""
    o=validate_navigation_observation(observation)
    cloud=o['sensors']['pointcloud']; imu=o['sensors']['imu']; raw=decode_points(cloud)
    header=dict(stamp=stamp_ns(cloud['acquisition_start_ns']),frame_id=cloud['frame'])
    points=[dict(zip(('x','y','z','offset_time','reflectivity','tag','line'),row)) for row in POINT_STRUCT.iter_unpack(raw)]
    fields=[dict(name=n,offset=p,datatype=d,count=1) for n,p,d in
        [('x',0,7),('y',4,7),('z',8,7),('offset_time',12,6),('reflectivity',16,2),('tag',17,2),('line',18,2)]]
    samples=[]
    for s in imu['samples']:
        samples.append(dict(header=dict(stamp=stamp_ns(s['sample_sim_ns']),frame_id=imu['frame']),
            angular_velocity=tuple(s['angular_velocity_rps']),linear_acceleration=tuple(s['linear_acceleration_mps2']),
            orientation_covariance=(-1.,0.,0.,0.,0.,0.,0.,0.,0.)))
    return dict(custom=dict(header=header,timebase=cloud['acquisition_start_ns'],point_num=len(points),lidar_id=0,rsvd=[0,0,0],points=points),
        pointcloud=dict(header=copy.deepcopy(header),height=1,width=len(points),fields=fields,
            is_bigendian=False,point_step=20,row_step=len(raw),data=raw,is_dense=True),
        imu=samples,clock=stamp_ns(cloud['acquisition_end_ns']),extrinsics=copy.deepcopy(cloud['extrinsics']))


def navigation_status(o,status):
    return validate_navigation_status(dict(schema=NAV_STATUS_SCHEMA,**{k:o[k] for k in IDENTITY},kind='navigation',status=status),o)


def sourced_result(observation, action, *, cloud_frame_id, localization_stamp_ns, controller_stamp_ns, controller_id, adapter_id='custom_pb_navigation'):
    """Called by a reviewed controller at computation, never by a Twist subscriber.

    The upstream integration must propagate request identity through the actual
    localization/controller computation. This helper cannot prove that itself.
    """
    o=validate_navigation_observation(observation)
    a=validate_action(action,o,dict(kind='navigation',output_modes=['velocity_body']))
    if any(type(a[k]) is not type(o[k]) or a[k]!=o[k] for k in IDENTITY):raise BridgeError('pb_controller_identity_mismatch')
    return dict(schema=RESULT_SCHEMA,adapter_id=adapter_id,action=a,
        source=dict(cloud_frame_id=cloud_frame_id,localization_stamp_ns=localization_stamp_ns,
            controller_stamp_ns=controller_stamp_ns,controller_id=controller_id))


def sourced_goal_result(observation, action, *, goal_uuid, **kwargs):
    """Envelope helper for a reviewed actual goal-server computation hook.

    A plain UUID cannot establish its own provenance. The upstream server must
    capture its real current goal around the original controller computation.
    """
    if type(goal_uuid) is not str or not re.fullmatch('[0-9a-f]{32}',goal_uuid):
        raise BridgeError('pb_invalid_goal_uuid')
    row=sourced_result(observation,action,**kwargs)
    row['schema']=GOAL_RESULT_SCHEMA;row['source']['goal_uuid']=goal_uuid
    return row


class NavigationBridge:
    def __init__(self,settings,*,clock=time.monotonic):
        self.settings=settings; self.clock=clock; self.context=None; self._pending=None
        self._result=None; self._deadline=None; self._last_seq=-1; self._last_frame=-1
        self._odom_stamp=-1; self._closed=False

    def reset(self,context,config):
        if self.context is not None or self._closed: raise BridgeError('pb_reset_once')
        exact(context,('robot_id','episode','binding_epoch'),'pb_context'); exact(config,(),'pb_config')
        string(context['robot_id'],'pb_context_robot')
        for k in ('episode','binding_epoch'):integer(context[k],k)
        expected=dict(robot_id=self.settings.expected_robot_id,episode=self.settings.expected_episode,binding_epoch=self.settings.expected_binding_epoch)
        if any(type(context[k]) is not type(v) or context[k]!=v for k,v in expected.items()):raise BridgeError('pb_fresh_stack_generation_required')
        self.context=dict(context)

    def begin(self,observation):
        if self._closed or self.context is None or self._pending is not None: raise BridgeError('pb_unavailable_or_pending')
        deadline=self.clock()+self.settings.response_timeout
        o=validate_navigation_observation(observation)
        if any(type(o[k]) is not type(v) or o[k]!=v for k,v in self.context.items()): raise BridgeError('pb_context_mismatch')
        frame=o['sensors']['pointcloud']['frame_id']
        if o['observed_seq']<=self._last_seq or frame<=self._last_frame: raise BridgeError('pb_nonincreasing_observation')
        bundle=sensor_bundle(o)
        request=encode_json(dict(schema=REQUEST_SCHEMA,adapter_id=self.settings.adapter_id,
            **{k:o[k] for k in IDENTITY},cloud_frame_id=frame,
            acquisition_start_ns=o['sensors']['pointcloud']['acquisition_start_ns'],
            acquisition_end_ns=o['sensors']['pointcloud']['acquisition_end_ns']),MAX_RESPONSE).decode()
        if self.clock()>=deadline: raise BridgeError('pb_serialization_exhausted_local_budget')
        self._pending=o;self._deadline=deadline;self._result=None
        self._last_seq=o['observed_seq'];self._last_frame=frame
        return bundle,request

    def receive_odom_stamp(self,stamp):
        integer(stamp,'algorithm_odom_stamp_ns')
        # This stamp is used only to label no-action, never to authorize velocity.
        self._odom_stamp=max(self._odom_stamp,stamp)

    def receive_result(self,payload):
        if self._pending is None or self._closed or self.clock()>=self._deadline: raise BridgeError('pb_no_live_pending')
        row=parse_json(payload,MAX_RESPONSE)
        exact(row,('schema','adapter_id','action','source'),'pb_result')
        goal_profile=self.settings.result_profile=='follow_path_uuid_v2'
        expected_schema=GOAL_RESULT_SCHEMA if goal_profile else RESULT_SCHEMA
        if type(row['schema']) is not str or row['schema']!=expected_schema or type(row['adapter_id']) is not str or row['adapter_id']!=self.settings.adapter_id: raise BridgeError('pb_result_route')
        source=row['source'];fields=('cloud_frame_id','localization_stamp_ns','controller_stamp_ns','controller_id')
        exact(source,(*fields,'goal_uuid') if goal_profile else fields,'pb_result_source')
        if goal_profile and (type(source['goal_uuid']) is not str or not re.fullmatch('[0-9a-f]{32}',source['goal_uuid'])):
            raise BridgeError('pb_invalid_goal_uuid')
        for k in ('cloud_frame_id','localization_stamp_ns','controller_stamp_ns'):integer(source[k],k)
        cloud=self._pending['sensors']['pointcloud']
        if (source['cloud_frame_id']!=cloud['frame_id'] or type(source['controller_id']) is not str or source['controller_id']!=self.settings.controller_id
            or not cloud['acquisition_start_ns']<=source['localization_stamp_ns']<=cloud['acquisition_end_ns']
            or not source['localization_stamp_ns']<=source['controller_stamp_ns']<=round(self._pending['sim_time']*1e9)):
            raise BridgeError('pb_result_sensor_or_localization_mismatch')
        a=validate_action(row['action'],self._pending,dict(kind='navigation',output_modes=['velocity_body']))
        if any(type(a[k]) is not type(self._pending[k]) or a[k]!=self._pending[k] for k in IDENTITY): raise BridgeError('pb_result_identity_mismatch')
        if self.clock()>=self._deadline: raise BridgeError('pb_result_local_budget_expired')
        if self._result is not None: raise BridgeError('pb_duplicate_result')
        self._result=a

    def exchange(self,observation,transport):
        bundle,request=self.begin(observation)
        try:
            transport.publish_bundle(bundle,request)
            while self._result is None and self.clock()<self._deadline:
                transport.spin_once(min(.002,max(0.,self._deadline-self.clock())))
            if self._result is not None and self.clock()<self._deadline:return 'action',self._result
            cloud=self._pending['sensors']['pointcloud']
            status='no_associated_command' if cloud['acquisition_start_ns']<=self._odom_stamp<=cloud['acquisition_end_ns'] else 'pending_localization'
            return 'status',navigation_status(self._pending,status)
        finally:self._pending=None;self._result=None

    def close(self):self._closed=True;self._pending=None;self._result=None


def serve_navigation(core,transport,input_stream,output_stream):
    while True:
        raw=input_stream.readline(MAX_REQUEST+1)
        if not raw:return
        if len(raw)>MAX_REQUEST or not raw.endswith(b'\n'):raise BridgeError('pb_jsonl_oversized_or_missing_newline')
        request=parse_json(raw,MAX_REQUEST)
        if type(request) is not dict or type(request.get('schema')) is not str or request['schema']!=JSONL_SCHEMA:raise BridgeError('pb_jsonl_schema')
        if request.get('op')=='reset':
            PHASES.mark('reset_received')
            exact(request,('schema','op','context','config'),'pb_reset_request');core.reset(request['context'],request['config']);transport.wait_ready(1.)
            response=dict(schema=JSONL_SCHEMA,op='reset',ok=True)
        elif request.get('op')=='act':
            exact(request,('schema','op','observation'),'pb_act_request')
            kind,value=core.exchange(request['observation'],transport)
            response=dict(schema=JSONL_SCHEMA,op='act',ok=True,**{kind:value})
        else:raise BridgeError('pb_jsonl_unknown_op')
        output_stream.write(encode_json(response,MAX_RESPONSE-1)+b'\n');output_stream.flush()
        if response['op']=='reset':PHASES.mark('reset_ack')


def main(argv=None):
    PHASES.mark('main')
    p=argparse.ArgumentParser(description=__doc__)
    for k in NavigationSettings.__dataclass_fields__:
        default=getattr(NavigationSettings(),k)
        p.add_argument('--'+k.replace('_','-'),default=default,type=type(default))
    args=p.parse_args(argv);core=None;transport=None;code=0
    sys.stdout.flush();protocol=os.fdopen(os.dup(sys.stdout.fileno()),'wb',buffering=0)
    os.dup2(sys.stderr.fileno(),sys.stdout.fileno())
    try:
        settings=NavigationSettings(**vars(args));core=NavigationBridge(settings)
        from .pb_navigation_transport import HumbleNavigationTransport
        transport=HumbleNavigationTransport(settings,core)
        serve_navigation(core,transport,sys.stdin.buffer,protocol)
    except KeyboardInterrupt:code=130
    except Exception as exc:
        PHASES.mark('main_failed')
        print(str(exc) if isinstance(exc,BridgeError) else 'pb_bridge_failed',file=sys.stderr,flush=True);code=2
    finally:
        PHASES.mark('cleanup_begin')
        if core is not None:core.close()
        try:
            if transport is not None:transport.close()
        except Exception:print('pb_shutdown_incomplete',file=sys.stderr,flush=True);code=2
        protocol.close()
        PHASES.mark('cleanup_end');PHASES.close()
    return code


if __name__=='__main__':raise SystemExit(main())
