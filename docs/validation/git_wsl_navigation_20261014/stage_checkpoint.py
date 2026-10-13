"""Stage the authorized checkpoint and verify exact index/source bytes."""
import hashlib
import json
from pathlib import Path
import subprocess

root=Path(__file__).resolve().parents[1]
def git(*args):
    return subprocess.check_output(['git',*args],cwd=root)
assert git('branch','--show-current').decode().strip()=='work/plan-t01-t03'
subprocess.run(['git','add','-u'],cwd=root,check=True)
new_files=['docs/PB_WSL_NAVIGATION.md','rm_match/integrations/owned_linux_group.py',
 'rm_match/integrations/pb_wsl_navigation.py','rm_match/integrations/pb_wsl_navigation_registry.py',
 'rm_match/integrations/pb_wsl_navigation_worker.py','tests/test_operator_http_rejection.py',
 'tests/test_owned_wsl_cleanup.py','tests/test_pb_navigation_goal_evidence.py',
 'tests/test_pb_wsl_navigation_registry.py','tests/test_pb_wsl_navigation_session.py',
 'tests/test_pb_wsl_navigation_stdio.py','tests/test_pb_wsl_navigation_worker.py',
 'tests/test_platform_wsl_navigation_cli.py','tools/qa_pb_wsl_navigation_sil.py']
subprocess.run(['git','add','--',*new_files],cwd=root,check=True)
for directory in ('pb_wsl_navigation_20261014','quality_wsl_navigation_20261014'):
    base=root/'docs/validation'/directory
    inventory=json.loads((base/'FILES.json').read_bytes())
    selected=[]
    for row in inventory['files']:
        p=base/row['path']
        if p.is_symlink() or not p.resolve().is_relative_to(base.resolve()):raise ValueError('unsafe archive path')
        raw=p.read_bytes()
        if len(raw)!=row['bytes'] or hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError(str(p))
        selected.append(p.relative_to(root).as_posix())
    selected.append((base/'FILES.json').relative_to(root).as_posix())
    subprocess.run(['git','add','-f','--',*selected],cwd=root,check=True)
names=[n for n in git('diff','--cached','--name-only','-z').decode().split('\0') if n]
raw=subprocess.run(['git','cat-file','--batch'],cwd=root,input=''.join(':'+n+'\n' for n in names).encode(),
    stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout
offset=0;rows=[]
for n in names:
    end=raw.index(b'\n',offset);head=raw[offset:end].split();offset=end+1
    if len(head)!=3 or head[1]!=b'blob':raise ValueError('nonblob staged entry')
    size=int(head[2]);blob=raw[offset:offset+size];offset+=size+1
    if blob!=(root/n).read_bytes():raise ValueError('index bytes differ: '+n)
    rows.append(dict(path=n,bytes=size,sha256=hashlib.sha256(blob).hexdigest()))
if offset!=len(raw):raise ValueError('batch output tail')
subprocess.run(['git','-c','core.whitespace=trailing-space,space-before-tab,cr-at-eol','diff','--cached','--check'],cwd=root,check=True)
report=dict(schema='polar.index-literal-audit.v1',count=len(rows),all_index_bytes_exact=True,files=rows)
(root/'artifacts/wsl-navigation-staged-byte-audit-20261014.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print(json.dumps({k:v for k,v in report.items() if k!='files'}))
