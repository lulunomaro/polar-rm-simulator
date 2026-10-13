#!/usr/bin/env python3
"""Independent read-only production-Gate observer and Nav2 action client."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import threading
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
SOURCE_FILES=(
    'tools/qa_pb_external_navigation_goal.py',
    'tools/qa_pb_external_goal_supervisor.py',
    'rm_match/integrations/owned_linux_group.py',
    'tools/qa_pb_navigation_sil.py',
    'tools/pb_navigation_stack.py',
    'rm_match/platform_v2/contracts.py',
    'rm_match/platform_v2/navigation_contracts.py',
)
SCHEMA='polar.pb.external-goal-spec.v1'
MAX_SPEC=1024*1024


def no_alias(path):
    path=Path(path)
    if (not path.is_absolute() or '..' in path.parts or path!=path.resolve()
        or any(p.is_symlink() for p in (path,*path.parents))):
        raise ValueError('external_goal_absolute_unaliased_path')
    return path


def snapshot(path):
    path=no_alias(path)
    with path.open('rb') as stream:raw=stream.read(MAX_SPEC+1)
    if len(raw)>MAX_SPEC:raise ValueError('external_goal_json_oversized')
    def pairs(items):
        value={}
        for k,v in items:
            if k in value:raise ValueError('external_goal_duplicate_key')
            value[k]=v
        return value
    def constant(_):raise ValueError('external_goal_nonfinite')
    def number(text):
        value=float(text)
        if not math.isfinite(value):raise ValueError('external_goal_nonfinite')
        return value
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=constant,parse_float=number),hashlib.sha256(raw).hexdigest()


def checked_ref(ref):
    if type(ref) is not dict or set(ref)!={'path','sha256'} or type(ref['path']) is not str or type(ref['sha256']) is not str or not re.fullmatch('[a-f0-9]{64}',ref['sha256']):
        raise ValueError('external_goal_reference_fields')
    value,digest=snapshot(ref['path'])
    if digest!=ref['sha256']:raise ValueError('external_goal_reference_changed')
    return value


def load_spec(path,expected_sha):
    value,digest=snapshot(path)
    if digest!=expected_sha:raise ValueError('external_goal_spec_changed')
    fields={'schema','run_uuid','session_run_uuid','session_ref','namespace','domain_id','root_linux','out_linux',
            'environment_ref','source_sha256','goal_offset_m','max_wall_seconds'}
    if type(value) is not dict or set(value)!=fields or value['schema']!=SCHEMA:raise ValueError('external_goal_spec_fields')
    for name in ('run_uuid','session_run_uuid'):
        if type(value[name]) is not str or not re.fullmatch('[a-f0-9]{32}',value[name]):raise ValueError('external_goal_uuid')
    if value['namespace']!='/polar_sil_'+value['session_run_uuid']+'/red_sentry':raise ValueError('external_goal_namespace')
    if type(value['domain_id']) is not int or value['domain_id']!=84:raise ValueError('external_goal_domain84')
    if type(value['root_linux']) is not str or no_alias(value['root_linux']).resolve()!=ROOT:raise ValueError('external_goal_repository')
    out=no_alias(value['out_linux'])
    if not out.is_dir() or not out.resolve().is_relative_to((ROOT/'artifacts').resolve()) or no_alias(path).parent.resolve()!=out.resolve():
        raise ValueError('external_goal_owned_output')
    if type(value['max_wall_seconds']) not in (int,float) or not math.isfinite(value['max_wall_seconds']) or not 5<=value['max_wall_seconds']<=60:
        raise ValueError('external_goal_wall_bound')
    if type(value['goal_offset_m']) is not list or len(value['goal_offset_m'])!=2 or any(type(v) is not float for v in value['goal_offset_m']) or value['goal_offset_m']!=[1.,0.]:
        raise ValueError('external_goal_fixed_offset')
    sources=value['source_sha256']
    if type(sources) is not dict or set(sources)!=set(SOURCE_FILES):raise ValueError('external_goal_source_roster')
    for name,expected in sources.items():
        source=no_alias(ROOT/name)
        if type(expected) is not str or hashlib.sha256(source.read_bytes()).hexdigest()!=expected:
            raise ValueError('external_goal_source_changed:'+name)
    session=checked_ref(value['session_ref'])
    if (type(session) is not dict or session.get('schema')!='polar.pb.wsl-session-spec.v1' or session.get('run_uuid')!=value['session_run_uuid']
        or session.get('namespace')!=value['namespace'] or session.get('relative_test_goal') is not False
        or session.get('expected_generation')!={'robot_id':'red_sentry','episode':0,'binding_epoch':1}
        or session.get('environment_ref')!=value['environment_ref']):
        raise ValueError('external_goal_production_session_required')
    generation=session['expected_generation']
    if any(type(generation[k]) is not type(v) for k,v in dict(robot_id='red_sentry',episode=0,binding_epoch=1).items()):
        raise ValueError('external_goal_session_generation_type')
    checked_ref(value['environment_ref'])
    return value,out


def bootstrap(spec,environment,argv):
    python=environment.get('venv_python');settings=environment.get('process_environment')
    if type(python) is not str or not Path(python).is_absolute() or not Path(python).is_file():raise ValueError('external_goal_verified_python')
    if type(settings) is not dict or any(type(k) is not str or type(v) is not str for k,v in settings.items()):raise ValueError('external_goal_process_environment')
    if 'PYTHONPATH' in settings or 'PYTHONHOME' in settings:raise ValueError('external_goal_python_environment_scrub')
    marker=spec['run_uuid']+':'+spec['environment_ref']['sha256']
    if (Path(sys.executable).absolute()!=Path(python).absolute() or os.environ.get('POLAR_EXTERNAL_GOAL_ENV')!=marker
        or any(os.environ.get(k)!=v for k,v in settings.items()) or 'PYTHONPATH' in os.environ or 'PYTHONHOME' in os.environ):
        env=dict(os.environ);env.update(settings);env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
        env['POLAR_EXTERNAL_GOAL_ENV']=marker
        os.execve(python,[python,'-u',str(Path(__file__).resolve()),*argv],env)


def process_identity():
    fields=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()
    return dict(pid=os.getpid(),start_ticks=int(fields[19]),boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip())


def publish_json(path,value):
    """Publish one complete fresh metadata record; readers never see partial JSON."""
    path=no_alias(path);temporary=no_alias(path.with_name(path.name+'.tmp'))
    if path.exists() or temporary.exists():raise ValueError('external_goal_metadata_reuse')
    raw=(json.dumps(value,indent=2,allow_nan=False)+'\n').encode('utf8')
    if len(raw)>MAX_SPEC:raise ValueError('external_goal_metadata_oversized')
    with temporary.open('xb') as stream:stream.write(raw)
    no_alias(path)
    if path.exists():raise ValueError('external_goal_metadata_reuse')
    os.replace(temporary,path)


def cleanup_record(run_uuid,ident,errors,observer_thread_alive):
    if type(observer_thread_alive) is not bool:raise ValueError('external_goal_thread_status_type')
    return dict(schema='polar.pb.external-goal-cleanup.v1',run_uuid=run_uuid,**ident,
        clean=not errors and not observer_thread_alive,errors=errors,
        observer_thread_alive=observer_thread_alive,session_node_processes_owned=False)


def goal_from_estimate(message,goal_factory):
    from tools.qa_pb_navigation_sil import recorded_transform,recorded_pose
    source=recorded_transform(message)
    goal=goal_factory();goal.header.frame_id='map';goal.header.stamp=message.header.stamp
    goal.pose.position.x=message.transform.translation.x+1.;goal.pose.position.y=message.transform.translation.y
    goal.pose.orientation=message.transform.rotation
    return goal,dict(source_kind='actual_tf_buffer_lookup',transform=source,goal=recorded_pose(goal),relative_offset_m=[1.,0.])


def gate_active(states):
    return all(type(states.get(name)) is int and states[name]==3 for name in ('controller_server','planner_server'))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',required=True);parser.add_argument('--spec-sha256',required=True);parser.add_argument('--run',action='store_true')
    args=parser.parse_args(argv);spec,out=load_spec(args.spec,args.spec_sha256)
    if not args.run:
        print(json.dumps(dict(scope='independent external Nav2 client; read-only Gate observation; no data published',spec=spec)));return 0
    if sys.platform!='linux':raise ValueError('external_goal_requires_humble_linux')
    bootstrap(spec,checked_ref(spec['environment_ref']),sys.argv[1:] if argv is None else argv)
    if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
    for name in ('READY.json','READY.json.tmp','RESULT.json','CLEANUP.json','CLEANUP.json.tmp','ROS_SOURCE.jsonl','GOAL_REPORT.json'):
        no_alias(out/name)
        if (out/name).exists():raise ValueError('external_goal_fresh_output_required')
    started=time.perf_counter();end=started+spec['max_wall_seconds'];stop=threading.Event()
    old={sig:signal.getsignal(sig) for sig in (signal.SIGINT,signal.SIGTERM)}
    for sig in old:signal.signal(sig,lambda *_:stop.set())
    events=[];errors=[];observer=None;clients=[];lifecycle=[];controller_handle=None;completed=False;ident=process_identity()
    def event(kind,**fields):
        if len(events)>=128:raise ValueError('external_goal_events_full')
        row=dict(event=kind,receive_wall=time.perf_counter(),receive_clock='linux_local_perf_counter',**fields)
        if len(json.dumps(row,allow_nan=False).encode())>16384:raise ValueError('external_goal_event_oversized')
        events.append(row)
    def check():
        if stop.is_set():raise InterruptedError('external_goal_requested_stop')
        if time.perf_counter()>=end:raise TimeoutError('external_goal_wall_bound')
        if observer is not None and observer.errors:raise RuntimeError('external_goal_observer_error:'+str(observer.errors))
    def wait(future,timeout=5.):
        deadline=min(end,time.perf_counter()+timeout)
        while not future.done():
            check()
            if time.perf_counter()>=deadline:raise TimeoutError('external_goal_action_or_service_timeout')
            stop.wait(.01)
        check();return future.result()
    try:
        import importlib.metadata
        if sys.version_info[:2]!=(3,10) or not importlib.metadata.version('rclpy').startswith('3.3.'):
            raise ValueError('external_goal_requires_humble_rclpy_python310')
        from tools.qa_pb_navigation_sil import AlgorithmObserver,recorded_goal_uuid,recorded_path_result
        from geometry_msgs.msg import PoseStamped
        from lifecycle_msgs.srv import GetState
        from nav2_msgs.action import ComputePathToPose,FollowPath
        from rclpy.action import ActionClient
        from rclpy.time import Time
        observer=AlgorithmObserver(spec['namespace'],84,receive_clock='linux_local_perf_counter')
        ready=dict(schema='polar.pb.external-goal-ready.v1',run_uuid=spec['run_uuid'],session_run_uuid=spec['session_run_uuid'],
            namespace=spec['namespace'],domain_id=84,state='OBSERVING_NO_INPUT_PUBLISHED',**ident,
            environment_sha256=spec['environment_ref']['sha256'],source_sha256=spec['source_sha256'],
            spec_sha256=args.spec_sha256,sensor_published=False,goal_sent=False,lifecycle_changed=False)
        publish_json(out/'READY.json',ready)
        event('observer_ready',**ident)
        states={}
        for name in ('controller_server','planner_server'):
            lifecycle.append((name,observer.node.create_client(GetState,spec['namespace']+'/'+name+'/get_state')))
        while True:
            check();pose=None
            if observer.odom_count and observer.map_count:
                try:pose=observer.buffer.lookup_transform('map','base_link',Time())
                except Exception:pass
            if pose is not None:
                for name,client in lifecycle:
                    if not client.service_is_ready():continue
                    response=wait(client.call_async(GetState.Request()),timeout=.5)
                    state=response.current_state.id
                    if type(state) is not int:raise ValueError('external_goal_lifecycle_state_type')
                    if states.get(name)!=state:event('gate_state_observed',node=name,state=state,service=spec['namespace']+'/'+name+'/get_state')
                    states[name]=state
                if gate_active(states):
                    pose=observer.buffer.lookup_transform('map','base_link',Time());break
            stop.wait(.05)
        goal,saved=goal_from_estimate(pose,PoseStamped)
        observer.action_request_id=spec['run_uuid'];observer.action_request_seq=1
        observer.record_algorithm('goal_source_tf',**saved,action_name=spec['namespace']+'/compute_path_to_pose',planner_id='GridBased',use_start=False)
        observer.goal_report=dict(source='actual_algorithm_map_to_base_link_tf',frame='map',
            source_stamp_ns=pose.header.stamp.sec*1000000000+pose.header.stamp.nanosec,
            relative_offset_m=[1.,0.],goal_xy=[goal.pose.position.x,goal.pose.position.y])
        planner=ActionClient(observer.node,ComputePathToPose,spec['namespace']+'/compute_path_to_pose');clients.append(planner)
        controller=ActionClient(observer.node,FollowPath,spec['namespace']+'/follow_path');clients.append(controller)
        for client in clients:
            while not client.wait_for_server(timeout_sec=min(.1,max(0.,end-time.perf_counter()))):check()
        check();request=ComputePathToPose.Goal();request.goal=goal;request.planner_id='GridBased';request.use_start=False
        handle=wait(planner.send_goal_async(request));planner_uuid=recorded_goal_uuid(handle)
        observer.record_algorithm('planner_goal_accepted',action_name=spec['namespace']+'/compute_path_to_pose',goal_uuid=planner_uuid,accepted=handle.accepted)
        if not handle.accepted:raise ValueError('external_planner_rejected')
        result=wait(handle.get_result_async())
        observer.record_algorithm('planner_path_result',action_name=spec['namespace']+'/compute_path_to_pose',planner_id='GridBased',use_start=False,**recorded_path_result(result,handle))
        if result.status!=4 or len(result.result.path.poses)<2:raise ValueError('external_planner_failed_or_empty')
        observer.goal_report.update(path_poses=len(result.result.path.poses),planner_status=result.status)
        request=FollowPath.Goal();request.path=result.result.path;request.controller_id='FollowPath';request.goal_checker_id='general_goal_checker'
        controller_handle=wait(controller.send_goal_async(request));controller_uuid=recorded_goal_uuid(controller_handle)
        observer.record_algorithm('follow_path_goal_accepted',action_name=spec['namespace']+'/follow_path',goal_uuid=controller_uuid,
            planner_goal_uuid=planner_uuid,accepted=controller_handle.accepted,controller_id='FollowPath',goal_checker_id='general_goal_checker')
        if not controller_handle.accepted:raise ValueError('external_follow_path_rejected')
        observer.goal_report['follow_path_accepted']=True
        future=controller_handle.get_result_async()
        while not future.done():check();stop.wait(.02)
        result=future.result()
        if type(result.status) is not int:raise ValueError('external_follow_path_status_type')
        observer.record_algorithm('follow_path_result',action_name=spec['namespace']+'/follow_path',goal_uuid=controller_uuid,planner_goal_uuid=planner_uuid,status=result.status)
        observer.goal_report['follow_path_status']=result.status
        if result.status!=4:raise ValueError('external_follow_path_failed')
        completed=True;event('goal_completed_observe_until_stop')
        while not stop.wait(.05):
            if time.perf_counter()>=end:event('bounded_observation_end');break
            if observer.errors:raise RuntimeError('external_observer_fault_after_goal')
    except InterruptedError:
        event('requested_stop',goal_completed=completed)
    except BaseException as error:
        errors.append(type(error).__name__+':'+str(error));traceback.print_exc()
    finally:
        if observer is not None:
            try:observer.record_ending_estimate()
            except BaseException as error:errors.append('ending_estimate:'+type(error).__name__)
        if controller_handle is not None and not completed:
            try:controller_handle.cancel_goal_async()
            except BaseException as error:errors.append('own_goal_cancel:'+type(error).__name__)
        for client in clients:
            try:client.destroy()
            except BaseException as error:errors.append('action_client_close:'+type(error).__name__)
        if observer is not None:
            for _,client in lifecycle:
                try:observer.node.destroy_client(client)
                except BaseException as error:errors.append('lifecycle_client_close:'+type(error).__name__)
            try:observer.close()
            except BaseException as error:errors.append('observer_close:'+type(error).__name__)
            errors+=observer.errors
            try:
                (out/'ROS_SOURCE.jsonl').write_text(''.join(json.dumps(row,allow_nan=False,separators=(',',':'))+'\n' for row in observer.rows),encoding='utf8')
                (out/'GOAL_REPORT.json').write_text(json.dumps(observer.goal_report,indent=2,allow_nan=False)+'\n',encoding='utf8')
            except BaseException as error:errors.append('observation_save:'+type(error).__name__)
        (out/'EXTERNAL_EVENTS.jsonl').write_text(''.join(json.dumps(row,allow_nan=False,separators=(',',':'))+'\n' for row in events),encoding='utf8')
        for name,expected in spec['source_sha256'].items():
            try:
                if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:errors.append('source_changed:'+name)
            except OSError:errors.append('source_missing:'+name)
        cleanup=cleanup_record(spec['run_uuid'],ident,errors,observer is not None and observer.thread.is_alive())
        publish_json(out/'CLEANUP.json',cleanup)
        result=dict(schema='polar.pb.external-goal-result.v1',run_uuid=spec['run_uuid'],session_run_uuid=spec['session_run_uuid'],
            namespace=spec['namespace'],goal_completed=completed,elapsed_s=time.perf_counter()-started,cleanup=cleanup,
            source_sha256=spec['source_sha256'],environment_ref=spec['environment_ref'],
            goal_report={} if observer is None else observer.goal_report,algorithm_input_has_truth=False,
            lifecycle_changed=False,sensor_published=False,cmd_vel_published=False,
            scope='independent external action client; production Gate observation only; not full mission/hardware')
        (out/'RESULT.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf8')
        for sig,previous in old.items():signal.signal(sig,previous)
    return 0 if completed and cleanup['clean'] else 2


if __name__=='__main__':raise SystemExit(main())
