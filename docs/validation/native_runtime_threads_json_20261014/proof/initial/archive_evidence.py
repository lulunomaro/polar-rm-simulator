"""Draft: fresh literal archive only after parent releases the QA source freeze.

No importing simulation, running tests or launching native/ROS/WSL processes.
Default is plan-only. Selection must explicitly be released before --run.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'rm_match').is_dir())
DESTINATION='docs/validation/native_runtime_threads_json_20261014'
MAX_BYTES=32*1024*1024
ALLOWED={'.json','.jsonl','.log','.txt','.yaml','.yml','.md','.py','.stdout','.stderr','.gz','.xml','.hpp','.h','.cpp','.cmake','.bgr'}
EXCLUDED_DIRS={'bin','cmake','CMakeFiles','build','install','objects','venv','__pycache__','.git','.pytest_cache','.mypy_cache','.ruff_cache'}


def sha(raw):return hashlib.sha256(raw).hexdigest()


def fail(message):raise ValueError(message)


def relative(value):
    if type(value) is not str or not value or '\\' in value or ':' in value:fail('noncanonical relative path')
    path=PurePosixPath(value)
    if path.is_absolute() or any(p in ('','.','..') for p in path.parts):fail('unsafe relative path')
    if str(path)!=value:fail('relative path not canonical')
    return Path(*path.parts)


def links_rejected(path):
    for p in (path,*path.parents):
        if not p.exists() and not p.is_symlink():continue
        info=p.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
            fail('symlink/reparse input rejected: '+str(p))


def json_checked(raw):
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:fail('duplicate JSON key')
            result[k]=v
        return result
    def constant(_):fail('nonfinite JSON')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)


def bounded_gzip(raw):
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:value=stream.read(MAX_BYTES+1)
    if len(value)>MAX_BYTES:fail('decompressed input exceeds bound')
    return value


def checked(path,exceptions):
    links_rejected(path)
    if not path.is_file() or path.stat().st_size>MAX_BYTES:fail('missing/oversized input: '+str(path))
    raw=path.read_bytes()
    if len(raw)>MAX_BYTES or raw.startswith((b'\x7fELF',b'MZ')):fail('executable/oversized payload: '+str(path))
    decoded=bounded_gzip(raw) if path.suffix=='.gz' else raw
    if decoded.startswith((b'\x7fELF',b'MZ')):fail('compressed executable rejected')
    text_candidates=[decoded.decode('utf8',errors='ignore')]
    if len(decoded)%2==0:text_candidates.append(decoded.decode('utf16',errors='ignore'))
    for content in text_candidates:
        # Exception is a source SHA plus one exact public semantic label. It
        # never redacts or changes stored bytes and never accepts raw secrets.
        for exception in exceptions:
            if exception['source']==path.relative_to(ROOT).as_posix() and exception['sha256']==sha(raw):
                content=content.replace(exception['literal'], '<reviewed_public_semantic_label>')
        if re.search(r'Bearer [A-Za-z0-9._~-]{16,}|["\'](?:credential|admission_credential|password|api_key)["\']\s*:\s*["\'][A-Za-z0-9._~-]{16,}["\']',content,re.I):
            fail('literal credential value rejected: '+str(path))
    return raw


def select_inputs(selection):
    selected=[];omitted=[]
    for label,name in selection['groups'].items():
        if not re.fullmatch('[a-z][a-z0-9_]{0,23}',label) or label=='build':fail('bad/ignored group label')
        rel=relative(name)
        if len(rel.parts)!=1:fail('group directory must be literal artifact basename')
        base=ROOT/'artifacts'/rel;links_rejected(base)
        if not base.is_dir():fail('required group missing: '+name)
        paths=[]
        for current,dirs,files in os.walk(base,followlinks=False):
            parent=Path(current);links_rejected(parent)
            kept=[]
            for directory in sorted(dirs):
                entry=parent/directory;links_rejected(entry)
                if directory in EXCLUDED_DIRS or directory.startswith('.venv') or (parent==base and directory in ('models','model')):
                    omitted.append(dict(source=entry.relative_to(ROOT).as_posix(),reason='ELF_model_objects_dependencies_cache_directory_excluded'))
                else:kept.append(directory)
            dirs[:]=kept
            for name in sorted(files):
                path=parent/name;links_rejected(path)
                allowed=path.suffix.lower() in ALLOWED or path.name in ('STOP','tracking_mode') or path.name.endswith(('.stdout.bin','.stderr.bin'))
                if not allowed:
                    omitted.append(dict(source=path.relative_to(ROOT).as_posix(),reason='non-evidence extension excluded'))
                else:paths.append(path)
        for index,path in enumerate(sorted(paths)):selected.append((label,index,path))
    for index,name in enumerate(selection['extra']):
        path=ROOT/relative(name)
        if not path.is_file():fail('explicit provenance source missing: '+name)
        selected.append(('refs',index,path))
    return selected,omitted


def store(source,label,index,dest,expected,exceptions):
    raw=checked(source,exceptions)
    if sha(raw)!=expected:fail('source changed after preflight: '+str(source))
    compressed=len(raw)>=65536 and source.suffix!='.gz'
    if compressed:
        buffer=io.BytesIO()
        with gzip.GzipFile(filename='',mode='wb',fileobj=buffer,mtime=0,compresslevel=3) as stream:stream.write(raw)
        payload=buffer.getvalue()
    else:payload=raw
    suffix=source.suffix if source.suffix else '.txt'
    rel=Path(label)/('f%05d%s%s'%(index,suffix,'.gz' if compressed else ''))
    target=dest/rel
    if len(str(target))>=240:fail('Windows archive path too long')
    target.parent.mkdir(parents=True,exist_ok=True);links_rejected(target.parent)
    with target.open('xb') as stream:stream.write(payload)
    stored=target.read_bytes();decoded=bounded_gzip(stored) if compressed else stored
    if decoded!=raw or source.read_bytes()!=raw:fail('literal source/store byte mismatch')
    return dict(source=source.relative_to(ROOT).as_posix(),stored_path=rel.as_posix(),original_bytes=len(raw),original_sha256=sha(raw),
        stored_bytes=len(stored),stored_sha256=sha(stored),encoding='gzip_mtime0' if compressed else 'original_bytes',decoded_bytes_identical=True,source_unchanged=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection',type=Path,default=Path(__file__).with_name('SELECTION.json'))
    parser.add_argument('--run',action='store_true')
    args=parser.parse_args();links_rejected(args.selection.absolute())
    selection_raw=args.selection.read_bytes();selection=json_checked(selection_raw)
    if type(selection) is not dict or selection.get('schema')!='polar.runtime-threads.archive-selection.v1':fail('selection schema')
    if selection.get('destination')!=DESTINATION:fail('only the new fixed package destination is allowed')
    if type(selection.get('groups')) is not dict or type(selection.get('extra')) is not list:fail('selection groups/extra')
    if not args.run:
        print(json.dumps(dict(mode='plan_only',destination=DESTINATION,groups=selection['groups'],pending=selection['pending'],released=selection['released_for_archive'])));return
    if selection.get('released_for_archive') is not True or selection.get('pending')!=[]:fail('parent QA/source freeze not released')
    dest=ROOT/DESTINATION;links_rejected(dest)
    if dest.exists():fail('fresh package required; previous/partial packages are never overwritten')
    exceptions=selection['credential_label_exceptions']
    if type(exceptions) is not list:fail('exception list required')
    for e in exceptions:
        if type(e) is not dict or set(e)!={'source','sha256','literal'} or not re.fullmatch('[0-9a-f]{64}',e['sha256']):fail('narrow reviewed exception required')
        relative(e['source'])
        if type(e['literal']) is not str or len(e['literal'])<8:fail('exact semantic label required')
    selected,omitted=select_inputs(selection)
    # Preflight every literal before creating the package, including credentials.
    expected={str(path):sha(checked(path,exceptions)) for _,_,path in selected}
    dest.mkdir(parents=True,exist_ok=False)
    rows=[store(path,label,index,dest,expected[str(path)],exceptions) for label,index,path in selected]
    controls={}
    for name,source in (('archive_evidence.py',Path(__file__)),('verify_archive.py',Path(__file__).with_name('verify_archive.py')),
                        ('README.md',Path(__file__).with_name('README.draft.md')),('SELECTION.json',args.selection),
                        ('.gitattributes',Path(__file__).with_name('package.gitattributes'))):
        raw=source.read_bytes();(dest/name).write_bytes(raw);controls[name]=sha(raw)
    if args.selection.read_bytes()!=selection_raw:fail('selection changed during archive')
    manifest=dict(schema='polar.evidence.literal-archive.v1',scope=selection['scope'],groups=selection['groups'],files=rows,omitted=omitted,
        payload_count=len(rows),total_original_bytes=sum(r['original_bytes'] for r in rows),total_stored_bytes=sum(r['stored_bytes'] for r in rows),
        controls_sha256=controls,all_original_and_stored_bytes_verified=True,original_failures_retained=True,
        older_packages_modified=False,ELF_models_objects_venv_bundled=False,live80_qualified=False,sentry_production_revalidated=False)
    (dest/'PRESERVATION_MANIFEST.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    (dest/'INDEX.tsv').write_text('stored_path\toriginal_sha256\tsource\n'+''.join('%s\t%s\t%s\n'%(r['stored_path'],r['original_sha256'],r['source']) for r in rows),encoding='utf8')
    print(json.dumps(dict(destination=str(dest),payload_count=len(rows),stored_and_restored_byteidentical=True,selection_sha256=sha(selection_raw))))


if __name__=='__main__':main()
