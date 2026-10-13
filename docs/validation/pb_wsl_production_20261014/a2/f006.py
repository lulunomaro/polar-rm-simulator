"""Capture the actual read-only independent audit, never rerun the ROS stack."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
SOURCE=ROOT/'artifacts/pb-wsl-production-sil-actual-20261014-attempt2'
command=[sys.executable,str(HERE/'audit.py'),'--source',str(SOURCE)]
paths=('RESULT.json','TRACE.jsonl','peer/ROS_SOURCE.jsonl','peer/EXTERNAL_EVENTS.jsonl',
       'peer/GOAL_REPORT.json','peer/RESULT.json','session/SESSION_SPEC.json','session/PRODUCTION_GATE_STATUS.json')
before={name:hashlib.sha256((SOURCE/name).read_bytes()).hexdigest() for name in paths}
script_before=hashlib.sha256((HERE/'audit.py').read_bytes()).hexdigest()
(HERE/'COMMAND.json').write_text(json.dumps(dict(command=command,qualification='Read-only frozen evidence audit; no new ROS/WSL/physics run'),indent=2)+'\n',encoding='utf8')
started=time.perf_counter();p=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
(HERE/'stdout.log').write_bytes(p.stdout);(HERE/'stderr.log').write_bytes(p.stderr)
after={name:hashlib.sha256((SOURCE/name).read_bytes()).hexdigest() for name in paths}
script_after=hashlib.sha256((HERE/'audit.py').read_bytes()).hexdigest()
record=dict(exit_code=p.returncode,elapsed_s=time.perf_counter()-started,owned_driver_reaped=True,
            source_before=before,source_after=after,source_unchanged=before==after,
            audit_script_before_sha256=script_before,audit_script_after_sha256=script_after,audit_script_unchanged=script_before==script_after,
            result_sha256=hashlib.sha256((HERE/'RESULT.json').read_bytes()).hexdigest(),
            stdout_sha256=hashlib.sha256(p.stdout).hexdigest(),stderr_sha256=hashlib.sha256(p.stderr).hexdigest(),
            scope='Actual independent read-only audit execution; no navigation/ROS/WSL/GL/NN rerun')
(HERE/'PROCESS_RESULT.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf8')
print(json.dumps(record,indent=2));raise SystemExit(0 if p.returncode==0 and before==after and script_before==script_after else 2)
