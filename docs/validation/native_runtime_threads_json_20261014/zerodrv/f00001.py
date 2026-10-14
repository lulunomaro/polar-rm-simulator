"""Own and save the zero-tick Linux resource probe, with exact executed sources."""
import hashlib,json,os,subprocess,time
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'artifacts/compiled-properties-probe-driver-20261014-01';out.mkdir()
files=['artifacts/probe_native_compiled_properties_20261014.py','tools/native_model_properties.py',
 'tools/validate_native_performance_profile.py','rm_match/integrations/owned_linux_group.py',
 'rm_match/integrations/wsl_operator_worker.py']
before={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in files}
for n in files:
 p=out/'source'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((root/n).read_bytes())
linux='/mnt/c/'+root.as_posix()[3:]
command=['C:/Windows/System32/wsl.exe','-d','Ubuntu','--cd',linux,'--exec','/usr/bin/python3','artifacts/probe_native_compiled_properties_20261014.py']
(out/'driver.py').write_bytes(Path(__file__).read_bytes())
(out/'COMMAND.json').write_text(json.dumps(dict(argv=command,cwd=str(root),source_before=before),indent=2)+'\n',encoding='utf-8')
started=time.perf_counter()
with (out/'stdout.log').open('xb') as stdout,(out/'stderr.log').open('xb') as stderr:
 child=subprocess.Popen(command,cwd=root,stdout=stdout,stderr=stderr,stdin=subprocess.DEVNULL,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
 (out/'PID.json').write_text(json.dumps(dict(pid=child.pid,driver_pid=os.getpid()))+'\n',encoding='utf-8')
 code=child.wait()
after={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in files}
result=dict(returncode=code,reaped=child.poll() is not None,elapsed_s=time.perf_counter()-started,
 source_before=before,source_after=after,source_unchanged=before==after)
(out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:v for k,v in result.items() if k not in ('source_before','source_after')}));raise SystemExit(code)
