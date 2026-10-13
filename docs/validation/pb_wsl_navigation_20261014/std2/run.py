import hashlib,json,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
LINUX_ROOT='/mnt/c/Users/lulu/Desktop/claude/polarsimulation/polar-rm-simulator'
names=['tests/test_pb_wsl_navigation_stdio.py','rm_match/integrations/pb_wsl_navigation_worker.py']
def hashes():return {n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
before=hashes()
command=['C:/Windows/System32/wsl.exe','-d','Ubuntu-22.04','--cd',LINUX_ROOT,'--','env',
    'POLAR_TEST_WSL=1','POLAR_WSL_STDIO_ARTIFACTS='+LINUX_ROOT+'/artifacts/'+OUT.name,
    '/root/polar-humble-ext4-20261014-01/venv/bin/python','-m','unittest','tests.test_pb_wsl_navigation_stdio','-v']
(OUT/'COMMAND.json').write_text(json.dumps(dict(command=command,source_before=before,
    driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    qualification='actual Linux stdio fixture only: fake stack/transport/gate; no ROS/DDS/NN/GL/SIL'),indent=2))
started=time.perf_counter()
with (OUT/'stdout.log').open('wb') as stdout,(OUT/'stderr.log').open('wb') as stderr:
    child=subprocess.Popen(command,cwd=ROOT,stdout=stdout,stderr=stderr)
    try:code=child.wait(timeout=130.);timeout=False
    except subprocess.TimeoutExpired:
        child.kill();child.wait(timeout=10.);code=child.returncode;timeout=True
after=hashes()
(OUT/'RESULT.json').write_text(json.dumps(dict(returncode=code,elapsed_s=time.perf_counter()-started,
    timed_out=timeout,driver_reaped=child.poll() is not None,source_before=before,source_after=after,
    source_unchanged=before==after,qualification='harmless actual Linux protocol/cancel only; no navigation qualification'),indent=2))
print(json.dumps(dict(returncode=code,timed_out=timeout,source_unchanged=before==after)))
raise SystemExit(0 if code==0 and not timeout and before==after else 2)
