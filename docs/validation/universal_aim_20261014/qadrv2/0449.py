"""Bounded no-render real-physics test server. No camera fixture is served here."""
from __future__ import annotations
import sys
if not __debug__:raise SystemExit('Qualification requires normal Python; -O is forbidden')
import argparse,hashlib,json,signal,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
def source_hashes():return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'rm_match').rglob('*.py'))}
IMPORTED_SOURCE=source_hashes()
from rm_match.platform_v2.backend import MuJoCoBackend
from rm_match.platform_v2.runtime import PlatformRuntime
from rm_match.platform_v2.server import PlatformHTTPServer,TransportConfig
import mujoco

def main(argv=None):
    p=argparse.ArgumentParser(allow_abbrev=False);p.add_argument('--out',type=Path,required=True);p.add_argument('--max-wall-seconds',type=float,default=20.)
    p.add_argument('--admission-manifest',type=Path,required=True)
    a=p.parse_args(argv)
    from rm_match.platform_v2.admission import AdmissionPolicy
    admission=AdmissionPolicy.from_manifest(a.admission_manifest)
    if not 1<=a.max_wall_seconds<=30:raise ValueError('Bounded duration required')
    a.out.mkdir(parents=True,exist_ok=False);rid='red_sentry'
    log=(a.out/'consumption.jsonl').open('x')
    def trace(event):
        if event['event']=='actuator_consumed' and event['robot_id']==rid and event['phase'] in ('integration_entry','fire'):log.write(json.dumps(event,allow_nan=False)+'\n')
    b=MuJoCoBackend(camera=False);runtime=PlatformRuntime(b,trace=trace)
    server=PlatformHTTPServer(TransportConfig(port=0,max_http_workers=8,admission_policy=admission),runtime)
    thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
    def stop(*_):runtime.request_stop()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    if source_hashes()!=IMPORTED_SOURCE:raise RuntimeError('Source changed during import/initialization')
    ready=dict(event='no_gl_control_ready',url='http://127.0.0.1:'+str(server.server_address[1]),robot_id=rid,camera_available=False,mujoco_version=mujoco.__version__,source_hashes=IMPORTED_SOURCE)
    (a.out/'ready.json').write_text(json.dumps(ready,indent=2)+'\n');print(json.dumps(ready),flush=True)
    try:runtime.run(max_wall_seconds=a.max_wall_seconds)
    finally:
        log.close();server.shutdown();server.server_close();thread.join(1)
        if thread.is_alive():raise RuntimeError('Server did not stop within bound')
        unchanged=source_hashes()==IMPORTED_SOURCE
        (a.out/'final.json').write_text(json.dumps(dict(state=runtime.cached,projectile_counter=b._sim.projectile_counter,error=runtime.error,source_unchanged=unchanged),indent=2)+'\n')
        if not unchanged:raise RuntimeError('Source changed during qualification')

if __name__=='__main__':main()
