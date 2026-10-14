"""Append new proof groups to the current unpublished archive, preserving payloads."""
from pathlib import Path
import gzip,hashlib,json
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/validation/universal_aim_20261014'
manifest=OUT/'PRESERVATION_MANIFEST.json';v=json.loads(manifest.read_text(encoding='utf8'))
groups={'qa2':'quality-aim-universal-20261014-02','qadrv2':'aim-universal-quality-driver-20261014-02',
 'opencv':'pb2025-aim-system-opencv-focused-20261014-01','pbpre4':'pb-aim-extra-prefix-preflight-driver-20261014-04',
 'pbbld':'pb-aim-seven-packages-build-driver-20261014-01','mechanical':'aim-mechanical-receipts-20261014-01'}
for label,relative in groups.items():
 out=OUT/label
 if out.exists():raise ValueError('Existing group:'+label)
 files=sorted(p for p in (ROOT/'artifacts'/relative).rglob('*') if p.is_file() and not p.is_symlink()
  and p.suffix in ('.json','.jsonl','.py','.hpp','.cpp','.log','.xml','.txt','.md') and '__pycache__' not in p.parts)
 for i,p in enumerate(files,1):
  raw=p.read_bytes();compress=len(raw)>65536;stored=gzip.compress(raw,compresslevel=6,mtime=0) if compress else raw
  target=out/(f'{i:04d}'+p.suffix+('.gz' if compress else ''));target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(stored)
  v['files'].append(dict(path=target.relative_to(OUT).as_posix(),original_path=p.relative_to(ROOT).as_posix(),original_bytes=len(raw),original_sha256=hashlib.sha256(raw).hexdigest(),encoding='gzip' if compress else 'literal',stored_bytes=len(stored),stored_sha256=hashlib.sha256(stored).hexdigest()))
raw=(ROOT/'artifacts/aim_failure_observations_20261014.md').read_bytes();(OUT/'FAILURE_OBSERVATIONS.md').write_bytes(raw)
manifest.write_text(json.dumps(v,indent=2)+'\n',encoding='utf8')
(OUT/'INDEX.tsv').write_text('stored_path\toriginal_path\toriginal_sha256\n'+''.join(f"{r['path']}\t{r['original_path']}\t{r['original_sha256']}\n" for r in v['files']),encoding='utf8')
(OUT/'supplement_evidence.py').write_bytes(Path(__file__).read_bytes())
print(json.dumps(dict(files=len(v['files']),manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest())))
