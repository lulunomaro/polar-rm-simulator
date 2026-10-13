"""Independent permanent inventory, local links, recorded raw receipts check."""
import hashlib
import json
from pathlib import Path
import re
HERE=Path(__file__).resolve().parent
def sha(raw): return hashlib.sha256(raw).hexdigest()
inventory=json.loads((HERE/'FILES.json').read_bytes())
seen=set()
for row in inventory['files']:
    rel=Path(row['path'])
    assert not rel.is_absolute() and '..' not in rel.parts and rel.as_posix() not in seen
    seen.add(rel.as_posix());p=HERE/rel
    assert p.is_file() and not p.is_symlink()
    raw=p.read_bytes();assert len(raw)==row['bytes'] and sha(raw)==row['sha256']
actual={p.relative_to(HERE).as_posix() for p in HERE.rglob('*') if p.is_file() and p.name!='FILES.json'}
assert actual==seen and inventory['listed_files']==len(seen)
assert inventory['total_listed_bytes']==sum(r['bytes'] for r in inventory['files'])
for target in re.findall(r'\]\(([^)]+)\)',(HERE/'README.md').read_text(encoding='utf8')):
    assert not target.startswith(('http:','https:')) and (HERE/target).is_file(),target
for label in ('archive','verify','append.archive','append.verify','append2.archive','append2.verify'):
    record=json.loads((HERE/(label+'.json')).read_bytes())
    assert record['exit_code']==0 and record['owned_process_reaped'] is True
    assert sha((HERE/(label+'.stdout.bin')).read_bytes())==record['stdout_sha256']
    assert sha((HERE/(label+'.stderr.bin')).read_bytes())==record['stderr_sha256']
old=json.loads((HERE/'OLD438_UNCHANGED.json').read_bytes())
assert old['passed'] is True and old['checked_files']==376 and old['before_sha256']==old['after_sha256']
manifest=json.loads((HERE/'PRESERVATION_MANIFEST.json').read_bytes())
assert manifest['payload_count']==len(manifest['files']) and manifest['all_original_and_stored_bytes_verified'] is True
print(json.dumps({'schema':'polar.evidence.permanent-metadata-check.v1','passed':True,
    'payload_records':manifest['payload_count'],'permanent_files_including_self':len(seen)+1,
    'inventory_bytes_sha_and_local_links_verified':True,'raw_archive_receipts_verified':True,
    'FILES_sha256':sha((HERE/'FILES.json').read_bytes()),
    'total_permanent_bytes':sum(r['bytes'] for r in inventory['files'])+(HERE/'FILES.json').stat().st_size}))
