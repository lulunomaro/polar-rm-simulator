"""Explicit followup selection. Run only after root announces QA/source freeze.

Immutable raw-content addressed blobs eliminate repeated source/pixel copies.
Every original path remains a distinct inventory row; no logs are reencoded.
"""
import argparse
import ast
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import stat

DESTINATION='docs/validation/aim_live_followup_20261014'
GROUPS={
    'losttarget':'aim-lost-target-fix-20261014-01',
    'consume_before':'native-consumption-sampling-20261014-before01',
    'consume_after1':'native-consumption-sampling-20261014-after01',
    'consume_after2':'native-consumption-sampling-20261014-after02',
    'stop_before':'wsl-jsonl-stop-poll-20261014-before01',
    'stop_after':'wsl-jsonl-stop-poll-20261014-after01',
    'stop_actual':'wsl-jsonl-followup-actual-20261014-01',
    'harmless_running':'wsl-jsonl-harmless-220bdc7f86b94003b77aa62bbbb38713',
    'harmless_leader_exit':'wsl-jsonl-harmless-cf4617eb031d42d3b85db44fda51b002',
    'scheduling_before':'host-scheduling-cli-20261014-before01',
    'scheduling_after':'host-scheduling-cli-20261014-after01',
    'amendment1':'aim-followup-source-amendment-20261014-01',
    'amendment2':'aim-followup-source-amendment-20261014-02',
    'amendment3':'aim-followup-source-amendment-20261014-03',
    'amendment4':'aim-followup-source-amendment-20261014-04',
    'cache_review_unimplemented':'control-snapshot-cache-review-20261014-01',
    'json_saved_input_only':'aim-json-serialization-offline-20261014-01',
    'pb_firstframe':'pb2025-aim-first-frame-probe-20261014-01',
    'pb_firstframe_audit':'pb2025-aim-first-frame-audit-20261014-01',
    'pb_controlled':'pb2025-aim-controlled-probe-20261014-01',
    'pb_controlled_fast':'pb2025-aim-controlled-fast-probe-20261014-01',
    'pb_controlled_fast_driver':'pb-aim-controlled-fast-driver-20261014-01',
    'formal_live':'aim-live-20261014-formal-scheduling-01',
    'formal_driver':'aim-formal-scheduling-driver-20261014-formal-scheduling-01',
    'quality_failed1':'quality-aim-followup-20261014-01',
    'quality_driver1':'aim-followup-quality-driver-20261014-01',
    'quality_final2':'quality-aim-followup-20261014-02',
    'quality_driver2':'aim-followup-quality-driver-20261014-02',
}
GIL_RUNS=(
    'production-cpu4-hostcv4-async-gil1ms01',
    'production-cpu4-hostcv4-async-gil05ms-fixed01',
    'production-cpu4-hostcv4-async-gil1ms-fixed02',
    'production-cpu4-hostcv4-async-gil1ms-affinity1-03',
    'production-cpu4-hostcv4-async-gil1ms-affinity16-04',
    'production-cpu4-hostcv4-async-gil08ms-affinity16-05',
    'production-cpu4-hostcv4-async-gil1ms-affinity16-lean-before06',
    'production-cpu4-hostcv4-async-gil1ms-affinity16-lean-repeat07',
)
for number,name in enumerate(GIL_RUNS,1):
    GROUPS[f'gil_live{number}']='aim-live-20261014-'+name
    GROUPS[f'gil_driver{number}']='aim-gil-driver-20261014-'+name

TEXT_SUFFIXES={'.json','.jsonl','.log','.xml','.py','.hpp','.h','.cpp','.c',
    '.txt','.yaml','.yml','.md','.toml','.patch','.tsv'}
ALLOWED_SUFFIXES=TEXT_SUFFIXES|{'.bgr','.rgb','.png','.gz'}
ALLOWED_NO_SUFFIX={'STOP','tracking_mode'}
EXCLUDED_NAMES={'sdk_events.json','admission.json','cmakecache.txt'}
EXCLUDED_PARTS={'models','weights','assets','bin','objects','upstream','external',
    'CMakeFiles','__pycache__','build','install','venv','.venv-linux','.venv-sim'}
SECRET_KEYS={'credential','admission_credential','access_token','bearer_token',
    'token','session_token','session_secret','authorization','password','api_key','secret',
    'polar_sim_admission_credential'}


def sha(raw):return hashlib.sha256(raw).hexdigest()


def safe(path,root):
    path=Path(path);root=Path(root).resolve()
    if not path.resolve().is_relative_to(root):raise ValueError('Path outside owned scope: '+str(path))
    current=path
    while current!=root:
        info=current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400):
            raise ValueError('Symlink/reparse path rejected: '+str(current))
        current=current.parent
    return path


def json_credentials(value):
    if type(value) is dict:
        for key,child in value.items():
            if key.lower() in SECRET_KEYS and child not in (None,''):
                # Reject even a hash-based grant document. No secret field is
                # silently redacted or rewritten into a purported original.
                raise ValueError('Credential-bearing JSON field rejected: '+key)
            json_credentials(child)
    elif type(value) is list:
        for child in value:json_credentials(child)


