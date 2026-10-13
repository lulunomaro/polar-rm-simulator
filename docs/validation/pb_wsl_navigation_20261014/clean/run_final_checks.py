"""Explicit harmless lifecycle checks; preserve exact subprocess output bytes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root=Path(__file__).resolve().parents[2];out=Path(__file__).parent
files=['rm_match/integrations/owned_linux_group.py','rm_match/integrations/wsl_operator.py',
       'rm_match/integrations/wsl_operator_worker.py','rm_match/integrations/wsl_operator_pipe_worker.py',
       'tests/test_owned_wsl_cleanup.py','rm_match/integrations/test_wsl_operator_pipe.py']
before={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in files}
env=dict(os.environ);env.pop('POLAR_TEST_WSL',None)
commands=[('windows-final',[sys.executable,'-m','pytest','tests/test_owned_wsl_cleanup.py',
    'rm_match/integrations/test_wsl_operator.py','rm_match/integrations/test_wsl_operator_pipe.py','-q']),
    ('linux-final',['wsl.exe','-d','Ubuntu','--cd','/mnt/c/Users/lulu/Desktop/claude/polarsimulation/polar-rm-simulator',
       '--','/usr/bin/python3','-m','unittest','discover','-s','tests','-p','test_owned_wsl_cleanup.py','-v'])]
rows=[]
for name,command in commands:
    start=time.perf_counter();p=subprocess.run(command,cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
    for stream,data in [('stdout',p.stdout),('stderr',p.stderr)]:
        (out/(name+'.'+stream+'.bin')).write_bytes(data)
    rows.append(dict(name=name,command=command,exit_code=p.returncode,elapsed_s=time.perf_counter()-start,
                     stdout_sha256=hashlib.sha256(p.stdout).hexdigest(),stderr_sha256=hashlib.sha256(p.stderr).hexdigest()))
after={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in files}
report=dict(scope='Harmless Windows pipe cleanup and actual Linux/WSL process groups; no ROS/NN/GL/native algorithm',
            commands=rows,source_before=before,source_after=after,source_unchanged=before==after)
(out/'FINAL_RESULT.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print(json.dumps(report,indent=2));raise SystemExit(0 if before==after and all(r['exit_code']==0 for r in rows) else 2)
