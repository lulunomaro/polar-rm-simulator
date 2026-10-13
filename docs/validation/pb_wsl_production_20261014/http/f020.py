import json,subprocess,sys,time,hashlib
from pathlib import Path
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1];label=sys.argv[1]
command=[sys.executable,str(OUT/'probe.py'),label]
(OUT/(label+'.COMMAND.json')).write_text(json.dumps(dict(command=command,probe_sha256=hashlib.sha256((OUT/'probe.py').read_bytes()).hexdigest()),indent=2))
started=time.perf_counter()
with (OUT/(label+'.stdout.log')).open('xb') as stdout,(OUT/(label+'.stderr.log')).open('xb') as stderr:
    child=subprocess.Popen(command,cwd=ROOT,stdout=stdout,stderr=stderr)
    try:code=child.wait(timeout=25.);timed_out=False
    except subprocess.TimeoutExpired:child.kill();child.wait(5.);code=child.returncode;timed_out=True
(OUT/(label+'.PROCESS_RESULT.json')).write_text(json.dumps(dict(pid=child.pid,returncode=code,timed_out=timed_out,
    owned_child_reaped=child.poll() is not None,elapsed_s=time.perf_counter()-started),indent=2))
print(json.dumps(dict(label=label,returncode=code,timed_out=timed_out)))
