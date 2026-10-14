"""Actual DDS/JSONL transport diagnostic with explicit fixture data, no navigation."""
from __future__ import annotations
import argparse
import base64
import gzip
import hashlib
import importlib.metadata
import json
import os
import queue
from pathlib import Path
import struct
import subprocess
import sys
import threading
import time
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO))
from rm_match.integrations.pb_navigation_adapter import register_pb_navigation,MANIFEST_SCHEMA
from rm_match.platform_v2.adapters import Registry
from rm_match.platform_v2.navigation_contracts import NAV_SCHEMA,NAV_FRAMES,POINT_ENCODING,validate_navigation_observation,validate_navigation_status
from rm_match.integrations.ros2_bridge import parse_json,encode_json,MAX_REQUEST,MAX_RESPONSE,JSONL_SCHEMA
from rm_match.integrations.pb_navigation_bridge import NavigationSettings


class ArchivedCodecChild:
    """Codec-only owned process: no host act/deadline authority or actuator."""
    def __init__(self,command):
        env=dict(os.environ)
        for key in ('PYTHONPATH','PYTHONHOME'):env.pop(key,None)
        self.process=subprocess.Popen(command,cwd=REPO,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,bufsize=0,start_new_session=True)
        self.requests=queue.Queue(1);self.responses=queue.Queue(1);child=self.process
        def io_loop():
            try:
                while True:
                    raw=self.requests.get()
                    if raw is None:return
                    view=memoryview(raw)
                    while view:
                        n=child.stdin.write(view)
                        if not n:raise EOFError('codec_input_closed')
                        view=view[n:]
                    child.stdin.flush();raw=child.stdout.readline(MAX_RESPONSE+1)
                    if not raw.endswith(b'\n') or len(raw)>MAX_RESPONSE:raise ValueError('codec_response_missing')
                    self.responses.put_nowait(parse_json(raw,MAX_RESPONSE))
            except Exception as exc:
                try:self.responses.put_nowait(exc)
                except queue.Full:pass
        self.thread=threading.Thread(target=io_loop,name='archived-dds-codec-io',daemon=True);self.thread.start()
    def exchange(self,packet):
        self.requests.put_nowait(encode_json(dict(schema=JSONL_SCHEMA,**packet),MAX_REQUEST-1)+b'\n')
        response=self.responses.get(timeout=2.)
        if isinstance(response,Exception):raise response
        return response
    def reset(self,context):
        response=self.exchange(dict(op='reset',context=context,config={}))
        if response!=dict(schema=JSONL_SCHEMA,op='reset',ok=True):raise ValueError('codec_reset_invalid')
    def act(self,o):
        response=self.exchange(dict(op='act',observation=o))
        if type(response) is not dict or set(response)!=set(('schema','op','ok','status')) or response['schema']!=JSONL_SCHEMA or response['op']!='act' or response['ok'] is not True:raise ValueError('archived_codec_must_not_emit_action')
        return validate_navigation_status(response['status'],o)
    def close(self):
        child=self.process
        if child.poll() is None:
            try:os.killpg(child.pid,9)
            except ProcessLookupError:pass
        child.wait(timeout=1.)
        for stream in (child.stdin,child.stdout):stream.close()
        try:self.requests.put_nowait(None)
        except queue.Full:pass
        self.thread.join(.3)
        if self.thread.is_alive():raise RuntimeError('codec_io_unclean')


