"""One captured full quality run on final followup program bytes."""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--attempt',required=True,type=int);a=p.parse_args();assert 1<=a.attempt<=20
out=ROOT/f'artifacts/aim-followup-quality-driver-20261014-{a.attempt:02}';out.mkdir()
names=['DEVELOPMENT_CHANGES.json','pyproject.toml']+sorted(x.relative_to(ROOT).as_posix() for d in ('rm_match','tools','tests') for x in (ROOT/d).rglob('*.py'))
before={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
env=dict(os.environ);env['POLAR_TEST_WSL']='1';env['POLAR_WSL_TEST_SPEC']=str(ROOT/'artifacts/native-production-cpu4-build-20261014/operator_source.local.json')
command=[sys.executable,str(ROOT/'tools/check_project.py'),'--out',str(ROOT/f'artifacts/quality-aim-followup-20261014-{a.attempt:02}')]
(out/'driver.py').write_bytes(Path(__file__).read_bytes())
(out/'COMMAND.json').write_bytes((json.dumps(dict(argv=command,explicit_env={k:env[k] for k in ('POLAR_TEST_WSL','POLAR_WSL_TEST_SPEC')},source_before=before),indent=2)+'\n').encode())
start=time.perf_counter()
with (out/'stdout.log').open('xb') as stdout,(out/'stderr.log').open('xb') as stderr:
    child=subprocess.Popen(command,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
    (out/'PID.json').write_bytes((json.dumps(dict(pid=child.pid,driver_pid=os.getpid()))+'\n').encode())
    code=child.wait()
after={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
result=dict(returncode=code,reaped=child.poll() is not None,elapsed_s=time.perf_counter()-start,source_before=before,source_after=after,source_unchanged=before==after)
(out/'RESULT.json').write_bytes((json.dumps(result,indent=2)+'\n').encode())
print(json.dumps({k:v for k,v in result.items() if k not in ('source_before','source_after')}));raise SystemExit(code)
