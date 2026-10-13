"""Owned controller-only fresh build; no algorithm process or DDS startup."""
import hashlib,json,os,signal,subprocess,time
from pathlib import Path
root=Path(__file__).absolute().parents[2];out=Path(__file__).absolute().parent
workspace=Path('/root/polar-controller-diag-build-20261014-01')
environment=root/'artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json'
raw=environment.read_bytes();env_sha=hashlib.sha256(raw).hexdigest()
if env_sha!='d60183ebf62d520c72eb20b84207fa4344d8f17183bb0df8eee92f97b7f981ee':raise ValueError('frozen_environment_changed')
settings=json.loads(raw);env=dict(os.environ);env.update(settings['process_environment'])
for key in ('PYTHONPATH','PYTHONHOME','POLAR_PB_BRIDGE_PHASE_FILE'):env.pop(key,None)
sources=['rm_match/integrations/pb_controller_context.hpp','rm_match/integrations/pb_request_context.hpp','rm_match/integrations/pb_navigation_workspace.py','tools/build_pb_nav2_plugins.py']
def hashes():return {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sources}
before=hashes()
cmd=[settings['venv_python'],str(root/'tools/build_pb_nav2_plugins.py'),'--source-root',str(root/'artifacts/polarbear-navigation-source-e05eb08e'),
 '--environment',str(environment),'--out',str(workspace),'--controller-only','--build-timeout-seconds','1800']
started=time.perf_counter();proc=None;timeout=False
with (out/'driver.log').open('xb') as log:
 try:
  proc=subprocess.Popen(cmd,cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
  proc.wait(timeout=1840)
 except subprocess.TimeoutExpired:timeout=True
 finally:
  if proc is not None:
   try:os.killpg(proc.pid,signal.SIGTERM)
   except ProcessLookupError:pass
   try:proc.wait(timeout=.5)
   except subprocess.TimeoutExpired:pass
   try:os.killpg(proc.pid,signal.SIGKILL)
   except ProcessLookupError:pass
   if proc.poll() is None:proc.wait(timeout=1.)
result=dict(schema='polar.pb-controller-diagnostic-build-driver.v1',command=cmd,elapsed_seconds=time.perf_counter()-started,
 exit_code=None if proc is None else proc.returncode,timed_out=timeout,source_before=before,source_after=hashes(),
 source_unchanged=before==hashes(),environment_sha256=env_sha,workspace=str(workspace),nodes_started=False,ROS_DDS_initialized=False)
if (workspace/'BUILD_RESULT.json').is_file():
 result['build_result']=json.loads((workspace/'BUILD_RESULT.json').read_bytes())
 (out/'BUILD_RESULT_ORIGINAL.json').write_bytes((workspace/'BUILD_RESULT.json').read_bytes())
(out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k in ('exit_code','elapsed_seconds','source_unchanged','timed_out')}))
