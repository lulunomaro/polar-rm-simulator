import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
records=[]
for name,mf in [('polar-rm-client-state-review','CLIENT_PATCH_MANIFEST.json'),('polar-rm-client-robotio-review','CLIENT_ROBOTIO_PATCH_MANIFEST.json'),('polar-rm-client-robotio-state-review','CLIENT_ROBOTIO_STATE_PATCH_MANIFEST.json')]:
    p=ROOT/'client_patches'/mf;m=json.loads(p.read_bytes());patch=p.parent/m['patch_file'];tree=ROOT/'external'/name
    records.append(dict(checkout=str(tree),manifest=str(p),manifest_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),patch=str(patch),patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),files={k:hashlib.sha256((tree/k).read_bytes()).hexdigest() for k in m['files']}))
for name in ('sim_platform_client.py','sim_platform_transport.py','sim_platform_handoff.py','sim_platform_diagnostics.py'):
    p=ROOT/'external/polar-rm-client-robotio-batch-review/rm_client'/name;out=HERE/'before'/name;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(p.read_bytes())
(HERE/'OLD_IDENTITIES.json').write_text(json.dumps(records,indent=2)+'\n',encoding='utf8')
