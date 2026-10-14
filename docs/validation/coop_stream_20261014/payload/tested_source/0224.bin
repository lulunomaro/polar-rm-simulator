"""Local Windows manual-infantry launcher foundation; default is plan only.

PB navigation is prepared/registered, not a match decision tree or test goal.
No HTTP-selected executable, automatic binding, firing or algorithm fallback.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import signal
import sys
import threading
import time
import uuid
from .launcher import ROOT,check_client,client_patch_identity,clean_environment,executable,ReadyLines

SCHEMA='polar.sim.coop-launch.v1'
ROBOTS=tuple(team+'_'+role for team in ('red','blue') for role in ('hero','infantry','sentry'))
LIMITATIONS=['Launch foundation only; not playable 3v3 qualification',
    'PB Nav2 recovery/navigation BT is not patrol/resupply/combat match decision logic',
    'Full PB match BT, four automatic opponents/teammates, moving aim, firing arbitration and full match remain unimplemented']


def strict_json(raw):
    def pairs(rows):
        value={}
        for key,item in rows:
            if key in value:raise ValueError('Duplicate configuration key')
            value[key]=item
        return value
    def reject(_):raise ValueError('Nonfinite configuration')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=reject)


def read_local(path,limit=131072):
    path=Path(path).absolute()
    if path.is_symlink() or path.resolve()!=path or not path.is_file():raise ValueError('Plain absolute local file required')
    raw=path.read_bytes()
    if len(raw)>limit:raise ValueError('Local configuration oversized')
    value=strict_json(raw)
    return value,hashlib.sha256(raw).hexdigest()


def build_plan(config,*,out=None):
    if type(config) is not dict:raise ValueError('Local configuration object required')
    known={'schema','client_root','client_python','manual_robots','port','camera_total_fps','max_wall_seconds',
        'pb_wsl_navigation_manifest','wsl_native_spec','raw_base64_codec','host_opencv_threads',
        'host_python_switch_interval_ms','authority_affinity_mask'}
    if set(config)-known or config.get('schema')!=SCHEMA:raise ValueError('Unknown co-op configuration')
    manual=config.get('manual_robots',['red_infantry'])
    if type(manual) is not list or not manual or any(type(r) is not str or r not in ROBOTS for r in manual) or len(set(manual))!=len(manual):
        raise ValueError('Explicit local manual robot scope required')
    port=config.get('port',8766);fps=config.get('camera_total_fps',15.);duration=config.get('max_wall_seconds',600.)
    if type(port) is not int or not 1024<=port<=65535:raise ValueError('Invalid local port')
    for value,low,high in ((fps,0,15),(duration,0,3600)):
        if type(value) not in (int,float) or not math.isfinite(value) or not low<value<=high:raise ValueError('Invalid bounded FPS/duration')
    def path(value):
        if type(value) is not str or not value or '\x00' in value:raise ValueError('Local path string required')
        return str((ROOT/value).absolute())
    client_root=path(config['client_root']);client_python=path(config['client_python'])
    target=Path(out).absolute() if out else ROOT/'artifacts'/('coop-manual-'+uuid.uuid4().hex)
    if not target.is_relative_to(ROOT/'artifacts') or target.resolve()!=target:raise ValueError('Fresh owned output must be under repo/artifacts')
    core=[str(Path(sys.executable).absolute()),'-u','-m','rm_match.platform_v2','--camera','--port',str(port),
        '--camera-total-fps',str(fps),'--max-wall-seconds',str(duration),'--admission-manifest',str(target/'admission.json')]
    codec=config.get('raw_base64_codec','stdlib_chunked')
    if codec not in ('stdlib_chunked','pybase64_1_5_1'):raise ValueError('Unknown raw codec')
    core+=['--raw-base64-codec',codec]
    nav=config.get('pb_wsl_navigation_manifest');native=config.get('wsl_native_spec')
    if nav:core+=['--pb-wsl-navigation-manifest',path(nav)]
    if native:core+=['--wsl-native-spec',path(native),'--native-out',str(target/'native'),
        '--wsl-native-distribution','Ubuntu','--wsl-native-transport','wsl_async_bgr_v3','--private-native-pixels']
    from ..platform_v2.host_scheduling import switch_interval_ms,affinity_mask
    threads=config.get('host_opencv_threads')
    if threads is not None:
        if type(threads) is not int or not 1<=threads<=32:raise ValueError('Invalid host OpenCV threads')
        core+=['--host-opencv-threads',str(threads)]
    switch=config.get('host_python_switch_interval_ms')
    if switch is not None:core+=['--host-python-switch-interval-ms',str(switch_interval_ms(switch))]
    mask=config.get('authority_affinity_mask')
    if mask is not None:core+=['--authority-affinity-mask',hex(affinity_mask(mask))]
    server_data=dict(schema=SCHEMA,core_argv=core,url=f'http://127.0.0.1:{port}')
    server_sha=hashlib.sha256((json.dumps(server_data,allow_nan=False)+'\n').encode()).hexdigest()
    return dict(schema=SCHEMA,core_server_argv=core,
        server_argv=[core[0],'-u','-m','rm_match.deployment.coop_launcher','--worker-plan',str(target/'server-plan.json'),
            '--worker-plan-sha256',server_sha],
        client_argv=[client_python,str(Path(client_root)/'main.py'),'--sim-platform-v2','--sim-role','operator',
            '--sim-endpoint',f'http://127.0.0.1:{port}'],client_root=client_root,out=str(target),
        url=f'http://127.0.0.1:{port}',manual_robots=list(manual),robot_count=6,timestep_s=.002,
        max_wall_seconds=duration,startup_timeout_s=60.,cleanup_budget_s=8.,
        client_patch=client_patch_identity(),pb_navigation_registered=bool(nav),native_registered=bool(native),
        automatic_binding=False,automatic_goal=False,fire_authority='existing_manual_only',
        phase='PLAN_ONLY_NOT_READY',limitations=LIMITATIONS)


class _ReadyTap:
    def __init__(self,stream,ready,url):self.stream=stream;self.ready=ready;self.url=url;self.buffer=''
    def write(self,value):
        self.stream.write(value);self.stream.flush();self.buffer+=value
        if len(self.buffer)>65536:raise ValueError('Server stdout line oversized')
        while '\n' in self.buffer:
            line,self.buffer=self.buffer.split('\n',1)
            try:row=strict_json(line)
            except ValueError:continue
            if (type(row) is dict and row.get('transport')=='loopback_only'
                    and row.get('url')==self.url and row.get('camera')=='real_opt_in'):self.ready.set()
        return len(value)
    def flush(self):self.stream.flush()
    def __getattr__(self,name):return getattr(self.stream,name)


class CappedStderr:
    """Own the pipe reader; store at most 2MiB, then discard and fail launch."""
    def __init__(self,path):
        self.limit=2*1024*1024;self.overflow=False;self.error=None;self.written=0
        self.reader=self.writer=self.file=None;handles=[]
        try:
            read_fd,write_fd=os.pipe();handles.extend((read_fd,write_fd))
            self.reader=os.fdopen(read_fd,'rb',buffering=0);handles.remove(read_fd)
            self.writer=os.fdopen(write_fd,'wb',buffering=0);handles.remove(write_fd)
            self.file=Path(path).open('xb')
        except BaseException as original:
            errors=[]
            for stream in (self.reader,self.writer,self.file):
                if stream is not None:
                    try:stream.close()
                    except BaseException as exc:errors.append(type(exc).__name__)
            for handle in handles:
                try:os.close(handle)
                except BaseException as exc:errors.append(type(exc).__name__)
            if errors:raise RuntimeError('Stderr construction cleanup failed') from original
            raise
        def drain():
            try:
                while True:
                    raw=self.reader.read(65536)
                    if not raw:break
                    count=min(len(raw),self.limit-self.written)
                    if count:self.file.write(raw[:count]);self.written+=count
                    if count<len(raw):self.overflow=True
            except BaseException as exc:self.error=type(exc).__name__
            finally:
                for stream in (self.file,self.reader):
                    try:stream.close()
                    except BaseException as exc:
                        if self.error is None:self.error='close:'+type(exc).__name__
        self.thread=threading.Thread(target=drain,name='coop-capped-stderr',daemon=True)
        try:self.thread.start()
        except BaseException as original:
            errors=[]
            for stream in (self.writer,self.reader,self.file):
                try:stream.close()
                except BaseException as exc:errors.append(type(exc).__name__)
            if errors:raise RuntimeError('Stderr thread launch cleanup failed') from original
            raise
    def close_until(self,deadline):
        if not self.writer.closed:self.writer.close()
        self.thread.join(max(0.,deadline-time.perf_counter()))
        if self.thread.is_alive() or self.error or self.overflow:raise RuntimeError('Stderr stream incomplete or exceeded cap')


def read_stop(done):
    """Nonblocking reads on this owned Windows stdin pipe; no daemon read leak."""
    import ctypes
    import msvcrt
    from ctypes import wintypes
    api=ctypes.WinDLL('kernel32',use_last_error=True).PeekNamedPipe
    api.argtypes=[wintypes.HANDLE,wintypes.LPVOID,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),ctypes.POINTER(wintypes.DWORD)];api.restype=wintypes.BOOL
    handle=msvcrt.get_osfhandle(0);buffer=bytearray()
    while not done.is_set():
        available=wintypes.DWORD()
        if not api(handle,None,0,None,ctypes.byref(available),None):
            code=ctypes.get_last_error()
            if code in (109,232):return True  # Exact inherited pipe EOF cancels.
            raise ctypes.WinError(code)
        if available.value:
            part=os.read(0,min(available.value,1025-len(buffer)))
            if not part:return True
            buffer.extend(part)
            if len(buffer)>1024:raise ValueError('Local stop line oversized')
            if b'\n' in buffer:
                line,_,tail=buffer.partition(b'\n')
                if tail or strict_json(line)!={'op':'stop'}:raise ValueError('Invalid local stop command')
                return True
        done.wait(.02)
    return False


def worker(path,expected_sha):
    if sys.platform!='win32':raise ValueError('Owned co-op worker requires Windows')
    value,actual=read_local(path)
    if actual!=expected_sha or set(value)!={'schema','core_argv','url'} or value['schema']!=SCHEMA:raise ValueError('Server plan identity mismatch')
    argv=value['core_argv']
    if type(argv) is not list or argv[:4]!=[str(Path(sys.executable).absolute()),'-u','-m','rm_match.platform_v2']:
        raise ValueError('Only the local platform v2 entry is admitted')
    ready=threading.Event();stopped=threading.Event();errors=[]
    def control():
        request=False
        try:
            request=read_stop(stopped)
        except BaseException as exc:errors.append(type(exc).__name__);request=True
        finally:
            # Never raise the default SIGTERM during resource preparation. The
            # actual CLI installs its own handler before publishing readiness.
            while request and not ready.wait(.05):
                if stopped.is_set():return
            if request and not stopped.is_set():signal.raise_signal(signal.SIGTERM)
    thread=threading.Thread(target=control,daemon=True,name='coop-local-stop');thread.start()
    original=sys.stdout
    try:
        sys.stdout=_ReadyTap(original,ready,value['url'])
        from ..platform_v2.__main__ import main as platform_main
        platform_main(argv[4:])
        if errors:raise RuntimeError('Local stop protocol failed:'+errors[0])
    finally:
        stopped.set();sys.stdout=original
        thread.join(.5)
        if thread.is_alive():raise RuntimeError('Local stop thread unfinished')
    print(json.dumps(dict(event='coop_server_finished',url=value['url'],clean=True)),flush=True)
    return 0


def launch(plan):
    if sys.platform!='win32':raise ValueError('Explicit Windows host required')
    if os.environ.get('QT_QPA_PLATFORM','').lower() in ('offscreen','minimal','minimalegl'):raise ValueError('Visible Qt required for this launcher')
    from .windows_owned_job import WindowsOwnedJobProcess
    from .enrollment import provision_operator
    from ..platform_v2.admission import AdmissionPolicy
    executable(plan['core_server_argv'][0]);executable(plan['client_argv'][0])
    identity=check_client(plan['client_root'])
    if identity['client_patch']!=plan['client_patch']:raise ValueError('Client patch changed after plan')
    out=Path(plan['out']);out.mkdir(parents=True,exist_ok=False)
    credential=provision_operator(out/'admission.json',plan['manual_robots'])
    policy=AdmissionPolicy.from_manifest(out/'admission.json');policy.authenticate('operator',credential)
    server_data=dict(schema=SCHEMA,core_argv=plan['core_server_argv'],url=plan['url'])
    encoded=(json.dumps(server_data,allow_nan=False)+'\n').encode();(out/'server-plan.json').write_bytes(encoded)
    plan=dict(plan);plan['server_argv']=plan['server_argv'][:-1]+[hashlib.sha256(encoded).hexdigest()]
    (out/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    server=client=reader=qtreader=None;finished=False;result=dict(phase='STARTING',clean=False,game_ready=False)
    logs=[];server_attempted=False
    try:
        for name in ('server.stderr.log','client.stderr.log'):logs.append(CappedStderr(out/name))
        env=clean_environment();env['POLAR_USER_DATA_ROOT']=str(out/'client_user_data')
        senv=dict(env,MUJOCO_GL='glfw')
        server_attempted=True
        server=WindowsOwnedJobProcess(plan['server_argv'],cwd=ROOT,env=senv,stderr=logs[0].writer)
        logs[0].writer.close()
        reader=ReadyLines(server.stdout);deadline=time.perf_counter()+plan['startup_timeout_s']
        def next_row(timeout=.05):
            if reader.error is not None:raise RuntimeError('Server stdout failed')
            try:raw=reader.queue.get(timeout=timeout)
            except queue.Empty:return None
            try:row=strict_json(raw);return row if type(row) is dict else None
            except ValueError:return None
        while time.perf_counter()<deadline:
            if any(log.overflow or log.error for log in logs):raise RuntimeError('Stderr stream limit/error')
            row=next_row()
            if row and row.get('url')==plan['url'] and row.get('transport')=='loopback_only' and row.get('camera')=='real_opt_in':
                (out/'READY.json').write_text(json.dumps(row,indent=2)+'\n');break
            if server.poll() is not None:raise RuntimeError('Server exited before actual ready')
        else:raise TimeoutError('Server startup timeout')
        policy.verify_manifest_unchanged(out/'admission.json')
        if check_client(plan['client_root'])['client_patch']!=plan['client_patch']:raise ValueError('Client identity changed during startup')
        env['POLAR_SIM_ADMISSION_CREDENTIAL']=credential
        client=WindowsOwnedJobProcess(plan['client_argv'],cwd=plan['client_root'],env=env,stderr=logs[1].writer)
        logs[1].writer.close()
        qtreader=ReadyLines(client.stdout)
        print(json.dumps(dict(event='coop_client_started',manual_robots=plan['manual_robots'],out=str(out),
            game_ready=False,note='Select the granted infantry, claim/arm explicitly; no auto goal or fire')),flush=True)
        result['phase']='CLIENT_STARTED_NOT_GAME_QUALIFIED';deadline=time.perf_counter()+plan['max_wall_seconds']
        while server.poll() is None and client.poll() is None and time.perf_counter()<deadline:
            if any(log.overflow or log.error for log in logs):raise RuntimeError('Stderr stream limit/error')
            row=next_row()
            if row and row.get('event')=='coop_server_finished' and row.get('url')==plan['url']:
                finished=row.get('clean') is True
                if finished:(out/'SERVER_FINISHED.json').write_text(json.dumps(row)+'\n')
            if qtreader.error is not None:raise RuntimeError('Client stdout failed')
            # Drain bounded client lines; no SDK/credential bytes are echoed.
            while True:
                try:qtreader.queue.get_nowait()
                except queue.Empty:break
        result['reason']='client_closed' if client.poll() is not None else 'server_returned' if server.poll() is not None else 'wall_limit'
    except KeyboardInterrupt:result['reason']='user_interrupt'
    except BaseException as exc:
        result.update(reason='launch_failed',error_type=type(exc).__name__)
        if getattr(exc,'cleanup_status',None) is not None:result['launch_cleanup_status']=exc.cleanup_status
    finally:
        deadline=time.perf_counter()+plan['cleanup_budget_s'];failures=[]
        if server_attempted and server is None:failures.append('server_launch_cleanup_not_fully_confirmed')
        if result.get('launch_cleanup_status',{}).get('clean') is False:failures.append('failed_launch_cleanup_unproved')
        if server is not None and server.poll() is None:
            try:server.stdin.write(b'{"op":"stop"}\n');server.stdin.flush()
            except BaseException as exc:failures.append('cooperative_stop:'+type(exc).__name__)
        if server is not None:
            while server.poll() is None and time.perf_counter()<deadline-1.:
                if reader is None:break
                try:raw=reader.queue.get(timeout=.05);row=strict_json(raw)
                except queue.Empty:continue
                except ValueError:continue
                if type(row) is not dict:continue
                if row.get('event')=='coop_server_finished' and row.get('url')==plan['url']:
                    finished=row.get('clean') is True
                    if finished:(out/'SERVER_FINISHED.json').write_text(json.dumps(row)+'\n')
            if reader is not None:
                while True:
                    try:row=strict_json(reader.queue.get_nowait())
                    except queue.Empty:break
                    except ValueError:continue
                    if type(row) is not dict:continue
                    if row.get('event')=='coop_server_finished' and row.get('url')==plan['url']:
                        finished=row.get('clean') is True
                        if finished:(out/'SERVER_FINISHED.json').write_text(json.dumps(row)+'\n')
            if not finished:failures.append('server_or_linux_cleanup_ack_missing')
            result['server_returncode_before_job_cleanup']=server.poll()
            if finished and result['server_returncode_before_job_cleanup']!=0:failures.append('server_nonzero_or_not_returned_after_ack')
        for label,child,line_reader in (('client',client,qtreader),('server',server,reader)):
            if child is None:continue
            result[label+'_returncode_before_cleanup']=child.poll()
            if label=='client' and result[label+'_returncode_before_cleanup'] not in (None,0):failures.append('client_nonzero_returncode')
            try:
                proof=child.cleanup(deadline);result[label+'_ownership']=proof
                if not proof.get('clean') or not proof.get('reaped') or not proof.get('group_empty'):failures.append(label+'_owned_cleanup_unproved')
            except BaseException as exc:failures.append(label+'_cleanup:'+type(exc).__name__)
            for stream in (child.stdin,child.stdout):
                try:stream.close()
                except BaseException as exc:failures.append(label+'_pipe_close:'+type(exc).__name__)
            try:child.release_handles()
            except BaseException as exc:failures.append(label+'_handles:'+type(exc).__name__)
            if line_reader is not None:
                line_reader.thread.join(max(0,deadline-time.perf_counter()))
                if line_reader.thread.is_alive():failures.append(label+'_stdout_thread_unfinished')
        for log in logs:
            try:log.close_until(deadline)
            except BaseException as exc:failures.append('log_close:'+type(exc).__name__)
        result.update(clean=not failures,cleanup_errors=failures,server_clean_ack=finished)
        (out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2));return 0 if result['clean'] and result.get('reason')!='launch_failed' else 2


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--config',type=Path);p.add_argument('--out',type=Path);p.add_argument('--run',action='store_true')
    p.add_argument('--worker-plan',type=Path,help=argparse.SUPPRESS);p.add_argument('--worker-plan-sha256',help=argparse.SUPPRESS)
    a=p.parse_args(argv)
    if a.worker_plan:
        if not a.worker_plan_sha256 or a.config or a.run or a.out:p.error('Worker is a separate owned local invocation')
        return worker(a.worker_plan,a.worker_plan_sha256)
    if not a.config:p.error('--config is required')
    config,_=read_local(a.config);plan=build_plan(config,out=a.out)
    if a.run:return launch(plan)
    print(json.dumps(plan,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
