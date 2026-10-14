"""Own the frozen full quality process; no silent extra NN/render run."""
import argparse,hashlib,json,os,subprocess,time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--attempt',type=int,default=1);args=p.parse_args()
out=root/f'artifacts/prepared-bgr-quality-driver-20261014-{args.attempt:02}';out.mkdir()
command=[str(root/'.venv-sim/Scripts/python.exe'),'tools/check_project.py','--out',str(root/f'artifacts/quality-20261014-prepared-bgr-frozen-{args.attempt:02}')]
environment=os.environ.copy();environment['POLAR_TEST_WSL']='1'
environment['POLAR_WSL_TEST_SPEC']=str(root/'artifacts/native-original-nav-checkpoint-build-20261013/operator_source.local.json')
(out/'driver.py').write_bytes(Path(__file__).read_bytes())
(out/'COMMAND.json').write_text(json.dumps(dict(argv=command,cwd=str(root),environment_override={k:environment[k] for k in ('POLAR_TEST_WSL','POLAR_WSL_TEST_SPEC')},
 driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),indent=2)+'\n',encoding='utf-8')
started=time.perf_counter()
with (out/'stdout.log').open('xb') as stdout,(out/'stderr.log').open('xb') as stderr:
 child=subprocess.Popen(command,cwd=root,stdout=stdout,stderr=stderr,stdin=subprocess.DEVNULL,env=environment,
  shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
 (out/'PID.json').write_text(json.dumps(dict(pid=child.pid,driver_pid=os.getpid()))+'\n',encoding='utf-8')
 code=child.wait()
 result=dict(returncode=code,reaped=child.poll() is not None,elapsed_s=time.perf_counter()-started)
 (out/'PROCESS_RESULT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result))
raise SystemExit(code)