def fixture():
    """Synthetic unit data explicitly tagged in report; never physics proof."""
    ext=dict(parent_frame='base_link',translation_m=[0,0,.5],rotation_xyzw=[0,0,0,1],calibration_id='explicit_dds_fixture')
    raw=b''.join(struct.pack('<fffIBBBx',x,0.,0.,t,r,16,line) for x,t,r,line in [(1.,0,24,0),(2.,98000000,32,3)])
    return dict(schema=NAV_SCHEMA,robot_id='red_sentry',episode=0,binding_epoch=1,observed_seq=1,
        sim_time=.1,wall_deadline=0.,frames=dict(NAV_FRAMES),own=dict(team='red',role='sentry',hp=100.,ammo=10.,heat=0.,alive=True),
        referee=dict(phase='running',remaining_seconds=299.,emergency_stop=False),
        sensors=dict(pointcloud=dict(available=True,reason='available',frame_id=1,acquisition_start_ns=0,
            acquisition_end_ns=100000000,capture_sim_time=.1,frame='livox_frame',encoding=POINT_ENCODING,
            point_count=2,data_base64=base64.b64encode(raw).decode(),range_min_m=.1,range_max_m=20.,
            time_quantization_ns=2000000,provenance='mujoco_ray_cast_nonrepeating_profile_v1',profile_sha256='1'*64,extrinsics=ext),
            imu=dict(available=True,reason='available',frame='livox_frame',capture_sim_time=.1,extrinsics=ext,
                provenance='mujoco_gyro_accelerometer_v1',samples=[dict(sample_sim_ns=t,angular_velocity_rps=[0,0,0],
                    linear_acceleration_mps2=[0,0,9.81]) for t in range(0,100000001,2000000)])))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True);p.add_argument('--domain-id',type=int,default=82)
    p.add_argument('--archived-observation',help='gzip JSON archived DTO, original stamps unchanged; codec-only, no host act authority')
    p.add_argument('--namespace',default='',help='explicit trusted local topic prefix; all absolute topics remapped')
    a=p.parse_args(argv);out=Path(a.out).absolute()
    if sys.platform!='linux':raise ValueError('actual_humble_diagnostic_requires_linux')
    if out.exists() or any(x.is_symlink() for x in (out,*out.parents)):raise ValueError('requires_new_owned_output')
    if not 0<=a.domain_id<=101:raise ValueError('invalid_local_domain')
    topics=dict(cloud_topic='/livox/lidar',pointcloud_topic='/livox/lidar/pointcloud',imu_topic='/livox/imu',
        request_topic='/polar/pb/request',result_topic='/polar/pb/result',odom_topic='/Odometry',clock_topic='/clock',tf_static_topic='/tf_static')
    if a.namespace:
        topics={k:a.namespace+v for k,v in topics.items()}
    NavigationSettings(**topics)  # strict local topic validation, no HTTP fields
    out.mkdir(parents=True)
    for k,v in dict(ROS_DOMAIN_ID=str(a.domain_id),ROS_LOCALHOST_ONLY='1',ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST',
        ROS_STATIC_PEERS='',RMW_IMPLEMENTATION='rmw_fastrtps_cpp',RCUTILS_LOGGING_USE_STDOUT='0',ROS_LOG_DIR=str(out/'ros_logs')).items():os.environ[k]=v
    report=dict(schema='polar.sim.pb-dds-sensors-diagnostic.v1',qualification='actual_dds_explicit_fixture_not_physics_lio_nav2',
        fixture=True,navigation_algorithm=False,physics=False,original_reset_timeout=2.,python=sys.version,executable=sys.executable,
        domain_id=a.domain_id,discovery='LOCALHOST',rmw='rmw_fastrtps_cpp',checks={},clean_shutdown=False)
    report['topics']=topics
    o=fixture()
    if a.archived_observation:
        path=Path(a.archived_observation)
        compressed=path.read_bytes()
        if len(compressed)>12*1024*1024:raise ValueError('archived_sensor_input_oversized')
        with gzip.open(path,'rb') as stream:raw=stream.read(MAX_REQUEST+1)
        o=validate_navigation_observation(parse_json(raw,MAX_REQUEST))
        report.update(fixture=False,qualification='actual_dds_archived_sensor_codec_only_not_current_physics_lio_nav2',
            host_deadline_authority_exercised=False,original_stamp_refresh=False,
            reset_gate_implementation='codec_only_bounded_wait_no_host_authority',
            archived_source=str(path),archived_gzip_sha256=hashlib.sha256(compressed).hexdigest(),archived_json_sha256=hashlib.sha256(raw).hexdigest())
    else:report.update(host_deadline_authority_exercised=True,reset_gate_implementation='original_JsonLineAdapter')
    node=None;context=None;executor=None;thread=None;adapter=None;child=None;stop=threading.Event();observed={'imu':[]};lock=threading.Lock()
    try:
        import rclpy
        from rclpy.context import Context
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import QoSProfile,ReliabilityPolicy,DurabilityPolicy
        from livox_ros_driver2.msg import CustomMsg
        from sensor_msgs.msg import PointCloud2,Imu
        from rosgraph_msgs.msg import Clock
        from std_msgs.msg import String
        from tf2_msgs.msg import TFMessage
        report['rclpy_version']=importlib.metadata.version('rclpy')
        report['numpy_version']=importlib.metadata.version('numpy')
        context=Context();rclpy.init(args=[],context=context,domain_id=a.domain_id)
        node=rclpy.create_node('polar_pb_actual_fixture_peer',context=context,use_global_arguments=False,enable_rosout=False)
        def capture(key):
            def receive(value):
                with lock:
                    if key=='imu':
                        if len(observed['imu'])<1024:observed['imu'].append(value)
                    else:observed[key]=value
            return receive
        sensor=QoSProfile(depth=1024,reliability=ReliabilityPolicy.BEST_EFFORT,durability=DurabilityPolicy.VOLATILE)
        control=QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.VOLATILE)
        subscriptions=[]
        for msg,topic,key,qos in [(CustomMsg,topics['cloud_topic'],'cloud',sensor),(PointCloud2,topics['pointcloud_topic'],'pointcloud',sensor),
            (Imu,topics['imu_topic'],'imu',sensor),(Clock,topics['clock_topic'],'clock',control),(String,topics['request_topic'],'request',control),
            (TFMessage,topics['tf_static_topic'],'tf',QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.TRANSIENT_LOCAL))]:
            subscriptions.append(node.create_subscription(msg,topic,capture(key),qos))
        # Graph-ready only: this fixture publishes NO action/localization result.
        publisher=node.create_publisher(String,topics['result_topic'],control)
        executor=SingleThreadedExecutor(context=context);executor.add_node(node)
        def spin():
            while not stop.is_set():executor.spin_once(timeout_sec=.005)
        thread=threading.Thread(target=spin,name='pb-actual-dds-fixture-peer');thread.start()
        command=[sys.executable,'-u','-m','rm_match.integrations.pb_navigation_bridge','--domain-id',str(a.domain_id),
            '--expected-robot-id',o['robot_id'],'--expected-episode',str(o['episode']),'--expected-binding-epoch',str(o['binding_epoch'])]
        for key,value in topics.items():command.extend(['--'+key.replace('_','-'),value])
        manifest=out/'local_manifest.json';manifest.write_text(json.dumps(dict(schema=MANIFEST_SCHEMA,adapters=[dict(
            adapter_id='custom_pb_navigation',label='explicit DDS fixture diagnostic',command=command,cwd=str(REPO))]),indent=2)+'\n')
        if a.archived_observation:adapter=ArchivedCodecChild(command)
        else:
            registry=Registry();register_pb_navigation(registry,manifest);adapter=registry.create('custom_pb_navigation',{})
        t=time.perf_counter()
        spawned=[];original_popen=subprocess.Popen
        def recorded_popen(*args,**kwargs):
            proc=original_popen(*args,**kwargs);spawned.append(proc);return proc
        try:
            with patch('rm_match.deployment.json_adapter.subprocess.Popen',recorded_popen):
                adapter.reset({k:o[k] for k in ('robot_id','episode','binding_epoch')})
        finally:
            report['reset_elapsed_seconds']=time.perf_counter()-t
            child=spawned[-1] if spawned else adapter.process
        report['checks']['reset_within_2s']=report['reset_elapsed_seconds']<2.
        if not a.archived_observation:o['wall_deadline']=time.perf_counter()+.15
        t=time.perf_counter();status=adapter.act(o);report['act_elapsed_seconds']=time.perf_counter()-t
        report['status']=status;report['checks']['no_fabricated_action']=status['status']=='pending_localization' and 'command' not in status
        deadline=time.perf_counter()+2.
        while time.perf_counter()<deadline:
            with lock:complete=all(k in observed for k in ('cloud','pointcloud','clock','request','tf')) and len(observed['imu'])==len(o['sensors']['imu']['samples'])
            if complete:break
            time.sleep(.005)
        with lock:
            raw=base64.b64decode(o['sensors']['pointcloud']['data_base64'])
            cloud=observed.get('cloud');pc=observed.get('pointcloud');imu=list(observed['imu']);clock=observed.get('clock');tf=observed.get('tf')
            customraw=b'' if cloud is None else b''.join(struct.pack('<fffIBBBx',p.x,p.y,p.z,p.offset_time,p.reflectivity,p.tag,p.line) for p in cloud.points)
            cloud_dto=o['sensors']['pointcloud'];samples=o['sensors']['imu']['samples']
            start=cloud_dto['acquisition_start_ns'];end=cloud_dto['acquisition_end_ns'];ext=cloud_dto['extrinsics']
            report['checks']['custom_exact_bytes']=customraw==raw and cloud is not None and cloud.timebase==start and cloud.point_num==cloud_dto['point_count'] and cloud.header.stamp.sec*1000000000+cloud.header.stamp.nanosec==start
            report['checks']['pointcloud_exact_bytes']=pc is not None and bytes(pc.data)==raw and pc.point_step==20 and pc.row_step==len(raw) and pc.header.stamp.sec*1000000000+pc.header.stamp.nanosec==start
            report['checks']['imu_actual_stamps']=sorted(m.header.stamp.sec*1000000000+m.header.stamp.nanosec for m in imu)==[s['sample_sim_ns'] for s in samples]
            report['checks']['imu_no_orientation']=len(imu)==len(samples) and all(m.orientation_covariance[0]==-1 for m in imu)
            report['checks']['clock_actual_end']=clock is not None and clock.clock.sec*1000000000+clock.clock.nanosec==end
            report['checks']['static_measurement_tf']=tf is not None and len(tf.transforms)==1 and tf.transforms[0].header.frame_id==ext['parent_frame'] and tf.transforms[0].child_frame_id==cloud_dto['frame'] and [getattr(tf.transforms[0].transform.translation,k) for k in ('x','y','z')]==ext['translation_m'] and [getattr(tf.transforms[0].transform.rotation,k) for k in ('x','y','z','w')]==ext['rotation_xyzw']
            report['checks']['original_identity']=all(status[k]==o[k] and type(status[k]) is type(o[k]) for k in ('robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline'))
            report['received_imu']=len(imu);report['cloud_sha256']=hashlib.sha256(customraw).hexdigest();report['pointcloud_sha256']=hashlib.sha256(b'' if pc is None else bytes(pc.data)).hexdigest()
    except Exception as exc:report['failure_type']=type(exc).__name__
    finally:
        errors=[]
        if adapter is not None:
            if child is None:child=adapter.process
            try:adapter.close()
            except Exception:errors.append('adapter_close')
            report['adapter_io_alive']=getattr(adapter,'thread',None) is not None and adapter.thread.is_alive()
        stop.set()
        if thread is not None:thread.join(.3);report['peer_thread_alive']=thread.is_alive()
        if executor is not None:
            try:
                if not executor.shutdown(timeout_sec=.15):errors.append('peer_executor')
            except Exception:errors.append('peer_executor')
        if node is not None:
            try:node.destroy_node()
            except Exception:errors.append('peer_node')
        if context is not None:
            try:rclpy.try_shutdown(context=context)
            except Exception:errors.append('peer_context')
            report['peer_context_ok']=context.ok()
        if child is not None:
            report['child_returncode']=child.poll();report['child_reaped']=child.poll() is not None
            report['child_pipes_closed']=child.stdin.closed and child.stdout.closed
        report['cleanup_errors']=errors
        report['clean_shutdown']=not errors and not report.get('adapter_io_alive',False) and not report.get('peer_thread_alive',False) and not report.get('peer_context_ok',False) and (child is None or report['child_reaped'] and report['child_pipes_closed'])
        report['passed']=not report.get('failure_type') and len(report['checks'])==9 and all(report['checks'].values()) and report['clean_shutdown']
        report['source_sha256']={str(x.relative_to(REPO)):hashlib.sha256(x.read_bytes()).hexdigest() for x in [Path(__file__),REPO/'rm_match/integrations/pb_navigation_bridge.py',REPO/'rm_match/integrations/pb_navigation_transport.py',REPO/'rm_match/integrations/pb_navigation_adapter.py',REPO/'rm_match/deployment/json_adapter.py']}
        (out/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n')
    return 0 if report['passed'] else 2


if __name__=='__main__':raise SystemExit(main())
