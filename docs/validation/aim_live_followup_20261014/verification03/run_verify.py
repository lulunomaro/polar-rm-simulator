"""Actual independent package/original verification driver; no ROS/NN/physics."""
import hashlib,json,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
ARCHIVE=ROOT/'docs/validation/aim_live_followup_20261014'
OUT=ARCHIVE/'verification03';OUT.mkdir(exist_ok=False)
SCRIPT=ARCHIVE/'verify_archive.py'
before=hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
manifest_before=hashlib.sha256((ARCHIVE/'PRESERVATION_MANIFEST.json').read_bytes()).hexdigest()
(OUT/'run_verify.py').write_bytes(Path(__file__).read_bytes())
for label,extra in [('package',[]),('originals',['--check-originals','--repo-root',str(ROOT)])]:
    command=[sys.executable,str(SCRIPT),*extra]
    (OUT/(label+'.COMMAND.json')).write_text(json.dumps(dict(argv=command,cwd=str(ROOT)),indent=2)+'\n')
    start=time.perf_counter()
    with (OUT/(label+'.stdout.log')).open('wb') as stdout,(OUT/(label+'.stderr.log')).open('wb') as stderr:
        child=subprocess.Popen(command,cwd=ROOT,stdout=stdout,stderr=stderr)
        (OUT/(label+'.PID.json')).write_text(json.dumps({'pid':child.pid})+'\n')
        code=child.wait(timeout=300)
    result=dict(exit_code=code,elapsed_s=time.perf_counter()-start,reaped=child.poll() is not None,
        verifier_sha256_before=before,verifier_sha256_after=hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
        manifest_sha256_before=manifest_before,manifest_sha256_after=hashlib.sha256((ARCHIVE/'PRESERVATION_MANIFEST.json').read_bytes()).hexdigest())
    (OUT/(label+'.PROCESS_RESULT.json')).write_text(json.dumps(result,indent=2)+'\n')
    print(label+':'+json.dumps(result),flush=True)
    print((OUT/(label+'.stdout.log')).read_text(errors='replace'),flush=True)
    print((OUT/(label+'.stderr.log')).read_text(errors='replace'),flush=True)
    if code:raise SystemExit(code)