def inspect_text(path,raw):
    suffix=path.suffix.lower()
    if suffix not in TEXT_SUFFIXES:return
    text=raw.decode('utf-8-sig')
    if suffix=='.json':json_credentials(json.loads(text))
    elif suffix=='.jsonl':
        for line in text.splitlines():
            if line.strip():json_credentials(json.loads(line))
    if suffix=='.xml' and re.search(r'<net\s+[^>]*version=',text[:4096]):
        raise ValueError('OpenVINO model XML is not an evidence log: '+str(path))
    if re.search(r'(?i)(?:authorization\s*:\s*bearer|POLAR_SIM_ADMISSION_CREDENTIAL\s*[=:]\s*[^\s\"\']+)',text):
        raise ValueError('Possible real credential in text: '+str(path))
    if suffix=='.py':
        # Public APIs mention credential keys. Reject literal assigned values,
        # rather than suppressing every line containing the word credential.
        try:tree=ast.parse(text)
        except SyntaxError:return  # Literal diagnostic fragments remain literal.
        for node in ast.walk(tree):
            pairs=[]
            if isinstance(node,ast.Dict):pairs=zip(node.keys,node.values)
            elif isinstance(node,ast.Call):pairs=((ast.Constant(k.arg),k.value) for k in node.keywords if k.arg)
            elif isinstance(node,(ast.Assign,ast.AnnAssign)):
                targets=node.targets if isinstance(node,ast.Assign) else [node.target]
                pairs=((ast.Constant(t.id),node.value) for t in targets if isinstance(t,ast.Name))
            for key,value in pairs:
                if (isinstance(key,ast.Constant) and type(key.value) is str and key.value.lower() in SECRET_KEYS
                        and isinstance(value,ast.Constant) and type(value.value) is str and value.value):
                    raise ValueError('Literal credential-like source value requires explicit review: '+str(path))


def selection(source):
    accepted=[];excluded=[]
    for current,dirs,names in os.walk(source,followlinks=False):
        current=Path(current);safe(current,source)
        for name in list(dirs):
            child=current/name
            if name in EXCLUDED_PARTS:
                excluded.append({'path':child.relative_to(source).as_posix()+'/',
                    'reason':'excluded dependency/model/build directory'});dirs.remove(name)
            else:safe(child,source)
        for name in sorted(names):
            path=current/name;safe(path,source);rel=path.relative_to(source).as_posix()
            reason=None
            if name.lower() in EXCLUDED_NAMES:reason='admission/SDK credential surface excluded'
            elif path.suffix.lower() not in ALLOWED_SUFFIXES and name not in ALLOWED_NO_SUFFIX:reason='non-evidence/binary extension excluded'
            if reason:excluded.append({'path':rel,'reason':reason});continue
            accepted.append(path)
    return sorted(accepted),excluded


