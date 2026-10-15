"""Owned Linux navigation session for a Windows authority; no clock conversion.

Only trusted local preparation chooses assets. Input sensor times and the six
host identity fields remain unchanged. Linux's 50 ms wait is diagnostic/local;
the Windows host independently enforces its original deadline and SDK grants.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import sys
import threading
import time
import traceback

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
WIRE='polar.pb.wsl-session.v1'
SPEC='polar.pb.wsl-session-spec.v1'
CLEANUP='polar.pb.wsl-session-cleanup.v1'
MAX_REQUEST=12*1024*1024
MAX_RESPONSE=64*1024
EXPECTED={'robot_id':'red_sentry','episode':0,'binding_epoch':1}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked_ref(ref):
    from rm_match.deployment.profile import read_json_snapshot
    value,digest=read_json_snapshot(ref['path'],16*1024*1024)
    if digest!=ref['sha256']:raise ValueError('wsl_session_reference_changed')
    return value


def no_alias(path):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('wsl_session_linked_input')
    return path


def load_spec(path,expected):
    from rm_match.deployment.profile import read_json_snapshot
    from rm_match.integrations.pb_wsl_navigation import SOURCE_FILES
    from tools.pb_navigation_stack import namespace_checked
    path=no_alias(path)
    value,digest=read_json_snapshot(path)
    if digest!=expected:raise ValueError('wsl_session_spec_changed')
    fields={'schema','run_uuid','namespace','root_linux','out_linux','config_ref','environment_ref',
            'source_sha256','diagnostics','relative_test_goal','expected_generation'}
    if type(value) is not dict or set(value)!=fields or value['schema']!=SPEC:raise ValueError('wsl_session_spec_fields')
    import re
    if type(value['run_uuid']) is not str or not re.fullmatch('[0-9a-f]{32}',value['run_uuid']):raise ValueError('wsl_session_run_identity')
    if namespace_checked(value['namespace'])!='/polar_sil_'+value['run_uuid']+'/red_sentry':raise ValueError('wsl_session_namespace_identity')
    if Path(value['root_linux']).resolve()!=ROOT:raise ValueError('wsl_session_repository_identity')
    out=Path(value['out_linux']).absolute()
    if not out.is_dir() or not out.resolve().is_relative_to(ROOT/'artifacts') or any(p.is_symlink() for p in (out,*out.parents)):
        raise ValueError('wsl_session_owned_output_required')
    if path.parent!=out:raise ValueError('wsl_session_spec_outside_owned_output')
    for key in ('diagnostics','relative_test_goal'):
        if type(value[key]) is not bool:raise ValueError('wsl_session_boolean_required')
    generation=value['expected_generation']
    if type(generation) is not dict or set(generation)!=set(EXPECTED) or any(type(generation[k]) is not type(v) or generation[k]!=v for k,v in EXPECTED.items()):
        raise ValueError('wsl_session_generation_identity')
    if type(value['source_sha256']) is not dict or set(value['source_sha256'])!=set(SOURCE_FILES):raise ValueError('wsl_session_source_roster')
    for name,digest in value['source_sha256'].items():
        if sha(ROOT/name)!=digest:raise ValueError('wsl_session_source_changed:'+name)
    for key in ('config_ref','environment_ref'):
        ref=value[key]
        if type(ref) is not dict or set(ref)!={'path','sha256'} or not Path(ref['path']).is_absolute():
            raise ValueError('wsl_session_reference_changed')
        no_alias(ref['path'])
        checked_ref(ref)
    return value,out


def bootstrap(spec,argv):
    """Re-exec before ROS imports; neither sensor input nor NN is warmed."""
    settings=checked_ref(spec['environment_ref'])
    python=settings['venv_python'];process_env=settings['process_environment']
    if not Path(python).is_absolute() or not Path(python).is_file():raise ValueError('wsl_session_verified_python_missing')
    marker=spec['run_uuid']+':'+spec['environment_ref']['sha256']
    if Path(sys.executable).absolute()!=Path(python).absolute() or os.environ.get('POLAR_PB_WSL_SESSION_ENV')!=marker or any(os.environ.get(k)!=v for k,v in process_env.items()):
        env=dict(os.environ);env.update(process_env);env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
        env['POLAR_PB_WSL_SESSION_ENV']=marker
        os.execve(python,[python,'-u',str(Path(__file__).resolve()),*argv],env)


def process_identity():
    fields=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()
    return dict(supervisor_pid=os.getpid(),start_ticks=int(fields[19]),
                boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip())


def checked_rpc(request,last_id,run_uuid):
    from rm_match.integrations.ros2_bridge import JSONL_SCHEMA
    if type(request) is not dict or set(request)!={'schema','op','id','run_uuid','packet'} or request['schema']!=WIRE or request['run_uuid']!=run_uuid:
        raise ValueError('wsl_request_identity')
    serial=request['id'];op=request['op'];packet=request['packet']
    if type(serial) is not int or serial!=last_id+1:raise ValueError('wsl_request_sequence')
    fields={'status':{'schema','op'},'reset':{'schema','op','context','config'},'act':{'schema','op','observation'}}
    if type(op) is not str or op not in fields:raise ValueError('wsl_operation_unknown')
    if type(packet) is not dict or set(packet)!=fields[op] or packet['schema']!=JSONL_SCHEMA or packet['op']!=op:
        raise ValueError('wsl_inner_packet_identity')
    return op,serial,packet


class StopGuard:
    def __init__(self,out,spec):
        self.out=out;self.spec=spec;self.stop=threading.Event();self.prepared=False
        self.start=time.monotonic();self.last_stop_check=-1.;self.reason='normal_stop'
        self.poll_count=0;self.max_poll_seconds=0.;self.slow_polls=[]

    def check(self):
        now=time.monotonic()
        if now-self.last_stop_check>=.01:
            self.last_stop_check=now
            poll_start=time.perf_counter()
            path=self.out/'STOP'
            if path.exists():
                from rm_match.deployment.profile import read_json_snapshot
                value,_=read_json_snapshot(path)
                if value!={'run_uuid':self.spec['run_uuid'],'config_sha256':self.spec['config_ref']['sha256']}:
                    self.reason='stop_identity_mismatch'
                else:self.reason='host_stop'
                self.stop.set()
            elapsed=time.perf_counter()-poll_start
            self.poll_count+=1;self.max_poll_seconds=max(self.max_poll_seconds,elapsed)
            if elapsed>.005 and len(self.slow_polls)<64:
                self.slow_polls.append(dict(local_wall=poll_start,duration_s=elapsed))
        if not self.prepared and now-self.start>=10.:
            self.reason='linux_prepare_resource_timeout';self.stop.set()
        if self.stop.is_set():raise InterruptedError(self.reason)


class NavigationGate:
    """Activate original servers only after actual estimated TF and SLAM map."""
    def __init__(self,transport,stack,guard):
        import rclpy
        from rclpy.qos import QoSProfile,ReliabilityPolicy,DurabilityPolicy
        from nav_msgs.msg import OccupancyGrid
        from tf2_ros import Buffer,TransformListener
        from rclpy.time import Time
        self.Time=Time;self.stack=stack;self.guard=guard;self.transport=transport
        ns=stack.namespace;remaps=[]
        for name in ('clock','tf','tf_static'):remaps+=['--remap','/'+name+':='+ns+'/'+name]
        self.node=rclpy.create_node('polar_wsl_navigation_gate',namespace=ns,context=transport.context,
            cli_args=['--ros-args',*remaps],use_global_arguments=False,enable_rosout=False,
            parameter_overrides=[rclpy.parameter.Parameter('use_sim_time',value=True)])
        self.buffer=Buffer(node=self.node);self.listener=TransformListener(self.buffer,self.node,spin_thread=False)
        self.maps=0;self.errors=[];self.thread=None
        def received(msg):
            if msg.info.width and msg.info.height:self.maps+=1
        self.sub=self.node.create_subscription(OccupancyGrid,ns+'/map',received,
            QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.TRANSIENT_LOCAL))
        transport.executor.add_node(self.node)

    def poll(self,core):
        if self.errors:raise RuntimeError(self.errors[0])
        if self.thread is not None or not self.maps or core._odom_stamp<0:return
        try:self.buffer.lookup_transform('map','base_link',self.Time())
        except Exception:return
        def activate():
            try:self.stack.activate_navigation()
            except Exception as error:
                if not self.guard.stop.is_set():self.errors.append(type(error).__name__+':'+str(error))
        self.thread=threading.Thread(target=activate,name='pb-wsl-activation',daemon=True);self.thread.start()

    def close(self):
        self.transport.executor.remove_node(self.node);self.listener.unregister();self.node.destroy_node()
        if self.thread is not None:self.thread.join(.1)
        return self.thread is None or not self.thread.is_alive()


def session_worker(spec,out,*,stack_factory=None,transport_factory=None):
    from rm_match.integrations.ros2_bridge import JSONL_SCHEMA,parse_json,encode_json
    from rm_match.integrations.pb_navigation_bridge import NavigationBridge,NavigationSettings
    from rm_match.integrations.pb_navigation_transport import HumbleNavigationTransport
    from tools.pb_navigation_stack import PBNavigationStack
    identity=process_identity();guard=StopGuard(out,spec)
    errors=[];stack=transport=core=observer=gate=None;goal_thread=None;code=2;old_signals={}
    rpc_rows=[];rpc_total=0;rpc_dropped=0;current_serial=None;current_op=None;odometry_messages=0
    def phase(name):
        nonlocal rpc_total,rpc_dropped
        if not spec['diagnostics']:return
        rpc_total+=1
        if len(rpc_rows)<4096:
            rpc_rows.append(dict(phase=name,id=current_serial,op=current_op,
                local_wall=time.perf_counter(),clock='linux_local_perf_counter'))
        else:rpc_dropped+=1
    for sig in (signal.SIGINT,signal.SIGTERM):
        old_signals[sig]=signal.getsignal(sig)
        signal.signal(sig,lambda *_:guard.stop.set())
    os.set_blocking(0,False);os.set_blocking(1,False)
    def emit(value):
        phase('stdout_emit_begin')
        raw=encode_json(value,MAX_RESPONSE-1)+b'\n';view=memoryview(raw);end=time.monotonic()+.15
        while view:
            guard.check()
            if time.monotonic()>=end:raise TimeoutError('wsl_protocol_output_blocked')
            _,writable,_=select.select([],[1],[],.002)
            guard.check()
            if time.monotonic()>=end:raise TimeoutError('wsl_protocol_output_blocked')
            if writable:
                try:count=os.write(1,view)
                except BlockingIOError:continue
                if not count:raise BrokenPipeError('wsl_protocol_output_closed')
                view=view[count:]
        phase('stdout_emit_end')
    class OwnedStack(PBNavigationStack):
        def poll_health(self,generation=None):guard.check();return super().poll_health(generation)
        def stop(self,grace_s=.15):return super().stop(grace_s=min(grace_s,.15))
    try:
        config=checked_ref(spec['config_ref'])
        stack=(stack_factory or OwnedStack)(config,out/'stack',namespace=spec['namespace'],
            environment=spec['environment_ref'],diagnostics=spec['diagnostics'])
        ready=stack.start();guard.check()
        from tools.pb_navigation_stack import controller_result_settings
        # The real stack has already validated its complete configuration.
        # Legacy injected stacks retain the old scan-only default; only an
        # explicit, build-bound v2 configuration enables the new wire profile.
        result_settings=(controller_result_settings(config) if config.get('schema')=='polar.pb-stack-config.v2'
            else dict(result_profile='scan_v1',controller_id='pb_controller_sourced_v1'))
        settings=NavigationSettings(node_name='polar_wsl_bridge_'+spec['run_uuid'][:16],domain_id=84,
            cloud_topic=ready['topics']['cloud'],pointcloud_topic=ready['topics']['cloud']+'/pointcloud',
            imu_topic=ready['topics']['imu'],request_topic=ready['topics']['request'],result_topic=ready['topics']['result'],
            odom_topic=ready['topics']['odom'],clock_topic=ready['topics']['clock'],tf_static_topic=ready['topics']['tf_static'],
            **result_settings)
        core=NavigationBridge(settings)
        original_odom=core.receive_odom_stamp
        def received_odom(stamp):
            nonlocal odometry_messages
            original_odom(stamp);odometry_messages+=1
        core.receive_odom_stamp=received_odom
        transport=(transport_factory or HumbleNavigationTransport)(settings,core)
        original_spin=transport.spin_once
        def spin(timeout):
            guard.check();stack.poll_health();original_spin(timeout)
        transport.spin_once=spin
        if spec['relative_test_goal']:
            # Explicit QA-only goal; production sessions accept external ROS
            # action clients once the actual readiness gate activates servers.
            from tools.qa_pb_navigation_sil import AlgorithmObserver
            observer=AlgorithmObserver(stack.namespace,84,diagnostics=spec['diagnostics'],receive_clock='linux_local_perf_counter')
        else:gate=NavigationGate(transport,stack,guard)
        guard.check();guard.prepared=True
        emit(dict(schema=WIRE,event='ready',run_uuid=spec['run_uuid'],namespace=stack.namespace,
            config_sha256=spec['config_ref']['sha256'],environment_sha256=spec['environment_ref']['sha256'],
            state='CONFIGURED',**identity))
        buffer=bytearray();last_id=0
        while True:
            guard.check();stack.poll_health()
            if gate is not None:gate.poll(core)
            if observer is not None and observer.errors:raise RuntimeError('wsl_actual_goal_failed:'+str(observer.errors))
            readable,_,_=select.select([0],[],[],.002)
            if not readable:transport.spin_once(0.);continue
            chunk=os.read(0,65536)
            if not chunk:
                if buffer:raise ValueError('wsl_partial_request_at_eof')
                guard.reason='host_eof';code=0;break
            buffer.extend(chunk)
            if len(buffer)>MAX_REQUEST:raise ValueError('wsl_request_oversized')
            if b'\n' not in buffer:continue
            raw,_,tail=buffer.partition(b'\n');buffer=bytearray(tail)
            if buffer:raise ValueError('wsl_concurrent_request_rejected')
            request=parse_json(bytes(raw),MAX_REQUEST)
            op,serial,packet=checked_rpc(request,last_id,spec['run_uuid']);last_id=serial
            current_serial=serial;current_op=op;phase('rpc_parsed')
            if op=='status':
                if packet!={'schema':JSONL_SCHEMA,'op':'status'}:raise ValueError('wsl_status_packet')
                result=dict(stack_state=stack.state,bridge_reset=core.context is not None,
                    namespace=stack.namespace,goal_report={} if observer is None else observer.goal_report,
                    odometry_messages=odometry_messages if observer is None else observer.odom_count,
                    map_messages=gate.maps if gate is not None else observer.map_count,
                    errors=gate.errors if gate is not None else observer.errors,clock_domain='linux_local_receive_only')
            elif op in ('reset','act'):
                if op=='reset':
                    core.reset(packet['context'],packet['config']);transport.wait_ready(1.)
                    result=dict(schema=JSONL_SCHEMA,op=op,ok=True)
                    if observer is not None:
                        goal_thread=threading.Thread(target=observer.drive_goal,args=(stack,guard.stop),name='pb-wsl-relative-test-goal',daemon=True)
                        goal_thread.start()
                else:
                    phase('bridge_exchange_begin')
                    kind,value=core.exchange(packet['observation'],transport)
                    phase('bridge_exchange_end')
                    result=dict(schema=JSONL_SCHEMA,op=op,ok=True,**{kind:value})
            else:raise ValueError('wsl_operation_unknown')
            emit(dict(schema=WIRE,op=op,id=serial,run_uuid=spec['run_uuid'],result=result))
    except InterruptedError:
        code=0 if guard.reason in ('normal_stop','host_stop','host_eof') else 2
    except BaseException as error:
        errors.append(type(error).__name__+':'+str(error));traceback.print_exc(file=sys.stderr)
    finally:
        guard.stop.set()
        cleanup=None
        if gate is not None:
            try:
                (out/'PRODUCTION_GATE_STATUS.json').write_text(json.dumps(dict(schema='polar.pb.production-gate-status.v1',
                    run_uuid=spec['run_uuid'],production_gate=True,
                    namespace=stack.namespace,stack_state=stack.state,map_messages=gate.maps,
                    odometry_messages=odometry_messages,latest_odom_stamp_ns=core._odom_stamp,
                    activation_started=gate.thread is not None,errors=gate.errors,
                    clock_domain='linux_local_receive_only'),allow_nan=False)+'\n',encoding='utf8')
            except BaseException as error:errors.append('gate_status_save:'+type(error).__name__)
        if observer is not None:
            try:observer.record_ending_estimate()
            except BaseException as error:errors.append('ending_estimate:'+type(error).__name__)
        # Cancel/join lifecycle activation while its own stack context is alive.
        # Gate uses no action/velocity authority; this is only owned teardown.
        if gate is not None:
            try:
                if not gate.close():errors.append('activation_thread_not_reaped')
            except BaseException as error:errors.append('gate_cleanup:'+type(error).__name__)
        if stack is not None:
            try:cleanup=stack.stop(grace_s=.15)
            except BaseException as error:errors.append('stack_cleanup:'+type(error).__name__)
        if goal_thread is not None:
            goal_thread.join(.1)
            if goal_thread.is_alive():errors.append('goal_thread_not_reaped')
        if observer is not None:
            try:
                observer.close()
            except BaseException as error:errors.append('observer_cleanup:'+type(error).__name__)
            try:
                (out/'ROS_SOURCE.jsonl').write_text(''.join(json.dumps(r,allow_nan=False,separators=(',',':'))+'\n' for r in observer.rows),encoding='utf8')
                (out/'GOAL_REPORT.json').write_text(json.dumps(observer.goal_report,indent=2)+'\n',encoding='utf8')
                errors+=observer.errors
            except BaseException as error:errors.append('observer_evidence_save:'+type(error).__name__)
        if core is not None:
            try:core.close()
            except BaseException as error:errors.append('core_cleanup:'+type(error).__name__)
        if transport is not None:
            try:transport.close()
            except BaseException as error:errors.append('transport_cleanup:'+type(error).__name__)
        groups=[]
        if cleanup is not None:
            for row in cleanup.get('processes',[]):
                if row.get('remaining_members'):groups.append(row)
            if not cleanup.get('clean'):errors.append('stack_cleanup_unclean')
        elif stack is not None:errors.append('stack_cleanup_missing')
        source_unchanged=True
        for n,h in spec['source_sha256'].items():
            try:
                if sha(ROOT/n)!=h:source_unchanged=False
            except OSError as error:source_unchanged=False;errors.append('source_recheck:'+type(error).__name__)
        if not source_unchanged:errors.append('session_source_changed')
        if spec['diagnostics']:
            try:
                (out/'LINUX_RPC_PHASES.json').write_text(json.dumps(dict(rows=rpc_rows,total=rpc_total,
                    dropped=rpc_dropped,capacity=4096,complete=rpc_dropped==0,
                    stop_poll_count=guard.poll_count,max_stop_poll_seconds=guard.max_poll_seconds,
                    slow_stop_polls=guard.slow_polls,clock='linux_local_perf_counter'),allow_nan=False)+'\n',encoding='utf8')
            except BaseException as error:errors.append('rpc_evidence_save:'+type(error).__name__)
        record=dict(schema=CLEANUP,run_uuid=spec['run_uuid'],config_sha256=spec['config_ref']['sha256'],
            clean=not errors and not groups,owned_groups=groups,errors=errors,**identity)
        temp=out/'CLEANUP.tmp';temp.write_text(json.dumps(record,indent=2,allow_nan=False)+'\n',encoding='utf8');temp.replace(out/'CLEANUP.json')
        for sig,old in old_signals.items():signal.signal(sig,old)
    return code if not errors else 2


def main(argv=None):
    if sys.platform!='linux':raise ValueError('owned_session_requires_linux')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--spec',required=True);parser.add_argument('--spec-sha256',required=True)
    args=parser.parse_args(argv);spec,out=load_spec(args.spec,args.spec_sha256)
    bootstrap(spec,sys.argv[1:] if argv is None else argv)
    for name in ('CLEANUP.json','WORKER_STARTED.json','ROS_SOURCE.jsonl','GOAL_REPORT.json','stack'):
        if (out/name).exists():raise ValueError('wsl_session_reuse_forbidden')
    fd=os.open(str(out/'WORKER_STARTED.json'),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w',encoding='utf8') as stream:stream.write(json.dumps(dict(run_uuid=spec['run_uuid'],
        config_sha256=spec['config_ref']['sha256'],**process_identity()),allow_nan=False)+'\n')
    return session_worker(spec,out)


if __name__=='__main__':raise SystemExit(main())
