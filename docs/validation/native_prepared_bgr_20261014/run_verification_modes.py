"""Record package-only and strict current-original checks independently."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
def sha(raw):return hashlib.sha256(raw).hexdigest()
for label,flags in (('package',[]),('originals',['--check-originals'])):
    command=[sys.executable,str(HERE/'verify_archives.py'),'--archive',str(HERE),*flags]
    assert not (HERE/(label+'.json')).exists(),'Fresh raw verification receipt required'
    started=time.perf_counter();p=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
    (HERE/(label+'.stdout.bin')).write_bytes(p.stdout);(HERE/(label+'.stderr.bin')).write_bytes(p.stderr)
    record={'command':command,'exit_code':p.returncode,'elapsed_s':time.perf_counter()-started,'owned_process_reaped':True,
       'verifier_sha256':sha((HERE/'verify_archives.py').read_bytes()),'stdout_sha256':sha(p.stdout),'stderr_sha256':sha(p.stderr)}
    (HERE/(label+'.json')).write_text(json.dumps(record,indent=2)+'\n',encoding='utf8')
    assert p.returncode==0,p.stderr.decode('utf8',errors='replace')
    print(p.stdout.decode('utf8'))
