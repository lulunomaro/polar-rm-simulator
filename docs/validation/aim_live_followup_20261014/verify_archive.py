"""Independent package reconstruction; original-workspace comparison is opt-in."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat


def sha(raw):return hashlib.sha256(raw).hexdigest()


def safe(root,relative):
    rel=PurePosixPath(relative)
    if rel.is_absolute() or not rel.parts or any(part in ('.','..') for part in rel.parts) or '\\' in relative:
        raise ValueError('Unsafe relative path')
    root=root.resolve();path=root.joinpath(*rel.parts)
    if not path.resolve().is_relative_to(root):raise ValueError('Path escaped verification root')
    current=path
    while current!=root:
        info=current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400):
            raise ValueError('Linked/reparse verification path')
        current=current.parent
    return path


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',type=Path,default=Path(__file__).resolve().parent)
    p.add_argument('--check-originals',action='store_true')
    p.add_argument('--repo-root',type=Path)
    a=p.parse_args(argv);archive=a.archive.resolve()
    if a.check_originals and a.repo_root is None:p.error('--repo-root is required with --check-originals')
    manifest_raw=safe(archive,'PRESERVATION_MANIFEST.json').read_bytes()
    manifest=json.loads(manifest_raw)
    if manifest.get('schema')!='polar.evidence.content-addressed.v1':raise ValueError('Unknown manifest schema')
    rows=manifest['files'];seen=set();stored_blobs={};originals_checked=0;originals_missing=[]
    index=['group\toriginal_path\tstored_path\toriginal_bytes\toriginal_sha256\tstored_bytes\tstored_sha256\tencoding\n']
    for row in rows:
        original=row['original_path']
        if original in seen:raise ValueError('Duplicate original path')
        seen.add(original)
        if type(row['original_bytes']) is not int or row['original_bytes']<0:raise ValueError('Invalid original size')
        digest=row['original_sha256']
        if type(digest) is not str or not re.fullmatch('[0-9a-f]{64}',digest):raise ValueError('Invalid original SHA')
        encoding=row['encoding']
        if encoding not in ('gzip','literal'):raise ValueError('Unknown blob encoding')
        expected='blobs/'+digest[:2]+'/'+digest+('.gz' if encoding=='gzip' else '.bin')
        if row['path']!=expected:raise ValueError('Content-addressed blob path mismatch')
        blob=safe(archive,row['path'])
        stored=blob.read_bytes()
        if len(stored)!=row['stored_bytes'] or sha(stored)!=row['stored_sha256']:raise ValueError('Stored hash/size mismatch')
        if encoding=='gzip' and (stored[:3]!=b'\x1f\x8b\x08' or stored[4:8]!=b'\x00'*4):
            raise ValueError('Nonzero gzip mtime or bad header')
        raw=gzip.decompress(stored) if encoding=='gzip' else stored
        if len(raw)!=row['original_bytes'] or sha(raw)!=digest:raise ValueError('Reconstructed raw hash/size mismatch')
        identity=(row['encoding'],row['stored_bytes'],row['stored_sha256'])
        if digest in stored_blobs and stored_blobs[digest]!=identity:raise ValueError('Same raw SHA has conflicting blob metadata')
        stored_blobs[digest]=identity
        if a.check_originals:
            try:original_path=safe(a.repo_root,original)
            except FileNotFoundError:originals_missing.append(original)
            else:
                # Byte equality is checked, in addition to SHA reconstruction.
                if original_path.read_bytes()!=raw:raise ValueError('Literal workspace original mismatch: '+original)
                originals_checked+=1
        index.append('\t'.join(str(row[k]) for k in ('group','original_path','path','original_bytes','original_sha256','stored_bytes','stored_sha256','encoding'))+'\n')
    if safe(archive,'INDEX.tsv').read_bytes()!=''.join(index).encode('utf-8'):raise ValueError('INDEX is not exact manifest inventory')
    result=dict(schema='polar.evidence.independent-reconstruction.v1',verified=not originals_missing,
        original_paths=len(rows),unique_blobs=len(stored_blobs),manifest_sha256=sha(manifest_raw),
        originals_requested=a.check_originals,originals_checked=originals_checked,originals_missing=originals_missing,
        scope='Package hashes/decompression/INDEX only' if not a.check_originals else 'Package plus literal current-workspace originals',
        algorithm_or_physics_execution=False)
    print(json.dumps(result,indent=2))
    return 0 if result['verified'] else 2


if __name__=='__main__':raise SystemExit(main())
