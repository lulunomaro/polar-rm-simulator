"""Explicit Windows-host / WSL-native stdio transport, never Windows-native.

One bounded transaction, persistent Linux supervisor, host QPC authority.
The supervisor owns and reaps its ELF child on EOF/cancel/timeout.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import uuid
from .wsl_operator_worker import validate_sensor_frame
from ..deployment.wsl_profile import _host_path as checked_host_path, host_to_linux_path, validate_wsl_spec

MAX_LINE = 65536


class WslOperatorProcess:
    def __init__(self, spec_path, out, fov, *, distribution='Ubuntu', timeout=.08,
                 startup_timeout=15., registered_spec_sha=None):
        self.repo_root = Path(__file__).resolve().parents[2]
        self.out = Path(out).resolve(); self.out.mkdir(parents=True, exist_ok=True)
        self.spec_path = Path(spec_path).resolve(); self.fov = dict(fov)
        if set(self.fov) != {'fov_degrees','circle_radius_x_norm','circle_radius_y_norm'}:
            raise ValueError('invalid operator FOV keys')
        for k,lo,hi in [('fov_degrees',10,180),('circle_radius_x_norm',1e-6,2),('circle_radius_y_norm',1e-6,2)]:
            v=self.fov[k]
            if type(v) not in (int,float) or not math.isfinite(v) or not lo<=v<=hi: raise ValueError('invalid operator FOV')
        if not 0 < timeout <= .08 or not 0 < startup_timeout <= 60:
            raise ValueError('invalid bridge budgets')
        self.timeout=timeout; self.startup_timeout=startup_timeout; self.distribution=distribution
        self.checked=validate_wsl_spec(self.spec_path,repo_root=self.repo_root,shared_out=self.out,
            distribution=distribution,expected_spec_sha=registered_spec_sha)
        self.process=None; self.stderr=None; self.ready=None; self.cleanup=None; self.evidence_out=None
        self._stop=threading.Event(); self._broken=threading.Event(); self._transaction=threading.Lock()
        self._incoming=queue.Queue(maxsize=2); self._outgoing=queue.Queue(maxsize=1)
        self._threads=[]; self._serial=0; self.diagnostics=[]

    def _record(self,event,**fields):
        self.diagnostics.append(dict(event=event,host_perf_counter=time.perf_counter(),**fields))
        del self.diagnostics[:-128]

    def _read(self, child):
        try:
            while True:
                raw=child.stdout.readline(MAX_LINE+1)
                if not raw: raise EOFError('WSL supervisor closed stdout')
                if len(raw)>MAX_LINE or not raw.endswith(b'\n'): raise ValueError('oversize WSL message')
                self._incoming.put_nowait(json.loads(raw))
        except Exception:
            self._broken.set(); self.request_stop()

    def _write(self, child):
        try:
            while not self._stop.is_set():
                try: raw=self._outgoing.get(timeout=.02)
                except queue.Empty: continue
                view=memoryview(raw)
                while view:
                    written=child.stdin.write(view)
                    if not written: raise BrokenPipeError('WSL write failed')
                    view=view[written:]
        except Exception:
            self._broken.set(); self.request_stop()

    def _receive(self, deadline):
        while True:
            if self._stop.is_set(): raise RuntimeError('WSL bridge stopped')
            remaining=deadline-time.perf_counter()
            if remaining<=0: raise TimeoutError('host bridge deadline expired')
            try: return self._incoming.get(timeout=min(.01,remaining))
            except queue.Empty:
                if self._broken.is_set(): raise RuntimeError('WSL bridge stdio failed')

    def reset(self,message):
        if self._stop.is_set(): raise RuntimeError('WSL bridge stopped; create a new instance')
        if self.process is not None: raise RuntimeError('bridge already started')
        self.checked.verify_unchanged()
        # This is a new owned binding runtime file, not a frozen source asset.
        # Windows text mode would turn the source's required LF into CRLF.
        (self.out/'tracking_mode').write_bytes(self.checked.linux_spec['runtime_mode_contents'].encode('utf8'))
        mapping=lambda p: str(host_to_linux_path(p,repo_root=self.repo_root,shared_out=self.out))
        self.evidence_out=self.out/('wsl_supervisor_'+uuid.uuid4().hex); self.evidence_out.mkdir()
        self.stderr=(self.evidence_out/'supervisor_stderr.log').open('wb')
        command=['wsl.exe','-d',self.distribution,'--cd',mapping(self.repo_root),'--',
            '/usr/bin/python3','-m','rm_match.integrations.wsl_operator_worker',
            '--spec',mapping(self.spec_path),'--spec-sha256',self.checked.linux_spec_sha256,
            '--out',mapping(self.evidence_out),'--fov-degrees',str(self.fov['fov_degrees']),
            '--radius-x',str(self.fov['circle_radius_x_norm']),'--radius-y',str(self.fov['circle_radius_y_norm']),
            '--startup-timeout',str(self.startup_timeout),'--control-timeout',str(self.timeout)]
        self._record('startup_begin',transport='wsl_stdio_v1',windows_native=False,command=command)
        try:
            self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr,
                bufsize=0,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            for method in (self._read,self._write):
                thread=threading.Thread(target=method,args=(self.process,),daemon=True); thread.start(); self._threads.append(thread)
            reply=self._receive(time.perf_counter()+self.startup_timeout)
            if reply.get('event')!='ready' or reply.get('spec_sha256')!=self.checked.linux_spec_sha256 or reply.get('transport')!='wsl_stdio_v1':
                raise RuntimeError('invalid WSL startup identity')
            self.ready=reply; self._record('startup_ready',native_pid=reply['native_pid'])
        except BaseException:
            self.request_stop(); self.close(); raise

    def control(self,packet):
        if not self._transaction.acquire(blocking=False): raise RuntimeError('concurrent WSL transaction rejected')
        deadline=time.perf_counter()+self.timeout
        prep_started=time.perf_counter();stages={};phase='admission';phase_started=prep_started;prep_recorded=False
        def next_phase(name):
            nonlocal phase,phase_started
            now=time.perf_counter();stages[phase+'_s']=now-phase_started;phase=name;phase_started=now
        def record_preparation(error=None):
            nonlocal prep_recorded
            if prep_recorded:return
            now=time.perf_counter();stages[phase+'_s']=now-phase_started;stages['total_s']=now-prep_started
            self._record('control_prepare',stages_s=stages.copy(),failed_phase=phase if error else None,
                error_type=type(error).__name__ if error else None,original_host_deadline=deadline,
                remaining_host_budget_s=deadline-now,clock_domain='host_perf_counter')
            prep_recorded=True
        try:
            if self.ready is None or self.process is None or self._stop.is_set(): raise RuntimeError('WSL bridge not ready')
            if 'host_deadline' in packet:
                authority=packet['host_deadline']
                if type(authority) not in (int,float) or not math.isfinite(authority): raise ValueError('invalid host authority deadline')
                deadline=min(deadline,authority)
            if time.perf_counter()>=deadline: raise TimeoutError('host authority deadline expired')
            # Persistent child has already loaded the verified ELF/model. Asset
            # hashes belong to registration/reset/startup, not each sensor tick.
            next_phase('frame_copy')
            frame=copy.deepcopy(packet['frame']); image=frame['image']; path=Path(image['path'])
            next_phase('sensor_validate')
            validate_sensor_frame(frame)
            next_phase('path_map')
            # Same canonical/no-reparse guard on every ancestor, once per frame.
            # Image must be in this binding directory, stricter than generic
            # repo/shared-root admission; do not cache checks across frames.
            path=checked_host_path(path)
            if not path.is_relative_to(self.out): raise ValueError('image outside binding directory')
            mapped='/mnt/c/'+path.as_posix()[3:]
            next_phase('bgr_read')
            with path.open('rb') as stream: raw=stream.read(4665601)
            next_phase('bgr_hash')
            if len(raw)!=4665600 or image.get('bytes')!=4665600 or hashlib.sha256(raw).hexdigest()!=image['sha256']:
                raise ValueError('image SHA/size mismatch')
            next_phase('serialize')
            image['path']=mapped
            ns=packet['control_time_ns']
            if type(ns) is not int or ns<0: raise ValueError('invalid control clock')
            self._serial+=1; serial=self._serial
            request=dict(control_time_ns=ns,time_s=ns/1e9,frame=frame,operator_fov=self.fov)
            remaining=deadline-time.perf_counter()
            if remaining<=0: raise TimeoutError('host frame preparation expired')
            wrapper=dict(event='control',id=serial,timeout_s=min(remaining,self.timeout),packet=request)
            encoded=json.dumps(wrapper,allow_nan=False,separators=(',',':')).encode()+b'\n'
            if len(encoded)>MAX_LINE: raise ValueError('oversize bridge request')
            if time.perf_counter()>=deadline: raise TimeoutError('host serialization deadline expired')
            record_preparation()
            self._record('native_request',request_id=serial,control_time_ns=ns,image_sha256=image['sha256'])
            self._outgoing.put_nowait(encoded)
            message=self._receive(deadline)
            if message.get('event')!='result' or message.get('id')!=serial: raise ValueError('WSL transaction identity mismatch')
            response=message['response']
            if response.get('status')!='ok' or response.get('runner_identity')!='rmcs-sim-operator-fov-v1' or response.get('clock_time_ns')!=ns or response.get('direction_frame')!='world' or type(response.get('tracking')) is not bool:
                raise ValueError('native identity/clock/output mismatch')
            if time.perf_counter()>deadline: raise TimeoutError('host result deadline expired')
            self._record('native_result',request_id=serial,control_time_ns=ns)
            return dict(response,episode=packet['episode'],should_control=response['tracking'])
        except BaseException as exc:
            record_preparation(exc)
            self.request_stop(); raise
        finally:
            self._transaction.release()

    def request_stop(self):
        self._stop.set()
        if self.evidence_out is not None:
            try: (self.evidence_out/'STOP').write_bytes(b'cancel\n')
            except OSError: self._broken.set()

    def close(self):
        self.request_stop(); child=self.process
        if child is None:
            if self.stderr is not None and not self.stderr.closed: self.stderr.close()
            if getattr(self,'_close_error',None):raise RuntimeError(self._close_error)
            return
        # STOP is independent of a potentially blocked pipe writer. Linux owns
        # native cleanup; do not terminate a distro or rely on killing wsl.exe.
        deadline=time.perf_counter()+1.3
        errors=[];cleanup_path=self.evidence_out/'CLEANUP.json'
        try:
            while not cleanup_path.exists() and time.perf_counter()<deadline-.1 and child.poll() is None:
                time.sleep(.01)
            if not cleanup_path.exists():raise RuntimeError('missing Linux child cleanup proof')
            self.cleanup=json.loads(cleanup_path.read_text())
            owned=json.loads((self.evidence_out/'OWNED_CHILD.json').read_text())
            ready=self.ready
            for key in ('run_id','supervisor_pid','pid','pgid','boot_id','leader_start_ticks','spec_sha256','transport'):
                if key not in owned or type(self.cleanup.get(key)) is not type(owned[key]) or self.cleanup[key]!=owned[key]:
                    raise RuntimeError('Linux cleanup ownership mismatch: '+key)
            if owned['spec_sha256']!=self.checked.linux_spec_sha256:
                raise RuntimeError('Linux cleanup spec mismatch')
            if ready is not None and any(type(ready.get(k)) is not type(owned[v]) or ready[k]!=owned[v]
                for k,v in (('run_id','run_id'),('supervisor_pid','supervisor_pid'),('native_pid','pid'),('transport','transport'))):
                raise RuntimeError('Linux cleanup belongs to another startup')
            if self.cleanup.get('clean') is not True or self.cleanup.get('reaped') is not True or self.cleanup.get('group_empty') is not True or self.cleanup.get('remaining_members')!=[] or self.cleanup.get('errors')!=[]:
                raise RuntimeError('Linux owned process group cleanup not proved')
            child.wait(timeout=max(0.,deadline-.1-time.perf_counter()))
        except Exception as exc:errors.append(type(exc).__name__+':'+str(exc))
        finally:
            # Host launcher cleanup never proves Linux descendants have exited.
            # Durable STOP remains even when an unresponsive launcher is killed.
            if child.poll() is None:
                errors.append('Linux supervisor did not exit within original cleanup budget')
                try:child.kill();child.wait(timeout=max(0.,deadline-time.perf_counter()))
                except Exception as exc:errors.append('launcher_close:'+type(exc).__name__)
            for stream in (child.stdin,child.stdout,self.stderr):
                try:
                    if stream is not None:stream.close()
                except Exception as exc:errors.append('pipe_close:'+type(exc).__name__)
            for thread in self._threads:
                if thread is threading.current_thread():continue
                thread.join(timeout=max(0.,deadline-time.perf_counter()))
                if thread.is_alive():errors.append('owned_IO_thread_did_not_stop')
            self.process=None
            self._record('closed',clean=not errors,linux_child_reaped=not errors,errors=errors)
            try:(self.evidence_out/'HOST_TRACE.json').write_text(json.dumps(self.diagnostics,indent=2)+'\n',encoding='utf8')
            except Exception as exc:errors.append('trace_write:'+type(exc).__name__)
            self._close_error='; '.join(errors) if errors else None
        if errors:raise RuntimeError(self._close_error)
