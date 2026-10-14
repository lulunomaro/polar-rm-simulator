#!/usr/bin/env python3
"""Actual ROS peer + original JsonLineAdapter reset deadline diagnostic.

Explicit fixture only: no physics, navigation algorithm, NN or GPU. ROS remains
optional; missing dependencies and the original 2s reset timeout are failures.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
ARTIFACT=ROOT/'artifacts/ros2-local-lyrical-20261013'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def local_environment(prefix,out,*,domain=80):
    """Select the already audited prefix; no global configuration changes."""
    prefix=Path(prefix).resolve(strict=True);out=Path(out).resolve(strict=True)
    extraction=json.loads((ARTIFACT/'EXTRACTION.json').read_text())
    if prefix!=Path(extraction['prefix']).resolve(strict=True):raise ValueError('Unverified ROS prefix; a relocated copy needs separate byte/link provenance')
    if type(domain) is not int or not 0<=domain<=101:raise ValueError('Explicit local ROS domain required')
    ros=prefix/'opt/ros/lyrical'
    for required in (ros/'lib/python3.14/site-packages/rclpy/__init__.py',ros/'lib/librmw_fastrtps_cpp.so'):
        if not required.resolve(strict=True).is_relative_to(prefix):raise ValueError('ROS input leaves verified prefix')
    env={k:os.environ[k] for k in ('PATH','HOME','LANG','LC_ALL','TMPDIR') if k in os.environ}
    env.update(PYTHONPATH=':'.join(map(str,(ros/'lib/python3.14/site-packages',prefix/'usr/lib/python3/dist-packages',ROOT))),
        LD_LIBRARY_PATH=':'.join(map(str,(ros/'lib',ros/'lib/x86_64-linux-gnu',prefix/'usr/lib/x86_64-linux-gnu'))),
        AMENT_PREFIX_PATH=str(ros),ROS_DISTRO='lyrical',ROS_DOMAIN_ID=str(domain),
        ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST',ROS_STATIC_PEERS='',ROS_LOCALHOST_ONLY='1',
        RMW_IMPLEMENTATION='rmw_fastrtps_cpp',RCUTILS_LOGGING_USE_STDOUT='0',
        ROS_HOME=str(out/'ros_home'),ROS_LOG_DIR=str(out/'ros_logs'))
    return env


def fixture_observation(deadline):
    from rm_match.platform_v2.contracts import FRAMES
    return dict(schema='polar.sim.observation.v2',robot_id='red_sentry',episode=1,
        binding_epoch=1,observed_seq=1,sim_time=1.,wall_deadline=deadline,frames=dict(FRAMES),
        own=dict(team='red',role='sentry',qpos=[0.]*5,qvel=[0.]*5,odom_xyyaw=[0.]*3,
            odom_vxyw=[0.]*3,hp=100.,ammo=1.,heat=0.,alive=True),
        referee=dict(phase='running',remaining_seconds=299.,emergency_stop=False),
        sensors=dict(camera=dict(available=False,reason='explicit_startup_fixture_no_camera'),
            ranges=dict(available=False,reason='explicit_startup_fixture_no_ranges')))


def bridge_arguments(aid,namespace,domain):
    return ['--adapter-id',aid,'--kind','navigation','--node-name','polar_startup_bridge',
        '--observation-topic',namespace+'/observation','--action-topic',namespace+'/action',
        '--domain-id',str(domain),'--response-timeout','0.08']


def write_manifest(out,prefix,*,mode,python,domain=80):
    """Commands are fixed in a local manifest, never binding config or HTTP."""
    out=Path(out).resolve();aid='custom_ros2_startup_fixture';namespace='/polar/startup_'+str(os.getpid())
    args=bridge_arguments(aid,namespace,domain)
    command=[str(python),'-u','-m','rm_match.integrations.ros2_bridge',*args]
    if mode=='prefix-bootstrap':
        spec=out/'bridge_bootstrap.json'
        value=dict(prefix=str(Path(prefix).resolve()),output=str(out),arguments=args)
        spec.write_text(json.dumps(value,separators=(',',':'))+'\n')
        command=[str(python),'-u',str(Path(__file__).resolve()),'--bridge-child',str(spec),'--child-spec-sha',sha(spec)]
    elif mode!='module':raise ValueError('Unknown fixed command mode')
    row=dict(adapter_id=aid,kind='navigation',label='Actual ROS startup/JSONL fixture; no physics/navigation',
        command=command,cwd=str(ROOT),required_sensors=[])
    manifest=out/'adapter_manifest.json'
    manifest.write_text(json.dumps(dict(schema='polar.sim.adapter.jsonl.v1',adapters=[row]),indent=2)+'\n')
    return manifest,aid,namespace


def run_bridge_child(spec_path,expected_sha):
    # This entry is chosen only by the trusted local diagnostic manifest. It
    # restores reviewed sys.path explicitly despite the host's PYTHONPATH scrub.
    from rm_match.deployment.profile import read_json_snapshot
    spec,actual=read_json_snapshot(spec_path)
    if actual!=expected_sha:raise ValueError('Bootstrap spec changed')
    if set(spec)!= {'prefix','output','arguments'}:raise ValueError('Invalid bootstrap spec')
    out=Path(spec['output']).resolve(strict=True);prefix=Path(spec['prefix']).resolve(strict=True)
    local_environment(prefix,out)  # scope validation; loader env came at exec.
    ros=prefix/'opt/ros/lyrical'
    sys.path[:0]=[str(ros/'lib/python3.14/site-packages'),str(prefix/'usr/lib/python3/dist-packages')]
    stages=out/'CHILD_PHASES.jsonl'
    def record(event):
        with stages.open('a') as stream:stream.write(json.dumps(dict(event=event,wall_perf_counter=time.perf_counter(),pid=os.getpid()))+'\n')
    record('bootstrap_enter')
    from rm_match.integrations import ros2_bridge,ros2_bridge_transport
    original_init=ros2_bridge_transport.RclpyTransport.__init__
    original_ready=ros2_bridge_transport.RclpyTransport.wait_ready
    def observed_init(self,*args,**kwargs):
        record('rclpy_transport_init_begin')
        try:return original_init(self,*args,**kwargs)
        finally:record('rclpy_transport_init_end')
    def observed_ready(self,*args,**kwargs):
        record('graph_wait_begin')
        try:return original_ready(self,*args,**kwargs)
        finally:record('graph_wait_end')
    # Observation only; actual transport, QoS, imports and clocks are unchanged.
    ros2_bridge_transport.RclpyTransport.__init__=observed_init
    ros2_bridge_transport.RclpyTransport.wait_ready=observed_ready
    return ros2_bridge.main(spec['arguments'])


@contextmanager
def measured_adapter(adapter,report,stderr_path):
    """Instrument a real adapter without replacing its clock or deadline logic."""
    real_popen=subprocess.Popen;real_exchange=adapter._exchange;owned=[]
    def popen(*args,**kwargs):
        report['popen_begin']=time.perf_counter()
        kwargs=dict(kwargs);kwargs['stderr']=stderr
        child=real_popen(*args,**kwargs);owned.append(child)
        report['popen_end']=time.perf_counter();report['child_pid']=child.pid
        return child
    def exchange(packet,*,timeout):
        before=time.perf_counter();phase=dict(op=packet['op'],begin=before,original_timeout_s=timeout)
        if packet['op']=='act':phase['original_wall_deadline']=packet['observation']['wall_deadline']
        report.setdefault('exchanges',[]).append(phase)
        try:
            result=real_exchange(packet,timeout=timeout);phase['accepted']=True;return result
        except Exception as exc:
            phase['accepted']=False;phase['error_type']=type(exc).__name__;raise
        finally:phase['end']=time.perf_counter();phase['elapsed_s']=phase['end']-before
    with Path(stderr_path).open('wb') as stderr:
        with patch('rm_match.deployment.json_adapter.subprocess.Popen',popen),patch.object(adapter,'_exchange',exchange):
            try:yield owned
            finally:
                try:adapter.close()
                except Exception as exc:report['adapter_close_error']=type(exc).__name__
                report['owned_children']=[dict(pid=p.pid,returncode=p.poll(),reaped=p.poll() is not None,
                    pipes_closed=all(s is None or s.closed for s in (p.stdin,p.stdout))) for p in owned]
                thread=getattr(adapter,'thread',None)
                report['adapter_io_thread_alive']=bool(thread is not None and thread.is_alive())


class ActualPeer:
    def __init__(self,aid,namespace,domain):
        # Lazy import real ROS; no fake production transport.
        import rclpy
        from rclpy.context import Context
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import QoSProfile,HistoryPolicy,ReliabilityPolicy,DurabilityPolicy
        from std_msgs.msg import String
        from rm_match.integrations.ros2_bridge import ENVELOPE_SCHEMA
        from rm_match.platform_v2.contracts import action_for
        self.rclpy=rclpy;self.context=Context();self.node=None;self.executor=None;self.thread=None
        self.stop=threading.Event();self.errors=[];self.packets=[]
        rclpy.init(args=[],context=self.context,domain_id=domain)
        try:
            self.node=rclpy.create_node('polar_startup_peer_'+str(os.getpid()),context=self.context,
                use_global_arguments=False,enable_rosout=False,start_parameter_services=False)
            qos=QoSProfile(history=HistoryPolicy.KEEP_LAST,depth=1,reliability=ReliabilityPolicy.BEST_EFFORT,durability=DurabilityPolicy.VOLATILE)
            publisher=self.node.create_publisher(String,namespace+'/action',qos)
            def received(message):
                try:
                    packet=json.loads(message.data);self.packets.append(packet)
                    if packet['adapter_id']!=aid:raise ValueError('Unexpected fixture route')
                    response=action_for(packet['observation'],'navigation','velocity_body',
                        dict(frame='base_link',vx_mps=0.,vy_mps=0.,wz_rps=0.))
                    reply=String();reply.data=json.dumps(dict(schema=ENVELOPE_SCHEMA,type='action',adapter_id=aid,action=response))
                    publisher.publish(reply)
                except Exception as exc:self.errors.append(type(exc).__name__)
            self.node.create_subscription(String,namespace+'/observation',received,qos)
            self.executor=SingleThreadedExecutor(context=self.context);self.executor.add_node(self.node)
            def run():
                try:
                    while not self.stop.is_set():self.executor.spin_once(timeout_sec=.01)
                except Exception as exc:self.errors.append(type(exc).__name__)
            self.thread=threading.Thread(target=run,name='actual-ros2-startup-peer');self.thread.start()
        except BaseException:self.close();raise

    def close(self):
        self.stop.set()
        if self.thread is not None:self.thread.join(.5)
        errors=[];executor_clean=False
        try:executor_clean=self.executor is None or self.executor.shutdown(timeout_sec=.15)
        except Exception as exc:errors.append(type(exc).__name__)
        try:
            if self.node is not None:self.node.destroy_node()
        except Exception as exc:errors.append(type(exc).__name__)
        try:self.rclpy.try_shutdown(context=self.context)
        except Exception as exc:errors.append(type(exc).__name__)
        return dict(thread_alive=bool(self.thread and self.thread.is_alive()),executor_clean=bool(executor_clean),context_ok=self.context.ok(),errors=errors)


def run_actual(out,prefix,mode,*,domain=80):
    from rm_match.deployment.json_adapter import register_json_adapters
    from rm_match.platform_v2.adapters import Registry
    from rm_match.platform_v2.contracts import IDENTITY
    report=dict(scope='Actual JsonLineAdapter original 2s reset + actual DDS peer; explicit zero-motion fixture; no physics/NN/navigation',
        mode=mode,clock='Linux time.perf_counter',fixture=True,reset_ack_received=False,action_received=False,
        fresh_exec_child=True,parent_import_not_counted_as_child_start=True,kernel_page_cache_not_purged=True)
    manifest,aid,namespace=write_manifest(out,prefix,mode=mode,python=sys.executable,domain=domain)
    registry=Registry();register_json_adapters(registry,manifest);adapter=registry.create(aid,{})
    peer=None;owned=[];started=time.perf_counter()
    try:
        peer=ActualPeer(aid,namespace,domain);report['peer_setup_s']=time.perf_counter()-started
        with measured_adapter(adapter,report,Path(out)/'BRIDGE_STDERR.log') as owned:
            try:
                adapter.reset(dict(robot_id='red_sentry',episode=1,binding_epoch=1))
                report['reset_ack_received']=True;report['reset_ack_wall']=time.perf_counter()
                report['popen_to_reset_ack_s']=report['reset_ack_wall']-report['popen_begin']
                observation=fixture_observation(time.perf_counter()+.08);response=adapter.act(observation)
                report['action_received']=True;report['six_identity_echo']=all(type(response[k]) is type(observation[k]) and response[k]==observation[k] for k in IDENTITY)
                report['fixture_zero_motion']=all(response['command'][k]==0 for k in ('vx_mps','vy_mps','wz_rps'))
            except Exception as exc:report['failure_type']=type(exc).__name__
    except Exception as exc:report['setup_failure_type']=type(exc).__name__
    finally:
        if not owned:
            try:adapter.close()
            except Exception as exc:report['adapter_close_error']=type(exc).__name__
        if peer is not None:
            report['peer_cleanup']=peer.close();report['peer_errors']=peer.errors;report['peer_observations']=len(peer.packets)
        report['elapsed_s']=time.perf_counter()-started
    report['original_reset_gate_passed']=report['reset_ack_received']
    report['clean_shutdown']=bool(report.get('owned_children') and all(c['reaped'] and c['pipes_closed'] for c in report['owned_children'])
        and not report.get('adapter_io_thread_alive',True) and not report.get('adapter_close_error') and peer is not None
        and not report['peer_cleanup']['thread_alive'] and report['peer_cleanup']['executor_clean'] and not report['peer_cleanup']['context_ok'] and not report['peer_cleanup']['errors'])
    stages=Path(out)/'CHILD_PHASES.jsonl'
    report['child_phases']=[json.loads(line) for line in stages.read_text().splitlines()] if stages.exists() else []
    report['manifest_sha256']=sha(manifest)
    report['sources']={rel:sha(ROOT/rel) for rel in ('rm_match/deployment/json_adapter.py','rm_match/integrations/ros2_bridge.py','rm_match/integrations/ros2_bridge_transport.py','tools/diagnose_ros2_jsonl_startup.py')}
    report['provenance_sha256']={name:sha(ARTIFACT/name) for name in ('PACKAGES_MANIFEST.json','EXTRACTION.json','UBUNTU_PACKAGES_MANIFEST.json','UBUNTU_PYTHON_PACKAGES_MANIFEST.json')}
    with (Path(out)/'RESULT.json').open('x') as stream:json.dump(report,stream,indent=2);stream.write('\n')
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out');parser.add_argument('--prefix',default=str(ARTIFACT/'prefix'))
    parser.add_argument('--mode',choices=('module','prefix-bootstrap'),default='module')
    parser.add_argument('--domain',type=int,default=80);parser.add_argument('--worker',action='store_true')
    parser.add_argument('--bridge-child');parser.add_argument('--child-spec-sha')
    args=parser.parse_args(argv)
    if args.bridge_child:return run_bridge_child(args.bridge_child,args.child_spec_sha)
    if not args.out:parser.error('--out required')
    out=Path(args.out).absolute()
    if not args.worker:
        out.mkdir(parents=True,exist_ok=False)
        environment=local_environment(args.prefix,out,domain=args.domain)
        command=[sys.executable,str(Path(__file__).resolve()),'--worker','--out',str(out),
            '--prefix',str(Path(args.prefix).absolute()),'--mode',args.mode,'--domain',str(args.domain)]
        with (out/'ENVIRONMENT.json').open('x') as stream:
            json.dump({k:v for k,v in environment.items() if k not in ('PATH','HOME','LANG','LC_ALL','TMPDIR')},stream,indent=2)
        result=subprocess.run(command,cwd=ROOT,env=environment,capture_output=True,timeout=40.)
        (out/'WORKER_STDOUT.log').write_bytes(result.stdout);(out/'WORKER_STDERR.log').write_bytes(result.stderr)
        print(json.dumps(dict(worker_returncode=result.returncode,result=str(out/'RESULT.json'))),flush=True)
        return result.returncode
    report=run_actual(out,args.prefix,args.mode,domain=args.domain)
    print(json.dumps({k:report[k] for k in ('mode','original_reset_gate_passed','action_received','clean_shutdown')}),flush=True)
    return 0 if report['original_reset_gate_passed'] and report['action_received'] and report['clean_shutdown'] else 1


if __name__=='__main__':raise SystemExit(main())
