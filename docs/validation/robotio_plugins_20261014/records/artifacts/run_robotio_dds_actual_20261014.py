"""Captured actual DDS retry; explicit existing ext4 supervisor Python."""
from pathlib import Path
import json,os,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/robotio-dds-actual-driver-20261014-02';OUT.mkdir()
old=ROOT/'artifacts/robotio-ros2-actual-candidate-20261014-01/driver.py'
text=old.read_text(encoding='utf8')
before="ROOT=Path(__file__).resolve().parents[2]"
assert text.count(before)==1
text=text.replace(before,"ROOT=Path(__file__).resolve().parents[1]")
before="python=mounted_path(ROOT/'.venv-linux/bin/python')"
assert text.count(before)==1
text=text.replace(before,"python=env['venv_python']")
candidate=ROOT/'artifacts/robotio_ros2_actual_ext4_20261014.py';candidate.write_bytes(text.encode())
argv=[sys.executable,str(candidate),'--out',str(ROOT/'artifacts/robotio-ros2-actual-20261014-02'),'--run']
(OUT/'driver.py').write_bytes(Path(__file__).read_bytes())
(OUT/'COMMAND.json').write_bytes((json.dumps(dict(argv=argv,change='Explicit supervisor Python matches existing verified ext4 venv with NumPy; old failed attempt retained'),indent=2)+'\n').encode())
started=time.perf_counter()
with (OUT/'stdout.log').open('xb') as stdout,(OUT/'stderr.log').open('xb') as stderr:
    child=subprocess.Popen(argv,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
    (OUT/'PID.json').write_bytes((json.dumps(dict(pid=child.pid,driver_pid=os.getpid()))+'\n').encode())
    code=child.wait()
result=dict(returncode=code,reaped=child.poll() is not None,elapsed_s=time.perf_counter()-started)
(OUT/'RESULT.json').write_bytes((json.dumps(result,indent=2)+'\n').encode());print(json.dumps(result))
raise SystemExit(code)
