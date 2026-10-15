"""Capture stop-before-wait protocol regressions; no team algorithm claim."""
from pathlib import Path
import hashlib,json,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/pb-pipeline-cleanup-focused-20261015-02';OUT.mkdir()
names=['rm_match/deployment/robotio_plugin.py','tests/test_robotio_plugin.py']
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
write=lambda n,v:(OUT/n).write_bytes((json.dumps(v,indent=2)+'\n').encode())
before={n:sha(ROOT/n) for n in names};write('SOURCE_BEFORE.json',before)
for name in names:
    target=OUT/'source'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/name).read_bytes())
command=[sys.executable,'-m','pytest',names[1],'-q','--tb=short','--junitxml='+str(OUT/'pytest.xml')]
write('COMMAND.json',dict(argv=command,scope=__doc__))
start=time.perf_counter()
with (OUT/'stdout.log').open('xb') as stdout,(OUT/'stderr.log').open('xb') as stderr:
    child=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
    code=child.wait()
after={n:sha(ROOT/n) for n in names};write('SOURCE_AFTER.json',after)
result=dict(passed=code==0 and before==after,returncode=code,reaped=child.poll() is not None,
    source_unchanged=before==after,elapsed_s=time.perf_counter()-start)
write('RESULT.json',result);print(json.dumps(result));raise SystemExit(0 if result['passed'] else 2)
