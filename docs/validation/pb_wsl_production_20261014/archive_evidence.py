"""Explicit production evidence archive. Run only after parent releases fullQA freeze."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'rm_match').is_dir())
ALLOWED = {'.json','.jsonl','.log','.txt','.yaml','.yml','.md','.py','.stdout','.stderr','.gz','.bin','.xml','.hpp','.h','.cpp'}
GROUPS = {
    's1':'pb-wsl-production-sil-actual-20261014-attempt1', 'd1':'pb-wsl-production-driver-20261014-01',
    's2':'pb-wsl-production-sil-actual-20261014-attempt2', 'd2':'pb-wsl-production-driver-20261014-02',
    's3':'pb-wsl-production-sil-actual-20261014-attempt3', 'd3':'pb-wsl-production-driver-20261014-03',
    'f1':'pb-production-focused-20261014-01', 'f2':'pb-production-focused-20261014-02',
    'r6':'pb-wsl-session-repair-20261014-06',
    'p1':'pb-wsl-production-phase-audit-20261014-01', 'p2':'pb-wsl-production-phase-audit-20261014-02',
    'p3':'pb-wsl-production-phase-audit-20261014-03',
    'c1':'pb-external-goal-costmap-fixture-20261014-01', 'c2':'pb-external-goal-costmap-fixture-20261014-02',
    'path':'pb-external-goal-path-fixture-20261014-01',
    're':'pb-external-goal-review-20261014-01', 'rn':'pb-wsl-navigation-review-20261014-05',
    'pr':'pb-progress-audit-20261014-05',
    'a2':'pb-wsl-production-audit-20261014-02', 'a3':'pb-wsl-production-audit-20261014-03',
    'q1':'quality-20261014-wsl-production-frozen-01', 'qd1':'pb-production-quality-driver-20261014-01',
    'q2':'quality-20261014-wsl-production-frozen-02', 'qd2':'pb-production-quality-driver-20261014-02',
    'http':'platform-http-rejection-20261014-01',
    'post':'pb-postcheck-documentation-20261014',
    'post2':'pb-postcheck-documentation-20261014-02',
}
EXTRA = ('artifacts/update_platform_http_provenance_20261014.py',
         'artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json',
         'artifacts/pb-navigation-sil-config-20261014-04.json',
         'DEVELOPMENT_CHANGES.json', 'EXTRACTION_VALIDATION.json',
         'artifacts/preserve_postcheck_documentation_20261014.py')
MAX_BYTES = 32*1024*1024
def sha(raw): return hashlib.sha256(raw).hexdigest()
def links_rejected(path):
    for p in (path,*path.parents):
        if p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()):
            raise ValueError('Archive link rejected: '+str(p))
def checked(source):
    links_rejected(source)
    raw=source.read_bytes()
    if len(raw)>MAX_BYTES or raw.startswith((b'\x7fELF',b'MZ')):
        raise ValueError('Executable or oversized input: '+str(source))
    scan=gzip.decompress(raw) if source.suffix=='.gz' else raw
    if len(scan)>MAX_BYTES: raise ValueError('Decompressed evidence exceeds bound')
    candidates=(scan.decode('utf8',errors='ignore'),scan.decode('utf16',errors='ignore') if len(scan)%2==0 else '')
    for content in candidates:
        if re.search(r'Bearer [A-Za-z0-9._~-]{16,}|["\'](?:credential|admission_credential|password|api_key)["\']\s*:\s*["\'][A-Za-z0-9._~-]{16,}["\']',content,re.I):
            raise ValueError('Literal credential rejected: '+str(source))
    return raw
def store(source,group,index,target):
    raw=checked(source)
    compressed=len(raw)>=65536 and source.suffix!='.gz'
    if compressed:
        buffer=io.BytesIO()
        with gzip.GzipFile(filename='',mode='wb',fileobj=buffer,mtime=0,compresslevel=3) as stream: stream.write(raw)
        encoded=buffer.getvalue()
    else: encoded=raw
    relative=Path(group)/('f%03d%s%s'%(index,source.suffix,'.gz' if compressed else ''))
    dest=target/relative
    assert len(str(dest))<240,'Short Windows path required'
    links_rejected(dest.parent)
    dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists(): assert dest.read_bytes()==encoded,'Immutable existing payload differs'
    else:
        with dest.open('xb') as stream: stream.write(encoded)
    stored=dest.read_bytes()
    restored=gzip.decompress(stored) if compressed else stored
    assert restored==raw and source.read_bytes()==raw,'Literal source/storage byte mismatch'
    return dict(source=source.relative_to(ROOT).as_posix(),stored_path=relative.as_posix(),
        original_sha256=sha(raw),stored_sha256=sha(stored),original_bytes=len(raw),stored_bytes=len(stored),
        encoding='gzip_mtime0' if compressed else 'original_bytes',decoded_bytes_identical=True,source_unchanged=True)
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dest',type=Path,required=True)
    parser.add_argument('--without-final-quality',action='store_true')
    args=parser.parse_args();target=args.dest.absolute()
    assert target==ROOT/'docs/validation/pb_wsl_production_20261014'
    links_rejected(target)
    groups=dict(GROUPS)
    if args.without_final_quality:
        groups.pop('q2');groups.pop('qd2')
    target.mkdir(parents=True,exist_ok=True)
    rows=[];omitted=[];stop_records=[]
    for label,name in groups.items():
        source_root=ROOT/'artifacts'/name
        assert source_root.is_dir(),'Expected frozen group missing: '+name
        selected=[]
        for p in sorted(source_root.rglob('*')):
            if not p.is_file(): continue
            if p.name=='STOP':
                stop_records.append(p)
                continue
            if '__pycache__' in p.parts or p.suffix.lower() not in ALLOWED:
                omitted.append({'source':p.relative_to(ROOT).as_posix(),'reason':'cache_or_nontext_extension'})
            else: selected.append(p)
        for index,p in enumerate(selected): rows.append(store(p,label,index,target))
    for index,p in enumerate(stop_records): rows.append(store(p,'stop',index,target))
    for index,name in enumerate(EXTRA):
        p=ROOT/name;assert p.is_file(),'Explicit provenance recipe missing'
        rows.append(store(p,'refs',index,target))
    record=dict(schema='polar.evidence.literal-archive.v1',scope='Single-generation production Gate/external QA goal; not milestone or full match acceptance',
        files=rows,groups=groups,omitted=omitted,payload_count=len(rows),
        total_original_bytes=sum(r['original_bytes'] for r in rows),total_stored_bytes=sum(r['stored_bytes'] for r in rows),
        all_original_and_stored_bytes_verified=True,original_failures_retained=True,
        frozen_old438_archives_modified=False,elf_venv_dependency_bundled=False)
    (target/'PRESERVATION_MANIFEST.json').write_text(json.dumps(record,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    (target/'INDEX.tsv').write_text('stored_path\toriginal_sha256\tsource\n'+''.join('%s\t%s\t%s\n'%(r['stored_path'],r['original_sha256'],r['source']) for r in rows),encoding='utf8')
    print(json.dumps({k:record[k] for k in ('payload_count','total_original_bytes','total_stored_bytes','all_original_and_stored_bytes_verified')}))
if __name__=='__main__': main()
