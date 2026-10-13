"""Own and record this checkpoint's bounded child; no global process cleanup."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('mode',choices=['focused','actual']);args=p.parse_args()
names=['rm_match/integrations/pb_wsl_navigation.py','rm_match/integrations/pb_wsl_navigation_registry.py',
 'rm_match/integrations/pb_wsl_navigation_worker.py','tools/pb_navigation_stack.py','tools/qa_pb_wsl_navigation_sil.py',
 'tools/pb_external_goal_session.py','tools/pb_sil_duration.py','tools/qa_pb_external_goal_supervisor.py',
 'tools/qa_pb_external_navigation_goal.py','tools/qa_pb_wsl_production_sil.py']
tests=['tests/test_pb_external_goal_session.py','tests/test_pb_external_navigation_goal.py','tests/test_pb_sil_duration.py',
 'tests/test_pb_stack_shutdown_deadline.py','tests/test_pb_wsl_navigation_worker.py','tests/test_pb_wsl_navigation_session.py',
 'tests/test_pb_wsl_navigation_registry.py','tests/test_pb_wsl_navigation_stdio.py']
names+=tests
def hashes():return {n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
before=hashes()
if args.mode=='focused':
 out=ROOT/'artifacts/pb-production-focused-20261014-01'
 command=[str(ROOT/'.venv-sim/Scripts/python.exe'),'-m','pytest','-q',*tests,'--tb=short',
  '--junitxml='+str(out/'pytest.xml')]
else:
 out=ROOT/'artifacts/pb-wsl-production-driver-20261014-01'
 command=[str(ROOT/'.venv-sim/Scripts/python.exe'),str(ROOT/'tools/qa_pb_wsl_production_sil.py'),
  '--environment',str(ROOT/'artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json'),
  '--stack-config',str(ROOT/'artifacts/pb-navigation-sil-config-20261014-04.json'),
  '--out',str(ROOT/'artifacts/pb-wsl-production-sil-actual-20261014-attempt1'),'--seconds','30','--diagnostics','--run']
out.mkdir()
for n in names:
 target=out/'source'/n;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/n).read_bytes())
(out/'COMMAND.json').write_text(json.dumps(dict(argv=command,cwd=str(ROOT),source_before=before,
 driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),indent=2)+'\n',encoding='utf8')
with (out/'stdout.log').open('xb') as stdout,(out/'stderr.log').open('xb') as stderr:
 started=time.perf_counter()
 child=subprocess.Popen(command,cwd=ROOT,stdout=stdout,stderr=stderr,stdin=subprocess.DEVNULL,
  shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
 (out/'PID.json').write_text(json.dumps(dict(pid=child.pid,driver_pid=__import__('os').getpid()))+'\n',encoding='utf8')
 code=child.wait()
 after=hashes()
 result=dict(returncode=code,reaped=child.poll() is not None,elapsed_s=time.perf_counter()-started,
  source_unchanged=before==after,source_before=before,source_after=after)
 (out/'PROCESS_RESULT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
 print(json.dumps(dict(out=str(out),**{k:result[k] for k in ('returncode','reaped','elapsed_s','source_unchanged')})))
raise SystemExit(code)
