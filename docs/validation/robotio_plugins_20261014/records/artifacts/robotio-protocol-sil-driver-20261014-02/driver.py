"""Captured bounded actual protocol SIL; only explicit fixture commands."""
from pathlib import Path
import argparse, ast, hashlib, json, os, subprocess, sys, time
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--attempt',required=True,type=int);a=p.parse_args()
assert 1<=a.attempt<=10
out=ROOT/f'artifacts/robotio-protocol-sil-driver-20261014-{a.attempt:02}';out.mkdir()
tool=ROOT/'tools/qa_robotio_protocol_sil.py'
tree=ast.parse(tool.read_bytes())
files=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SOURCE_FILES' for t in n.targets)))
before={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in files}
argv=[sys.executable,str(tool),'--out',str(ROOT/f'artifacts/robotio-protocol-sil-20261014-{a.attempt:02}'),'--duration','4','--run']
(out/'driver.py').write_bytes(Path(__file__).read_bytes())
(out/'COMMAND.json').write_text(json.dumps(dict(argv=argv,source_before=before,scope='two independent synthetic policies; actual MuJoCo protocol consumption'),indent=2)+'\n',encoding='utf8')
started=time.perf_counter();timed_out=False
with (out/'stdout.log').open('xb') as so,(out/'stderr.log').open('xb') as se:
    child=subprocess.Popen(argv,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=so,stderr=se,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
    (out/'PID.json').write_text(json.dumps(dict(pid=child.pid,driver_pid=os.getpid()))+'\n',encoding='utf8')
    try:code=child.wait(timeout=30)
    except subprocess.TimeoutExpired:
        timed_out=True;child.kill();code=child.wait(timeout=2)
after={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in files}
result=dict(returncode=code,timed_out=timed_out,reaped=child.poll() is not None,elapsed_s=time.perf_counter()-started,source_before=before,source_after=after,source_unchanged=before==after)
(out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k not in ('source_before','source_after')}));raise SystemExit(code if code else int(timed_out or before!=after))
