"""Captured explicit Qt protocol test on a frozen local patched client."""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,sys,time
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--attempt',type=int,required=True);a=p.parse_args()
out=root/f'artifacts/qt-robotio-protocol-driver-20261014-{a.attempt:02}';out.mkdir()
command=[sys.executable,str(root/'tools/qa_qt_robotio_protocol.py'),'--out',str(root/f'artifacts/qt-robotio-protocol-actual-20261014-{a.attempt:02}'),'--duration','3.5','--run']
before={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in ('tools/qa_qt_robotio_protocol.py','tools/qa_qt_robotio_peer.py','client_patches/CLIENT_ROBOTIO_PATCH_MANIFEST.json','client_patches/robotio_navigation_v1.patch')}
(out/'driver.py').write_bytes(Path(__file__).read_bytes())
(out/'COMMAND.json').write_bytes((json.dumps(dict(argv=command,source_before=before,scope='offscreen widget and Qt SDK to actual low-rate MuJoCo; not F2/camera/visible GUI/team algorithm'),indent=2)+'\n').encode())
start=time.perf_counter()
with (out/'stdout.log').open('xb') as so,(out/'stderr.log').open('xb') as se:
    child=subprocess.Popen(command,cwd=root,stdin=subprocess.DEVNULL,stdout=so,stderr=se,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
    (out/'PID.json').write_bytes((json.dumps(dict(pid=child.pid,driver_pid=os.getpid()))+'\n').encode())
    code=child.wait(timeout=40)
after={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in before}
result=dict(returncode=code,reaped=child.poll() is not None,elapsed_s=time.perf_counter()-start,source_before=before,source_after=after,source_unchanged=before==after)
(out/'RESULT.json').write_bytes((json.dumps(result,indent=2)+'\n').encode());print(json.dumps({k:v for k,v in result.items() if k not in ('source_before','source_after')}));raise SystemExit(code)
