"""Bounded OFFLINE/SIL server for the preregistered one-vehicle native scenario."""
import sys
if not __debug__:raise SystemExit('Qualification requires Python without -O')
import os
os.environ.setdefault('MUJOCO_GL','egl');os.environ.setdefault('EGL_PLATFORM','surfaceless');os.environ.setdefault('OMP_NUM_THREADS','1');os.environ.setdefault('MESA_SHADER_CACHE_DISABLE','true')
import argparse,hashlib,json,time,threading,signal,platform
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--scene-json',type=Path,required=True);p.add_argument('--native-spec',type=Path,required=True);p.add_argument('--host-delay',type=float,choices=(0.,.15),required=True);p.add_argument('--port',type=int,default=0);a=p.parse_args()
a.out.mkdir(parents=True,exist_ok=False);root=Path(__file__).resolve().parents[3]
def hashes():return {str(x.relative_to(root)):hashlib.sha256(x.read_bytes()).hexdigest() for x in sorted((root/'rm_match').rglob('*.py'))}
source=hashes()
import mujoco
import numpy as np
from PIL import Image
from rm_match.platform_v2.backend import MuJoCoBackend
from rm_match.platform_v2.camera import CameraProvider,MuJoCoCameraRenderer
from rm_match.platform_v2.offline_runtime import OfflineRuntime
from rm_match.platform_v2.offline_native import OfflineNativeAdapter
from rm_match.platform_v2.native_adapter import validate_native_spec
from rm_match.platform_v2.server import PlatformHTTPServer,TransportConfig
from rm_match.platform_v2.offline_lifecycle import wait_for_driver_cleanup
if hashes()!=source:raise RuntimeError('Source changed during import')
(a.out/'loaded-source.json').write_text(json.dumps(source,indent=2));spec,spec_sha=validate_native_spec(a.native_spec)
backend=MuJoCoBackend(camera=True);sim=backend._sim;snapshot=min(json.loads(a.scene_json.read_text()),key=lambda v:abs(v['t']-18.))
sim.data.qpos[:]=snapshot['qpos'];sim.data.qvel[:]=0;mujoco.mj_forward(sim.model,sim.data)
mujoco.mj_saveLastXML(str(a.out/'actual-model.xml'),sim.model)
model_identity=dict(mjcf_sha256=hashlib.sha256((a.out/'actual-model.xml').read_bytes()).hexdigest(),mujoco_version=mujoco.__version__,numpy_version=np.__version__,python_version=platform.python_version())
rows=[]
def trace(row):rows.append(row)
class Render(MuJoCoCameraRenderer):
 def __init__(self,*args):
  super().__init__(*args)
  from OpenGL.GL import glGetString,GL_RENDERER
  trace(dict(event='renderer',renderer=glGetString(GL_RENDERER).decode(),wall_time=time.monotonic()))
 def render(self,cap):
  start=time.monotonic();rgb=super().render(cap);end=time.monotonic()
  frame_path=a.out/f'frame-{cap.frame_seq:04}.png';Image.fromarray(rgb).save(frame_path)
  trace(dict(event='rendered',robot_id=cap.robot_id,episode=cap.episode,frame_id=cap.frame_seq,capture_sim_time=cap.sim_time,capture_wall=cap.wall_time,render_start=start,render_end=end,raw_rgb_sha256=hashlib.sha256(rgb.tobytes()).hexdigest(),raw_bgr_sha256=hashlib.sha256(np.ascontiguousarray(rgb[:,:,::-1]).tobytes()).hexdigest(),own_at_capture=cap.own,frame_file=frame_path.name))
  return rgb
camera=CameraProvider(sim,renderer_factory=Render)
def factory():return OfflineNativeAdapter(dict(fov_degrees=180.,circle_radius_x_norm=1.,circle_radius_y_norm=1.),spec_path=a.native_spec,out=a.out/'native',registered_spec_sha=spec_sha,trace=trace)
runtime=OfflineRuntime(backend,camera=camera,native_factory=factory,captures=24,host_delay_s=a.host_delay,trace=trace)
signal.signal(signal.SIGTERM,lambda *_:runtime.request_stop());signal.signal(signal.SIGINT,lambda *_:runtime.request_stop())
server=PlatformHTTPServer(TransportConfig(port=a.port),runtime);http=threading.Thread(target=server.serve_forever,daemon=True);http.start()
ready=dict(model_identity=model_identity,url=f'http://127.0.0.1:{server.server_address[1]}',clock_profile='offline_modeled_latency_v1',configured_host_delay_s=a.host_delay,captures=24,source_manifest_sha256=hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest(),spec_sha256=spec_sha,scene_sha256=hashlib.sha256(a.scene_json.read_bytes()).hexdigest(),initial_pose_snapshot_time=snapshot['t'],actual_new_episode_mj_time=float(sim.time),source_binary_sha256=spec['sha256']['binary'],model_sha256=spec['model_sha256'])
(a.out/'ready.json').write_text(json.dumps(ready,indent=2));print(json.dumps(ready),flush=True)
started=time.monotonic();cleanup_result=dict(confirmed=False,reason='terminal_not_reached')
try:
 runtime.run(max_wall_seconds=90.)
 # Runtime has already neutralized and revoked leases; retain only bounded HTTP
 # cleanup service so the driver can stop renewal before closing its session.
 terminal=dict(event='offline_terminal',state=runtime.state,reason=runtime.halt_reason,wall_time=time.monotonic(),sim_time=float(sim.time),episode=backend.episode,cleanup_grace_s=2.)
 trace(terminal);print(json.dumps(terminal),flush=True)
 cleanup_result=wait_for_driver_cleanup(a.out/'driver-cleanup.json',runtime.binding['owner'] if runtime.binding else None,runtime.control)
 trace(dict(event='http_cleanup_handshake',**cleanup_result))
finally:
 camera.wait_closed(3)
 if runtime.worker:runtime.worker.thread.join(3)
 server.shutdown();server.server_close();http.join(2)
 (a.out/'ledger.jsonl').write_text(''.join(json.dumps(r,allow_nan=False)+'\n' for r in rows))
 if hashes()!=source:runtime.state='HALTED';runtime.halt_reason='source_changed_during_run'
 result=dict(lifecycle_cleanup=cleanup_result,state=runtime.state,reason=runtime.halt_reason,completed_captures=runtime.completed_captures,sim_time=float(sim.time),tick=runtime.tick,wall_elapsed_s=time.monotonic()-started,host_delay_s=a.host_delay,source=source,scope='offline_SIL_not_realtime_HIL_or_full_match',final_state=runtime.cached)
 (a.out/'summary.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ('source','final_state')}),flush=True)
