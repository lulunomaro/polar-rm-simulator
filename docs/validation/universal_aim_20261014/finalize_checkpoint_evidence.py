"""Preserve a new zero-image probe and prove bytes; do not alter tested programs."""
from pathlib import Path
import gzip, hashlib, json, subprocess

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/validation/universal_aim_20261014'
DELIVERY=ROOT/'artifacts/aim-git-delivery-20261014-01'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def write(path,value):path.write_bytes((json.dumps(value,indent=2,sort_keys=True)+'\n').encode())

template=ROOT/'examples/aim_plugins.json'
original=template.read_bytes()
normalized=original.replace(b'\r\n',b'\n')
assert json.loads(original)==json.loads(normalized)
if original!=normalized:
    (DELIVERY/'aim_plugins.before-eol.json').write_bytes(original)
    template.write_bytes(normalized)
write(DELIVERY/'TEMPLATE_EOL_EQUIVALENCE.json',dict(before_sha256=sha(original),after_sha256=sha(normalized),parsed_json_equal=True,only_crlf_to_lf=True))

mp=OUT/'PRESERVATION_MANIFEST.json';manifest=json.loads(mp.read_bytes())
group=OUT/'pbprobe'
if group.exists():raise ValueError('Fresh proof group required')
files=sorted(p for p in (ROOT/'artifacts/pb2025-aim-registration-probe-20261014-01').rglob('*')
    if p.is_file() and not p.is_symlink() and '__pycache__' not in p.parts
    and p.suffix in ('.json','.jsonl','.py','.yaml','.log','.txt','.md'))
for i,p in enumerate(files,1):
    raw=p.read_bytes();compress=len(raw)>65536
    stored=gzip.compress(raw,compresslevel=6,mtime=0) if compress else raw
    target=group/(f'{i:04d}'+p.suffix+('.gz' if compress else ''))
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(stored)
    manifest['files'].append(dict(path=target.relative_to(OUT).as_posix(),original_path=p.relative_to(ROOT).as_posix(),original_bytes=len(raw),original_sha256=sha(raw),encoding='gzip' if compress else 'literal',stored_bytes=len(stored),stored_sha256=sha(stored)))
write(mp,manifest)
(OUT/'INDEX.tsv').write_bytes(('stored_path\toriginal_path\toriginal_sha256\n'+''.join(f"{r['path']}\t{r['original_path']}\t{r['original_sha256']}\n" for r in manifest['files'])).encode())
(OUT/'finalize_checkpoint_evidence.py').write_bytes(Path(__file__).read_bytes())

qa=json.loads((ROOT/'artifacts/quality-aim-universal-20261014-02/manifest.json').read_bytes())
differences=[];missing=[];programs=0
for n,expected in qa['source_files_sha256'].items():
    p=ROOT/n
    if not p.is_file():missing.append(n);continue
    actual=sha(p.read_bytes())
    if n.startswith(('rm_match/','operator_native/','adapters/','tools/','tests/')):programs+=1
    if actual!=expected:differences.append(dict(path=n,qa_sha256=expected,current_sha256=actual))
allowed=lambda n:n.startswith('docs/') or n in ('.gitattributes','examples/aim_plugins.json')
assert not missing,missing
assert all(allowed(r['path']) for r in differences),differences
report=dict(qa_manifest_sha256=sha((ROOT/'artifacts/quality-aim-universal-20261014-02/manifest.json').read_bytes()),tested_program_files_unchanged=programs,post_qa_changes=differences,only_documentation_git_attributes_or_equivalent_json=True,archive_payloads=len(manifest['files']),archive_manifest_sha256=sha(mp.read_bytes()))
write(DELIVERY/'POST_QA_IDENTITY.json',report)
print(json.dumps(dict(tested_program_files_unchanged=programs,post_qa_changes=[r['path'] for r in differences],archive_payloads=len(manifest['files']),archive_manifest_sha256=sha(mp.read_bytes()))))
