"""Bounded real camera/native loop; private scene JSON is an explicit QA input."""
import sys
if not __debug__:raise SystemExit('Qualification refuses Python optimization')
import os
os.environ.setdefault('MUJOCO_GL','egl');os.environ.setdefault('EGL_PLATFORM','surfaceless');os.environ.setdefault('OMP_NUM_THREADS','1');os.environ.setdefault('MESA_SHADER_CACHE_DISABLE','true')
import argparse,base64,hashlib,json,time,threading
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--scene-json',required=True);p.add_argument('--native-spec',required=True);p.add_argument('--max-wall-seconds',type=float,default=25.);p.add_argument('--real-time-factor',type=float,default=.1);a=p.parse_args()
if not 5<a.max_wall_seconds<=90:raise SystemExit('Bounded 5..90 wall seconds required')
out=Path(a.out);out.mkdir(parents=True,exist_ok=False)
source_root=Path(__file__).resolve().parents[3]
def loaded_source_manifest():
 return {str(p.relative_to(source_root)):hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted((source_root/'rm_match').rglob('*.py'))}
source_before=loaded_source_manifest()
import mujoco
import numpy as np
from PIL import Image
from rm_match.platform_v2.backend import MuJoCoBackend
from rm_match.platform_v2.camera import CameraProvider,MuJoCoCameraRenderer
from rm_match.platform_v2.runtime import PlatformRuntime
from rm_match.platform_v2.adapters import default_registry
from rm_match.platform_v2.server import PlatformHTTPServer,TransportConfig
from rm_match.platform_v2.qa_multiclient import HTTPClient

if loaded_source_manifest()!=source_before:raise RuntimeError('Source changed during imports')
(out/'loaded-source.json').write_text(json.dumps(source_before,indent=2))
rows=[];errors=[];samples=[]
backend=MuJoCoBackend(camera=True);sim=backend._sim
scene=Path(a.scene_json);snap=min(json.loads(scene.read_text()),key=lambda v:abs(v['t']-18.))
sim.data.qpos[:]=snap['qpos'];sim.data.qvel[:]=0;mujoco.mj_forward(sim.model,sim.data)
# The existing physical scene only initializes QA. Other vehicles are passively held.
# No scene pose/roster enters native request beyond controlled vehicle own sensors.
def trace(row):
 if row['event']=='actuator_consumed' and row['robot_id']!='red_sentry':return
 if row['event']=='physics_apply':
  rid='red_sentry';target=row['targets'][rid];budget=row['output_budgets'][rid];epoch=row['aim_bindings'][rid]
  row={k:v for k,v in row.items() if k not in ('targets','output_budgets','aim_bindings')}
  row.update(robot_id=rid,target=target,budget=budget,binding_epoch=epoch,
      own_qpos=sim.data.qpos[sim.qindices[rid]].tolist(),own_qvel=sim.data.qvel[sim.vindices[rid]].tolist(),actuator_ctrl=sim.data.ctrl[sim.aindices[rid]].tolist(),command=backend.last_commands.get(rid))
 rows.append(row)
class Render(MuJoCoCameraRenderer):
 def __init__(self,*v):
  super().__init__(*v)
  from OpenGL.GL import glGetString,GL_RENDERER
  rows.append(dict(event='renderer',renderer=glGetString(GL_RENDERER).decode(),wall_time=time.monotonic()))
 def render(self,cap):
  begin=time.monotonic();rgb=super().render(cap)
  rows.append(dict(event='rendered',robot_id=cap.robot_id,episode=cap.episode,frame_id=cap.frame_seq,capture_wall=cap.wall_time,capture_sim_time=cap.sim_time,render_start=begin,render_end=time.monotonic(),raw_rgb_sha256=hashlib.sha256(rgb.tobytes()).hexdigest(),raw_bgr_sha256=hashlib.sha256(np.ascontiguousarray(rgb[:,:,::-1]).tobytes()).hexdigest(),own_at_capture=cap.own))
  if cap.frame_seq<=3:Image.fromarray(rgb).save(out/f'frame-{cap.frame_seq}.png')
  return rgb
provider=CameraProvider(sim,renderer_factory=Render,total_fps=2.)
registry=default_registry(native_spec=a.native_spec,native_out=out/'native',native_trace=trace)
runtime=PlatformRuntime(backend,camera=provider,registry=registry,observation_period=.001,trace=trace)
server=PlatformHTTPServer(TransportConfig(port=0),runtime)
http=threading.Thread(target=server.serve_forever,daemon=True)
def authority():
 try:runtime.run(max_wall_seconds=a.max_wall_seconds+5,real_time_factor=a.real_time_factor)
 except BaseException as e:errors.append(type(e).__name__+':'+str(e))
physics=threading.Thread(target=authority,daemon=True)
http.start();physics.start();client=HTTPClient(f'http://127.0.0.1:{server.server_address[1]}');start=time.monotonic();ep=None
try:
 client.open('operator');client.call('/v2/watch',dict(robot_id='red_sentry'))
 ep=client.call('/v2/claim',dict(robot_id='red_sentry',channels=['gimbal']))['lease_epochs']
 bound=client.call('/v2/bind',dict(robot_id='red_sentry',kind='aim',lease_epochs=ep,adapter_id='aim_native_rmcs_v1',config=dict(fov_degrees=180.,circle_radius_x_norm=1.,circle_radius_y_norm=1.)))
 while time.monotonic()-start<a.max_wall_seconds:
  client.call('/v2/renew',dict(robot_id='red_sentry',lease_epochs=ep));state=client.call('/v2/state')
  samples.append({k:state.get(k) for k in ('sim_time','algorithm_status','applied_targets','applied_commands','camera')})
  time.sleep(.15)
 release_wall=time.monotonic();client.call('/v2/release',dict(robot_id='red_sentry',lease_epochs=ep));time.sleep(.3);samples.append(client.call('/v2/state'))
except BaseException as e:errors.append(type(e).__name__+':'+str(e));release_wall=None
finally:
 runtime.request_stop();physics.join(4);provider.wait_closed(4);server.shutdown();server.server_close();http.join(2)
 if loaded_source_manifest()!=source_before:errors.append('Source changed during run')
 (out/'ledger.jsonl').write_text(''.join(json.dumps(r,allow_nan=False)+'\n' for r in rows));(out/'samples.json').write_text(json.dumps(samples,indent=2))
 natives=[r for r in rows if r['event']=='native_result'];applied=[r for r in rows if r['event']=='physics_apply' and r['target']['gimbal'] is not None]
 result=dict(scope='bounded_actual_camera_native_loop_not_full_match',errors=errors,real_time_factor_limit=a.real_time_factor,actual_elapsed_wall=time.monotonic()-start,sim_time=sim.time,native_frames=len(natives),native_active=sum(r['response']['should_control'] is True for r in natives),applied_aim_ticks=len(applied),all_manual_fire_false=all(not r['target']['fire'] for r in rows if r['event']=='physics_apply'),release_wall=release_wall,scene_sha256=hashlib.sha256(scene.read_bytes()).hexdigest(),spec_sha256=hashlib.sha256(Path(a.native_spec).read_bytes()).hexdigest(),raw_sampling='native_1440x1080',camera=provider.status())
 (out/'summary.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
