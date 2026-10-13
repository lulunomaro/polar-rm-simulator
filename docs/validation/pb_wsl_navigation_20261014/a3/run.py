"""Persist original stdout/stderr and process evidence of pure Python read-only audits."""
import hashlib,json,shutil,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
SCRIPT=HERE/'audit.py'
source=SCRIPT.read_bytes()
for attempt in (3,4):
    out=ROOT/f'artifacts/pb-wsl-navigation-audit-20261014-0{attempt}'
    out.mkdir(exist_ok=True)
    if attempt==4:shutil.copyfile(SCRIPT,out/'audit.py')
    command=[sys.executable,str(out/'audit.py'),'--attempt',str(attempt)]
    with (out/'COMMAND.json').open('x',encoding='utf8') as handle:
        json.dump(dict(command=command,audit_script_sha256=hashlib.sha256(source).hexdigest(),
            driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            scope='pure Python read-only original artifact audit; no ROS/physics/NN'),handle,indent=2)
    started=time.perf_counter()
    with (out/'stdout.log').open('xb') as stdout,(out/'stderr.log').open('xb') as stderr:
        process=subprocess.Popen(command,cwd=ROOT,stdout=stdout,stderr=stderr)
        try:code=process.wait(timeout=30.);timeout=False
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5.);code=process.returncode;timeout=True
    with (out/'PROCESS_RESULT.json').open('x',encoding='utf8') as handle:
        json.dump(dict(pid=process.pid,returncode=code,timed_out=timeout,elapsed_s=time.perf_counter()-started,
            owned_child_reaped=process.poll() is not None,audit_script_unchanged=SCRIPT.read_bytes()==source,
            stdout_sha256=hashlib.sha256((out/'stdout.log').read_bytes()).hexdigest(),
            stderr_sha256=hashlib.sha256((out/'stderr.log').read_bytes()).hexdigest()),handle,indent=2)
    print(json.dumps(dict(attempt=attempt,returncode=code,timed_out=timeout)))
    if code!=0 or timeout:raise SystemExit(2)
