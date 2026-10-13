"""Append verified, byte-exact text/raw-log groups; never overwrite old records.

Use --include-attempt2 only after the second actual run is frozen. Historical
source bytes are copied only when their SHA matches recorded execution identity.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
GROUPS={
    'f1':'pb-wsl-navigation-sil-actual-20261014-attempt1',
    'd1':'pb-wsl-navigation-driver-20261014-01',
    'std1':'pb-wsl-navigation-stdio-fixture-20261014-01',
    'std2':'pb-wsl-navigation-stdio-fixture-20261014-02',
    'clean':'wsl-owned-group-cleanup-20261014',
}
ALLOWED={'.json','.jsonl','.log','.txt','.yaml','.yml','.md','.py','.stdout','.stderr','.gz','.bin'}
MAX_FILE=24*1024*1024


def sha(raw):return hashlib.sha256(raw).hexdigest()


def no_links(path):
    for item in (path,*path.parents):
        if item.is_symlink() or (hasattr(item,'is_junction') and item.is_junction()):
            raise ValueError('archive link rejected:'+str(item))


def checked_bytes(src):
    no_links(src);raw=src.read_bytes()
    if len(raw)>MAX_FILE or raw.startswith((b'\x7fELF',b'MZ')):
        raise ValueError('oversize/executable archive input:'+str(src))
    scan=gzip.decompress(raw) if src.suffix=='.gz' else raw
    if len(scan)>MAX_FILE:raise ValueError('oversize decompressed evidence')
    # Raw logs may include the original mixed UTF-16 WSL warning. Preserve them
    # literally; scan byte patterns and both text views without re-encoding.
    candidates=(scan.decode('utf8',errors='ignore'),scan.decode('utf16',errors='ignore') if len(scan)%2==0 else '')
    for text in candidates:
        if re.search(r'Bearer [A-Za-z0-9._~-]{16,}|["\'](?:credential|admission_credential|password|api_key)["\']\s*:\s*["\'][A-Za-z0-9._~-]{16,}["\']',text,re.I):
            raise ValueError('literal credential must not be archived:'+str(src))
    return raw


def store(src,relative,rows,*,raw=None,extra=None):
    raw=checked_bytes(src) if raw is None else raw
    compressed=len(raw)>=65536 and src.suffix!='.gz'
    dest=HERE/(str(relative)+'.gz' if compressed else relative)
    no_links(dest.parent)
    if len(str(dest))>=240:raise ValueError('short archive destination required')
    if compressed:
        stream=io.BytesIO()
        with gzip.GzipFile(filename='',mode='wb',fileobj=stream,mtime=0,compresslevel=3) as handle:handle.write(raw)
        encoded=stream.getvalue()
    else:encoded=raw
    if dest.exists():
        if dest.read_bytes()!=encoded:raise ValueError('immutable archive record already differs:'+str(dest))
    else:
        dest.parent.mkdir(parents=True,exist_ok=True)
        with dest.open('xb') as output:output.write(encoded)
    reread=dest.read_bytes();restored=gzip.decompress(reread) if compressed else reread
    if restored!=raw:raise ValueError('archive raw bytes mismatch')
    if (extra is None or extra.get('source_origin')=='current_exact_sha') and src.read_bytes()!=raw:
        raise ValueError('original source changed during archive')
    key=dest.relative_to(HERE).as_posix()
    row=dict(source=src.relative_to(ROOT).as_posix(),stored_path=key,original_bytes=len(raw),original_sha256=sha(raw),
             stored_bytes=len(reread),stored_sha256=sha(reread),encoding='gzip_mtime0' if compressed else 'original_bytes',
             decoded_bytes_identical=True,source_unchanged=True)
    if extra:row.update(extra)
    if src.suffix=='.gz':row['existing_gzip_payload_sha256']=sha(gzip.decompress(raw))
    previous=next((r for r in rows if r['stored_path']==key),None)
    if previous is not None:
        if {k:v for k,v in previous.items() if k!='used_by'}!={k:v for k,v in row.items() if k!='used_by'}:
            raise ValueError('immutable archive metadata differs:'+key)
        if 'used_by' in row:previous['used_by']=sorted(set(previous['used_by'])|set(row['used_by']))
    else:rows.append(row)


def verify(rows):
    for row in rows:
        dest=HERE/row['stored_path'];no_links(dest)
        raw=dest.read_bytes()
        if len(raw)!=row['stored_bytes'] or sha(raw)!=row['stored_sha256']:raise ValueError('stored identity changed')
        decoded=gzip.decompress(raw) if row['encoding']=='gzip_mtime0' else raw
        if len(decoded)!=row['original_bytes'] or sha(decoded)!=row['original_sha256']:raise ValueError('original identity changed')


def archive(include_attempt2=False,include_attempt3=False,include_attempt4=False):
    manifest=HERE/'MANIFEST.json'
    previous=json.loads(manifest.read_text()) if manifest.exists() else None
    rows=[] if previous is None else previous['files'];verify(rows)
    groups=dict(GROUPS)
    if include_attempt2 or include_attempt3 or include_attempt4:groups.update(s2='pb-wsl-navigation-sil-actual-20261014-attempt2',d2='pb-wsl-navigation-driver-20261014-02')
    if include_attempt3 or include_attempt4:groups.update(s3='pb-wsl-navigation-sil-actual-20261014-attempt3',d3='pb-wsl-navigation-driver-20261014-03')
    if include_attempt4:groups.update(s4='pb-wsl-navigation-sil-actual-20261014-attempt4',d4='pb-wsl-navigation-driver-20261014-04')
    if include_attempt3 or include_attempt4:groups['a3']='pb-wsl-navigation-audit-20261014-03'
    if include_attempt4:groups['a4']='pb-wsl-navigation-audit-20261014-04'
    observed_sources={};missing=[];snapshots={}
    for name in ('pb-navigation-sil-config-20261014-04.json','run_pb_wsl_navigation_20261014_02.py'):
        src=ROOT/'artifacts'/name
        if src.is_file():store(src,Path('refs')/name,rows)
    store(ROOT/'artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json',
          Path('refs/ENVIRONMENT_COMPAT_FINAL.json'),rows)
    for attempt in range(2,5 if include_attempt4 else 4 if include_attempt3 else 3):
        source_manifest=ROOT/f'artifacts/pb-wsl-navigation-source-20261014-attempt{attempt}/MANIFEST.json'
        if (include_attempt2 or include_attempt3 or include_attempt4) and source_manifest.is_file():
            store(source_manifest,Path('refs')/f'ATTEMPT{attempt}_SOURCE_MANIFEST.json',rows)
            for item in json.loads(source_manifest.read_text())['files']:
                rel=item['path'];expected=item['sha256'];path=Path(rel)
                if path.is_absolute() or '..' in path.parts or not re.fullmatch('[a-f0-9]{64}',expected):
                    raise ValueError('invalid saved source identity')
                snapshot=source_manifest.parent/path
                raw=checked_bytes(snapshot)
                if sha(raw)!=expected:raise ValueError('saved source snapshot changed')
                snapshots[(rel,expected)]=snapshot
    for group,name in groups.items():
        base=ROOT/'artifacts'/name
        if not base.is_dir():raise ValueError('requested frozen group missing:'+name)
        # Never traverse a venv/clone. These exact small result directories contain
        # bounded logs/JSON/config/fixture drivers only.
        cases=sorted(p.name for p in base.iterdir() if p.is_dir() and p.name.startswith('test_'))
        case_map={name:f'c{i:02d}' for i,name in enumerate(cases,1)}
        for src in sorted(base.rglob('*')):
            if not src.is_file() or not (src.suffix in ALLOWED or src.name=='STOP'):continue
            relative=src.relative_to(base)
            if any(p in {'install','build','src','external','.git','venv','prefix'} or p.startswith('.venv') for p in relative.parts):
                raise ValueError('dependency/source tree not allowed in evidence group')
            parts=list(relative.parts)
            if parts[0] in case_map:parts[0]=case_map[parts[0]]
            store(src,Path(group).joinpath(*parts),rows)
        for result in (base/'RESULT.json',base/'FINAL_RESULT.json'):
            if not result.exists():continue
            value=json.loads(result.read_text())
            source=value.get('source_sha256',value.get('source_before',{}))
            if type(source) is not dict:continue
            for rel,digest in source.items():
                observed_sources.setdefault((rel,digest),[]).append(group)
    # Exact current source is valid only when it matches the run's recorded SHA.
    # For a changed file, obtain Git blob bytes only after exact hash equality.
    for (rel,expected),uses in sorted(observed_sources.items()):
        preserved=next((row for row in rows if row.get('executed_sha256')==expected and row['source']==rel),None)
        if preserved is not None:
            # verify(rows) already checked exact preserved bytes. Later live
            # source edits do not make an existing historical snapshot missing.
            preserved['used_by']=sorted(set(preserved['used_by'])|set(uses))
            continue
        src=ROOT/rel;raw=src.read_bytes() if src.is_file() else b'';origin='current_exact_sha'
        saved=snapshots.get((rel,expected))
        if sha(raw)!=expected and saved is not None:
            raw=checked_bytes(saved);origin='saved_snapshot_exact_sha'
        if sha(raw)!=expected:
            try:raw=subprocess.check_output(['git','show','HEAD:'+rel],cwd=ROOT,stderr=subprocess.DEVNULL)
            except subprocess.CalledProcessError:raw=b''
            origin='HEAD_git_blob_exact_sha'
        if sha(raw)!=expected:
            missing.append(dict(path=rel,expected_sha256=expected,used_by=uses,reason='no matching saved bytes; not reconstructed'))
            continue
        dest=Path('src')/('s_'+expected[:16]+'_'+Path(rel).name)
        # Check source payload for credentials using current path scanning when
        # exact; git blob payload was retrieved without altering its bytes.
        if origin=='current_exact_sha':checked_bytes(src)
        extra=dict(source_origin=origin,executed_sha256=expected,used_by=uses)
        if origin=='saved_snapshot_exact_sha':extra['saved_snapshot_path']=saved.relative_to(ROOT).as_posix()
        store(src,dest,rows,raw=raw,extra=extra)
    rows.sort(key=lambda r:r['stored_path']);verify(rows)
    result=dict(schema='polar.pb-windows-wsl-navigation-evidence.v1',files=rows,count=len(rows),
                original_total_bytes=sum(r['original_bytes'] for r in rows),stored_total_bytes=sum(r['stored_bytes'] for r in rows),
                missing_historical_sources=missing,all_raw_and_stored_verified=True,
                archive_script_sha256=sha(Path(__file__).read_bytes()),
                qualification='Windows/WSL navigation attempts and separately scoped harmless lifecycle fixtures; no full mission/match/HIL; no ELF/venv/dependency/source clone/secret bundled')
    if previous is not None:
        history=HERE/('MANIFEST_'+sha(manifest.read_bytes())[:12]+'.json')
        if not history.exists():history.write_bytes(manifest.read_bytes())
    manifest.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(count=len(rows),missing_historical_sources=len(missing),manifest_sha256=sha(manifest.read_bytes()),
                         original_total_bytes=result['original_total_bytes'],stored_total_bytes=result['stored_total_bytes'])))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--include-attempt2',action='store_true');parser.add_argument('--include-attempt3',action='store_true');parser.add_argument('--include-attempt4',action='store_true')
    args=parser.parse_args();archive(args.include_attempt2,args.include_attempt3,args.include_attempt4)
