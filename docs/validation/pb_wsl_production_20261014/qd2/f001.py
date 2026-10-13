"""Capture final frozen quality check process and actual raw output."""
import hashlib
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--attempt',type=int,default=1);args=p.parse_args()
if not 1<=args.attempt<=20:p.error('attempt 1..20 required')
out=ROOT/f'artifacts/pb-production-quality-driver-20261014-{args.attempt:02}';out.mkdir()
(out/'driver.py').write_bytes(Path(__file__).read_bytes())
command=[str(ROOT/'.venv-sim/Scripts/python.exe'),str(ROOT/'tools/check_project.py'),
 '--out',str(ROOT/f'artifacts/quality-20261014-wsl-production-frozen-{args.attempt:02}')]
(out/'COMMAND.json').write_text(json.dumps(dict(argv=command,cwd=str(ROOT),
 driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
 scope='frozen local quality; no camera/native realtime/match/hardware qualification'),indent=2)+'\n',encoding='utf8')
with (out/'stdout.log').open('xb') as stdout,(out/'stderr.log').open('xb') as stderr:
 started=time.perf_counter();child=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,
  stdout=stdout,stderr=stderr,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
 (out/'PID.json').write_text(json.dumps(dict(pid=child.pid,driver_pid=os.getpid()))+'\n',encoding='utf8')
 code=child.wait();result=dict(returncode=code,reaped=child.poll() is not None,elapsed_s=time.perf_counter()-started)
 (out/'PROCESS_RESULT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8');print(json.dumps(result))
raise SystemExit(code)
