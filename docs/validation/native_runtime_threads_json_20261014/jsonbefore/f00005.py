import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
source=ROOT/'rm_match/deployment/json_adapter.py';before=source.read_bytes()
(HERE/'json_adapter.before.py').write_bytes(before)
command=[sys.executable,str(HERE/'repro.py')]
(HERE/'COMMAND.json').write_text(json.dumps(command,indent=2)+'\n')
started=time.perf_counter();p=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=12)
(HERE/'stdout.log').write_bytes(p.stdout);(HERE/'stderr.log').write_bytes(p.stderr)
record=dict(exit_code=p.returncode,elapsed_s=time.perf_counter()-started,reaped=True,
    source_unchanged=source.read_bytes()==before,source_sha256=hashlib.sha256(before).hexdigest())
(HERE/'PROCESS_RESULT.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record));raise SystemExit(p.returncode)
