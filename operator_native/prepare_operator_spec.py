"""Generate a machine-local operator spec; do not overwrite frozen source specs."""
import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--base-spec',type=Path,required=True);p.add_argument('--binary',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
if a.out.resolve()==a.base_spec.resolve():raise ValueError('Output must not overwrite the original source spec')
s=json.loads(a.base_spec.read_text());binary=a.binary.resolve()
if not binary.is_file():raise FileNotFoundError(binary)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
for key in ('executor_yaml','autoaim_config'):
 if s.get('sha256',{}).get(key)!=sha(s[key]):raise ValueError('Base source configuration mismatch: '+key)
if s['model_sha256']!=sha(Path(s['model_share'])/'shenzhen-0526.onnx'):raise ValueError('Base detector mismatch')
s.update(operator_identity='rmcs-sim-operator-fov-v1',binary=str(binary),operator_source_reference=s.pop('source_commit',None))
s.setdefault('frozen_build',{})['binary_sha256']=sha(binary);s.setdefault('sha256',{})['binary']=sha(binary)
a.out.write_text(json.dumps(s,indent=2))
