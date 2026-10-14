"""Observer-only reproduction of the retained five-second drive fault."""
import json
from pathlib import Path
from dataclasses import replace
from rm_match.match_model import make_match_xml
from rm_match.match_engine import MatchSimulation
from rm_match.match_controllers import MatchNavigationPolicy
from rm_match.match_evidence import MatchEvidence
from rm_match.serialization import dumps
import mujoco
from PIL import Image

out=Path('artifacts/drive_dropout_diagnostic');out.mkdir(exist_ok=True)
sim=MatchSimulation(render=False,model_xml=make_match_xml())
nav={r:MatchNavigationPolicy() for r in sim.robot_ids};e=MatchEvidence(sim);commands={};i=0;trace=[]
while sim.time<40-1e-8:
 if i%50==0:
  for rid in sim.robot_ids:
   o=sim.observe(rid,False);d=nav[rid].decide(o);commands[rid]=d.command
   if d.purchase_bundles:sim.judge.purchase_ammo(rid,d.purchase_bundles,episode=o.episode)
  p=nav['red_sentry'];n=p.nav;o=sim.observe('red_sentry',False)
  trace.append(dict(t=sim.time,xy=o.odom_xyyaw,velocity=o.odom_vxyw,goal=n.intent.target_point,
   mode=p.mode,status=n.last_status,desired=p.desired_velocity,path=n.path,goal_blocked=not n.grid.free(n.grid.cell(n.intent.target_point)),
   recover_until=n.recover_until,recovery_direction=n.recovery_direction,
   poses={rid:sim.observe(rid,False,False).odom_xyyaw for rid in sim.robot_ids},
   blocked_cells=[n.grid.center(c) for c in sorted(n.grid.blocked)],
   range_min=min(o.ranges)))
 applied=commands
 if 8<=sim.time<13:
  applied={rid:(replace(c,force_x=0,force_y=0) if rid.endswith('sentry') else c) for rid,c in commands.items()}
 sim.step(applied);e.tick(sim);i+=1
(out/'trace.json').write_text(dumps(trace,indent=2));(out/'summary.json').write_text(dumps(e.snapshot(sim,nav),indent=2))
r=mujoco.Renderer(sim.model,640,960);r.update_scene(sim.data,camera='broadcast_overview');Image.fromarray(r.render()).save(out/'final_overview.png');r.close()
for t in (8,13,16,20,30,39.9):
 row=min(trace,key=lambda r:abs(r['t']-t));print({k:v for k,v in row.items() if k not in ('blocked_cells','poses')},flush=True)
sim.close()
