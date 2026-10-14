"""Explicit production evidence archive. Run only after parent releases fullQA freeze."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'rm_match').is_dir())
ALLOWED = {'.json','.jsonl','.log','.txt','.yaml','.yml','.md','.py','.stdout','.stderr','.gz','.bin','.xml','.hpp','.h','.cpp','.bgr','.cmake'}
GROUPS = {'a1': 'wsl-native-live-20261014-prepared-bgr-attempt1', 'a2': 'wsl-native-live-20261014-prepared-bgr-attempt2', 'a3': 'wsl-native-live-20261014-prepared-bgr-attempt3', 'd1': 'prepared-bgr-live-driver-20261014-01', 'd2': 'prepared-bgr-live-driver-20261014-02', 'd3': 'prepared-bgr-live-driver-20261014-03', 'f1': 'prepared-bgr-focused-20261014-01', 'f2': 'prepared-bgr-focused-20261014-02', 'f3': 'prepared-bgr-focused-20261014-03', 'f4': 'prepared-bgr-focused-20261014-04', 'f5': 'prepared-bgr-focused-20261014-05', 'linux': 'prepared-bgr-linux-cleanup-20261014-01', 'prov': 'prepared-bgr-provenance-20261014', 'valid': 'prepared-bgr-current-build-validation-20261014', 'start': 'prepared-native-startup-probe-20261014-01', 'navcpu': 'pb-wsl-hotpath-readonly-20261014-01', 'review': 'native-attempt12-readonly-review-20261014', 'sources': 'prepared-bgr-actual3-source-capture-20261014', 'build': 'native-original-nav-checkpoint-build-20261013', 'f6': 'prepared-bgr-focused-20261014-06', 'linux2': 'prepared-bgr-linux-cleanup-20261014-02', 'start2': 'prepared-native-startup-probe-20261014-02', 'q1': 'quality-20261014-prepared-bgr-frozen-01', 'qd1': 'prepared-bgr-quality-driver-20261014-01', 'q2': 'quality-20261014-prepared-bgr-frozen-02', 'qd2': 'prepared-bgr-quality-driver-20261014-02', 'post':'prepared-bgr-postcheck-docs-20261014', 'post2':'prepared-bgr-postcheck-docs-20261014-02'}
EXTRA = ('operator_native/runtime/build_portable.py', 'operator_native/runtime/CMakeLists.txt', 'operator_native/runtime/overlays/corners_contour_v3.cpp', 'operator_native/runtime/candidate/src/utility/model/common_model.hpp', 'operator_native/runtime/candidate/src/module/detector/models/shenzhen.hpp', 'operator_native/runtime/candidate/src/module/detector/armor_detection.cpp', 'artifacts/plan-checkpoint-draft-20261014-prepared-bgr/capture_current_sources.py', 'artifacts/plan-checkpoint-draft-20261014-prepared-bgr/update_postcheck_docs.py', 'artifacts/plan-checkpoint-draft-20261014-prepared-bgr/revise_postcheck_docs.py', 'artifacts/native-attempt12-readonly-review-20261014/PREPARED_REVIEW.json', 'artifacts/native-attempt12-readonly-review-20261014/REVIEW.json')
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
        # Exact public HEAD53fb source: semantic storage label, never a value.
        # File SHA and exact key/value both bind this exception; raw bytes stay.
        if source.name=='launcher.py' and sha(raw)=='241fd3660883763069577d34058fbc83b69b04ae64f11a7cda50b61edf7c3ed7':
            content=re.sub(r'["\']credential["\']\s*:\s*["\']provisioned_in_memory_at_launch["\']', '<public_storage_semantics_label>', content)
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
    assert target==ROOT/'docs/validation/native_prepared_bgr_20261014'
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
            if label=='build' and p.relative_to(source_root).parts[0] in ('bin','cmake'):
                omitted.append({'source':p.relative_to(ROOT).as_posix(),'reason':'ELF_objects_build_intermediates_not_bundled'})
                continue
            if p.name=='STOP':
                stop_records.append(p)
                continue
            if '__pycache__' in p.parts or (p.suffix.lower() not in ALLOWED and p.name!='tracking_mode'):
                omitted.append({'source':p.relative_to(ROOT).as_posix(),'reason':'cache_or_nontext_extension'})
            else: selected.append(p)
        for index,p in enumerate(selected): rows.append(store(p,label,index,target))
    for index,p in enumerate(stop_records): rows.append(store(p,'stop',index,target))
    for index,name in enumerate(EXTRA):
        p=ROOT/name;assert p.is_file(),'Explicit provenance recipe missing'
        rows.append(store(p,'refs',index,target))
    record=dict(schema='polar.evidence.literal-archive.v1',scope='Prepared-BGR native diagnostics and preserved startup/live failures; no live or milestone acceptance',
        files=rows,groups=groups,omitted=omitted,payload_count=len(rows),
        total_original_bytes=sum(r['original_bytes'] for r in rows),total_stored_bytes=sum(r['stored_bytes'] for r in rows),
        all_original_and_stored_bytes_verified=True,original_failures_retained=True,
        frozen_old438_archives_modified=False,elf_venv_dependency_bundled=False)
    (target/'PRESERVATION_MANIFEST.json').write_text(json.dumps(record,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    (target/'INDEX.tsv').write_text('stored_path\toriginal_sha256\tsource\n'+''.join('%s\t%s\t%s\n'%(r['stored_path'],r['original_sha256'],r['source']) for r in rows),encoding='utf8')
    print(json.dumps({k:record[k] for k in ('payload_count','total_original_bytes','total_stored_bytes','all_original_and_stored_bytes_verified')}))
if __name__=='__main__': main()
