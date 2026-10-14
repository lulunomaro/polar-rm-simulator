"""Update only three reviewed current hashes; preserve extraction identities."""
from pathlib import Path
import hashlib,json,subprocess
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'DEVELOPMENT_CHANGES.json';raw=p.read_bytes();value=json.loads(raw)
reasons={
 'rm_match/platform_v2/control.py':'Explicit three-channel control_batch_v1 validates every original lease/window/binding/sequence and detached bounded value before one atomic commit; real lease and unchanged 150ms window cap every member, with no new authority or fire permit',
 'rm_match/platform_v2/server.py':'Advertise control_batch_version=1 only for strict operator window negotiation and dispatch the exact bounded atomic batch request; retain original transport, limits, admission and legacy endpoints',
 'rm_match/platform_v2/client.py':'Opt-in no-retry complete batch SDK with original typed acknowledgements and request-start relative expiry bounds for every member; duplicate JSON fields and uncertain or late ACKs fail closed, while legacy single calls remain available'}
rows={r['path']:r for r in value['files']}
before={}
for name,reason in reasons.items():
    row=rows[name];before[name]=dict(row)
    old=subprocess.check_output(['git','show','HEAD:'+name],cwd=ROOT)
    assert hashlib.sha256(old).hexdigest()==row['current_sha256'],name
    row['current_sha256']=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    row['reason']+='; '+reason
updated=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
if b'\r\n' in raw:updated=updated.replace(b'\n',b'\r\n')
p.write_bytes(updated)
print(json.dumps({name:rows[name]['current_sha256'] for name in reasons}))
