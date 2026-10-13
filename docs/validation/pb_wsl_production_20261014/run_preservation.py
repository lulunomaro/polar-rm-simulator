"""Capture literal archive and independent verification outputs; no actual reruns."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
def sha(raw): return hashlib.sha256(raw).hexdigest()
def execute(label,command):
    for suffix in ('.stdout.bin','.stderr.bin','.json'):
        assert not (HERE/(label+suffix)).exists(),'New receipt required'
    started=time.perf_counter()
    proc=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
    (HERE/(label+'.stdout.bin')).write_bytes(proc.stdout)
    (HERE/(label+'.stderr.bin')).write_bytes(proc.stderr)
    record={'command':command,'exit_code':proc.returncode,'elapsed_s':time.perf_counter()-started,
            'owned_process_reaped':True,'stdout_sha256':sha(proc.stdout),'stderr_sha256':sha(proc.stderr),
            'scope':'Archive byte preservation check only; no simulation/ROS/WSL/NN or test rerun'}
    (HERE/(label+'.json')).write_text(json.dumps(record,indent=2)+'\n',encoding='utf8')
    assert proc.returncode==0,proc.stderr.decode('utf8',errors='replace')
    print(proc.stdout.decode('utf8'))
execute('archive',[sys.executable,str(HERE/'archive_evidence.py'),'--dest',str(HERE)])
execute('verify',[sys.executable,str(HERE/'verify_archives.py'),'--archive',str(HERE)])
before=json.loads((ROOT/'artifacts/pb-wsl-production-archive-plan-20261014/OLD438_BEFORE.json').read_bytes())
after={name:sha((ROOT/name).read_bytes()) for name in before}
assert before==after,'Old frozen archive changed'
(HERE/'OLD438_UNCHANGED.json').write_text(json.dumps({'schema':'polar.evidence.frozen-archive-check.v1',
    'passed':True,'checked_files':len(before),'before_sha256':before,'after_sha256':after},indent=2)+'\n',encoding='utf8')
print(json.dumps({'old438_files':len(before),'old438_all_bytes_unchanged':True}))
