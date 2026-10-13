import hashlib,json,subprocess,sys,time
from pathlib import Path
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1]
names=['tools/qa_pb_external_navigation_goal.py','tests/test_pb_external_navigation_goal.py']
def hashes():return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}
before=hashes();command=[sys.executable,'-m','pytest','tests/test_pb_external_navigation_goal.py','-q']
for name,expected in before.items():
    raw=(ROOT/name).read_bytes();assert hashlib.sha256(raw).hexdigest()==expected
    saved=OUT/'source'/name;saved.parent.mkdir(parents=True,exist_ok=True);saved.write_bytes(raw)
(OUT/'COMMAND.json').write_text(json.dumps(dict(command=command,source_before=before,
    qualification='Windows pure unit path/metadata checks, no ROS/WSL/NN/SIL',
    driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),indent=2))
started=time.perf_counter()
with (OUT/'stdout.log').open('xb') as stdout,(OUT/'stderr.log').open('xb') as stderr:
    process=subprocess.Popen(command,cwd=ROOT,stdout=stdout,stderr=stderr)
    try:code=process.wait(timeout=15.);timeout=False
    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5.);code=process.returncode;timeout=True
after=hashes()
record=dict(pid=process.pid,returncode=code,timed_out=timeout,elapsed_s=time.perf_counter()-started,
    owned_child_reaped=process.poll() is not None,source_before=before,source_after=after,source_unchanged=before==after,
    stdout_sha256=hashlib.sha256((OUT/'stdout.log').read_bytes()).hexdigest(),
    stderr_sha256=hashlib.sha256((OUT/'stderr.log').read_bytes()).hexdigest())
(OUT/'RESULT.json').write_text(json.dumps(record,indent=2));print(json.dumps(record))
raise SystemExit(0 if code==0 and not timeout and before==after else 2)
