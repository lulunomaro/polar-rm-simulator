"""Explicit async T2 BGR transport: one original compute, no late retagging.

Pending is a typed progress object, not a native NN result or an actuator hold.
The caller must turn it into the current observation's canonical aim status.
"""
from __future__ import annotations
import copy
from dataclasses import dataclass,replace
import hashlib
import json
import math
from pathlib import Path
import queue
import subprocess
import threading
import time
import uuid
from .wsl_operator_pipe import WslPipeOperatorProcess,IMAGE_BYTES,CHUNK
from .wsl_operator import checked_host_path,host_to_linux_path,MAX_LINE
from .wsl_aim_async_worker import TRANSPORT,SCHEMA,checked_header,checked_response,parse_json,same_identity,validate_source_context,WATCHDOG_S
from ..platform_v2.native_image import prepared_native_bgr_matches

RETURN_MARGIN_S=.005
MAX_HOST_EVENTS=4096


@dataclass(frozen=True)
class NativeAimPending:
    reason:str
    request_id:int|None
    submitted:bool
    # Immutable JSON metadata; contains no pixels, receipt/token or fake angle.
    source_context_json:bytes
    @property
    def source_context(self):return parse_json(self.source_context_json)


class WslAsyncAimProcess(WslPipeOperatorProcess):
    def __init__(self,*args,trace_event=None,**kwargs):
        if trace_event is not None and not callable(trace_event):raise ValueError('async_local_trace_callable_required')
        self._trace_event=trace_event;self._async_lock=threading.RLock();self._async_wake=threading.Event()
        self._inflight=None;self._fault=None;self._last_frame=-1;self._last_seq=-1;self._generation=None
        super().__init__(*args,**kwargs)
        from ..deployment.profile import digest
        metadata=copy.deepcopy(self.checked.metadata);identities=dict(self.checked._identities)
        for rel in ('rm_match/integrations/wsl_aim_async.py','rm_match/integrations/wsl_aim_async_worker.py'):
            selected=checked_host_path(self.repo_root/rel);sha=digest(selected)
            identities[str(selected)]=sha;metadata['transport_source_sha256'][rel]=sha
        metadata.update(transport=TRANSPORT,image_transport='exact_inline_bgr_one_original_async_compute',
            compute_watchdog_s=WATCHDOG_S,qualification='Explicit async progress; late stdout never action; live qualification requires actual samples')
        self.checked=replace(self.checked,metadata=metadata,_identities=identities);self.checked.verify_unchanged()

    def _record(self,event,**fields):
        row=dict(event=event,transport=TRANSPORT,wall_time=time.perf_counter(),wall_clock='host_perf_counter')
        row.update(fields)
        with self._async_lock:
            if len(self.diagnostics)>=MAX_HOST_EVENTS:raise ValueError('async_host_evidence_bound')
            self.diagnostics.append(row)
        if self._trace_event is not None:self._trace_event(copy.deepcopy(row))

    @property
    def busy(self):
        with self._async_lock:
            if self._fault is not None or self._broken.is_set():raise RuntimeError('async_bridge_fault:'+str(self._fault))
            return self._inflight is not None
    def is_busy(self):return self.busy

    def _source_fields(self,slot):
        h=slot['header'];f=h['packet']['frame'];s=h['source_context']
        return dict(request_id=h['id'],source_context=copy.deepcopy(s),**copy.deepcopy(s),frame_id=f['frame_id'],
            capture_sim_time=f['capture_time_s'],exposure_timestamp_ns=f['exposure_timestamp_ns'],
            control_time_ns=h['packet']['control_time_ns'],raw_bgr_sha256=f['image']['sha256'],bgr_bytes=IMAGE_BYTES)

    def _set_fault(self,error):
        with self._async_lock:
            if self._fault is None:
                self._fault=type(error).__name__+':'+str(error)
                fields={} if self._inflight is None else self._source_fields(self._inflight)
                try:self._record('async_native_fault',error=self._fault,**fields)
                except Exception:pass
        self._broken.set();self._async_wake.set();self.request_stop()

    def _handle_message(self,message):
        if type(message) is not dict:raise ValueError('async_supervisor_message')
        if message.get('event')=='ready':
            self._incoming.put_nowait(message);return
        if message.get('event')=='error':raise RuntimeError('async_supervisor_fault:'+str(message.get('error_type')))
        if message.get('schema')!=SCHEMA or message.get('transport')!=TRANSPORT:raise ValueError('async_supervisor_protocol')
        if message.get('clock_domain')!='linux_local_diagnostic_only':raise ValueError('async_linux_clock_domain')
        with self._async_lock:
            slot=self._inflight
            if slot is None:raise ValueError('async_unsolicited_transaction_reply')
            h=slot['header'];f=h['packet']['frame']
            if (type(message.get('id')) is not int or message['id']!=h['id']
                or not same_identity(message.get('source_context'),h['source_context'])
                or type(message.get('frame_id')) is not int or message['frame_id']!=f['frame_id']
                or type(message.get('exposure_timestamp_ns')) is not int or message['exposure_timestamp_ns']!=f['exposure_timestamp_ns']
                or type(message.get('control_time_ns')) is not int or message['control_time_ns']!=h['packet']['control_time_ns']
                or message.get('image_sha256')!=f['image']['sha256'] or type(message.get('bgr_bytes')) is not int or message['bgr_bytes']!=IMAGE_BYTES):
                raise ValueError('async_reply_original_source_mismatch')
            fields=self._source_fields(slot);event=message.get('event')
            if event=='native_started':
                if slot['started']:raise ValueError('async_duplicate_native_started')
                if (message.get('native_stdin_complete') is not True
                    or type(message.get('native_stdin_bytes_written')) is not int or message['native_stdin_bytes_written']<1
                    or type(message.get('native_stdin_expected_bytes')) is not int
                    or message['native_stdin_bytes_written']!=message['native_stdin_expected_bytes']):
                    raise ValueError('async_native_stdin_not_complete')
                slot['started']=True
                self._record('async_native_started',native_stdin_complete=True,
                    native_stdin_bytes_written=message['native_stdin_bytes_written'],native_stdin_expected_bytes=message['native_stdin_expected_bytes'],**fields)
            elif event=='result':
                if not slot['started'] or slot['terminal'] is not None:raise ValueError('async_result_without_native_started')
                elapsed=message.get('native_elapsed_linux_s')
                if type(elapsed) not in (int,float) or not math.isfinite(elapsed) or not 0<=elapsed<WATCHDOG_S:
                    raise ValueError('async_native_elapsed_bound')
                response=checked_response(message.get('response'),h)
                now=time.perf_counter();late=now>=slot['deadline']
                if slot['abandoned'] or late:
                    disposition='late_discard' if late else 'after_pending_discard'
                    self._record('async_'+disposition,response=response,original_host_deadline=slot['deadline'],
                        receive_host_age_s=now-slot['host_started'],linux_elapsed_s=message.get('native_elapsed_linux_s'),
                        linux_clock_domain=message.get('clock_domain'),**fields)
                    if slot['abandoned']:self._inflight=None
                    else:slot['terminal']=dict(kind='late_discard')
                else:
                    slot['terminal']=dict(kind='result',response=response)
                    self._record('async_native_stdout',response=response,original_host_deadline=slot['deadline'],
                        linux_elapsed_s=message.get('native_elapsed_linux_s'),linux_clock_domain=message.get('clock_domain'),**fields)
            elif event=='discarded_before_native':
                if slot['started'] or slot['terminal'] is not None:raise ValueError('async_invalid_precompute_discard')
                self._record('async_discarded_before_native',reason=message.get('reason'),**fields)
                if slot['abandoned']:self._inflight=None
                else:slot['terminal']=dict(kind='discarded_before_native')
            else:raise ValueError('async_unknown_supervisor_event')
        self._async_wake.set()

    def _read(self,child):
        buffer=bytearray()
        try:
            while True:
                chunk=child.stdout.read(CHUNK)
                if not chunk:raise EOFError('async_supervisor_stdout_eof')
                buffer.extend(chunk)
                while b'\n' in buffer:
                    line,_,tail=buffer.partition(b'\n');buffer=bytearray(tail)
                    self._handle_message(parse_json(line))
                if len(buffer)>MAX_LINE:raise ValueError('async_supervisor_stdout_bound')
        except Exception as error:
            if not self._stop.is_set():self._set_fault(error)

    def _write(self,child):
        try:
            while not self._stop.is_set():
                try:header,payload,deadline,serial=self._outgoing.get(timeout=.02)
                except queue.Empty:continue
                if type(header) is not bytes or len(header)>MAX_LINE or type(payload) is not bytes or len(payload)!=IMAGE_BYTES:
                    raise ValueError('async_invalid_binary_transaction')
                if time.perf_counter()>=deadline:
                    with self._async_lock:
                        slot=self._inflight
                        if slot is None or slot['header']['id']!=serial:raise ValueError('async_writer_identity')
                        self._record('async_discarded_before_write',**self._source_fields(slot))
                        if slot['abandoned']:self._inflight=None
                        else:slot['terminal']=dict(kind='discarded_before_native')
                    self._async_wake.set();continue
                # At most one bounded whole WriteFile. An ongoing transfer may
                # finish after the action deadline; it grants no new authority.
                view=memoryview(header+payload)
                while view:
                    if self._stop.is_set():return
                    count=child.stdin.write(view)
                    if type(count) is not int or not 0<count<=len(view):raise BrokenPipeError('async_binary_write_failed')
                    view=view[count:]
        except Exception as error:self._set_fault(error)

    def reset(self,message):
        if self._stop.is_set() or self.process is not None:raise RuntimeError('async_bridge_not_fresh')
        self.checked.verify_unchanged();(self.out/'tracking_mode').write_bytes(b'multi_ekf\n')
        mapping=lambda p:str(host_to_linux_path(p,repo_root=self.repo_root,shared_out=self.out))
        self.evidence_out=self.out/('wsl_async_supervisor_'+uuid.uuid4().hex);self.evidence_out.mkdir()
        self.stderr=(self.evidence_out/'supervisor_stderr.log').open('xb')
        command=['wsl.exe','-d',self.distribution,'--cd',mapping(self.repo_root),'--','/usr/bin/python3','-m',
            'rm_match.integrations.wsl_aim_async_worker','--spec',mapping(self.spec_path),'--spec-sha256',self.checked.linux_spec_sha256,
            '--out',mapping(self.evidence_out),'--fov-degrees',str(self.fov['fov_degrees']),
            '--radius-x',str(self.fov['circle_radius_x_norm']),'--radius-y',str(self.fov['circle_radius_y_norm']),
            '--startup-timeout',str(self.startup_timeout),'--control-timeout',str(self.timeout)]
        self._record('startup_begin',command=command,windows_native=False)
        try:
            self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr,
                bufsize=0,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            for method in (self._read,self._write):
                thread=threading.Thread(target=method,args=(self.process,),daemon=True);thread.start();self._threads.append(thread)
            reply=self._receive(time.perf_counter()+self.startup_timeout)
            if (reply.get('event')!='ready' or reply.get('schema')!=SCHEMA or reply.get('transport')!=TRANSPORT
                or reply.get('spec_sha256')!=self.checked.linux_spec_sha256 or reply.get('tmpfs_mode')!='0o700'
                or type(reply.get('compute_watchdog_s')) is not float or reply['compute_watchdog_s']!=WATCHDOG_S
                or any(type(reply.get(k)) is not int or reply[k]<=1 for k in ('native_pid','supervisor_pid'))
                or type(reply.get('run_id')) is not str or len(reply['run_id'])!=32
                or any(c not in '0123456789abcdef' for c in reply['run_id'])
                or type(reply.get('startup_elapsed_linux_s')) not in (int,float)
                or not math.isfinite(reply['startup_elapsed_linux_s']) or not 0<=reply['startup_elapsed_linux_s']<self.startup_timeout
                or any(type(reply.get(k)) is not int or reply[k]!=0 for k in ('native_ticks','inference_calls','camera_captures','physics_steps'))):
                raise RuntimeError('async_invalid_zero_tick_ready')
            self.ready=reply;self._record('startup_ready',native_pid=reply['native_pid'],compute_watchdog_s=WATCHDOG_S)
        except BaseException as error:
            self._record('startup_failed',error_type=type(error).__name__,error=str(error));self.request_stop();self.close();raise

    def _pending(self,source,reason,serial=None,submitted=False):
        return NativeAimPending(reason,serial,submitted,json.dumps(source,allow_nan=False,separators=(',',':')).encode())

    def control(self,packet,*,source_context=None):
        if not self._transaction.acquire(blocking=False):raise RuntimeError('async_concurrent_host_control')
        try:
            if type(packet) is not dict:raise ValueError('async_control_packet')
            packet=dict(packet);source=validate_source_context(source_context if source_context is not None else packet.get('source_context'))
            if self.ready is None or self.process is None or self._stop.is_set() or self._broken.is_set():raise RuntimeError('async_bridge_not_ready')
            if not same_identity({'wall_deadline':packet.get('host_deadline')},{'wall_deadline':source['wall_deadline']}):
                raise ValueError('async_original_authority_mismatch')
            host_started=time.perf_counter();deadline=min(host_started+self.timeout,source['wall_deadline'])
            if host_started>=deadline-RETURN_MARGIN_S:return self._pending(source,'original_deadline_no_budget')
            with self._async_lock:
                if self._fault is not None:raise RuntimeError(self._fault)
                if self._inflight is not None:return self._pending(source,'native_compute_inflight')
            frame=copy.deepcopy(packet['frame']);image=frame['image']
            if 'image_bytes' in packet:
                raw=packet['image_bytes']
                if type(raw) is not bytes or len(raw)!=IMAGE_BYTES or image['path']!=str(self.out/'sensor_input.bgr'):
                    raise ValueError('async_private_image_source')
            else:
                path=checked_host_path(Path(image['path']))
                if not path.is_relative_to(self.out):raise ValueError('async_image_outside_binding')
                with path.open('rb') as stream:raw=stream.read(IMAGE_BYTES+1)
            if 'prepared_image' in packet:
                if not prepared_native_bgr_matches(packet['prepared_image'],raw,dict(packet,frame=frame)):
                    raise ValueError('async_prepared_source_mismatch')
            elif len(raw)!=IMAGE_BYTES or hashlib.sha256(raw).hexdigest()!=image['sha256']:
                raise ValueError('async_image_sha_mismatch')
            ns=packet['control_time_ns'];remaining=deadline-time.perf_counter()
            if remaining<=RETURN_MARGIN_S:return self._pending(source,'original_deadline_no_budget')
            self._serial+=1;serial=self._serial
            header=checked_header(dict(schema=SCHEMA,event='control',id=serial,image_bytes=IMAGE_BYTES,
                timeout_s=min(remaining,self.timeout),packet=dict(control_time_ns=ns,time_s=ns/1e9,frame=frame,operator_fov=self.fov),
                source_context=source),self.fov,self.timeout)
            generation=tuple(source[k] for k in ('robot_id','episode','binding_epoch'))
            if (self._generation is not None and self._generation!=generation) or frame['frame_id']<=self._last_frame or source['observed_seq']<=self._last_seq:
                raise ValueError('async_replayed_or_foreign_generation')
            encoded=json.dumps(header,allow_nan=False,separators=(',',':')).encode()+b'\n'
            if len(encoded)>MAX_LINE:raise ValueError('async_binary_header_bound')
            with self._async_lock:
                self._inflight=dict(header=header,deadline=deadline,host_started=host_started,started=False,abandoned=False,terminal=None)
                self._generation=generation;self._last_frame=frame['frame_id'];self._last_seq=source['observed_seq']
                self._async_wake.clear();self._record('async_transport_request',original_host_deadline=deadline,**self._source_fields(self._inflight))
            self._outgoing.put_nowait((encoded,raw,deadline,serial))
            while True:
                with self._async_lock:
                    if self._fault is not None or self._broken.is_set():raise RuntimeError('async_compute_fault:'+str(self._fault))
                    slot=self._inflight
                    if slot is None:raise ValueError('async_original_transaction_missing')
                    if self._stop.is_set():
                        # An owned stop revokes this request; it is not a native
                        # failure or a completed inference. Keep the transaction
                        # for the independent Linux stdout/cancellation proof.
                        slot['abandoned']=True
                        self._record('async_control_cancelled',reason='owned_stop_requested',**self._source_fields(slot))
                        return self._pending(source,'owned_stop_requested',serial,slot['started'])
                    terminal=slot['terminal'];now=time.perf_counter()
                    if terminal is not None:
                        self._inflight=None
                        if terminal['kind']=='result' and now<deadline:
                            self._record('async_result_accepted80',original_host_deadline=deadline,response=terminal['response'],**self._source_fields(slot))
                            return dict(terminal['response'],episode=source['episode'],should_control=terminal['response']['tracking'])
                        if terminal['kind']=='result':self._record('async_late_discard',response=terminal['response'],**self._source_fields(slot))
                        return self._pending(source,'original_deadline_expired' if terminal['kind'] in ('result','late_discard') else 'discarded_before_native',serial,slot['started'])
                    if now>=deadline-RETURN_MARGIN_S:
                        slot['abandoned']=True;self._record('async_pending',original_host_deadline=deadline,**self._source_fields(slot))
                        return self._pending(source,'response_not_available_before_original_deadline',serial,slot['started'])
                    self._async_wake.clear()
                self._async_wake.wait(min(.005,max(0.,deadline-RETURN_MARGIN_S-time.perf_counter())))
        except BaseException as error:
            self._set_fault(error);raise
        finally:self._transaction.release()

    def _load_cleanup_proof(self):
        from ..deployment.profile import read_json_snapshot
        out=self.evidence_out
        if (out/'PRE_NATIVE_EXIT.json').is_file():
            if self.ready is not None or (out/'OWNED_CHILD.json').exists() or (out/'CLEANUP.json').exists():raise RuntimeError('async_ambiguous_pre_native_exit')
            proof,_=read_json_snapshot(out/'PRE_NATIVE_EXIT.json');start,_=read_json_snapshot(out/'WORKER_STARTUP.json')
            for key in ('run_id','supervisor_pid','supervisor_start_ticks','boot_id','spec_sha256','transport'):
                if type(proof.get(key)) is not type(start.get(key)) or proof.get(key)!=start.get(key):raise RuntimeError('async_pre_exit_ownership')
            if (type(proof.get('run_id')) is not str or len(proof['run_id'])!=32
                or any(c not in '0123456789abcdef' for c in proof['run_id'])
                or any(type(proof.get(k)) is not int or proof[k]<=0 for k in ('supervisor_pid','supervisor_start_ticks'))
                or type(proof.get('boot_id')) is not str or not proof['boot_id']
                or proof.get('reason') not in ('host_cancel','validation_failed','startup_timeout')):
                raise RuntimeError('async_pre_exit_identity_or_reason')
            if (proof.get('transport')!=TRANSPORT or proof.get('spec_sha256')!=self.checked.linux_spec_sha256
                or proof.get('native_spawn_attempted') is not False or proof.get('native_child_reaped') is not False
                or start.get('native_spawn_attempted') is not False
                or proof.get('tmpfs_removed') is not True or proof.get('clean') is not True or proof.get('errors')!=[]):
                raise RuntimeError('async_pre_exit_not_proved')
            self.cleanup=proof;return
        cleanup,_=read_json_snapshot(out/'CLEANUP.json');owned,_=read_json_snapshot(out/'OWNED_CHILD.json')
        for key in ('run_id','supervisor_pid','pid','pgid','boot_id','leader_start_ticks','spec_sha256','transport'):
            if key not in owned or type(cleanup.get(key)) is not type(owned[key]) or cleanup.get(key)!=owned[key]:raise RuntimeError('async_cleanup_ownership')
        if owned.get('transport')!=TRANSPORT or owned.get('spec_sha256')!=self.checked.linux_spec_sha256:raise RuntimeError('async_cleanup_spec')
        if self.ready is not None and any(type(self.ready.get(k)) is not type(owned[v]) or self.ready[k]!=owned[v]
            for k,v in (('run_id','run_id'),('supervisor_pid','supervisor_pid'),('native_pid','pid'),('transport','transport'))):
            raise RuntimeError('async_cleanup_startup_mismatch')
        if any(cleanup.get(k) is not True for k in ('clean','reaped','group_empty','tmpfs_removed')) or cleanup.get('remaining_members')!=[] or cleanup.get('errors')!=[]:
            raise RuntimeError('async_cleanup_not_proved')
        self.cleanup=cleanup
