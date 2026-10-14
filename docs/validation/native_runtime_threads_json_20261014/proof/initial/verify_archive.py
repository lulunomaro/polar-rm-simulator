"""Independent package-only literal verifier; no archive/simulation imports.

Original artifacts are required only with explicit --check-originals.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat

MAX_BYTES=32*1024*1024


def fail(message):raise ValueError(message)
def sha(raw):return hashlib.sha256(raw).hexdigest()


def rel_checked(value):
    if type(value) is not str or not value or '\\' in value or ':' in value:fail('noncanonical relative path')
    p=PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or str(p)!=value:fail('relative path escapes package')
    return Path(*p.parts)


def links_rejected(path):
    for p in (path,*path.parents):
        if not p.exists() and not p.is_symlink():continue
        info=p.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:fail('package/original symlink or reparse path')


def integer(value):return type(value) is int and 0<=value<=MAX_BYTES
def hash_value(value):return type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None


def json_checked(raw):
    def pairs(items):
        d={}
        for k,v in items:
            if k in d:fail('duplicate manifest key')
            d[k]=v
        return d
    def constant(_):fail('nonfinite manifest')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)


def read_bounded(path):
    links_rejected(path)
    if not path.is_file() or path.stat().st_size>MAX_BYTES:fail('missing/oversized package payload: '+str(path))
    raw=path.read_bytes()
    if len(raw)>MAX_BYTES:fail('oversized payload')
    return raw


def restore_gzip(raw):
    if raw[:2]!=b'\x1f\x8b' or raw[4:8]!=b'\0\0\0\0':fail('noncanonical evidence gzip mtime')
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:value=stream.read(MAX_BYTES+1)
    if len(value)>MAX_BYTES:fail('decoded gzip exceeds bound')
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--check-originals',action='store_true')
    parser.add_argument('--repo-root',type=Path,help='Optional original repository root, used only by --check-originals')
    args=parser.parse_args();target=args.archive.absolute();links_rejected(target)
    # Package-only mode deliberately does not search for a workspace or read
    # anything under original source paths; a fresh clone needs only this pack.
    repo=None
    if args.check_originals:
        repo=args.repo_root.absolute() if args.repo_root is not None else next((p for p in target.parents if (p/'rm_match').is_dir()),None)
        if repo is None:fail('strict-originals requires --repo-root or original repository')
        links_rejected(repo)
    raw=read_bounded(target/'PRESERVATION_MANIFEST.json');m=json_checked(raw)
    if type(m) is not dict or m.get('schema')!='polar.evidence.literal-archive.v1':fail('wrong manifest schema')
    if type(m.get('files')) is not list or type(m.get('payload_count')) is not int or m['payload_count']!=len(m['files']):fail('wrong payload count')
    seen=set();originals=0
    for row in m['files']:
        required={'source','stored_path','original_bytes','original_sha256','stored_bytes','stored_sha256','encoding','decoded_bytes_identical','source_unchanged'}
        if type(row) is not dict or set(row)!=required:fail('unexpected payload record')
        relative=rel_checked(row['stored_path']);source=rel_checked(row['source'])
        if relative.as_posix() in seen:fail('duplicate stored payload path')
        seen.add(relative.as_posix())
        if not all(integer(row[k]) for k in ('original_bytes','stored_bytes')) or not all(hash_value(row[k]) for k in ('original_sha256','stored_sha256')):fail('wrong record size/hash types')
        if row['decoded_bytes_identical'] is not True or row['source_unchanged'] is not True:fail('unverified archive row')
        stored=read_bounded(target/relative)
        if sha(stored)!=row['stored_sha256'] or len(stored)!=row['stored_bytes']:fail('stored byte mismatch: '+str(relative))
        if row['encoding']=='gzip_mtime0':decoded=restore_gzip(stored)
        elif row['encoding']=='original_bytes':decoded=stored
        else:fail('unknown storage encoding')
        if sha(decoded)!=row['original_sha256'] or len(decoded)!=row['original_bytes']:fail('restored byte mismatch: '+str(relative))
        if decoded.startswith((b'\x7fELF',b'MZ')):fail('executable payload rejected')
        if args.check_originals:
            actual=read_bounded(repo/source)
            if actual!=decoded:fail('current original differs: '+row['source'])
            originals+=1
    if m.get('total_original_bytes')!=sum(r['original_bytes'] for r in m['files']) or m.get('total_stored_bytes')!=sum(r['stored_bytes'] for r in m['files']):fail('manifest byte totals mismatch')
    expected='stored_path\toriginal_sha256\tsource\n'+''.join('%s\t%s\t%s\n'%(r['stored_path'],r['original_sha256'],r['source']) for r in m['files'])
    if read_bounded(target/'INDEX.tsv').decode('utf8')!=expected:fail('INDEX differs from manifest')
    if type(m.get('controls_sha256')) is not dict:fail('control file hashes absent')
    for name,h in m['controls_sha256'].items():
        if not hash_value(h) or sha(read_bounded(target/rel_checked(name)))!=h:fail('archive control changed')
    print(json.dumps(dict(schema='polar.evidence.independent-literal-verification.v1',passed=True,
        checked_payloads=len(seen),stored_and_restored_sha_verified=True,originals_checked=args.check_originals,
        originals_verified=originals,package_only_independent_of_original_workspace=not args.check_originals,
        preservation_manifest_sha256=sha(raw),scope='Package plus exact current originals' if args.check_originals else 'Package byte hashes and INDEX only; originals not inspected',
        live80_qualified=False,sentry_production_revalidated=False)))


if __name__=='__main__':main()
