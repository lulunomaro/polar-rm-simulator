import hashlib
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
path=root/'DEVELOPMENT_CHANGES.json';raw=path.read_bytes();value=json.loads(raw)
row=next(r for r in value['files'] if r['path']=='rm_match/platform_v2/server.py')
assert row['current_sha256']=='d5b172ce5e7aef18910228f8322ff7163ecd2fb819e2a03e4f06582b8fbcc0ba'
sha=hashlib.sha256((root/row['path']).read_bytes()).hexdigest()
assert sha=='f7051d9c4beab13cd4ea2863c3ca8c2ea0c0d06d542be6618615de67bf016fbc'
out=root/'artifacts/platform-http-provenance-20261014';out.mkdir()
(out/'DEVELOPMENT_CHANGES.before.json').write_bytes(raw)
row['current_sha256']=sha
row['reason']+='; preserve rejected HTTP responses with flush/FIN then at most 64KiB/100ms discard, and enforce the original 1s valid-body timeout as a total read deadline; keep 16384-byte acceptance, admission and SDK control windows unchanged'
encoded=(json.dumps(value,indent=2,ensure_ascii=False)+'\n').encode()
if b'\r\n' in raw:encoded=encoded.replace(b'\n',b'\r\n')
path.write_bytes(encoded)
(out/'DEVELOPMENT_CHANGES.after.json').write_bytes(encoded)
(out/'RESULT.json').write_text(json.dumps(dict(original_extraction_sha256=row['original_sha256'],
 current_server_sha256=sha,manifest_before_sha256=hashlib.sha256(raw).hexdigest(),
 manifest_after_sha256=hashlib.sha256(encoded).hexdigest(),scope='attribution update; no original manifest or algorithm source rewritten'),indent=2)+'\n',encoding='utf8')
print(json.dumps(dict(current_server_sha256=sha)))
