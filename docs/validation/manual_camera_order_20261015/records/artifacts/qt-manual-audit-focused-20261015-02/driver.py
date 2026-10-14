"""Captured owned original-manual receipt-audit tests; no actual GUI/physics."""
from pathlib import Path
import argparse,hashlib,json,os,sys,threading,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from rm_match.deployment.json_owned_process import OwnedJsonProcess
p=argparse.ArgumentParser();p.add_argument('--attempt',type=int,required=True);a=p.parse_args()
out=ROOT/f'artifacts/qt-manual-audit-focused-20261015-{a.attempt:02}';out.mkdir()
names=['tools/audit_qt_manual.py','tests/test_qt_manual_audit.py']
before={}
for name in names:
    raw=(ROOT/name).read_bytes();before[name]=hashlib.sha256(raw).hexdigest();target=out/'source'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
argv=[sys.executable,'-m','pytest','-q','tests/test_qt_manual_audit.py','--junitxml='+str(out/'pytest.xml')]
(out/'driver.py').write_bytes(Path(__file__).read_bytes());(out/'COMMAND.json').write_bytes((json.dumps(dict(argv=argv,source_before=before),indent=2)+'\n').encode())
started=time.perf_counter();stop=threading.Event();owner=reader=None;errors=[];code=proof=None
try:
    with (out/'stderr.log').open('xb') as err:
        owner=OwnedJsonProcess(argv,cwd=str(ROOT),env=dict(os.environ),stop_event=stop,stderr=err)
        def read():
            try:
                with (out/'stdout.log').open('xb') as stream:
                    count=0
                    while True:
                        raw=owner.child.stdout.read(65536)
                        if not raw:return
                        count+=len(raw)
                        if count>4*1024*1024:raise RuntimeError('log_limit')
                        stream.write(raw)
            except BaseException as exc:errors.append(type(exc).__name__)
        reader=threading.Thread(target=read);reader.start();code=owner.child.wait(timeout=60.)
finally:
    stop.set();deadline=time.perf_counter()+1.5
    if owner is not None:
        proof=owner.cleanup(deadline)
        if reader is not None:reader.join(max(0.,deadline-time.perf_counter()))
        owner.child.stdin.close();owner.child.stdout.close();owner.release_handles()
    after={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}
    result=dict(exit_code=code,elapsed_s=time.perf_counter()-started,cleanup=proof,errors=errors,reader_stopped=reader is None or not reader.is_alive(),source_before=before,source_after=after,source_unchanged=before==after)
    (out/'RESULT.json').write_bytes((json.dumps(result,indent=2)+'\n').encode())
print(json.dumps({k:v for k,v in result.items() if k not in ('source_before','source_after')}));raise SystemExit(0 if code==0 and proof and proof['clean'] and result['source_unchanged'] and result['reader_stopped'] and not errors else 2)
