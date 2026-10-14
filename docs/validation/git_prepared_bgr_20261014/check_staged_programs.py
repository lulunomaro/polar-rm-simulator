"""Compare frozen QA source to working tree and literal staged program bytes."""
import hashlib,json,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
out=root/'artifacts/prepared-bgr-qa-index-proof-20261014';out.mkdir()
qa=json.loads((root/'artifacts/quality-20261014-prepared-bgr-frozen-02/manifest.json').read_bytes())
allowed={'docs/IMPLEMENTATION_PROGRESS.md','docs/WSL_NATIVE_TRANSPORT.md'}
hashes=qa['source_files_sha256'];changes=[];checked=0
for n,h in hashes.items():
 p=root/n;current=hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
 if current!=h:changes.append(dict(path=n,qa_sha256=h,current_sha256=current,allowed_docs_only=n in allowed))
 if n not in allowed:
  assert current==h,'Executed/checked source changed after QA: '+n
  checked+=1
names=subprocess.check_output(['git','diff','--cached','--name-only','-z'],cwd=root).decode('utf-8').split('\0')
rows=[]
for n in filter(None,names):
 if not (n=='DEVELOPMENT_CHANGES.json' or n.startswith(('rm_match/','tests/','tools/'))):continue
 raw=subprocess.check_output(['git','show',':'+n],cwd=root)
 assert raw==(root/n).read_bytes(),'Git changed staged literal bytes: '+n
 assert hashlib.sha256(raw).hexdigest()==hashes[n],'Staged program differs from QA: '+n
 rows.append(dict(path=n,sha256=hashes[n],bytes=len(raw)))
assert len(rows)==13,(len(rows),rows)
result=dict(schema='polar.frozen-qa-staged-program-proof.v1',passed=True,
 qa_manifest_sha256=hashlib.sha256((root/'artifacts/quality-20261014-prepared-bgr-frozen-02/manifest.json').read_bytes()).hexdigest(),
 checked_source_files=checked,post_qa_changes=changes,staged_programs=rows,
 scope='Literal current/staged checked programs match frozen QA; post-QA docs/evidence are separately preserved, not retroactive QA')
(out/'driver.py').write_bytes(Path(__file__).read_bytes())
(out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(dict(passed=True,checked_source_files=checked,staged_programs=len(rows),post_qa_changes=changes)))
