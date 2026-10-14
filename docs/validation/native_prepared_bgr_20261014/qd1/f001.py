"""Own the frozen full quality process; no silent extra NN/render run."""
import hashlib,json,os,subprocess,time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
out=root/'artifacts/prepared-bgr-quality-driver-20261014-01';out.mkdir()
command=[str(root/'.venv-sim/Scripts/python.exe'),'tools/check_project.py','--out',str(root/'artifacts/quality-20261014-prepared-bgr-frozen-01')]
environment=os.environ.copy();environment['POLAR_TEST_WSL']='1'
(out/'driver.py').write_bytes(Path(__file__).read_bytes())
(out/'COMMAND.json').write_text(json.dumps(dict(argv=command,cwd=str(root),environment_override=dict(POLAR_TEST_WSL='1'),
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
