"""Owned Linux external ROS client supervisor; never starts algorithm nodes."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
SCHEMA='polar.pb.external-goal-supervisor.v1'

def identity():
    fields=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()
    return dict(supervisor_pid=os.getpid(),start_ticks=int(fields[19]),
        boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip())

def main(argv=None):
    if sys.platform!='linux':raise RuntimeError('Linux owned supervisor required')
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--spec',required=True);p.add_argument('--spec-sha256',required=True)
    args=p.parse_args(argv)
    from tools.qa_pb_external_navigation_goal import load_spec,publish_json
    from rm_match.deployment.profile import read_json_snapshot
    from rm_match.integrations.owned_linux_group import LinuxOwnedProcessGroup
    spec,out=load_spec(args.spec,args.spec_sha256)
    for name in ('READY.json','RESULT.json','CLEANUP.json','SUPERVISOR_CLEANUP.json','SUPERVISOR_STARTED.json',
                 'SUPERVISOR_STARTED.json.tmp','SUPERVISOR_CLEANUP.json.tmp','client.stdout.log','client.stderr.log','SPAWN.json'):
        if (out/name).exists() or (out/name).is_symlink():raise ValueError('external_goal_output_reuse')
    token=identity();stop=threading.Event();old={};group=None;child=None;cleanup=None;errors=[];code=2
    publish_json(out/'SUPERVISOR_STARTED.json',dict(run_uuid=spec['run_uuid'],spec_sha256=args.spec_sha256,**token))
    for sig in (signal.SIGINT,signal.SIGTERM):
        old[sig]=signal.getsignal(sig);signal.signal(sig,lambda *_:stop.set())
    try:
        group=LinuxOwnedProcessGroup()
        command=['/usr/bin/python3','-u',str(ROOT/'tools/qa_pb_external_navigation_goal.py'),
            '--spec',str(Path(args.spec).absolute()),'--spec-sha256',args.spec_sha256,'--run']
        with (out/'client.stdout.log').open('xb') as stdout,(out/'client.stderr.log').open('xb') as stderr:
            child=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
                start_new_session=True,shell=False)
            owned=group.attach(child)
            (out/'SPAWN.json').write_text(json.dumps(dict(argv=command,identity=owned),indent=2)+'\n',encoding='utf8')
            end=time.monotonic()+4.;ready=False
            while not stop.is_set():
                marker=out/'STOP'
                if marker.exists():
                    value,_=read_json_snapshot(marker,4096)
                    if value!={'run_uuid':spec['run_uuid'],'spec_sha256':args.spec_sha256}:raise ValueError('external_stop_identity')
                    stop.set();code=0;break
                if not ready:
                    path=out/'READY.json'
                    if path.exists():
                        value,_=read_json_snapshot(path,16384)
                        if (value.get('schema')!='polar.pb.external-goal-ready.v1' or value.get('run_uuid')!=spec['run_uuid']
                            or value.get('session_run_uuid')!=spec['session_run_uuid'] or value.get('spec_sha256')!=args.spec_sha256
                            or value.get('namespace')!=spec['namespace'] or value.get('source_sha256')!=spec['source_sha256']
                            or value.get('environment_sha256')!=spec['environment_ref']['sha256']):
                            raise ValueError('external_client_ready_identity')
                        # Client must still be this exact child after bootstrap exec.
                        group._verified_members()
                        if (type(value.get('pid')) is not int or value['pid']!=child.pid
                            or value.get('start_ticks')!=owned['leader_start_ticks'] or value.get('boot_id')!=owned['boot_id']):
                            raise ValueError('external_client_ready_pid')
                        print(json.dumps(dict(schema=SCHEMA,event='ready',run_uuid=spec['run_uuid'],
                            spec_sha256=args.spec_sha256,client=value,owned_identity=owned,**token)),flush=True)
                        ready=True
                    elif time.monotonic()>=end:raise TimeoutError('external_client_ready_resource_timeout')
                if child.poll() is not None:
                    code=child.returncode
                    if not ready:raise RuntimeError('external_client_exited_before_ready')
                    break
                stop.wait(.01)
            if stop.is_set() and code==2:code=0
            cleanup=group.cleanup()
            if not cleanup['clean']:errors+=cleanup['errors']
            if cleanup['returncode']!=0:errors.append('external_client_exit_nonzero:'+str(cleanup['returncode']))
    except BaseException as error:
        errors.append(type(error).__name__+':'+str(error));traceback.print_exc(file=sys.stderr)
    finally:
        stop.set()
        if group is not None and not group.closed:
            try:cleanup=group.cleanup()
            except BaseException as error:errors.append('group_cleanup:'+type(error).__name__+':'+str(error))
        client_cleanup=None
        if child is not None:
            try:client_cleanup,_=read_json_snapshot(out/'CLEANUP.json',65536)
            except BaseException as error:errors.append('client_cleanup_missing:'+type(error).__name__)
            if client_cleanup is not None and (client_cleanup.get('schema')!='polar.pb.external-goal-cleanup.v1'
                or client_cleanup.get('run_uuid')!=spec['run_uuid'] or client_cleanup.get('clean') is not True
                or client_cleanup.get('observer_thread_alive') is not False or client_cleanup.get('errors')!=[]
                or type(client_cleanup.get('pid')) is not int or client_cleanup['pid']!=child.pid
                or group is None or group.identity is None
                or client_cleanup.get('start_ticks')!=group.identity['leader_start_ticks'] or client_cleanup.get('boot_id')!=group.boot_id):
                errors.append('external_client_cleanup_unclean')
        record=dict(schema=SCHEMA,run_uuid=spec['run_uuid'],spec_sha256=args.spec_sha256,**token,
            clean=not errors and cleanup is not None and cleanup['clean'],errors=errors,group=cleanup,
            client_cleanup=client_cleanup,returncode=code)
        publish_json(out/'SUPERVISOR_CLEANUP.json',record)
        for sig,handler in old.items():signal.signal(sig,handler)
    return code if not errors else 2

if __name__=='__main__':raise SystemExit(main())
