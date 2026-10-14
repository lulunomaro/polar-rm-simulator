"""Capture owned focused/real-live processes without hiding failed attempts."""
import argparse,hashlib,json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('mode',choices=['focused','live','linux']);p.add_argument('--attempt',type=int,default=1)
p.add_argument('--native-spec',default='artifacts/native-original-nav-checkpoint-build-20261013/operator_source.local.json');a=p.parse_args()
files=['rm_match/platform_v2/native_image.py','rm_match/platform_v2/native_adapter.py',
 'rm_match/platform_v2/wsl_native_adapter.py','rm_match/integrations/wsl_operator_pipe.py',
 'rm_match/integrations/test_wsl_operator_pipe.py','tests/test_prepared_native_bgr.py',
 'rm_match/integrations/wsl_operator.py','rm_match/integrations/wsl_operator_pipe_worker.py',
 'tools/smoke_wsl_native_live.py','tests/test_wsl_native_live_classification.py','tests/test_owned_wsl_cleanup.py']
def hashes():return {n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in files}
before=hashes()
if a.mode=='focused':
 out=ROOT/f'artifacts/prepared-bgr-focused-20261014-{a.attempt:02}'
 command=[str(ROOT/'.venv-sim/Scripts/python.exe'),'-m','pytest','-q','tests/test_prepared_native_bgr.py',
  'rm_match/platform_v2/test_native_image.py','rm_match/integrations/test_wsl_operator_pipe.py',
  'rm_match/platform_v2/test_native_early_pixels.py','rm_match/platform_v2/test_native_early_pixels_review.py',
  'tests/test_wsl_registry.py','tests/test_owned_wsl_cleanup.py','tests/test_wsl_native_live_classification.py',
  'rm_match/platform_v2/test_native_deferred_trace.py','--tb=short','--junitxml='+str(out/'pytest.xml')]
elif a.mode=='linux':
 out=ROOT/f'artifacts/prepared-bgr-linux-cleanup-20261014-{a.attempt:02}'
 command=['C:/Windows/System32/wsl.exe','-d','Ubuntu','--cd','/mnt/c/'+ROOT.as_posix()[3:],
  '--exec','/usr/bin/python3','-m','unittest','-v','tests.test_owned_wsl_cleanup']
else:
 out=ROOT/f'artifacts/prepared-bgr-live-driver-20261014-{a.attempt:02}'
 command=[str(ROOT/'.venv-sim/Scripts/python.exe'),str(ROOT/'tools/smoke_wsl_native_live.py'),'--run',
  '--native-transport','wsl_stdio_bgr_v2','--private-native-pixels','--raw-base64-codec','pybase64_1_5_1',
  '--linux-native-spec',str(ROOT/a.native_spec),
  '--client-root',str(ROOT/'external/polar-rm-client-state-review'),
  '--out',str(ROOT/f'artifacts/wsl-native-live-20261014-prepared-bgr-attempt{a.attempt}'),'--seconds','10']
out.mkdir();(out/'driver.py').write_bytes(Path(__file__).read_bytes())
for n in files:
 q=out/'source'/n;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes((ROOT/n).read_bytes())
(out/'COMMAND.json').write_bytes((json.dumps(dict(argv=command,cwd=str(ROOT),source_before=before,
 driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),indent=2)+'\n').encode())
with (out/'stdout.log').open('xb') as stdout,(out/'stderr.log').open('xb') as stderr:
 start=time.perf_counter();child=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,
  stdout=stdout,stderr=stderr,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
 (out/'PID.json').write_bytes((json.dumps(dict(pid=child.pid,driver_pid=os.getpid()))+'\n').encode())
 code=child.wait();result=dict(returncode=code,reaped=child.poll() is not None,elapsed_s=time.perf_counter()-start,
  source_before=before,source_after=hashes(),source_unchanged=before==hashes())
 (out/'PROCESS_RESULT.json').write_bytes((json.dumps(result,indent=2)+'\n').encode())
 print(json.dumps({k:v for k,v in result.items() if k not in ('source_before','source_after')}))
raise SystemExit(code)
