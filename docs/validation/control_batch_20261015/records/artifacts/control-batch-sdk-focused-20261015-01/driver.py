"""Captured owned SDK regression: synthetic clocks/actual loopback, no physics."""
from pathlib import Path
import argparse,hashlib,json,os,sys,threading,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from rm_match.deployment.json_owned_process import OwnedJsonProcess
p=argparse.ArgumentParser();p.add_argument('--attempt',type=int,required=True);a=p.parse_args()
out=ROOT/f'artifacts/control-batch-sdk-focused-20261015-{a.attempt:02}';out.mkdir()
names=['rm_match/platform_v2/client.py','rm_match/platform_v2/control.py','rm_match/platform_v2/server.py',
 'rm_match/platform_v2/runtime.py','tests/test_control_batch_client.py',
 'rm_match/platform_v2/test_window_client.py','rm_match/platform_v2/test_client.py']
before={}
for name in names:
    raw=(ROOT/name).read_bytes();before[name]=hashlib.sha256(raw).hexdigest()
    target=out/'source'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
argv=[sys.executable,'-m','pytest','-q','tests/test_control_batch_client.py',
 'rm_match/platform_v2/test_client.py','rm_match/platform_v2/test_window_client.py','--junitxml='+str(out/'pytest.xml')]
(out/'driver.py').write_bytes(Path(__file__).read_bytes())
(out/'COMMAND.json').write_bytes((json.dumps(dict(argv=argv,cwd=str(ROOT),source_before=before),indent=2)+'\n').encode())
env=dict(os.environ)
for key in tuple(env):
    if any(part in key.upper() for part in ('CREDENTIAL','TOKEN','SECRET','PASSWORD')):env.pop(key,None)
started=time.perf_counter();stop=threading.Event();owner=None;reader=None;errors=[];code=None;proof=None
try:
    with (out/'stderr.log').open('xb') as err:
        owner=OwnedJsonProcess(argv,cwd=str(ROOT),env=env,stop_event=stop,stderr=err)
        (out/'PID.json').write_bytes((json.dumps(dict(pid=owner.child.pid,driver_pid=os.getpid()))+'\n').encode())
        def read():
            try:
                total=0
                with (out/'stdout.log').open('xb') as log:
                    while True:
                        raw=owner.child.stdout.read(65536)
                        if not raw:return
                        total+=len(raw)
                        if total>16*1024*1024:raise RuntimeError('bounded_output')
                        log.write(raw)
            except BaseException as exc:errors.append(type(exc).__name__)
        reader=threading.Thread(target=read);reader.start();code=owner.child.wait(timeout=120.)
except BaseException as exc:errors.append(type(exc).__name__)
finally:
    stop.set();deadline=time.perf_counter()+1.5
    if owner is not None:
        proof=owner.cleanup(deadline)
        if reader is not None:reader.join(max(0.,deadline-time.perf_counter()))
        for stream in (owner.child.stdin,owner.child.stdout):stream.close()
        owner.release_handles()
    after={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}
    result=dict(exit_code=code,elapsed_s=time.perf_counter()-started,cleanup=proof,errors=errors,
        reader_stopped=reader is None or not reader.is_alive(),source_before=before,source_after=after,source_unchanged=before==after)
    (out/'RESULT.json').write_bytes((json.dumps(result,indent=2)+'\n').encode())
print(json.dumps({k:v for k,v in result.items() if k not in ('source_before','source_after')}))
raise SystemExit(0 if code==0 and proof and proof['clean'] and result['reader_stopped'] and result['source_unchanged'] and not errors else 2)
