from pathlib import Path
import hashlib,json,subprocess
root=Path(__file__).resolve().parents[1]
path=root/'DEVELOPMENT_CHANGES.json';raw=path.read_bytes();value=json.loads(raw)
base=json.loads((root/'EXTRACTION_MANIFEST.json').read_bytes())
original={r['path']:r['sha256'] for r in base['files']+base['derived_files']}
changes={r['path']:r for r in value['files']}
dirty=subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=root,text=True).splitlines()
updated=[]
for name in dirty:
    if name not in original:continue
    sha=hashlib.sha256((root/name).read_bytes()).hexdigest()
    row=changes[name];assert row['original_sha256']==original[name]
    if row['current_sha256']==sha:continue
    row['current_sha256']=sha
    row['task']=','.join(dict.fromkeys(row['task'].split(',')+['T01','T07']))
    row['reason']+='; team-independent component graph and authenticated scoped navigation/decision/aim catalog with SDK pipeline binding, arbitrary declared robot scopes and original source/deadline/authority retained'
    updated.append(name)
if updated:
    ending='\r\n' if b'\r\n' in raw else '\n'
    path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2)+'\n').replace('\n',ending).encode())
print(json.dumps(dict(updated=updated,baseline_unchanged=True)))
