import hashlib,json,subprocess,sys,time
from pathlib import Path
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1]
names=['rm_match/platform_v2/server.py','tests/test_platform_http_rejection.py']
def hashes():return {n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
before=hashes()
for name,expected in before.items():
    raw=(ROOT/name).read_bytes();assert hashlib.sha256(raw).hexdigest()==expected
    dest=OUT/'focused_source'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
command=[sys.executable,'-m','pytest','tests/test_platform_http_rejection.py','rm_match/platform_v2/test_server.py',
    'rm_match/platform_v2/test_admission.py','rm_match/platform_v2/test_window_client.py','-q']
(OUT/'focused.COMMAND.json').write_text(json.dumps(dict(command=command,source_before=before,
    driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    qualification='real Windows loopback/fake backend HTTP tests; no ROS, WSL, actual physics/native'),indent=2))
started=time.perf_counter()
with (OUT/'focused.stdout.log').open('xb') as stdout,(OUT/'focused.stderr.log').open('xb') as stderr:
    child=subprocess.Popen(command,cwd=ROOT,stdout=stdout,stderr=stderr)
    try:code=child.wait(timeout=40.);timeout=False
    except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5.);code=child.returncode;timeout=True
after=hashes()
record=dict(pid=child.pid,returncode=code,timed_out=timeout,owned_child_reaped=child.poll() is not None,
    elapsed_s=time.perf_counter()-started,source_before=before,source_after=after,source_unchanged=before==after,
    stdout_sha256=hashlib.sha256((OUT/'focused.stdout.log').read_bytes()).hexdigest(),
    stderr_sha256=hashlib.sha256((OUT/'focused.stderr.log').read_bytes()).hexdigest())
(OUT/'focused.RESULT.json').write_text(json.dumps(record,indent=2));print(json.dumps(record))
raise SystemExit(0 if code==0 and not timeout and before==after else 2)
