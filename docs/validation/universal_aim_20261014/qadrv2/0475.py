"""Additional local obstacle/fault fixtures, not competition outcome claims.

The six main robot spawn coordinates are never changed. Added parked robot-shaped
obstacles and temporary drive dropout are explicit test-only faults, not tactics
used to weaken either team in the recorded full matches.
"""
from copy import deepcopy
from pathlib import Path
import json,xml.etree.ElementTree as ET
from dataclasses import replace
from rm_match.match_model import make_match_xml
from rm_match.match_engine import MatchSimulation
from rm_match.match_controllers import MatchNavigationPolicy
from rm_match.match_evidence import MatchEvidence
from rm_match.contracts import Command
from rm_match.serialization import dumps


def run(name):
 root=ET.fromstring(make_match_xml('baseline'))
 if name=='enemy_shaped_egress_obstacle':
  for team,side in [('red',1),('blue',-1)]:
   # Copy full opposing body shape into a named static obstacle. Remove every
   # joint/camera to keep it an obstacle fixture, not an extra scored player.
   enemy='blue' if team=='red' else 'red'
   body=deepcopy(root.find(f'worldbody/body[@name="{enemy}_sentry__robot"]'))
   for parent in list(body.iter()):
    for child in list(parent):
     if child.tag in ('joint','freejoint','camera'):parent.remove(child)
    if 'name' in parent.attrib:parent.set('name','fixture_'+team+'_'+parent.get('name'))
   body.set('pos',f'{-5.25*side} {1.65*side} .25')
   root.find('worldbody').append(body)
 sim=MatchSimulation(render=False,model_xml=ET.tostring(root,encoding='unicode'))
 nav={r:MatchNavigationPolicy() for r in sim.robot_ids};e=MatchEvidence(sim);commands={};i=0
 while sim.time<40-1e-8:
  if i%50==0:
   for rid in sim.robot_ids:
    o=sim.observe(rid,False);d=nav[rid].decide(o);commands[rid]=d.command
    if d.purchase_bundles:sim.judge.purchase_ammo(rid,d.purchase_bundles,episode=o.episode)
  applied=commands
  if name=='symmetric_drive_dropout' and 8<=sim.time<13:
   applied={rid:(replace(c,force_x=0,force_y=0) if rid.endswith('sentry') else c) for rid,c in commands.items()}
  sim.step(applied);e.tick(sim);i+=1
 result=e.snapshot(sim,nav);result['scenario']=name;result['contacts']=e.contacts
 if name=='enemy_shaped_egress_obstacle':
  result['pass']=not e.contacts and all(nav[r].opening.started_at==0 and nav[r].opening.arrived_at is None for r in ('red_sentry','blue_sentry'))
  result['scope']='Actual same-sized opposing chassis shape as anonymous static range obstacle; no enemy behavior or referee occupant claim'
 else:
  result['pass']=not e.contacts and all(nav[r].opening.arrived_at is not None for r in ('red_sentry','blue_sentry'))
  result['scope']='Five-second symmetric drive command dropout; no qpos teleport, ordinary damping and feedback; eventual arrival required'
 sim.close();return result

if __name__=='__main__':
 results=[];out=Path('artifacts/navigation_extended_matrix.json')
 for name in ('enemy_shaped_egress_obstacle','symmetric_drive_dropout'):
  result=run(name);results.append(result);out.write_text(dumps(results,indent=2));print(name,result['pass'],flush=True)
 if not all(x['pass'] for x in results):raise SystemExit(1)
