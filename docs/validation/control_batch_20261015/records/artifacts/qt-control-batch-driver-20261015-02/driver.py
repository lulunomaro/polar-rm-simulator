"""Captured bounded actual original-window batch protocol attempt."""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--attempt',type=int,required=True);a=p.parse_args();assert 1<=a.attempt<=8
out=ROOT/f'artifacts/qt-control-batch-driver-20261015-{a.attempt:02}';out.mkdir()
names=['tools/qa_qt_platform_robotio.py','tools/qa_qt_platform_robotio_peer.py','rm_match/platform_v2/client.py',
 'rm_match/platform_v2/control.py','rm_match/platform_v2/server.py','rm_match/platform_v2/runtime.py','rm_match/platform_v2/camera.py',
 'client_patches/CLIENT_ROBOTIO_BATCH_PATCH_MANIFEST.json','client_patches/robotio_control_batch_v1.patch']
names+=['external/polar-rm-client-robotio-batch-review/rm_client/'+name for name in
 ('sim_platform_client.py','sim_platform_transport.py','sim_platform_handoff.py')]
before={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}
argv=[sys.executable,str(ROOT/'tools/qa_qt_platform_robotio.py'),'--out',str(ROOT/f'artifacts/qt-control-batch-actual-20261015-{a.attempt:02}'),
 '--client-root',str(ROOT/'external/polar-rm-client-robotio-batch-review'),
 '--patch-manifest',str(ROOT/'client_patches/CLIENT_ROBOTIO_BATCH_PATCH_MANIFEST.json'),
 '--duration','12','--host-opencv-threads','4','--host-python-switch-interval-ms','1','--require-control-batch','--run']
(out/'driver.py').write_bytes(Path(__file__).read_bytes())
(out/'COMMAND.json').write_bytes((json.dumps(dict(argv=argv,source_before=before),indent=2)+'\n').encode())
started=time.perf_counter();timed_out=False
with (out/'stdout.log').open('xb') as stdout,(out/'stderr.log').open('xb') as stderr:
    child=subprocess.Popen(argv,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
    (out/'PID.json').write_bytes((json.dumps(dict(pid=child.pid,driver_pid=os.getpid()))+'\n').encode())
    try:code=child.wait(timeout=45.)
    except subprocess.TimeoutExpired:
        timed_out=True;child.terminate();code=child.wait(timeout=5.)
after={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}
result=dict(returncode=code,reaped=child.poll() is not None,elapsed_s=time.perf_counter()-started,timed_out=timed_out,
 forced_direct_child_termination=timed_out,source_before=before,source_after=after,source_unchanged=before==after)
(out/'RESULT.json').write_bytes((json.dumps(result,indent=2)+'\n').encode());print(json.dumps({k:v for k,v in result.items() if k not in ('source_before','source_after')}));raise SystemExit(2 if timed_out else code)
