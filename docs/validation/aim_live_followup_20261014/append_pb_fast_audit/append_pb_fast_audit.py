"""Append one final frozen read-only audit; never rewrite any prior blob."""
import gzip,hashlib,importlib.util,json
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
OUT=ROOT/'docs/validation/aim_live_followup_20261014';PROOF=OUT/'append_pb_fast_audit'
PROOF.mkdir(exist_ok=False)
spec=importlib.util.spec_from_file_location('_archive_selection',HERE/'archive_evidence.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
before=(OUT/'PRESERVATION_MANIFEST.json').read_bytes();manifest=json.loads(before)
(PROOF/'PRESERVATION_MANIFEST.before.json').write_bytes(before)
(PROOF/'INDEX.before.tsv').write_bytes((OUT/'INDEX.tsv').read_bytes())
label='pb_fast_audit';relative='pb2025-aim-controlled-fast-audit-20261014-01'
source=ROOT/'artifacts'/relative;helper.safe(source,ROOT/'artifacts')
paths,omissions=helper.selection(source)
blobs={r['original_sha256']:{k:r[k] for k in ('path','encoding','stored_bytes','stored_sha256')} for r in manifest['files']}
old_blobs={p:hashlib.sha256((OUT/p).read_bytes()).hexdigest() for p in {r['path'] for r in manifest['files']}}
rows=[]
for original in paths:
    raw=original.read_bytes();helper.inspect_text(original,raw);digest=helper.sha(raw)
    if digest not in blobs:
        compress=len(raw)>65536;rel='blobs/'+digest[:2]+'/'+digest+('.gz' if compress else '.bin')
        target=OUT/rel;target.parent.mkdir(parents=True,exist_ok=True)
        if compress:
            with target.open('xb') as stream:
                with gzip.GzipFile(filename='',mode='wb',fileobj=stream,mtime=0,compresslevel=6) as encoder:encoder.write(raw)
        else:
            with target.open('xb') as stream:stream.write(raw)
        stored=target.read_bytes()
        assert (gzip.decompress(stored) if compress else stored)==raw
        blobs[digest]=dict(path=rel,encoding='gzip' if compress else 'literal',stored_bytes=len(stored),stored_sha256=helper.sha(stored))
    assert original.read_bytes()==raw
    rows.append(dict(group=label,original_path=original.relative_to(ROOT).as_posix(),original_bytes=len(raw),original_sha256=digest,**blobs[digest]))
manifest['groups'][label]=relative;manifest['files'].extend(rows)
manifest['omissions'].extend(dict(group=label,original_path='artifacts/'+relative+'/'+r['path'],reason=r['reason']) for r in omissions)
helper.write_json(OUT/'PRESERVATION_MANIFEST.json',manifest)
(OUT/'INDEX.tsv').write_text('group\toriginal_path\tstored_path\toriginal_bytes\toriginal_sha256\tstored_bytes\tstored_sha256\tencoding\n'+
    ''.join('\t'.join(str(r[k]) for k in ('group','original_path','path','original_bytes','original_sha256','stored_bytes','stored_sha256','encoding'))+'\n' for r in manifest['files']),encoding='utf-8',newline='\n')
assert all(hashlib.sha256((OUT/p).read_bytes()).hexdigest()==digest for p,digest in old_blobs.items())
helper.write_json(PROOF/'RESULT.json',dict(added_originals=len(rows),added_group=label,old_payload_blobs_unchanged=True,
    before_manifest_sha256=helper.sha(before),after_manifest_sha256=helper.sha((OUT/'PRESERVATION_MANIFEST.json').read_bytes()),
    final_original_paths=len(manifest['files']),final_unique_blobs=len(blobs),original_byte_equality=True,
    qualification='Archive append only; source audit remains read-only and no new execution qualification'))
(PROOF/'append_pb_fast_audit.py').write_bytes(Path(__file__).read_bytes())
print((PROOF/'RESULT.json').read_text())
