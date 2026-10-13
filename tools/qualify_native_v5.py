"""Short source/clock/camera qualification, not scored match evidence."""
import argparse,json,os,sys,time
from pathlib import Path
os.environ.setdefault('MUJOCO_GL','egl');os.environ.setdefault('EGL_PLATFORM','surfaceless');os.environ.setdefault('OMP_NUM_THREADS','1')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mujoco
from rm_match.timing.plant import AuditedMatchSimulation
from rm_match.timing.aim import TimingMatchAim
from rm_match.timing.transport import MatchFireTransport
from rm_match.rmcs_stop_aim import verify_own_contract
from rm_match.contracts import Command
p=argparse.ArgumentParser();p.add_argument('--scene',type=Path,required=True);p.add_argument('--spec',type=Path,required=True);p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--seconds',type=float,default=1.5);a=p.parse_args()
a.out.mkdir(parents=True,exist_ok=False)
sim=AuditedMatchSimulation(render=False,model_xml=a.scene.read_text())
rows=json.loads(a.snapshot.read_text());snap=min(rows,key=lambda x:abs(x['t']-18.))
sim.data.qpos[:]=snap['qpos'];sim.data.qvel[:]=0;mujoco.mj_forward(sim.model,sim.data)
source=TimingMatchAim(sim,a.spec,a.out/'source');transport=MatchFireTransport('red_sentry');cmd=Command();start=time.perf_counter()
try:
 for i in range(round(a.seconds*2000)):
  o=sim.observe('red_sentry',False,False)
  if i%25==0:source.capture_tick(o)
  decision=None
  if i%20==0:
   cmd=source.act(o,'occupation',(0.,0.));decision=bool(cmd.fire)
   if source.error:raise RuntimeError(source.error)
  cmd=transport.apply(sim,i,cmd,source,(0.,0.),decision=decision)
  sim.step({'red_sentry':cmd})
 checks=verify_own_contract(sim,'red_sentry')
 result=dict(qualification_only=True,physics_seconds=sim.time,wall_seconds=time.perf_counter()-start,
  source_calls=source.source_calls,captures=source.captured_frames,delivered_frames=source.delivered_frames,
  tracking_ticks=source.tracking_ticks,fire_permission_ticks=source.fire_ticks,uid=sim.terminal_uid_audit(),pose=checks,
  fixture='Historical 18-second world qpos, zeroed velocities, passive others; not a scored match')
 if source.source_calls<50 or source.delivered_frames<10:raise ValueError('Insufficient native coverage')
 for name,value in [('result.json',result),('launches.json',sim.launches),('resolutions.json',sim.resolutions),('fire_transport.json',transport.events)]:
  (a.out/name).write_text(json.dumps(value,indent=2))
 print(json.dumps(result),flush=True)
finally:
 transport.delay.advance(sim.physics_step,safe=False,reasons=['qualification_end']);source.close();sim.close()
