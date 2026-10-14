"""Independent byte-level check. No import from archive recipe or simulation."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
def sha(raw): return hashlib.sha256(raw).hexdigest()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--check-originals',action='store_true',help='Strictly compare current workspace original bytes; requires local artifacts')
    args=parser.parse_args()
    target=args.archive.absolute();root=next(p for p in target.parents if (p/'rm_match').is_dir())
    raw=(target/'PRESERVATION_MANIFEST.json').read_bytes();manifest=json.loads(raw)
    assert manifest['payload_count']==len(manifest['files'])
    seen=set();missing=[];originals_verified=0
    for row in manifest['files']:
        rel=Path(row['stored_path']);assert not rel.is_absolute() and '..' not in rel.parts and rel not in seen
        seen.add(rel);p=target/rel;assert p.is_file() and not p.is_symlink()
        stored=p.read_bytes();assert sha(stored)==row['stored_sha256'] and len(stored)==row['stored_bytes']
        if row['encoding']=='gzip_mtime0':
            assert stored[:2]==b'\x1f\x8b' and stored[4:8]==b'\0\0\0\0'
            decoded=gzip.decompress(stored)
        else:
            assert row['encoding']=='original_bytes';decoded=stored
        assert sha(decoded)==row['original_sha256'] and len(decoded)==row['original_bytes']
        source_rel=Path(row['source']);assert not source_rel.is_absolute() and '..' not in source_rel.parts
        src=root/source_rel
        if not src.is_file(): missing.append(row['source'])
        if args.check_originals:
            assert src.is_file() and not src.is_symlink(),'Missing or unsafe current original: '+row['source']
            assert src.read_bytes()==decoded,'Original source byte mismatch: '+row['source']
            originals_verified+=1
    assert manifest['total_original_bytes']==sum(r['original_bytes'] for r in manifest['files'])
    assert manifest['total_stored_bytes']==sum(r['stored_bytes'] for r in manifest['files'])
    expected='stored_path\toriginal_sha256\tsource\n'+''.join('%s\t%s\t%s\n'%(r['stored_path'],r['original_sha256'],r['source']) for r in manifest['files'])
    assert (target/'INDEX.tsv').read_text(encoding='utf8')==expected
    print(json.dumps({'schema':'polar.evidence.independent-literal-verification.v1','passed':True,
        'checked_payloads':len(seen),'stored_and_restored_sha_verified':True,'all_gzip_mtime_zero':True,
        'originals_checked':args.check_originals,'originals_verified':originals_verified,
        'originals_missing':missing,'originals_missing_count':len(missing),
        'scope':'Package + strict current workspace original bytes' if args.check_originals else 'Package stored/restored SHA and INDEX only; original bytes not compared',
        'preservation_manifest_sha256':sha(raw)}))
if __name__=='__main__': main()
