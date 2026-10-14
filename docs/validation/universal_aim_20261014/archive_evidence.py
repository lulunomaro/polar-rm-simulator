"""Literal evidence selection; no credentials, binaries, weights or old rewrites."""
from pathlib import Path
import gzip,hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/validation/universal_aim_20261014';OUT.mkdir(parents=True,exist_ok=False)
groups={
 'peer':'aim-wsl-jsonl-interface-20261014-02','actual':'wsl-jsonl-actual-20261014-01',
 'stderr':'owned-stderr-sink-focused-20261014-01','threads':'production-inference-threads-focused-20261014-01',
 'cpu4':'native-production-cpu4-build-20261014','cpu4drv':'production-cpu4-build-driver-20261014-01',
 'ov4':'native-ov4-api-thread-comparison-20261014-01','ov4drv':'native-ov4-api-comparison-driver-20261014-01',
 'hostcv':'host-opencv-threads-focused-20261014-01','status':'aim-status-runtime-focused-20261014-01',
 'mount':'aim-mount-calibration-20261014-03','pbsource':'pb2025-aim-plugin-focused-20261014-03',
 'pbtool':'pb2025-aim-build-bootstrap-focused-20261014-01',
 'pbretry':'pb2025-aim-https-retry-focused-20261014-01',
 'pbpre1':'pb-aim-preflight01-actual-evidence-20261014',
 'pbdep1':'pb-aim-deps01-actual-evidence-20261014','pbdep2':'pb-aim-deps02-actual-evidence-20261014',
 'pbbooterr':'pb-aim-extra-prefix-preflight-driver-20261014-02',
 'tjbuild':'tongji-aim-native-prepare-driver-20261014-04',
 'tjerr':'tongji-aim-actual-prepare-driver-20261014-01','tjstart':'tongji-aim-actual-prepare-driver-20261014-02',
 'tjreset':'tongji-aim-actual-prepare-reset-20261014-02','tjready':'tongji-aim-instance-20261014-02/evidence',
 'asyncunit':'wsl-aim-async-focused-20261014-01',
 'asyncerr':'aim-live-20261014-production-cpu4-hostcv4-async01',
 'async2':'aim-live-20261014-production-cpu4-hostcv4-async02',
 'asynctime':'aim-live-20261014-production-cpu4-hostcv4-async-stage01',
 'qa1':'quality-aim-universal-20261014-01','qadrv1':'aim-universal-quality-driver-20261014-01',
}
allowed={'.json','.jsonl','.log','.xml','.py','.hpp','.cpp','.txt','.yaml','.md','.bgr'}
excluded={'admission.json','SDK_EVENTS.json','CMakeCache.txt'}
rows=[]
for label,relative in groups.items():
 source=ROOT/'artifacts'/relative
 if not source.is_dir():raise ValueError('Missing group:'+relative)
 files=sorted(p for p in source.rglob('*') if p.is_file() and not p.is_symlink()
  and p.suffix in allowed and p.name not in excluded
  and not any(x in ('bin','models','objects','upstream','CMakeFiles','__pycache__','build') for x in p.relative_to(source).parts))
 for number,p in enumerate(files,1):
  raw=p.read_bytes();compress=len(raw)>65536;name=f'{number:04d}'+p.suffix+('.gz' if compress else '')
  stored=gzip.compress(raw,compresslevel=6,mtime=0) if compress else raw
  target=OUT/label/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(stored)
  assert (gzip.decompress(target.read_bytes()) if compress else target.read_bytes())==raw
  rows.append(dict(path=target.relative_to(OUT).as_posix(),original_path=p.relative_to(ROOT).as_posix(),
    original_bytes=len(raw),original_sha256=hashlib.sha256(raw).hexdigest(),encoding='gzip' if compress else 'literal',
    stored_bytes=len(stored),stored_sha256=hashlib.sha256(stored).hexdigest()))
(OUT/'PRESERVATION_MANIFEST.json').write_text(json.dumps(dict(schema='polar.evidence.preservation.v2',files=rows),indent=2)+'\n',encoding='utf8')
(OUT/'INDEX.tsv').write_text('stored_path\toriginal_path\toriginal_sha256\n'+''.join(f"{r['path']}\t{r['original_path']}\t{r['original_sha256']}\n" for r in rows),encoding='utf8')
(OUT/'.gitattributes').write_text('* -text -whitespace\n',encoding='utf8')
(OUT/'archive_evidence.py').write_bytes(Path(__file__).read_bytes())
print(json.dumps(dict(files=len(rows),stored_bytes=sum(r['stored_bytes'] for r in rows),
 manifest_sha256=hashlib.sha256((OUT/'PRESERVATION_MANIFEST.json').read_bytes()).hexdigest())))
