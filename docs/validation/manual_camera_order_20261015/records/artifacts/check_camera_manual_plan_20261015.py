"""Capture the fifth client dry plan without launching UI or simulation."""
from pathlib import Path
import hashlib,json,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/camera-manual-dryplan-20261015-01';OUT.mkdir()
names=['examples/coop_camera_order_manual.json','client_patches/CLIENT_CAMERA_ORDER_PATCH_MANIFEST.json','client_patches/robotio_camera_order_v1.patch']
def hashes():return {n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
before=hashes();argv=[sys.executable,'-m','rm_match.deployment.coop_launcher','--config','examples/coop_camera_order_manual.json']
start=time.perf_counter();p=subprocess.run(argv,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
(OUT/'stdout.json').write_bytes(p.stdout);(OUT/'stderr.log').write_bytes(p.stderr)
plan=json.loads(p.stdout) if p.returncode==0 else None
result=dict(argv=argv,returncode=p.returncode,reaped=True,elapsed_s=time.perf_counter()-start,source_before=before,source_after=hashes(),source_unchanged=before==hashes(),qualification='dry plan only; no GUI/physics/algorithm')
(OUT/'RESULT.json').write_bytes((json.dumps(result,indent=2)+'\n').encode())
assert p.returncode==0 and result['source_unchanged'];print(json.dumps(result))
