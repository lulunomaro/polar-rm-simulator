"""Record exact independent archive verifier output; no ROS/WSL/physics."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
command=[sys.executable,str(HERE/'verify_archives.py')]
started=time.perf_counter()
result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
for name,raw in [('VERIFICATION.stdout.bin',result.stdout),('VERIFICATION.stderr.bin',result.stderr)]:
    path=HERE/name
    if path.exists():raise ValueError('verification output already exists; use a new archive receipt')
    path.write_bytes(raw)
report=dict(scope='Actual independent archive byte/SHA validation only; no algorithm/ROS/WSL rerun',
            command=command,exit_code=result.returncode,elapsed_s=time.perf_counter()-started,
            stdout_sha256=hashlib.sha256(result.stdout).hexdigest(),stderr_sha256=hashlib.sha256(result.stderr).hexdigest(),
            manifest_sha256=hashlib.sha256((HERE/'MANIFEST.json').read_bytes()).hexdigest(),
            index_sha256=hashlib.sha256((HERE/'INDEX.json').read_bytes()).hexdigest())
(HERE/'VERIFICATION_RESULT.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print(json.dumps(report));raise SystemExit(result.returncode)
