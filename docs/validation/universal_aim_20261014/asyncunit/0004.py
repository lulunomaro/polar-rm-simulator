"""Pure tests only. Captures exact executing source bytes before subprocess."""
import hashlib,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
FILES=['rm_match/integrations/wsl_aim_async.py','rm_match/integrations/wsl_aim_async_worker.py','tests/test_wsl_aim_async.py']
def sha(raw):return hashlib.sha256(raw).hexdigest()
def write(name,value):(OUT/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
if (OUT/'RESULT.json').exists():raise RuntimeError('fresh fixture output required')
rows=[]
for rel in FILES:
    raw=(ROOT/rel).read_bytes();target=OUT/'source'/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    rows.append(dict(path=rel,sha256=sha(raw),bytes=len(raw),snapshot=str(target.relative_to(OUT))))
write('SOURCE_BEFORE.json',rows)
write('FIRST_FIXTURE_OBSERVATION.json',dict(kind='structured_observation_not_raw_stdout',command='.venv-sim/Scripts/python.exe -m pytest tests/test_wsl_aim_async.py -q',returncode=1,passed=35,failed=1,error='Windows mock boot-id path str used backslashes; actual fixture did not read Linux boot id. Fixed fixture via Path.as_posix; no production relaxation.',raw_stdout_saved=False))
command=[sys.executable,'-m','pytest','tests/test_wsl_aim_async.py','-q'];write('COMMAND.json',dict(command=command,cwd=str(ROOT),qualification='Pure mocked OS/protocol tests; no actual child, WSL, NN, ROS or camera.'))
started=time.perf_counter()
with (OUT/'stdout.log').open('xb') as stdout,(OUT/'stderr.log').open('xb') as stderr:
    child=subprocess.Popen(command,cwd=ROOT,stdout=stdout,stderr=stderr)
    code=child.wait(timeout=30)
unchanged=all(sha((ROOT/row['path']).read_bytes())==row['sha256'] for row in rows)
write('RESULT.json',dict(returncode=code,child_pid=child.pid,child_reaped=child.poll() is not None,elapsed_s=time.perf_counter()-started,source_unchanged=unchanged,stdout_sha256=sha((OUT/'stdout.log').read_bytes()),stderr_sha256=sha((OUT/'stderr.log').read_bytes()),qualification='Unit proof only. Actual startup/protocol cleanup and real >=10 new-frame <80ms consumption remain untested.'))
print(json.dumps(dict(returncode=code,source_unchanged=unchanged,sources=rows),indent=2))
raise SystemExit(code if unchanged else 2)
