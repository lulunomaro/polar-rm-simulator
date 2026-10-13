"""Append explicit docs-only postcheck originals, preserving first verification logs."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
def sha(raw): return hashlib.sha256(raw).hexdigest()
old=json.loads((HERE/'OLD438_UNCHANGED.json').read_bytes())
assert all(sha((ROOT/p).read_bytes())==h for p,h in old['before_sha256'].items())
post=json.loads((ROOT/'artifacts/pb-postcheck-documentation-20261014-02/RESULT.json').read_bytes())
assert post['all_other_checked_files_unchanged'] is True
for label,command in (
    ('append2.archive',[sys.executable,str(HERE/'archive_evidence.py'),'--dest',str(HERE)]),
    ('append2.verify',[sys.executable,str(HERE/'verify_archives.py'),'--archive',str(HERE)])):
    assert not (HERE/(label+'.json')).exists()
    started=time.perf_counter()
    proc=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
    (HERE/(label+'.stdout.bin')).write_bytes(proc.stdout)
    (HERE/(label+'.stderr.bin')).write_bytes(proc.stderr)
    result={'command':command,'exit_code':proc.returncode,'elapsed_s':time.perf_counter()-started,
        'owned_process_reaped':True,'stdout_sha256':sha(proc.stdout),'stderr_sha256':sha(proc.stderr),
        'scope':'Explicit postcheck docs-only archive append; no test/ROS/WSL/physics rerun'}
    (HERE/(label+'.json')).write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    assert proc.returncode==0,proc.stderr.decode('utf8',errors='replace')
    print(proc.stdout.decode('utf8'))
assert all(sha((ROOT/p).read_bytes())==h for p,h in old['before_sha256'].items())
