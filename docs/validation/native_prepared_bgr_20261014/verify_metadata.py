"""Permanent inventory/local links/raw receipts; no algorithm or test execution."""
import hashlib
import gzip
import json
from pathlib import Path
import re
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
def sha(raw):return hashlib.sha256(raw).hexdigest()
inventory=json.loads((HERE/'FILES.json').read_bytes());seen=set()
for row in inventory['files']:
    rel=Path(row['path']);assert not rel.is_absolute() and '..' not in rel.parts and rel.as_posix() not in seen
    seen.add(rel.as_posix());p=HERE/rel;assert p.is_file() and not p.is_symlink()
    raw=p.read_bytes();assert len(raw)==row['bytes'] and sha(raw)==row['sha256']
actual={p.relative_to(HERE).as_posix() for p in HERE.rglob('*') if p.is_file() and p.name!='FILES.json'}
assert actual==seen and inventory['listed_files']==len(seen)
assert inventory['total_listed_bytes']==sum(r['bytes'] for r in inventory['files'])
for target in re.findall(r'\]\(([^)]+)\)',(HERE/'README.md').read_text(encoding='utf8')):
    assert not target.startswith(('http:','https:')) and (HERE/target).is_file(),target
for label in ('archive','verify','package','originals','append.archive','append.package','append.originals',
              'append3.archive','append3.package','append3.originals',
              'append3-corrected.archive','append3-corrected.package','append3-corrected.originals'):
    record=json.loads((HERE/(label+'.json')).read_bytes())
    assert record['exit_code']==0 and record['owned_process_reaped'] is True
    assert sha((HERE/(label+'.stdout.bin')).read_bytes())==record['stdout_sha256']
    assert sha((HERE/(label+'.stderr.bin')).read_bytes())==record['stderr_sha256']
final=json.loads((HERE/'append3-corrected.originals.stdout.bin').read_bytes())
assert final['originals_checked'] is True and final['originals_verified']==552 and final['originals_missing_count']==0
package=json.loads((HERE/'append3-corrected.package.stdout.bin').read_bytes())
assert package['originals_checked'] is False and package['originals_verified']==0
old=json.loads((HERE/'OLD_ARCHIVES_UNCHANGED.json').read_bytes())
assert old['passed'] is True and old['checked_files']==1009 and old['before_sha256']==old['after_sha256']
manifest=json.loads((HERE/'PRESERVATION_MANIFEST.json').read_bytes())
assert manifest['payload_count']==len(manifest['files'])==552
row=next(r for r in manifest['files'] if r['source']=='artifacts/prepared-bgr-postcheck-docs-20261014-02/RESULT.json')
post_raw=(HERE/row['stored_path']).read_bytes()
post=json.loads(gzip.decompress(post_raw) if row['encoding']=='gzip_mtime0' else post_raw)
assert post['all_other_checked_files_unchanged'] is True
for row in post['postcheck_changed_files']:
    assert sha((ROOT/row['path']).read_bytes())==row['final_after_sha256']
print(json.dumps({'schema':'polar.evidence.permanent-metadata-check.v1','passed':True,
    'payload_records':552,'permanent_files_including_self':len(seen)+1,
    'inventory_bytes_sha_and_local_links_verified':True,'raw_archive_receipts_verified':True,
    'two_postcheck_docs_match_final_after':True,'FILES_sha256':sha((HERE/'FILES.json').read_bytes()),
    'preservation_manifest_sha256':sha((HERE/'PRESERVATION_MANIFEST.json').read_bytes()),
    'total_permanent_bytes':sum(r['bytes'] for r in inventory['files'])+(HERE/'FILES.json').stat().st_size}))
