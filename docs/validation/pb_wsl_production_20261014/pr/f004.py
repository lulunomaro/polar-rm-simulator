"""Capture the read-only audit output bytes and script/report identities."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

OUT=Path(__file__).resolve().parent;command=[sys.executable,str(OUT/'audit.py')]
start=time.perf_counter();p=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
(OUT/'stdout.log').write_bytes(p.stdout);(OUT/'stderr.log').write_bytes(p.stderr)
result=dict(scope='Read-only Git/plan/evidence audit, no quality/WSL/ROS/NN/GL/physics rerun',command=command,
            exit_code=p.returncode,elapsed_s=time.perf_counter()-start,
            audit_sha256=hashlib.sha256((OUT/'audit.py').read_bytes()).hexdigest(),
            result_sha256=hashlib.sha256((OUT/'RESULT.json').read_bytes()).hexdigest(),
            stdout_sha256=hashlib.sha256(p.stdout).hexdigest(),stderr_sha256=hashlib.sha256(p.stderr).hexdigest())
(OUT/'PROCESS_RESULT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
print(json.dumps(result));raise SystemExit(p.returncode)
