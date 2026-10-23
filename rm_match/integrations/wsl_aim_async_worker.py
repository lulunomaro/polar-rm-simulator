"""One real T2 compute at a time. Late stdout is evidence, never a new frame.

Linux local watchdogs bound resources. Original Windows authority deadlines are
opaque source metadata here; the host alone enforces capture80/SDK150 windows.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import select
import signal
import subprocess
import tempfile
import time
import uuid
from .wsl_operator_worker import MAX_LINE,MAX_IMAGE,_record,_stdin_wait,validate_linux_spec,validate_sensor_frame
from .wsl_operator_pipe_worker import _read_payload_into
from .owned_linux_group import LinuxOwnedProcessGroup,_stat

TRANSPORT='wsl_async_bgr_v3'
SCHEMA='polar.sim.wsl-async-aim.v1'
IDENTITY=('robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline')
WATCHDOG_S=1.0  # Resource hang bound; never an action/observation validity window.
MAX_EVENTS=4096
MAX_EVIDENCE_BYTES=8*1024*1024
OWNERSHIP_FIELDS=('run_id','supervisor_pid','pid','pgid','boot_id','leader_start_ticks','spec_sha256','transport')
READ_BATCH_LIMIT=16
READ_BATCH_WALL_S=.001


def _drain_payload(fd,payload,progress,*,deadline,clock=None):
    """Drain currently available bytes, yielding to the original supervisor.

    fd is already nonblocking. Never wait/spin for another fragment, extend the
    original transaction watchdog, read beyond the existing overflow byte, or
    let a continuously readable input starve stop/native-stdout processing.
    progress retains exact partial receipt counts even on EOF/overflow/fault.
    """
    if clock is None:clock=time.monotonic
    start=clock();progress['batches']+=1
    for attempt in range(READ_BATCH_LIMIT):
        now=clock()
        if now>=deadline:raise TimeoutError('async_input_transaction_watchdog')
        if attempt and now-start>=READ_BATCH_WALL_S:break
        progress['read_calls']+=1
        try:n=_read_payload_into(fd,payload,progress['received'])
        except BlockingIOError:
            progress['would_blocks']+=1;break
        if n==0:raise EOFError('async_partial_payload_eof')
        if n>len(payload)-progress['received']:
            progress['rejected_read_bytes']=progress.get('rejected_read_bytes',0)+n
            raise ValueError('async_extra_binary_bytes')
        progress['received']+=n;progress['bytes_read']+=n
        if progress['received']==len(payload):break
    return progress['received']


def input_source(header):
    f=header['packet']['frame']
    return dict(id=header['id'],source_context=copy.deepcopy(header['source_context']),frame_id=f['frame_id'],
        exposure_timestamp_ns=f['exposure_timestamp_ns'],control_time_ns=header['packet']['control_time_ns'],
        image_sha256=f['image']['sha256'],bgr_bytes=MAX_IMAGE)


def parse_json(raw):
    def pairs(rows):
        result={}
        for k,v in rows:
            if k in result:raise ValueError('async_duplicate_json_key')
            result[k]=v
        return result
    def bad(_):raise ValueError('async_nonfinite_json')
    def number(text):
        value=float(text)
        if not math.isfinite(value):raise ValueError('async_nonfinite_json')
        return value
    if len(raw)>MAX_LINE:raise ValueError('async_json_bound')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=bad,parse_float=number)


def same_identity(a,b):
    return type(a) is dict and type(b) is dict and set(a)==set(b) and all(type(a[k]) is type(b[k]) and a[k]==b[k] for k in a)


def validate_source_context(source):
    if type(source) is not dict or set(source)!=set(IDENTITY):raise ValueError('async_source_context_fields')
    if type(source['robot_id']) is not str or not 1<=len(source['robot_id'])<=128:raise ValueError('async_robot_identity')
    for k in ('episode','binding_epoch','observed_seq'):
        if type(source[k]) is not int or not 0<=source[k]<=2**53-1:raise ValueError('async_source_integer')
    for k in ('sim_time','wall_deadline'):
        if type(source[k]) not in (int,float) or not math.isfinite(source[k]) or not 0<=source[k]<=1e12:
            raise ValueError('async_source_clock')
    return copy.deepcopy(source)


def checked_header(value,fov,control_timeout=.08):
    fields={'schema','event','id','image_bytes','timeout_s','packet','source_context'}
    if (type(value) is not dict or set(value)!=fields or value['schema']!=SCHEMA or value['event']!='control'
        or type(value['id']) is not int or not 1<=value['id']<=2**53-1
        or type(value['image_bytes']) is not int or value['image_bytes']!=MAX_IMAGE):raise ValueError('async_header_fields')
    source=validate_source_context(value['source_context']);packet=value['packet']
    if type(packet) is not dict or set(packet)!={'control_time_ns','time_s','frame','operator_fov'} or not same_identity(packet['operator_fov'],fov):
        raise ValueError('async_native_packet')
    ns=packet['control_time_ns']
    if (type(ns) is not int or not 0<=ns<=2**63-1 or type(packet['time_s']) not in (int,float)
        or not math.isfinite(packet['time_s']) or packet['time_s']!=ns/1e9 or ns!=round(source['sim_time']*1e9)):
        raise ValueError('async_original_control_clock')
    frame=packet['frame'];validate_sensor_frame(frame)
    if (type(frame.get('episode')) is not int or frame['episode']!=source['episode']
        or type(frame.get('frame_id')) is not int or not 0<=frame['frame_id']<=2**53-1
        or type(frame.get('exposure_timestamp_ns')) is not int or not 0<=ns-frame['exposure_timestamp_ns']<=80000000
        or type(frame.get('capture_time_s')) not in (int,float) or not math.isfinite(frame['capture_time_s'])
        or round(frame['capture_time_s']*1e9)!=frame['exposure_timestamp_ns']):raise ValueError('async_original_capture_clock')
    image=frame['image']
    if (any(type(image[k]) is not int for k in ('width','height','stride_bytes','bytes'))
        or (image['encoding'],image['width'],image['height'],image['stride_bytes'],image['bytes'])!=('bgr8',1440,1080,4320,MAX_IMAGE)
        or type(image['sha256']) is not str or len(image['sha256'])!=64 or any(c not in '0123456789abcdef' for c in image['sha256'])):
        raise ValueError('async_actual_bgr_envelope')
    if type(image['path']) is not str or not 1<=len(image['path'])<=4096 or '\0' in image['path']:
        raise ValueError('async_image_record_path')
    budget=value['timeout_s']
    if type(budget) not in (int,float) or not math.isfinite(budget) or not 0<budget<=control_timeout:
        raise ValueError('async_local_input_budget')
    return copy.deepcopy(value)


def checked_response(response,header):
    if type(response) is not dict:raise ValueError('async_native_response_type')
    def finite_tree(value):
        if type(value) is float and not math.isfinite(value):raise ValueError('async_native_nonfinite')
        if type(value) is dict:
            for v in value.values():finite_tree(v)
        if type(value) is list:
            for v in value:finite_tree(v)
    finite_tree(response)
    packet=header['packet']
    if 'time_s' in response and (type(response['time_s']) not in (int,float)
        or not math.isfinite(response['time_s']) or response['time_s']!=packet['time_s']):
        raise ValueError('async_native_response_time')
    if (response.get('status')!='ok' or response.get('runner_identity')!='rmcs-sim-operator-fov-v1'
        or type(response.get('clock_time_ns')) is not int or response['clock_time_ns']!=packet['control_time_ns']
        or response.get('direction_frame')!='world' or type(response.get('tracking')) is not bool
        or response.get('detector_executed') is not True or response.get('frame_accepted') is not True
        or type(response.get('inference_calls')) is not int or response['inference_calls']<1):
        raise ValueError('async_native_response_identity_or_execution')
    for k in ('direction','robot_center'):
        values=response.get(k)
        # Original runner serializes an unavailable Point3d as [null,null,null].
        # That is no command only when tracking is explicitly false; a tracking
        # result must still provide three finite numbers. Never fill hold angles.
        unavailable=(response['tracking'] is False and type(values) is list
                     and len(values)==3 and all(v is None for v in values))
        if not unavailable and (type(values) is not list or len(values)!=3
            or any(type(v) not in (int,float) or not math.isfinite(v) for v in values)):
            raise ValueError('async_native_direction')
    return copy.deepcopy(response)


class NativeComputeSlot:
    """Pure lifecycle, with source metadata held until exactly one stdout line."""
    def __init__(self):
        self.current=None;self.generation=None;self.last_frame=-1;self.last_seq=-1;self.last_id=0;self.inferences=0
    def begin(self,header,now):
        if self.current is not None:raise ValueError('async_concurrent_native_compute')
        source=header['source_context'];frame=header['packet']['frame']
        generation=tuple(source[k] for k in ('robot_id','episode','binding_epoch'))
        if self.generation is not None and generation!=self.generation:raise ValueError('async_generation_changed')
        if header['id']<=self.last_id or frame['frame_id']<=self.last_frame or source['observed_seq']<=self.last_seq:
            raise ValueError('async_replayed_source')
        self.current=copy.deepcopy(header);self.started=now;self.generation=generation
        self.last_frame=frame['frame_id'];self.last_seq=source['observed_seq'];self.last_id=header['id']
    def source(self):
        h=self.current
        if h is None:raise ValueError('async_no_inflight_source')
        return input_source(h)
    def check_watchdog(self,now):
        if self.current is not None and now-self.started>=WATCHDOG_S:raise TimeoutError('async_native_compute_watchdog')
    def complete(self,response,now):
        if self.current is None:raise ValueError('async_unsolicited_stdout')
        self.check_watchdog(now);response=checked_response(response,self.current)
        if response['inference_calls']!=self.inferences+1:raise ValueError('async_native_inference_count')
        result=dict(event='result',schema=SCHEMA,transport=TRANSPORT,**self.source(),response=response,
            native_elapsed_linux_s=now-self.started,clock_domain='linux_local_diagnostic_only')
        self.inferences=response['inference_calls'];self.current=None
        return result


def supervise(command,out,fov,*,env=None,spec_sha=None,startup_timeout=15.,control_timeout=.08,
              startup_deadline=None,startup_guard=None,pre_native_exit=None):
    """Nonblocking child protocol. Tests may supply harmless children, not NN."""
    out=Path(out)
    if not out.is_dir():raise ValueError('async_fresh_output_missing')
    if any((out/name).exists() for name in ('OWNED_CHILD.json','STARTUP.json','CLEANUP.json','native_stderr.log')):
        raise ValueError('async_output_reuse')
    stopped=False;child=None;tmp=None;errorlog=None;owner=None;owned=None;reason='startup_failure';events=[];exit_code=0;attempted=False;evidence_bytes=0
    def stop(*_):
        nonlocal stopped
        stopped=True
    old={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    started=time.monotonic();limit=started+startup_timeout if startup_deadline is None else startup_deadline
    slot=NativeComputeSlot();header=bytearray();header_started=None;incoming=None;payload=None;received=0;payload_verified=False
    native_buffer=bytearray();writebuf=b'';written=0;expected=0;outputs=[];ready=False;next_stop=started;startup_error=None
    input_io=dict(profile='nonblocking_readv_batch16_1ms_v1',received=0,batches=0,read_calls=0,would_blocks=0,
        bytes_read=0,rejected_read_bytes=0,header_payload_bytes=0,images_verified=0,max_read_calls_per_batch=READ_BATCH_LIMIT,max_batch_wall_s=READ_BATCH_WALL_S)
    def journal(data):
        nonlocal evidence_bytes
        if len(events)>=MAX_EVENTS:raise ValueError('async_evidence_bound')
        size=len(json.dumps(data,allow_nan=False,separators=(',',':')).encode())
        if evidence_bytes+size>MAX_EVIDENCE_BYTES:raise ValueError('async_evidence_byte_bound')
        evidence_bytes+=size
        events.append(copy.deepcopy(data))
    def emit(data):
        raw=json.dumps(data,allow_nan=False,separators=(',',':')).encode()+b'\n'
        if len(raw)>MAX_LINE or len(outputs)>=2:raise ValueError('async_output_bound')
        outputs.append(raw);journal(data)
    try:
        owner=LinuxOwnedProcessGroup();tmp=tempfile.TemporaryDirectory(prefix='polar-aim-async-',dir='/dev/shm')
        os.chmod(tmp.name,0o700);(Path(tmp.name)/'tracking_mode').write_bytes(b'multi_ekf\n')
        errorlog=(out/'native_stderr.log').open('xb')
        if stopped or (out/'STOP').exists():raise InterruptedError('host_cancel_before_native_spawn')
        if startup_guard is not None:startup_guard()
        if time.monotonic()>=limit:raise TimeoutError('startup_timeout_before_native_spawn')
        attempted=True
        child=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errorlog,
            cwd=tmp.name,env=env,bufsize=0,start_new_session=True)
        owned=owner.attach(child)
        _record(out,'OWNED_CHILD.json',dict(owned,spec_sha256=spec_sha,transport=TRANSPORT,tmpfs_directory=tmp.name,tmpfs_mode='0o700'))
        for fd in (0,1,child.stdin.fileno(),child.stdout.fileno()):os.set_blocking(fd,False)
        while True:
            now=time.monotonic()
            if now>=next_stop:
                next_stop=now+.005
                if (out/'STOP').exists():stopped=True
            if stopped:reason='host_cancel';break
            if child.poll() is not None:raise RuntimeError('async_native_exit')
            if not ready:
                if now>=limit:raise TimeoutError('async_startup_timeout')
                wait=_stdin_wait(child.pid)
                if wait:
                    if time.monotonic()>=limit:raise TimeoutError('async_startup_timeout')
                    ready=True
                    data=dict(event='ready',schema=SCHEMA,transport=TRANSPORT,native_pid=child.pid,
                        run_id=owned['run_id'],supervisor_pid=owned['supervisor_pid'],spec_sha256=spec_sha,
                        readiness=wait,startup_elapsed_linux_s=now-started,tmpfs_directory=tmp.name,tmpfs_mode='0o700',
                        compute_watchdog_s=WATCHDOG_S,native_ticks=0,inference_calls=0,camera_captures=0,physics_steps=0)
                    _record(out,'STARTUP.json',data);emit(data)
                elif now>=limit:raise TimeoutError('async_startup_timeout')
            slot.check_watchdog(now)
            if header_started is not None and now-header_started>=WATCHDOG_S:raise TimeoutError('async_input_transaction_watchdog')
            writable=([child.stdin.fileno()] if writebuf else [])+([1] if outputs else [])
            readable,writable,_=select.select([0,child.stdout.fileno()],writable,[],.005)
            now=time.monotonic();slot.check_watchdog(now)
            if header_started is not None and now-header_started>=WATCHDOG_S:raise TimeoutError('async_input_transaction_watchdog')
            if child.stdin.fileno() in writable:
                try:count=os.write(child.stdin.fileno(),writebuf)
                except BlockingIOError:count=None
                if count is not None and (type(count) is not int or not 0<count<=len(writebuf)):raise EOFError('async_native_stdin_closed')
                if count is None:count=0
                written+=count;writebuf=writebuf[count:]
                if not writebuf:
                    emit(dict(event='native_started',schema=SCHEMA,transport=TRANSPORT,**slot.source(),
                        native_stdin_bytes_written=written,native_stdin_expected_bytes=expected,native_stdin_complete=True,
                        clock_domain='linux_local_diagnostic_only'))
            if 1 in writable:
                try:count=os.write(1,outputs[0])
                except BlockingIOError:count=None
                if count is not None and (type(count) is not int or not 0<count<=len(outputs[0])):raise EOFError('async_host_stdout_closed')
                if count is None:count=0
                outputs[0]=outputs[0][count:]
                if not outputs[0]:outputs.pop(0)
            for fd in readable:
                if fd==child.stdout.fileno():
                    try:chunk=os.read(fd,65536)
                    except BlockingIOError:continue
                    if not chunk:raise EOFError('async_native_stdout_eof')
                    native_buffer.extend(chunk)
                    if len(native_buffer)>MAX_LINE:raise ValueError('async_native_stdout_bound')
                    if b'\n' in native_buffer:
                        line,_,tail=native_buffer.partition(b'\n')
                        try:
                            if tail or writebuf or slot.current is None:raise ValueError('async_unsolicited_or_multiple_stdout')
                            completed=slot.complete(parse_json(line),time.monotonic())
                        except Exception:
                            # Keep bounded original bytes even when validation
                            # fails before emit/journal; these are never a result.
                            rejected=bytes(native_buffer)
                            (out/'REJECTED_NATIVE_STDOUT.bin').write_bytes(rejected)
                            _record(out,'REJECTED_NATIVE_STDOUT.json',dict(
                                schema=SCHEMA,event='rejected_native_stdout',
                                bytes=len(rejected),sha256=hashlib.sha256(rejected).hexdigest(),
                                path='REJECTED_NATIVE_STDOUT.bin',
                                inflight=None if slot.current is None else slot.source()))
                            raise
                        (Path(tmp.name)/('sensor_'+str(completed['id'])+'.bgr')).unlink()
                        emit(completed);native_buffer.clear()
                    continue
                if payload is not None:
                    try:_drain_payload(0,payload,input_io,deadline=header_started+WATCHDOG_S)
                    finally:received=input_io['received']
                else:
                    try:chunk=os.read(0,65536)
                    except BlockingIOError:continue
                    if not chunk:
                        if header or incoming is not None:raise EOFError('async_partial_header_eof')
                        reason='host_eof';return 0
                    if slot.current is not None:raise ValueError('async_concurrent_host_transaction')
                    if not ready:raise ValueError('async_input_before_ready')
                    if header_started is None:header_started=time.monotonic()
                    newline=chunk.find(b'\n')
                    if newline<0:
                        header.extend(chunk)
                        if len(header)>MAX_LINE:raise ValueError('async_header_bound')
                        continue
                    header.extend(chunk[:newline])
                    incoming=checked_header(parse_json(header),fov,control_timeout);header.clear()
                    payload=bytearray(MAX_IMAGE);received=len(chunk)-newline-1;payload_verified=False
                    if received>MAX_IMAGE:raise ValueError('async_extra_binary_bytes')
                    payload[:received]=chunk[newline+1:]
                    input_io['received']=received;input_io['header_payload_bytes']+=received
                    journal(dict(event='input_header_received',schema=SCHEMA,transport=TRANSPORT,**input_source(incoming),
                        header_validated=True,received_bgr_bytes=received,clock_domain='linux_local_diagnostic_only'))
                if received!=MAX_IMAGE:continue
                sha=hashlib.sha256(payload).hexdigest()
                if sha!=incoming['packet']['frame']['image']['sha256']:raise ValueError('async_payload_sha_mismatch')
                payload_verified=True
                input_io['images_verified']+=1
                if stopped or (out/'STOP').exists():reason='host_cancel';break
                if time.monotonic()>=header_started+incoming['timeout_s']:
                    f=incoming['packet']['frame']
                    emit(dict(event='discarded_before_native',schema=SCHEMA,transport=TRANSPORT,id=incoming['id'],
                        source_context=incoming['source_context'],frame_id=f['frame_id'],exposure_timestamp_ns=f['exposure_timestamp_ns'],
                        control_time_ns=incoming['packet']['control_time_ns'],image_sha256=sha,bgr_bytes=received,
                        reason='linux_input_transaction_expired',clock_domain='linux_local_diagnostic_only'))
                else:
                    image_path=Path(tmp.name)/('sensor_'+str(incoming['id'])+'.bgr')
                    with image_path.open('xb') as stream:
                        if stream.write(payload)!=MAX_IMAGE:raise OSError('async_tmpfs_short_write')
                    if time.monotonic()>=header_started+incoming['timeout_s']:
                        image_path.unlink()
                        f=incoming['packet']['frame']
                        emit(dict(event='discarded_before_native',schema=SCHEMA,transport=TRANSPORT,id=incoming['id'],
                            source_context=incoming['source_context'],frame_id=f['frame_id'],exposure_timestamp_ns=f['exposure_timestamp_ns'],
                            control_time_ns=incoming['packet']['control_time_ns'],image_sha256=sha,bgr_bytes=received,
                            reason='linux_input_save_expired',clock_domain='linux_local_diagnostic_only'))
                    else:
                        slot.begin(incoming,time.monotonic())
                        # Only the private image path changes; all original source
                        # fields and fixed native control time remain unchanged.
                        request=copy.deepcopy(incoming['packet']);request['frame']['image']['path']=str(image_path)
                        writebuf=json.dumps(request,allow_nan=False,separators=(',',':')).encode()+b'\n'
                        if len(writebuf)>MAX_LINE:raise ValueError('async_native_header_bound')
                        written=0;expected=len(writebuf)
                payload=None;incoming=None;received=0;header_started=None;payload_verified=False
    except Exception as error:
        exit_code=2;reason='host_cancel' if isinstance(error,InterruptedError) else 'resource_or_protocol_fault'
        if child is None:startup_error=error
        data=dict(event='error',schema=SCHEMA,transport=TRANSPORT,reason=reason,error_type=type(error).__name__,error=str(error),
            inflight=None if slot.current is None else slot.source(),received_bgr_bytes=received,
            native_stdin_bytes_written=written,native_stdin_expected_bytes=expected,
            native_stdout_buffer_bytes=len(native_buffer),clock_domain='linux_local_diagnostic_only')
        _record(out,'SUPERVISOR_ERROR.json',data)
        try:journal(data)
        except ValueError:pass
        return exit_code
    finally:
        cleanup=None;errors=[];tmp_path=None if tmp is None else tmp.name
        try:_record(out,'INPUT_IO.json',dict(schema='polar.wsl.async.input-io.v1',**input_io,
            scope='Local receive diagnostics only; images_verified is original SHA verification, never NN/action proof'))
        except Exception as error:errors.append('input_io_evidence:'+type(error).__name__)
        if child is not None:
            try:cleanup=owner.cleanup()
            except Exception as error:errors.append('owned_cleanup:'+type(error).__name__)
            for stream in (child.stdin,child.stdout):
                try:stream.close()
                except Exception as error:errors.append('pipe_close:'+type(error).__name__)
        if tmp is not None:
            try:tmp.cleanup()
            except Exception as error:errors.append('tmpfs_close:'+type(error).__name__)
        if errorlog is not None:
            try:errorlog.close()
            except Exception as error:errors.append('stderr_close:'+type(error).__name__)
        ownership=None if owned is None else {**owned,'spec_sha256':spec_sha,'transport':TRANSPORT}
        if slot.current is not None:
            try:journal(dict(event='native_cancelled',schema=SCHEMA,transport=TRANSPORT,**slot.source(),reason=reason,
                native_stdin_bytes_written=written,native_stdin_expected_bytes=expected,
                native_stdout_buffer_bytes=len(native_buffer),ownership=ownership,clock_domain='linux_local_diagnostic_only'))
            except Exception as error:errors.append('cancel_evidence:'+type(error).__name__)
        elif incoming is not None and reason in ('host_cancel','host_eof'):
            try:journal(dict(event='input_cancelled',schema=SCHEMA,transport=TRANSPORT,**input_source(incoming),reason=reason,
                phase='validated_payload' if payload_verified else 'receiving_payload',header_validated=True,
                received_bgr_bytes=received,payload_sha256_verified=payload_verified,
                verified_image_sha256=incoming['packet']['frame']['image']['sha256'] if payload_verified else None,
                native_stdin_bytes_written=0,native_compute_started=False,ownership=ownership,
                clock_domain='linux_local_diagnostic_only'))
            except Exception as error:errors.append('input_cancel_evidence:'+type(error).__name__)
        try:_record(out,'NATIVE_EVENTS.json',dict(schema=SCHEMA,transport=TRANSPORT,events=events,
            inflight_at_close=None if slot.current is None else slot.source(),
            input_at_close=None if incoming is None and not header else dict(header_validated=incoming is not None,
                header_bytes=len(header),received_bgr_bytes=received,payload_sha256_verified=payload_verified),
            ownership=ownership,clock_domain='linux_local_diagnostic_only'))
        except Exception as error:errors.append('evidence_write:'+type(error).__name__)
        if child is not None:
            result=dict(cleanup or {},transport=TRANSPORT,spec_sha256=spec_sha,reason=reason,tmpfs_directory=tmp_path,
                tmpfs_removed=tmp_path is not None and not Path(tmp_path).exists(),clock_domain='linux_local_diagnostic_only')
            result['errors']=list(result.get('errors',[]))+errors
            result['clean']=result.get('clean') is True and not result['errors'] and result['tmpfs_removed']
            _record(out,'CLEANUP.json',result)
        elif startup_error is not None and pre_native_exit is not None and not attempted and not errors:
            pre_native_exit(startup_error,'before_native_spawn',tmp_path,tmp_path is None or not Path(tmp_path).exists())
        elif child is None and (attempted or errors):
            _record(out,'SPAWN_OR_CLEANUP_UNPROVED.json',dict(transport=TRANSPORT,clean=False,
                native_spawn_attempted=attempted,errors=errors,reason=reason))
        for s,handler in old.items():signal.signal(s,handler)


def prepare_and_supervise(spec_path,spec_sha,out,fov,*,startup_timeout=15.,control_timeout=.08):
    out=Path(out)
    if out.exists():
        # The host opens its own launcher stderr before starting this worker.
        # No prior Linux startup/native/proof/input file may be reused.
        if not out.is_dir() or any(p.name!='supervisor_stderr.log' or p.is_symlink() or not p.is_file() for p in out.iterdir()):
            raise ValueError('async_fresh_output_required')
    else:out.mkdir(parents=True)
    started=time.monotonic();stopped=False
    supervisor_entered=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    old={s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
    identity=dict(run_id=uuid.uuid4().hex,supervisor_pid=os.getpid(),supervisor_start_ticks=_stat(os.getpid())['start_ticks'],
        boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),transport=TRANSPORT,spec_sha256=spec_sha)
    _record(out,'WORKER_STARTUP.json',dict(identity,native_spawn_attempted=False,clock_domain='linux_local_diagnostic_only'))
    def guard():
        if stopped or (out/'STOP').exists():raise InterruptedError('host_cancel_before_native_spawn')
        if time.monotonic()>=started+startup_timeout:raise TimeoutError('startup_timeout_before_native_spawn')
    def pre_exit(error,stage,tmp=None,removed=True):
        _record(out,'PRE_NATIVE_EXIT.json',dict(identity,native_spawn_attempted=False,native_child_reaped=False,
            tmpfs_directory=tmp,tmpfs_removed=removed,reason='host_cancel' if isinstance(error,InterruptedError) else ('startup_timeout' if isinstance(error,TimeoutError) else 'validation_failed'),
            failed_phase=stage,error_type=type(error).__name__,error=str(error),clean=removed,errors=[] if removed else ['tmpfs_not_removed']))
    try:
        guard();spec,sha=validate_linux_spec(spec_path,spec_sha);guard()
        env=dict(os.environ);env.update(spec.get('environment',{}))
        env.update(AUTOAIM_CONFIG=spec['autoaim_config'],RMCS_HEADLESS_SHARE=spec['model_share'],ORT_DISABLE_TELEMETRY='1')
        supervisor_entered=True
        return supervise([spec['binary'],spec['executor_yaml']],out,fov,env=env,spec_sha=sha,startup_timeout=startup_timeout,
            control_timeout=control_timeout,startup_deadline=started+startup_timeout,startup_guard=guard,pre_native_exit=pre_exit)
    except Exception as error:
        if not supervisor_entered:pre_exit(error,'validation')
        else:
            # An exception while writing final evidence cannot prove no spawn.
            _record(out,'SPAWN_OR_CLEANUP_UNPROVED.json',dict(identity,clean=False,
                native_spawn_attempted='unknown_after_supervisor_entry',error_type=type(error).__name__,error=str(error)))
        return 0 if isinstance(error,InterruptedError) and not supervisor_entered else 2
    finally:
        for s,handler in old.items():signal.signal(s,handler)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec',type=Path,required=True);p.add_argument('--spec-sha256',required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--fov-degrees',type=float,required=True);p.add_argument('--radius-x',type=float,required=True);p.add_argument('--radius-y',type=float,required=True)
    p.add_argument('--startup-timeout',type=float,default=15.);p.add_argument('--control-timeout',type=float,default=.08)
    args=p.parse_args()
    if type(args.startup_timeout) not in (int,float) or not 0<args.startup_timeout<=60 or not 0<args.control_timeout<=.08:
        raise ValueError('async_invalid_resource_budgets')
    fov=dict(fov_degrees=args.fov_degrees,circle_radius_x_norm=args.radius_x,circle_radius_y_norm=args.radius_y)
    return prepare_and_supervise(args.spec,args.spec_sha256,args.out,fov,startup_timeout=args.startup_timeout,control_timeout=args.control_timeout)

if __name__=='__main__':raise SystemExit(main())
