"""Capture explicit argv without shell composition; fresh evidence only."""
import hashlib,json,os,subprocess,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
out=root/request['out'];out.mkdir()
files=request.get('sources',[])
before={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in files}
for n in files:
 p=out/'source'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((root/n).read_bytes())
(out/'driver.py').write_bytes(Path(__file__).read_bytes())
(out/'COMMANDS.json').write_text(json.dumps(request,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
steps=[]
for index,step in enumerate(request['commands'],1):
 env=dict(os.environ);env.update(step.get('env',{}))
 started=time.perf_counter()
 with (out/f'{index:02d}.stdout.log').open('xb') as stdout,(out/f'{index:02d}.stderr.log').open('xb') as stderr:
  child=subprocess.Popen(step['argv'],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
  row=dict(argv=step['argv'],pid=child.pid,driver_pid=os.getpid())
  (out/f'{index:02d}.PID.json').write_text(json.dumps(row)+'\n',encoding='utf-8')
  code=child.wait()
 row.update(returncode=code,reaped=child.poll() is not None,elapsed_s=time.perf_counter()-started)
 steps.append(row)
 (out/f'{index:02d}.RESULT.json').write_text(json.dumps(row,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(dict(step=index,returncode=code,reaped=row['reaped'],elapsed_s=row['elapsed_s'])),flush=True)
 if code not in step.get('allowed_exit_codes',[0]):break
after={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in files}
okay=len(steps)==len(request['commands']) and all(row['returncode'] in step.get('allowed_exit_codes',[0]) for row,step in zip(steps,request['commands']))
result=dict(steps=steps,all_expected_exit_codes=okay,source_before=before,source_after=after,source_unchanged=before==after)
(out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(dict(all_expected_exit_codes=okay,source_unchanged=before==after)),flush=True)
raise SystemExit(0 if okay and before==after else 2)
