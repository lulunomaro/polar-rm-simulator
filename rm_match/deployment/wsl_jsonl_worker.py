"""Owned Linux JSONL peer supervisor. HELLO proves ownership, not readiness.

Local configuration only; no shell, T2 identity substitution, sensor warmup or
foreign-clock arithmetic. The Windows caller remains the action authority.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import select
import math
import stat
import sys
import threading
import time
from .json_owned_process import OwnedJsonProcess
from .wsl_jsonl_owned_tree import WslJsonPeerTree
from .json_adapter import SCHEMA, MAX_REQUEST, MAX_RESPONSE
from ..integrations.owned_linux_group import _stat

PREFIX=b'@polar-wsl-jsonl:'
STOP_POLL_INTERVAL_S=.005
OPERATIONS=('prepare','reset','observe','act')

def strict_json(raw):
    def pairs(rows):
        out={}
        for key,value in rows:
            if key in out:raise ValueError('duplicate key')
            out[key]=value
        return out
    def reject(value):raise ValueError('nonfinite JSON')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=reject)

class StopTokenPoller:
    """Memory cancellation each loop; one local file check per 5 ms at most.

    The interval is a polling schedule, not a hard real-time OS guarantee. The
    pre-spawn call must be forced regardless of any preceding check.
    """
    def __init__(self,event,path,run_id,spec_sha256,*,clock=time.monotonic):
        self.event=event;self.path=path;self.run_id=run_id;self.sha=spec_sha256;self.clock=clock
        self.next_check=None;self.last_sample=None;self.checks=0;self.cost_s=0.
        self.cumulative=(0,0.);self.fault_kind=None
    def _fault(self,kind,message):
        self.fault_kind=kind;raise ValueError(message)
    def stopped(self,*,force=False):
        if self.event.is_set():return True
        started=self.clock()
        if type(started) not in (int,float) or not math.isfinite(started) or (self.last_sample is not None and started<self.last_sample):
            self._fault('clock_invalid','STOP local clock invalid/regressed')
        self.last_sample=started
        if not force and self.next_check is not None and started<self.next_check:
            return self.event.is_set()
        self.checks+=1;self.next_check=started+STOP_POLL_INTERVAL_S
        try:
            try:row=self.path.lstat()
            except FileNotFoundError:return self.event.is_set()
            if stat.S_ISLNK(row.st_mode):self._fault('link_rejected','STOP link rejected')
            if not stat.S_ISREG(row.st_mode):self._fault('nonregular_token','STOP regular token required')
            value=strict_json(self.path.read_bytes())
            if value!={'run_id':self.run_id,'spec_sha256':self.sha}:self._fault('identity_mismatch','STOP run identity mismatch')
            return True
        except BaseException:
            if self.fault_kind is None:self.fault_kind='file_check_error'
            raise
        finally:
            finished=self.clock()
            if type(finished) not in (int,float) or not math.isfinite(finished) or finished<started:
                self._fault('clock_invalid','STOP local clock invalid/regressed')
            self.last_sample=finished;self.cost_s+=finished-started
            # Immutable tuple replacement: ingress samples completed checks/cost
            # without waiting for the poll thread or its file call.
            self.cumulative=(self.checks,self.cost_s)


class OwnedStopPollThread:
    """One owned best-effort file poller, outside the large JSONL read loop."""
    def __init__(self,poller):
        self.poller=poller;self.error_type=None;self.started=False
        self.thread=threading.Thread(target=self._run,name='wsl-jsonl-stop-poll',daemon=True)
    def _run(self):
        try:
            while not self.poller.event.is_set():
                if self.poller.stopped():self.poller.event.set();break
                self.poller.event.wait(STOP_POLL_INTERVAL_S)
        except BaseException as exc:
            self.error_type=type(exc).__name__
            if self.poller.fault_kind is None:self.poller.fault_kind='thread_error'
            self.poller.event.set()
    def start(self):
        try:self.thread.start();self.started=True
        except BaseException as exc:
            self.error_type=type(exc).__name__;self.poller.fault_kind='thread_error';self.poller.event.set();raise
    def join_until(self,deadline):
        self.poller.event.set()
        if self.started:self.thread.join(max(0.,deadline-time.perf_counter()))
        return not self.thread.is_alive()


class RequestFramer:
    """Bounded buffer; scan each newly appended byte for LF only once."""
    def __init__(self,limit=MAX_REQUEST):
        self.buffer=bytearray();self.searched=0;self.limit=limit
    def feed(self,part,*,pending):
        if len(self.buffer)+len(part)>self.limit:raise ValueError('host request oversized')
        self.buffer.extend(part)
        newline=self.buffer.find(b'\n',self.searched)
        self.searched=len(self.buffer)
        if newline<0:return None
        tail=self.buffer[newline+1:]
        if pending or b'\n' in tail:raise ValueError('concurrent host request rejected')
        line=bytes(memoryview(self.buffer)[:newline]);self.buffer=tail;self.searched=len(tail)
        return line


def request_metrics(started,finished,first_stop,last_stop):
    return dict(first_read_wall=started,last_read_wall=finished,queued_wall=None,
        peer_write_completed_wall=None,response_received_wall=None,
        stop_checks_at_first_read=first_stop[0],stop_cost_at_first_read_s=first_stop[1],
        stop_checks_at_last_read=last_stop[0],stop_cost_at_last_read_s=last_stop[1])

def run(spec_path,expected_sha):
    raw=Path(spec_path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_sha:raise ValueError('local WSL configuration changed')
    spec=strict_json(raw)
    from .wsl_jsonl import validate_linux_settings
    settings=validate_linux_settings(spec['linux'])
    out=Path(spec_path).parent
    if out.is_symlink() or out.resolve()!=out.absolute():raise ValueError('shared output links rejected')
    for rel,sha in spec['source_sha256'].items():
        path=Path(__file__).resolve().parents[2]/rel
        if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('supervisor source changed')
    if not Path(settings['cwd']).is_dir() or not os.access(settings['command'][0],os.X_OK):
        raise ValueError('Linux local peer path unavailable')
    stop=threading.Event();owned=None;thread=None;error=None;proof=None;hello=None
    results=queue.Queue(1);requests=queue.Queue(1)
    poller=StopTokenPoller(stop,out/'STOP',spec['run_id'],expected_sha)
    stop_thread=OwnedStopPollThread(poller)
    metrics=dict(clock='linux_monotonic',input_chunks=0,input_bytes=0,complete_requests=0,
        last_request=dict(first_read_wall=None,last_read_wall=None,queued_wall=None,
            peer_write_completed_wall=None,response_received_wall=None,
            stop_checks_at_first_read=None,stop_cost_at_first_read_s=None,
            stop_checks_at_last_read=None,stop_cost_at_last_read_s=None))
    def emit(data,deadline):
        view=memoryview(data)
        while view:
            remaining=deadline-time.perf_counter()
            if remaining<=0:raise TimeoutError('supervisor stdout blocked')
            _,ready,_=select.select([], [1], [], min(.02,remaining))
            if ready:
                try:size=os.write(1,view)
                except BlockingIOError:continue
                view=view[size:]
    try:
        if poller.stopped(force=True):raise RuntimeError('cancel before peer spawn')
        env=dict(os.environ)
        for key in ('PYTHONPATH','PYTHONHOME'):env.pop(key,None)
        env.update(settings['process_env'])
        owned=OwnedJsonProcess(settings['command'],cwd=settings['cwd'],env=env,stop_event=stop,
            linux_owner_factory=WslJsonPeerTree,stderr=sys.stderr)
        stop_thread.start()
        row=_stat(os.getpid())
        hello=dict(event='hello',run_id=spec['run_id'],spec_sha256=expected_sha,
            worker_pid=os.getpid(),worker_start_ticks=row['start_ticks'],
            boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            peer_identity=dict(owned.owner.identity),algorithm_ready=False)
        os.set_blocking(1,False)
        emit(PREFIX+json.dumps(hello,separators=(',',':')).encode()+b'\n',time.perf_counter()+.5)
        def io_loop():
            nonlocal error
            try:
                while not stop.is_set():
                    try:item=requests.get(timeout=.02)
                    except queue.Empty:continue
                    raw,request_metrics=item;view=memoryview(raw)
                    while view:
                        size=owned.child.stdin.write(view)
                        if not size:raise BrokenPipeError('peer stdin closed')
                        view=view[size:]
                    owned.child.stdin.flush()
                    request_metrics['peer_write_completed_wall']=time.monotonic()
                    reply=owned.child.stdout.readline(MAX_RESPONSE+1)
                    if len(reply)>MAX_RESPONSE or not reply.endswith(b'\n'):raise ValueError('peer response oversized/partial')
                    request_metrics['response_received_wall']=time.monotonic()
                    value=strict_json(reply)
                    if type(value) is not dict or value.get('schema')!=SCHEMA or value.get('op') not in OPERATIONS:
                        raise ValueError('peer stdout is not canonical JSONL')
                    results.put_nowait(reply)
            except BaseException as exc:
                if error is None:error=type(exc).__name__
                try:results.put_nowait(exc)
                except queue.Full:pass
                stop.set()
        thread=threading.Thread(target=io_loop,daemon=True,name='wsl-jsonl-peer-io');thread.start()
        os.set_blocking(0,False);framer=RequestFramer();pending=False
        while not stop.is_set():
            try:reply=results.get_nowait()
            except queue.Empty:reply=None
            if reply is not None:
                if isinstance(reply,BaseException):raise reply
                if stop.is_set():break
                emit(reply,time.perf_counter()+.15);pending=False
            if owned.child.poll() is not None and not pending:break
            ready,_,_=select.select([0],[],[],.005)
            if ready:
                if stop.is_set():break
                read_started=time.monotonic()
                first_stop=poller.cumulative
                part=os.read(0,65536)
                if not part:break
                read_finished=time.monotonic()
                last_stop=poller.cumulative
                metrics['input_chunks']+=1;metrics['input_bytes']+=len(part)
                if not framer.buffer:
                    metrics['last_request']=request_metrics(read_started,read_finished,first_stop,last_stop)
                else:
                    metrics['last_request'].update(last_read_wall=read_finished,
                        stop_checks_at_last_read=last_stop[0],stop_cost_at_last_read_s=last_stop[1])
                line=framer.feed(part,pending=pending)
                if line is not None:
                    request=strict_json(line)
                    if type(request) is not dict or request.get('schema')!=SCHEMA or request.get('op') not in OPERATIONS:
                        raise ValueError('host JSONL operation rejected')
                    if stop.is_set():break
                    current_metrics=metrics['last_request'];current_metrics['queued_wall']=time.monotonic()
                    metrics['complete_requests']+=1
                    try:requests.put_nowait((line+b'\n',current_metrics))
                    except queue.Full:
                        current_metrics['queued_wall']=None
                        raise
                    pending=True
                    if framer.buffer:
                        # Tail starts in this actual read, not at a fabricated
                        # future request time; the IO job retains its own dict.
                        metrics['last_request']=request_metrics(read_started,read_finished,first_stop,last_stop)
    except BaseException as exc:
        if error is None:error=type(exc).__name__
        proof=getattr(exc,'cleanup_status',None)
    finally:
        stop.set();deadline=time.perf_counter()+1.3
        if owned is not None:
            try:proof=owned.cleanup(deadline)
            except Exception as exc:proof=dict(clean=False,group_empty=False,reaped=False,errors=[type(exc).__name__])
            for stream in (owned.child.stdin,owned.child.stdout):
                try:stream.close()
                except Exception as exc:
                    proof=dict(proof,clean=False,errors=list(proof.get('errors',[]))+['pipe_close:'+type(exc).__name__])
        if proof is None:proof=dict(clean=True,not_spawned=True,reaped=False,group_empty=True,errors=[])
        if thread is not None:thread.join(max(0,deadline-time.perf_counter()))
        io_stopped=thread is None or not thread.is_alive()
        stop_stopped=stop_thread.join_until(deadline)
        stop_error=stop_thread.error_type
        if stop_error is None and poller.fault_kind is not None:stop_error=error
        if error is None:
            error=stop_error if stop_error is not None else (None if stop_stopped else 'StopPollThreadUnfinished')
        # Fixed-key scalar dictionaries only; copying under the GIL retains a
        # bounded partial snapshot even when the IO thread could not be joined.
        # No additional mutex wait can extend the original cleanup budget.
        io_metrics=dict(metrics,last_request=dict(metrics['last_request']),
            stop_file_checks=poller.checks,stop_check_cost_s=poller.cost_s)
        record=dict(event='cleanup',run_id=spec['run_id'],spec_sha256=expected_sha,
            hello=hello,ownership=proof,io_thread_stopped=io_stopped,
            stop_poll_thread_started=stop_thread.started,stop_poll_thread_stopped=stop_stopped,
            stop_poll_error_type=stop_error,stop_poll_error_kind=poller.fault_kind,
            clean=proof.get('clean') is True and io_stopped and stop_stopped and stop_error is None,
            error_type=error,io_metrics=io_metrics)
        # Final evidence is independent of a blocked/broken stdout pipe.
        temporary=out/'CLEANUP.tmp'
        fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as stream:stream.write(json.dumps(record,separators=(',',':')))
        if (out/'CLEANUP.json').is_symlink():raise ValueError('cleanup output link rejected')
        temporary.replace(out/'CLEANUP.json')
    return 0 if record['clean'] else 2

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--spec',required=True);parser.add_argument('--sha256',required=True)
    args=parser.parse_args();return run(args.spec,args.sha256)
if __name__=='__main__':raise SystemExit(main())
