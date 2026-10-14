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
import sys
import threading
import time
from .json_owned_process import OwnedJsonProcess
from .wsl_jsonl_owned_tree import WslJsonPeerTree
from .json_adapter import SCHEMA, MAX_REQUEST, MAX_RESPONSE
from ..integrations.owned_linux_group import _stat

PREFIX=b'@polar-wsl-jsonl:'

def strict_json(raw):
    def pairs(rows):
        out={}
        for key,value in rows:
            if key in out:raise ValueError('duplicate key')
            out[key]=value
        return out
    def reject(value):raise ValueError('nonfinite JSON')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=reject)

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
    def stopped():
        if stop.is_set():return True
        path=out/'STOP'
        if not path.exists():return False
        if path.is_symlink():raise ValueError('STOP link rejected')
        value=strict_json(path.read_bytes())
        if value!={'run_id':spec['run_id'],'spec_sha256':expected_sha}:raise ValueError('STOP run identity mismatch')
        return True
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
        if stopped():raise RuntimeError('cancel before peer spawn')
        env=dict(os.environ)
        for key in ('PYTHONPATH','PYTHONHOME'):env.pop(key,None)
        env.update(settings['process_env'])
        owned=OwnedJsonProcess(settings['command'],cwd=settings['cwd'],env=env,stop_event=stop,
            linux_owner_factory=WslJsonPeerTree)
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
                    view=memoryview(item)
                    while view:
                        size=owned.child.stdin.write(view)
                        if not size:raise BrokenPipeError('peer stdin closed')
                        view=view[size:]
                    owned.child.stdin.flush()
                    reply=owned.child.stdout.readline(MAX_RESPONSE+1)
                    if len(reply)>MAX_RESPONSE or not reply.endswith(b'\n'):raise ValueError('peer response oversized/partial')
                    value=strict_json(reply)
                    if type(value) is not dict or value.get('schema')!=SCHEMA or value.get('op') not in ('prepare','reset','act'):
                        raise ValueError('peer stdout is not canonical JSONL')
                    results.put_nowait(reply)
            except BaseException as exc:
                error=type(exc).__name__
                try:results.put_nowait(exc)
                except queue.Full:pass
                stop.set()
        thread=threading.Thread(target=io_loop,daemon=True,name='wsl-jsonl-peer-io');thread.start()
        os.set_blocking(0,False);buffer=bytearray();pending=False
        while not stopped():
            try:reply=results.get_nowait()
            except queue.Empty:reply=None
            if reply is not None:
                if isinstance(reply,BaseException):raise reply
                emit(reply,time.perf_counter()+.15);pending=False
            if owned.child.poll() is not None and not pending:break
            ready,_,_=select.select([0],[],[],.005)
            if ready:
                part=os.read(0,65536)
                if not part:break
                buffer.extend(part)
                if len(buffer)>MAX_REQUEST:raise ValueError('host request oversized')
                if b'\n' in buffer:
                    line,_,tail=buffer.partition(b'\n');buffer=bytearray(tail)
                    if pending or b'\n' in buffer:raise ValueError('concurrent host request rejected')
                    request=strict_json(line)
                    if type(request) is not dict or request.get('schema')!=SCHEMA or request.get('op') not in ('prepare','reset','act'):
                        raise ValueError('host JSONL operation rejected')
                    requests.put_nowait(bytes(line)+b'\n');pending=True
    except BaseException as exc:
        error=type(exc).__name__
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
        record=dict(event='cleanup',run_id=spec['run_id'],spec_sha256=expected_sha,
            hello=hello,ownership=proof,io_thread_stopped=io_stopped,
            clean=proof.get('clean') is True and io_stopped,error_type=error)
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
