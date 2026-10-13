"""Capture actual independent archive verification output bytes."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
parser=argparse.ArgumentParser();parser.add_argument('--label',required=True);args=parser.parse_args()
if not re.fullmatch('[a-z][a-z0-9]{0,7}',args.label):raise ValueError('short receipt label required')
paths={name:HERE/(args.label+'.verify.'+name) for name in ('stdout.bin','stderr.bin','json')}
if any(p.exists() for p in paths.values()):raise ValueError('fresh verifier receipt required')
command=[sys.executable,str(HERE/'verify_archives.py')];started=time.perf_counter()
p=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
paths['stdout.bin'].write_bytes(p.stdout);paths['stderr.bin'].write_bytes(p.stderr)
result=dict(command=command,exit_code=p.returncode,elapsed_s=time.perf_counter()-started,
            stdout_sha256=hashlib.sha256(p.stdout).hexdigest(),stderr_sha256=hashlib.sha256(p.stderr).hexdigest(),
            preservation_sha256=hashlib.sha256((HERE/'PRESERVATION_MANIFEST.json').read_bytes()).hexdigest(),
            index_sha256=hashlib.sha256((HERE/'INDEX.json').read_bytes()).hexdigest(),scope='Actual archive verification; no quality/ROS/navigation rerun')
paths['json'].write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
print(json.dumps(result));raise SystemExit(p.returncode)
