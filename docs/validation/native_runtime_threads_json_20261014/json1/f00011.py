"""Actual harmless Windows test driver; no WSL/ROS/model/physics."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
paths=['rm_match/deployment/json_adapter.py','rm_match/deployment/json_owned_process.py',
       'rm_match/deployment/windows_owned_job.py','rm_match/integrations/owned_linux_group.py',
       'tests/test_json_owned_process.py','tests/test_deployment.py']
originals={name:(ROOT/name).read_bytes() for name in paths}
rows=[]
for i,(name,raw) in enumerate(originals.items()):
    target=f'source_{i:02d}.py';(HERE/target).write_bytes(raw)
    rows.append(dict(source=name,stored=target,size=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
(HERE/'SOURCE_MANIFEST.json').write_text(json.dumps(rows,indent=2)+'\n')
commands=[['repro',[sys.executable,str(HERE/'repro.py')]],
 ['focused',[sys.executable,'-m','pytest','tests/test_json_owned_process.py',
             'tests/test_deployment.py::JsonAdapterTests','-q',f'--junitxml={HERE / "focused.xml"}']]]
(HERE/'COMMAND.json').write_text(json.dumps(commands,indent=2)+'\n')
records=[]
for label,command in commands:
    started=time.perf_counter()
    p=subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    stdout,stderr=p.communicate(timeout=25)
    (HERE/(label+'.stdout.log')).write_bytes(stdout);(HERE/(label+'.stderr.log')).write_bytes(stderr)
    records.append(dict(step=label,exit_code=p.returncode,elapsed_s=time.perf_counter()-started,reaped=True))
record=dict(scope='Harmless actual Windows Job fixtures plus injected POSIX launch proofs; actual Linux cases explicitly skipped',
 steps=records,source_unchanged=all((ROOT/name).read_bytes()==raw for name,raw in originals.items()),
 source_manifest_sha256=hashlib.sha256((HERE/'SOURCE_MANIFEST.json').read_bytes()).hexdigest())
(HERE/'PROCESS_RESULT.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record));raise SystemExit(0 if record['source_unchanged'] and all(r['exit_code']==0 for r in records) else 1)
