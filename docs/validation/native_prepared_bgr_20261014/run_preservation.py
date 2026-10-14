"""Literal archive and independent verification receipts, no tests/algorithm runs."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
def sha(raw):return hashlib.sha256(raw).hexdigest()
old={}
for name in ('pb_wsl_navigation_20261014','quality_wsl_navigation_20261014','pb_wsl_production_20261014'):
    for p in sorted((ROOT/'docs/validation'/name).rglob('*')):
        if p.is_file():old[p.relative_to(ROOT).as_posix()]=sha(p.read_bytes())
for label,command in (
    ('archive',[sys.executable,str(HERE/'archive_evidence.py'),'--dest',str(HERE)]),
    ('verify',[sys.executable,str(HERE/'verify_archives.py'),'--archive',str(HERE)])):
    assert not (HERE/(label+'.json')).exists(),'Fresh receipt required'
    started=time.perf_counter();process=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
    (HERE/(label+'.stdout.bin')).write_bytes(process.stdout);(HERE/(label+'.stderr.bin')).write_bytes(process.stderr)
    record={'command':command,'exit_code':process.returncode,'elapsed_s':time.perf_counter()-started,
        'owned_process_reaped':True,'stdout_sha256':sha(process.stdout),'stderr_sha256':sha(process.stderr),
        'scope':'Evidence preservation only; no tests/ROS/WSL/GL/NN/build'}
    (HERE/(label+'.json')).write_text(json.dumps(record,indent=2)+'\n',encoding='utf8')
    assert process.returncode==0,process.stderr.decode('utf8',errors='replace')
    print(process.stdout.decode('utf8'))
after={p:sha((ROOT/p).read_bytes()) for p in old}
assert old==after,'Frozen old archive changed'
(HERE/'OLD_ARCHIVES_UNCHANGED.json').write_text(json.dumps({'schema':'polar.evidence.frozen-archive-check.v1',
 'passed':True,'checked_files':len(old),'before_sha256':old,'after_sha256':after},indent=2)+'\n',encoding='utf8')
print(json.dumps({'frozen_old_files':len(old),'all_bytes_unchanged':True}))