def write_json(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')


def default_repo():
    for parent in Path(__file__).resolve().parents:
        if (parent/'pyproject.toml').is_file() and (parent/'.git').exists():return parent
    raise ValueError('Pass explicit --repo-root; repository was not found')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root',type=Path)
    parser.add_argument('--generate',action='store_true',help='Only use after root authorizes post-QA evidence append')
    parser.add_argument('--audit-selection',action='store_true',help='Read-only inventory/token preflight; no compression or permanent package')
    args=parser.parse_args(argv);root=(args.repo_root or default_repo()).resolve()
    if args.generate and args.audit_selection:parser.error('Choose audit or generation, never both')
    if not args.generate and not args.audit_selection:
        print(json.dumps({'planned_destination':DESTINATION,'groups':GROUPS,
            'state':'PLAN_ONLY_NO_FILES_WRITTEN','cache_review':'unimplemented rejected optimization',
            'scope':'Local static live is separate from PB failure, saved-input/offline analysis, harmless lifecycle and full QA'},indent=2))
        return
    out=root/DESTINATION
    if out.exists():raise ValueError('Fresh archive required; never overwrite preserved evidence')
    prepared=[];excluded=[];missing=[]
    # Validate every original before creating the permanent package. The output
    # must remain incomplete on any race or verifier failure, never called clean.
    for label,relative in GROUPS.items():
        source=root/'artifacts'/relative
        if not source.is_dir():missing.append(relative);continue
        safe(source,root/'artifacts')
        paths,omissions=selection(source)
        excluded += [dict(group=label,original_path='artifacts/'+relative+'/'+r['path'],reason=r['reason']) for r in omissions]
        prepared += [(label,path) for path in paths]
    if missing:raise ValueError('Required groups missing: '+','.join(missing))
    if args.audit_selection:
        inventory=[];group_totals={};total=0;text_checked=0
        for label,path in prepared:
            safe(path,root/'artifacts');size=path.stat().st_size;digest=None
            with path.open('rb') as stream:magic=stream.read(4)
            if magic.startswith((b'\x7fELF',b'MZ')):raise ValueError('Executable file refused: '+str(path))
            if path.suffix.lower() in TEXT_SUFFIXES or path.suffix.lower()=='.gz':
                raw=path.read_bytes();inspect_text(path,raw)
                if path.suffix.lower()=='.gz':inspect_text(path.with_suffix(''),gzip.decompress(raw))
                digest=sha(raw);text_checked+=1
            if path.stat().st_size!=size:raise ValueError('Input changed during inventory')
            inventory.append(dict(group=label,original_path=path.relative_to(root).as_posix(),original_bytes=size,
                text_sha256=digest,binary_full_digest_deferred=digest is None))
            total+=size
            counts=group_totals.setdefault(label,dict(files=0,bytes=0));counts['files']+=1;counts['bytes']+=size
        result=dict(schema='polar.evidence.selection-preflight.v1',original_paths=len(inventory),
            original_bytes=total,text_or_gzip_inputs_scanned=text_checked,groups=group_totals,
            files=inventory,omissions=excluded,missing_groups=[],
            unique_blob_count=None,compressed_unique_bytes=None,
            scope='Read-only metadata and credential preflight; binary full hashes/compression/literal proof deferred to authorized generation',
            permanent_package_generated=False,algorithm_or_physics_execution=False)
        write_json(Path(__file__).with_name('SELECTION_AUDIT.json'),result)
        print(json.dumps({k:v for k,v in result.items() if k not in ('files','omissions','groups')},indent=2))
        return
    safe(root/'docs/validation',root)
    out.mkdir(parents=True,exist_ok=False);blobs={};rows=[]
    for label,path in prepared:
        safe(path,root/'artifacts');raw=path.read_bytes()
        if raw.startswith((b'\x7fELF',b'MZ')):raise ValueError('Executable file refused: '+str(path))
        inspect_text(path,raw)
        if path.suffix.lower()=='.gz':
            unpacked=gzip.decompress(raw)
            if unpacked.startswith((b'\x7fELF',b'MZ')):raise ValueError('Compressed executable refused: '+str(path))
            inspect_text(path.with_suffix(''),unpacked)
        digest=sha(raw)
        if digest not in blobs:
            compress=len(raw)>65536
            relative='blobs/'+digest[:2]+'/'+digest+('.gz' if compress else '.bin')
            target=out/relative;target.parent.mkdir(parents=True,exist_ok=True)
            if compress:
                with target.open('xb') as stream:
                    with gzip.GzipFile(filename='',mode='wb',fileobj=stream,compresslevel=6,mtime=0) as encoded:encoded.write(raw)
            else:target.write_bytes(raw)
            stored=target.read_bytes()
            rebuilt=gzip.decompress(stored) if compress else stored
            if rebuilt!=raw:raise ValueError('Literal byte reconstruction mismatch')
            blobs[digest]=dict(path=relative,encoding='gzip' if compress else 'literal',
                stored_bytes=len(stored),stored_sha256=sha(stored))
        row=dict(group=label,original_path=path.relative_to(root).as_posix(),
            original_bytes=len(raw),original_sha256=digest,**blobs[digest])
        if path.read_bytes()!=raw:raise ValueError('Original changed during preservation: '+str(path))
        rows.append(row)
    manifest=dict(schema='polar.evidence.content-addressed.v1',files=rows,groups=GROUPS,
        omissions=excluded,missing_groups=[],qualification='Evidence preservation only; no new algorithm or physics execution',
        cache_review='unimplemented optimization; never represented as a product change')
    write_json(out/'PRESERVATION_MANIFEST.json',manifest)
    (out/'INDEX.tsv').write_text('group\toriginal_path\tstored_path\toriginal_bytes\toriginal_sha256\tstored_bytes\tstored_sha256\tencoding\n'+
        ''.join('\t'.join(str(row[k]) for k in ('group','original_path','path','original_bytes','original_sha256','stored_bytes','stored_sha256','encoding'))+'\n' for row in rows),encoding='utf-8')
    (out/'.gitattributes').write_text('* -text -whitespace\n',encoding='utf-8')
    (out/'archive_evidence.py').write_bytes(Path(__file__).read_bytes())
    (out/'verify_archive.py').write_bytes(Path(__file__).with_name('verify_archive.py').read_bytes())
    write_json(out/'GENERATION_RECEIPT.json',dict(original_paths=len(rows),unique_blobs=len(blobs),
        original_bytes=sum(r['original_bytes'] for r in rows),stored_unique_bytes=sum(r['stored_bytes'] for r in blobs.values()),
        manifest_sha256=sha((out/'PRESERVATION_MANIFEST.json').read_bytes()),
        originals_compared_during_generation=True,scope='Originals at generation time; independent verifier still required'))
    print((out/'GENERATION_RECEIPT.json').read_text())


if __name__=='__main__':main()
