"""Root-owned actual Linux registration; no NN invocation or physics."""
from pathlib import Path
import hashlib,json,sys
ROOT=Path('/mnt/c/Users/lulu/Desktop/claude/polarsimulation/polar-rm-simulator')
sys.path.insert(0,str(ROOT))
from tools.prepare_tongji_aim_plugin import write_instance
prepared=ROOT/'artifacts/tongji-aim-native-preparation-20261014-04'
out=ROOT/'artifacts/tongji-aim-instance-20261014-02';out.mkdir()
identity=hashlib.sha256((prepared/'SOURCE_IDENTITY.json').read_bytes()).hexdigest()
value=write_instance(prepared,prepared/'build/polar_native_aim',out/'instance.json',source_identity_sha256=identity,repo_root=ROOT)
(out/'CREATION.json').write_text(json.dumps(dict(source_identity_sha256=identity,
    instance_sha256=hashlib.sha256((out/'instance.json').read_bytes()).hexdigest(),
    binary_sha256=value['binary_sha256'],model_loaded=False,inference_calls=0,physics_steps=0),indent=2)+'\n')
print(json.dumps(dict(instance=str(out/'instance.json'),binary_sha256=value['binary_sha256'],inference_calls=0)))
