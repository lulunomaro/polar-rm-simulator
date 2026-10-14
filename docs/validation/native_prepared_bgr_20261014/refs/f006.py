"""Save actual3 exact recorded source bytes AFTER execution; no preexecution claim."""
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'artifacts/prepared-bgr-actual3-source-capture-20261014'
reference=ROOT/'artifacts/wsl-native-live-20261014-prepared-bgr-attempt3/EXECUTED_SOURCE.json'
raw_reference=reference.read_bytes();sources=json.loads(raw_reference)
def sha(raw):return hashlib.sha256(raw).hexdigest()
assert not OUT.exists(),'fresh capture required'
rows=[]
for name,expected in sources.items():
    relative=Path(name)
    assert not relative.is_absolute() and '..' not in relative.parts
    source=ROOT/relative
    assert source.is_file() and not source.is_symlink()
    raw=source.read_bytes();assert sha(raw)==expected,'recorded source changed: '+name
    dest=OUT/'source'/relative;dest.parent.mkdir(parents=True,exist_ok=True)
    with dest.open('xb') as stream:stream.write(raw)
    assert dest.read_bytes()==raw and source.read_bytes()==raw
    rows.append({'path':name,'sha256':expected,'bytes':len(raw),'source_origin':'postexecution_current_bytes_exact_recorded_sha'})
(OUT/'EXECUTED_SOURCE.json').write_bytes(raw_reference)
(OUT/'MANIFEST.json').write_text(json.dumps({'schema':'polar.evidence.source-capture.v1','files':rows,
    'execution_reference':reference.relative_to(ROOT).as_posix(),'reference_sha256':sha(raw_reference),
    'all_exact_sha':True,'preexecution_independent_capture':False,
    'scope':'Source bytes captured after actual3, each matches original executed-source map; no rerun or reconstruction'},indent=2)+'\n',encoding='utf8')
print(json.dumps({'captured_sources':len(rows),'bytes':sum(r['bytes'] for r in rows),'all_recorded_sha_match':True}))
