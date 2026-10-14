"""Append explicitly revised postcheck docs; record current strict originals proof."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
def sha(raw):return hashlib.sha256(raw).hexdigest()
for label,command in (
    ('append.archive',[sys.executable,str(HERE/'archive_evidence.py'),'--dest',str(HERE)]),
    ('append.package',[sys.executable,str(HERE/'verify_archives.py'),'--archive',str(HERE)]),
    ('append.originals',[sys.executable,str(HERE/'verify_archives.py'),'--archive',str(HERE),'--check-originals'])):
    assert not (HERE/(label+'.json')).exists()
    started=time.perf_counter();p=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
    (HERE/(label+'.stdout.bin')).write_bytes(p.stdout);(HERE/(label+'.stderr.bin')).write_bytes(p.stderr)
    record={'command':command,'exit_code':p.returncode,'elapsed_s':time.perf_counter()-started,'owned_process_reaped':True,
        'stdout_sha256':sha(p.stdout),'stderr_sha256':sha(p.stderr),'scope':'Only archive/metadata verification; no business tests or algorithm execution'}
    (HERE/(label+'.json')).write_text(json.dumps(record,indent=2)+'\n',encoding='utf8')
    assert p.returncode==0,p.stderr.decode('utf8',errors='replace')
    print(p.stdout.decode('utf8'))
old=json.loads((HERE/'OLD_ARCHIVES_UNCHANGED.json').read_bytes())
assert all(sha((ROOT/name).read_bytes())==value for name,value in old['before_sha256'].items())
