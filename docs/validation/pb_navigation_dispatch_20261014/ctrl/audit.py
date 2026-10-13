import hashlib,json,os,subprocess
from pathlib import Path
root=Path(__file__).absolute().parents[2];out=Path(__file__).absolute().parent
workspace=Path('/root/polar-controller-diag-build-20261014-01')
environment=root/'artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json';raw=environment.read_bytes()
if hashlib.sha256(raw).hexdigest()!='d60183ebf62d520c72eb20b84207fa4344d8f17183bb0df8eee92f97b7f981ee':raise ValueError('environment_changed')
env=dict(os.environ);env.update(json.loads(raw)['process_environment'])
prefix=workspace/'install/pb_omni_pid_pursuit_controller';library=prefix/'lib/libpb_omni_pid_pursuit_controller.so'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(cmd,name):
 r=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=15)
 (out/(name+'.stdout')).write_text(r.stdout);(out/(name+'.stderr')).write_text(r.stderr)
 return dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr,command=cmd)
record=dict(path=str(library),sha256=sha(library),size=library.stat().st_size,prefix=str(prefix))
record['ldd']=run(['ldd',str(library)],'ldd');record['dynamic']=run(['readelf','-d',str(library)],'dynamic')
record['load']=run(['/usr/bin/python3','-c','import ctypes,os;ctypes.CDLL('+repr(str(library))+',mode=os.RTLD_NOW);print("ACTUAL_CONTROLLER_LOADED")'],'load')
record['symbols']=run(['nm','-D','-C','--defined-only',str(library)],'symbols')
record['all_resolved']=record['ldd']['exit_code']==0 and 'not found' not in record['ldd']['stdout'] and record['load']['exit_code']==0
xml=prefix/'share/pb_omni_pid_pursuit_controller/pb_omni_pid_pursuit_controller.xml'
assets=[workspace/'src/pb_omni_pid_pursuit_controller/SOURCE_IDENTITY.json',workspace/'BUILD_RESULT.json',xml]
source=json.loads(assets[0].read_bytes());old=root/'artifacts/pb2025-nav2-plugins-actual-build-20261013-02/src/pb_omni_pid_pursuit_controller/SOURCE_IDENTITY.json'
original=json.loads(old.read_bytes())
result=dict(schema='polar.pb-controller-diag-binary-audit.v1',record=record,assets=[dict(path=str(p),sha256=sha(p)) for p in assets],
 original_upstream_files_identical=source['upstream_files']==original['upstream_files'],
 original_algorithm_sha256=source['upstream_files'],new_header_sha256=source['overlay_header_sha256'],
 old_reports_unchanged={str(p):sha(p)==expected for p,expected in [
  (root/'artifacts/pb2025-nav2-plugins-actual-build-20261013-02/BUILD_RESULT.json','583bc17e6041f1b0ec3f7a4d4785505aabd7ab30a413e292e80c5111c0c50f93'),
  (root/'artifacts/pb2025-nav2-plugins-actual-build-20261013-02/build.log','979d330e4223cf2429b11931e4dc73fb2aaf4daed94eacb7bb59a941fb4200c6'),
  (root/'artifacts/pb2025-nav2-plugins-actual-build-20261013-02/install/pb_omni_pid_pursuit_controller/lib/libpb_omni_pid_pursuit_controller.so','def2bd7413e805067706278037bc4b8615938208ca33a16fd3edf550a6020911')]},
 diagnostics_default=False,diagnostic_max_records=256,qualification='real ELF loading only; no controller compute or navigation',nodes_started=False)
(out/'BINARY_AUDIT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k in ('original_upstream_files_identical','old_reports_unchanged')}));print(json.dumps({k:v for k,v in record.items() if k in ('path','sha256','size','all_resolved')}))
