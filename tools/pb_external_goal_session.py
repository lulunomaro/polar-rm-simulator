"""QA-only Windows ownership of an external Linux ROS goal client."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

from rm_match.deployment.profile import read_json_snapshot,digest
from rm_match.deployment.wsl_profile import _host_path,host_to_linux_path

SCHEMA='polar.pb.external-goal-supervisor.v1'

def strict_json(raw):
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:raise ValueError('external_duplicate_json_key')
            result[k]=v
        return result
    def bad(_):raise ValueError('external_nonfinite_json')
    def finite_float(value):
        result=float(value)
        if not math.isfinite(result):raise ValueError('external_nonfinite_json')
        return result
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=bad,parse_float=finite_float)

class ExternalGoalSession:
    def __init__(self,root,out,spec_path,spec_sha):
        if sys.platform!='win32':raise RuntimeError('Windows external-client owner required')
        self.root=_host_path(root);self.out=_host_path(out);self.spec_path=_host_path(spec_path)
        if not self.out.is_dir() or not self.out.resolve().is_relative_to(self.root/'artifacts'):
            raise ValueError('external_owned_output_required')
        self.spec,self.spec_sha=read_json_snapshot(self.spec_path)
        if self.spec_sha!=spec_sha or self.spec_path.parent!=self.out:raise ValueError('external_spec_identity')
        self.run_uuid=self.spec['run_uuid'];self.ready=self.cleanup=self.child=None;self.stderr=None
        self.stop=threading.Event();self.queue=queue.Queue(1);self.write_error=None;self.closed=False;self.failure=None
        self.threads=[];writer=threading.Thread(target=self._stop_file,name='external-stop-writer',daemon=True)
        self.threads.append(writer);writer.start()

    def _stop_file(self):
        self.stop.wait()
        try:
            _host_path(self.out);tmp=self.out/'STOP.tmp';path=self.out/'STOP'
            if path.exists() or path.is_symlink():raise ValueError('external_stop_reuse')
            with tmp.open('xb') as stream:stream.write(json.dumps(dict(run_uuid=self.run_uuid,spec_sha256=self.spec_sha)).encode())
            os.replace(tmp,path)
        except BaseException as error:self.write_error=type(error).__name__+':'+str(error)

    def _reader(self):
        try:
            raw=self.child.stdout.readline(32769)
            if not raw.endswith(b'\n') or len(raw)>32768:raise ValueError('external_ready_line_invalid')
            self.queue.put_nowait(strict_json(raw))
        except BaseException as error:self.queue.put_nowait(error)

    def prepare(self):
        end=time.perf_counter()+5.
        if self.child is not None or self.closed or self.stop.is_set():raise RuntimeError('external_owner_single_use')
        if digest(self.spec_path)!=self.spec_sha:raise ValueError('external_spec_changed')
        mapping=lambda p:host_to_linux_path(p,repo_root=self.root,shared_out=self.out)
        command=['C:/Windows/System32/wsl.exe','-d','Ubuntu-22.04','--cd',mapping(self.root),'--',
            '/usr/bin/python3','-u',mapping(self.root/'tools/qa_pb_external_goal_supervisor.py'),
            '--spec',mapping(self.spec_path),'--spec-sha256',self.spec_sha]
        self.stderr=(self.out/'supervisor.stderr.log').open('wb')
        self.child=subprocess.Popen(command,cwd=self.root,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
            stderr=self.stderr,shell=False,bufsize=0,creationflags=subprocess.CREATE_NO_WINDOW)
        reader=threading.Thread(target=self._reader,name='external-ready-reader',daemon=True)
        self.threads.append(reader);reader.start()
        try:value=self.queue.get(timeout=max(0.,end-time.perf_counter()))
        except queue.Empty as error:self.request_stop();raise TimeoutError('external_ready_timeout') from error
        if isinstance(value,BaseException):self.request_stop();raise value
        expected=dict(schema=SCHEMA,event='ready',run_uuid=self.run_uuid,spec_sha256=self.spec_sha)
        if type(value) is not dict or any(type(value.get(k)) is not str or value[k]!=v for k,v in expected.items()):
            self.request_stop();raise ValueError('external_supervisor_ready_identity')
        for key in ('supervisor_pid','start_ticks'):
            if type(value.get(key)) is not int or value[key]<(2 if key=='supervisor_pid' else 0):raise ValueError('external_supervisor_process_identity')
        client=value.get('client')
        if type(client) is not dict or client.get('session_run_uuid')!=self.spec['session_run_uuid'] or client.get('namespace')!=self.spec['namespace']:
            raise ValueError('external_client_namespace')
        if (client.get('schema')!='polar.pb.external-goal-ready.v1' or client.get('run_uuid')!=self.run_uuid
            or client.get('spec_sha256')!=self.spec_sha or type(client.get('domain_id')) is not int or client['domain_id']!=84
            or client.get('state')!='OBSERVING_NO_INPUT_PUBLISHED'):raise ValueError('external_client_ready_fields')
        if any(client.get(k) is not False for k in ('sensor_published','goal_sent','lifecycle_changed')):raise ValueError('external_client_warmed_data')
        if client.get('environment_sha256')!=self.spec['environment_ref']['sha256'] or client.get('source_sha256')!=self.spec['source_sha256']:
            raise ValueError('external_client_source')
        owned=value.get('owned_identity')
        if type(owned) is not dict or type(client.get('pid')) is not int or client['pid']!=owned.get('pid') or owned.get('supervisor_pid')!=value['supervisor_pid']:
            raise ValueError('external_child_ownership')
        if (client.get('start_ticks')!=owned.get('leader_start_ticks') or client.get('boot_id')!=owned.get('boot_id')
            or value.get('boot_id')!=client.get('boot_id')):raise ValueError('external_child_birth_identity')
        if time.perf_counter()>=end:raise TimeoutError('external_ready_deadline')
        self.ready=value;return value

    def request_stop(self):self.stop.set()

    def close(self):
        if self.closed:
            if self.failure:raise RuntimeError(self.failure)
            return
        errors=[];end=time.perf_counter()+1.3;self.request_stop()
        try:
            if self.child is not None:
                path=self.out/'SUPERVISOR_CLEANUP.json'
                while time.perf_counter()<end and not path.exists() and self.child.poll() is None:time.sleep(.005)
                try:
                    value,_=read_json_snapshot(path,65536)
                    if value.get('schema')!=SCHEMA or value.get('run_uuid')!=self.run_uuid or value.get('spec_sha256')!=self.spec_sha:
                        raise ValueError('external_cleanup_identity')
                    token=self.ready or read_json_snapshot(self.out/'SUPERVISOR_STARTED.json',4096)[0]
                    if any(type(value.get(k)) is not type(token[k]) or value[k]!=token[k] for k in ('supervisor_pid','start_ticks','boot_id')):
                        raise ValueError('external_cleanup_process_identity')
                    group=value.get('group')
                    if (value.get('clean') is not True or value.get('errors')!=[] or type(group) is not dict
                        or group.get('clean') is not True or group.get('reaped') is not True or group.get('group_empty') is not True
                        or group.get('remaining_members')!=[] or type(group.get('returncode')) is not int or group['returncode']!=0):
                        raise RuntimeError('external_linux_cleanup_unclean')
                    if self.ready is not None:
                        prior=self.ready['owned_identity']
                        for k in ('run_id','supervisor_pid','boot_id','pid','pgid','leader_start_ticks'):
                            if type(group.get(k)) is not type(prior[k]) or group[k]!=prior[k]:raise ValueError('external_cleanup_group_identity')
                    self.cleanup=value
                except BaseException as error:errors.append(type(error).__name__+':'+str(error))
                try:
                    if self.child.wait(timeout=max(0.,end-time.perf_counter()))!=0:errors.append('external_supervisor_exit_nonzero')
                except subprocess.TimeoutExpired:errors.append('external_supervisor_not_reaped')
        finally:
            for thread in self.threads:
                thread.join(max(0.,end-time.perf_counter()))
                if thread.is_alive():errors.append('external_owned_thread_unfinished')
            if self.write_error:errors.append('external_stop_write:'+self.write_error)
            if self.child is not None and self.child.poll() is not None and self.child.stdout is not None:self.child.stdout.close()
            if self.stderr is not None:self.stderr.close()
            self.closed=True
        if errors:self.failure=';'.join(errors);raise RuntimeError(self.failure)
