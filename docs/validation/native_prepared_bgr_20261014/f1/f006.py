"""Explicit Windows-host / WSL-native binary BGR transport; not Windows-native.

The authority never writes a pipe: one bounded transaction goes through an owned
writer thread. Linux receives original BGR bytes and gives the unchanged ELF a
private tmpfs path, preserving exposure, calibration and own sensor fields.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
from pathlib import Path
import queue
import subprocess
import threading
import time
import uuid
from dataclasses import replace
from .wsl_operator import WslOperatorProcess,MAX_LINE,checked_host_path,host_to_linux_path,validate_sensor_frame
from ..platform_v2.native_image import prepared_native_bgr_matches

TRANSPORT='wsl_stdio_bgr_v2'
CHUNK=65536
IMAGE_BYTES=4665600


class WslPipeOperatorProcess(WslOperatorProcess):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        from ..deployment.profile import digest
        metadata=copy.deepcopy(self.checked.metadata);identities=dict(self.checked._identities)
        for rel in ('rm_match/integrations/wsl_operator_pipe.py','rm_match/integrations/wsl_operator_pipe_worker.py',
                    'rm_match/integrations/owned_linux_group.py','rm_match/platform_v2/native_image.py',
                    'rm_match/platform_v2/native_camera_snapshot.py'):
            selected=checked_host_path(self.repo_root/rel)
            if not selected.is_relative_to(self.repo_root):raise ValueError('pipe source outside repository')
            sha=digest(selected);identities[str(selected)]=sha;metadata['transport_source_sha256'][rel]=sha
        metadata.update(transport=TRANSPORT,image_transport='exact_inline_bgr_to_owned_linux_tmpfs',
            qualification='Explicit Windows host + WSL inline BGR; live/full-match/Windows-native acceptance not qualified')
        self.checked=replace(self.checked,metadata=metadata,_identities=identities)
        self.checked.verify_unchanged()

    def _read(self,child):
        # FileIO.readline on Windows may issue a ReadFile for every byte. Read
        # bounded chunks in this owned reader, keeping a strict line cap.
        buffer=bytearray()
        try:
            while True:
                raw=child.stdout.read(CHUNK)
                if not raw:raise EOFError('WSL supervisor closed stdout')
                buffer.extend(raw)
                while b'\n' in buffer:
                    line,_,tail=buffer.partition(b'\n');buffer=bytearray(tail)
                    if len(line)+1>MAX_LINE:raise ValueError('oversize WSL message')
                    self._incoming.put_nowait(json.loads(line))
                if len(buffer)>MAX_LINE:raise ValueError('oversize WSL message')
        except Exception:self._broken.set();self.request_stop()

    def reset(self,message):
        if self._stop.is_set():raise RuntimeError('WSL bridge stopped; create a new instance')
        if self.process is not None:raise RuntimeError('bridge already started')
        self.checked.verify_unchanged()
        (self.out/'tracking_mode').write_bytes(self.checked.linux_spec['runtime_mode_contents'].encode('utf8'))
        mapping=lambda p:str(host_to_linux_path(p,repo_root=self.repo_root,shared_out=self.out))
        self.evidence_out=self.out/('wsl_pipe_supervisor_'+uuid.uuid4().hex);self.evidence_out.mkdir()
        self.stderr=(self.evidence_out/'supervisor_stderr.log').open('wb')
        command=['wsl.exe','-d',self.distribution,'--cd',mapping(self.repo_root),'--','/usr/bin/python3',
            '-m','rm_match.integrations.wsl_operator_pipe_worker','--spec',mapping(self.spec_path),
            '--spec-sha256',self.checked.linux_spec_sha256,'--out',mapping(self.evidence_out),
            '--fov-degrees',str(self.fov['fov_degrees']),'--radius-x',str(self.fov['circle_radius_x_norm']),
            '--radius-y',str(self.fov['circle_radius_y_norm']),'--startup-timeout',str(self.startup_timeout),
            '--control-timeout',str(self.timeout)]
        self._record('startup_begin',transport=TRANSPORT,windows_native=False,command=command)
        try:
            self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr,
                bufsize=0,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            for method in (self._read,self._write):
                thread=threading.Thread(target=method,args=(self.process,),daemon=True);thread.start();self._threads.append(thread)
            reply=self._receive(time.perf_counter()+self.startup_timeout)
            if reply.get('event')!='ready' or reply.get('spec_sha256')!=self.checked.linux_spec_sha256 or reply.get('transport')!=TRANSPORT or reply.get('tmpfs_mode')!='0o700':
                raise RuntimeError('invalid binary WSL startup identity')
            self.ready=reply;self._record('startup_ready',transport=TRANSPORT,native_pid=reply['native_pid'],tmpfs_directory=reply['tmpfs_directory'])
        except BaseException:self.request_stop();self.close();raise

    def _write(self,child):
        try:
            while not self._stop.is_set():
                try:parts=self._outgoing.get(timeout=.02)
                except queue.Empty:continue
                header,payload=parts
                if type(header) is not bytes or len(header)>MAX_LINE or type(payload) is not bytes or len(payload)!=IMAGE_BYTES:
                    raise ValueError('Invalid bounded binary write transaction')
                # Assemble only on this owned I/O thread. One WriteFile releases
                # the GIL for the whole pipe transfer rather than reacquiring it
                # 72 times between 64KiB chunks under 500Hz authority work.
                frame=header+payload;view=memoryview(frame)
                while view:
                    if self._stop.is_set():return
                    count=child.stdin.write(view)
                    if not count:raise BrokenPipeError('WSL binary write failed')
                    view=view[count:]
        except Exception:self._broken.set();self.request_stop()

    def control(self,packet):
        if not self._transaction.acquire(blocking=False):raise RuntimeError('concurrent WSL transaction rejected')
        deadline=time.perf_counter()+self.timeout;started=time.perf_counter();phase='admission';phase_started=started
        stages={};recorded=False
        def next_phase(name):
            nonlocal phase,phase_started
            now=time.perf_counter();stages[phase+'_s']=now-phase_started;phase=name;phase_started=now
        def record(error=None):
            nonlocal recorded
            if recorded:return
            now=time.perf_counter();stages[phase+'_s']=now-phase_started;stages['total_s']=now-started
            self._record('control_prepare',transport=TRANSPORT,stages_s=stages.copy(),failed_phase=phase if error else None,
                error_type=type(error).__name__ if error else None,original_host_deadline=deadline,
                remaining_host_budget_s=deadline-now,clock_domain='host_perf_counter');recorded=True
        try:
            if self.ready is None or self.process is None or self._stop.is_set():raise RuntimeError('WSL bridge not ready')
            if 'host_deadline' in packet:
                authority=packet['host_deadline']
                if type(authority) not in (int,float) or not math.isfinite(authority):raise ValueError('invalid host authority deadline')
                deadline=min(deadline,authority)
            if time.perf_counter()>=deadline:raise TimeoutError('host authority deadline expired')
            next_phase('frame_copy');frame=copy.deepcopy(packet['frame']);image=frame['image']
            next_phase('sensor_validate');validate_sensor_frame(frame)
            if (image['encoding'],image['width'],image['height'],image['stride_bytes'],image['bytes'])!=('bgr8',1440,1080,4320,IMAGE_BYTES):raise ValueError('invalid BGR image envelope')
            if 'image_bytes' in packet:
                next_phase('private_image_admission');raw=packet['image_bytes']
                if type(raw) is not bytes or len(raw)!=IMAGE_BYTES:raise ValueError('Private image must be exact immutable BGR bytes')
                # This path labels a retained/optional artifact. Linux never
                # opens it: only the verified private byte snapshot is sent.
                if image['path']!=str(self.out/'sensor_input.bgr'):raise ValueError('Private image record path outside owned binding')
            else:
                next_phase('path_check');path=checked_host_path(Path(image['path']))
                if not path.is_relative_to(self.out):raise ValueError('image outside binding directory')
                next_phase('bgr_read')
                with path.open('rb') as stream:raw=stream.read(IMAGE_BYTES+1)
            if 'prepared_image' in packet:
                next_phase('prepared_bgr_admission')
                detached=dict(packet,frame=frame)
                if not prepared_native_bgr_matches(packet['prepared_image'],raw,detached):raise ValueError('prepared BGR source mismatch')
            else:
                next_phase('bgr_hash')
                if len(raw)!=IMAGE_BYTES or hashlib.sha256(raw).hexdigest()!=image['sha256']:raise ValueError('image SHA/size mismatch')
            next_phase('serialize');ns=packet['control_time_ns']
            if type(ns) is not int or ns<0:raise ValueError('invalid control clock')
            self._serial+=1;serial=self._serial
            request=dict(control_time_ns=ns,time_s=ns/1e9,frame=frame,operator_fov=self.fov)
            remaining=deadline-time.perf_counter()
            if remaining<=0:raise TimeoutError('host frame preparation expired')
            header=json.dumps(dict(event='control',id=serial,image_bytes=IMAGE_BYTES,timeout_s=min(remaining,self.timeout),packet=request),
                allow_nan=False,separators=(',',':')).encode()+b'\n'
            if len(header)>MAX_LINE:raise ValueError('oversize binary WSL header')
            if time.perf_counter()>=deadline:raise TimeoutError('host serialization deadline expired')
            record();self._record('native_request',transport=TRANSPORT,request_id=serial,control_time_ns=ns,image_sha256=image['sha256'])
            self._outgoing.put_nowait((header,raw))
            message=self._receive(deadline)
            if message.get('event')!='result' or message.get('id')!=serial:raise ValueError('WSL transaction identity mismatch')
            response=message['response']
            if response.get('status')!='ok' or response.get('runner_identity')!='rmcs-sim-operator-fov-v1' or response.get('clock_time_ns')!=ns or response.get('direction_frame')!='world' or type(response.get('tracking')) is not bool:
                raise ValueError('native identity/clock/output mismatch')
            if time.perf_counter()>deadline:raise TimeoutError('host result deadline expired')
            self._record('native_result',transport=TRANSPORT,request_id=serial,control_time_ns=ns,
                linux_stages_s=message.get('linux_stages_s'),linux_clock_domain=message.get('clock_domain'))
            return dict(response,episode=packet['episode'],should_control=response['tracking'])
        except BaseException as exc:record(exc);self.request_stop();raise
        finally:self._transaction.release()

    def close(self):
        super().close()
        if self.ready is not None and self.cleanup is not None and self.cleanup.get('tmpfs_removed') is not True:
            raise RuntimeError('owned Linux tmpfs cleanup not proved')
