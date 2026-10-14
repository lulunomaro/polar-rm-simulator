"""New DDS attempt on frozen stop-intent module bytes; original attempts intact."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,time
root=Path(__file__).resolve().parents[1]
out=root/'artifacts/robotio-dds-actual-driver-20261014-03';out.mkdir()
tool=root/'artifacts/robotio_ros2_actual_ext4_20261014.py'
argv=[sys.executable,str(tool),'--out',str(root/'artifacts/robotio-ros2-actual-20261014-03'),'--run']
(out/'driver.py').write_bytes(Path(__file__).read_bytes())
(out/'COMMAND.json').write_text(json.dumps(dict(argv=argv,driver_sha256=hashlib.sha256(tool.read_bytes()).hexdigest(),change='Navigation stop intent validation was added; final source snapshot, same actual ext4 runtime'),indent=2)+'\n',encoding='utf8')
start=time.perf_counter()
with (out/'stdout.log').open('xb') as so,(out/'stderr.log').open('xb') as se:
    child=subprocess.Popen(argv,cwd=root,stdin=subprocess.DEVNULL,stdout=so,stderr=se,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
    (out/'PID.json').write_text(json.dumps(dict(pid=child.pid,driver_pid=os.getpid()))+'\n',encoding='utf8')
    code=child.wait(timeout=40)
result=dict(returncode=code,reaped=child.poll() is not None,elapsed_s=time.perf_counter()-start)
(out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8');print(json.dumps(result));raise SystemExit(code)
