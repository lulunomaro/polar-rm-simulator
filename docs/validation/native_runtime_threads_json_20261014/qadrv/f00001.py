"""Own checkpoint test processes and preserve exact commands/source/results."""
import argparse,hashlib,json,os,subprocess,time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('kind',choices=['linux','pipe','quality']);parser.add_argument('suffix');args=parser.parse_args()
out=root/f'artifacts/runtime-checkpoint-{args.kind}-20261014-{args.suffix}';out.mkdir()
files=['rm_match/deployment/json_adapter.py','rm_match/deployment/json_owned_process.py',
 'rm_match/deployment/windows_owned_job.py','tests/test_json_owned_process.py',
 'rm_match/integrations/wsl_operator_pipe_worker.py','tests/test_wsl_pipe_stdout_telemetry.py',
 'operator_native/runtime/overlays/first_frame_trace.hpp','operator_native/runtime/overlays/prepare_first_frame_profile.py',
 'tools/native_model_properties.py','tests/test_native_model_properties.py',
 'tools/compare_native_opencv_threads.py','tests/test_native_opencv_thread_comparison.py']
before={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in files}
for n in files:
 p=out/'source'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((root/n).read_bytes())
linux='/mnt/c/'+root.as_posix()[3:];env=dict(os.environ)
if args.kind=='linux':
 command=['C:/Windows/System32/wsl.exe','-d','Ubuntu','--cd',linux,'--exec','/usr/bin/env',
  'POLAR_TEST_JSON_OWNED_POSIX=1',linux+'/.venv-linux/bin/python','-m','pytest',
  'tests/test_json_owned_process.py','tests/test_deployment.py::JsonAdapterTests','-q',
  '--junitxml='+linux+'/artifacts/'+out.name+'/pytest.xml']
elif args.kind=='pipe':
 env['POLAR_TEST_WSL']='1'
 command=[str(root/'.venv-sim/Scripts/python.exe'),'-m','pytest',
  'rm_match/integrations/test_wsl_operator_pipe.py','tests/test_wsl_pipe_stdout_telemetry.py','-q',
  '--junitxml='+str(out/'pytest.xml')]
else:
 env['POLAR_TEST_WSL']='1';env['POLAR_WSL_TEST_SPEC']=str(root/'artifacts/native-original-nav-checkpoint-build-20261013/operator_source.local.json')
 command=[str(root/'.venv-sim/Scripts/python.exe'),'tools/check_project.py','--out',
  str(root/f'artifacts/quality-20261014-runtime-threads-frozen-{args.suffix}')]
(out/'driver.py').write_bytes(Path(__file__).read_bytes())
(out/'COMMAND.json').write_text(json.dumps(dict(argv=command,cwd=str(root),source_before=before,
 explicit_env={k:v for k,v in env.items() if k in ('POLAR_TEST_WSL','POLAR_WSL_TEST_SPEC')},
 scope='Actual harmless process fixtures for linux/pipe; full local quality for quality. Not live/match acceptance.'),indent=2)+'\n',encoding='utf-8')
started=time.perf_counter()
with (out/'stdout.log').open('xb') as stdout,(out/'stderr.log').open('xb') as stderr:
 child=subprocess.Popen(command,cwd=root,env=env,stdout=stdout,stderr=stderr,stdin=subprocess.DEVNULL,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
 (out/'PID.json').write_text(json.dumps(dict(pid=child.pid,driver_pid=os.getpid()))+'\n',encoding='utf-8')
 code=child.wait()
after={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in files}
result=dict(returncode=code,reaped=child.poll() is not None,elapsed_s=time.perf_counter()-started,
 source_before=before,source_after=after,source_unchanged=before==after)
(out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ('source_before','source_after')}));raise SystemExit(code)
