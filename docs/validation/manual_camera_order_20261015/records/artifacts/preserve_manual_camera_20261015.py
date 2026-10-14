"""Preserve literal new manual-camera sources, failures and actual SIL evidence."""
from pathlib import Path
import gzip,hashlib,json,subprocess
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/validation/manual_camera_order_20261015'
BASE='83c595bee600ab45daa7e75926af0d2edaa10dd6'
def sha(raw):return hashlib.sha256(raw).hexdigest()
driver=json.loads((ROOT/'artifacts/aim-followup-quality-driver-20261014-09/RESULT.json').read_bytes())
assert driver['returncode']==0 and driver['reaped'] and driver['source_unchanged']
for name,expected in driver['source_after'].items():assert sha((ROOT/name).read_bytes())==expected,name
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()==BASE
assert not OUT.exists(),'Immutable package already exists'
directories=['qt-manual-audit-focused-20261015-01','qt-manual-audit-focused-20261015-02',
 'qt-manual-peer-static-20261015-01','client-camera-order-20261015-01',
 'camera-manual-dryplan-20261015-01','pb-coop-route-readonly-20261015-01',
 'quality-aim-followup-20261014-09','aim-followup-quality-driver-20261014-09']
directories += [f'qt-manual-{kind}-20261015-{n:02}' for kind in ('actual','driver') for n in range(1,5)]
files=[]
for name in directories:
    d=ROOT/'artifacts'/name;assert d.is_dir(),name
    files += [p for p in d.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'}]
source=['tools/audit_qt_manual.py','tools/qa_qt_manual_peer.py','tools/qa_qt_manual_sil.py','tests/test_qt_manual_audit.py',
 'client_patches/CLIENT_CAMERA_ORDER_PATCH_MANIFEST.json','client_patches/robotio_camera_order_v1.patch','client_patches/README.md',
 'examples/coop_camera_order_manual.json','docs/CLIENT_ROBOTIO_INTERFACE.md','docs/COOP_PLAYABLE_PATH.md','docs/IMPLEMENTATION_PROGRESS.md',
 'artifacts/run_qt_manual_20261015.py','artifacts/run_manual_audit_focused_20261015.py',
 'artifacts/check_camera_manual_plan_20261015.py','artifacts/run_aim_followup_quality_20261014.py',
 'artifacts/preserve_manual_camera_20261015.py']
files += [ROOT/name for name in source]
rows=[]
for p in sorted(set(files)):
    original=p.relative_to(ROOT).as_posix();raw=p.read_bytes()
    assert p.suffix.lower() not in {'.exe','.elf','.dll','.onnx','.bin','.key','.pem','.pfx','.git'},original
    assert p.name not in {'SDK_EVENTS.jsonl','admission.json','UserData'} and not p.name.endswith('.local.json'),original
    assert len(raw)<=12*1024*1024,original
    if p.suffix in {'.json','.jsonl','.log','.txt','.stdout','.stderr'}:assert b'"POLAR_SIM_ADMISSION_CREDENTIAL":' not in raw,original
    compression='gzip' if len(raw)>4096 and p.suffix not in {'.gz','.png'} else 'literal'
    stored=Path('records')/original
    if compression=='gzip':stored=Path(str(stored)+'.gz');data=gzip.compress(raw,mtime=0)
    else:data=raw
    rows.append((stored,data,dict(original_path=original,original_bytes=len(raw),original_sha256=sha(raw),
        stored_path=stored.as_posix(),stored_bytes=len(data),stored_sha256=sha(data),compression=compression)))
OUT.mkdir(parents=True)
for stored,data,_ in rows:
    p=OUT/stored;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
manifest=dict(schema='polar.evidence.literal-preservation.v1',parent_commit=BASE,
    qualification='fifth full-base camera order client patch; original offscreen camera/manual keyboard/mouse/SDK/MuJoCo five and thirty second SIL passes; two original failures; no team algorithm/visible desktop/ROS/NN/performance/match acceptance',
    records=[r[2] for r in rows])
(OUT/'PRESERVATION_MANIFEST.json').write_bytes((json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode())
(OUT/'.gitattributes').write_bytes(b'# Literal evidence/source bytes; no checkout conversion.\n* -text -whitespace\n*.gz binary\n*.png binary\n')
print(json.dumps(dict(records=len(rows),original_bytes=sum(r[2]['original_bytes'] for r in rows),stored_bytes=sum(r[2]['stored_bytes'] for r in rows),manifest_sha256=sha((OUT/'PRESERVATION_MANIFEST.json').read_bytes()))))
