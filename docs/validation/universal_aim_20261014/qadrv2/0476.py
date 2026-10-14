"""Offline MuJoCo obstacle/phase regressions; never invokes a model or ROS."""
import argparse,json,math,xml.etree.ElementTree as ET
from pathlib import Path
from dataclasses import replace
from rm_match.match_model import make_match_xml
from rm_match.match_engine import MatchSimulation
from rm_match.match_controllers import MatchNavigationPolicy
from rm_match.match_evidence import MatchEvidence
from rm_match.contracts import Command
from rm_match.serialization import dumps


def scenario(name,seconds=40):
    root=ET.fromstring(make_match_xml())
    if name=='occupied_center':
        ET.SubElement(root.find('worldbody'),'geom',name='safety_fixture_center_blocker',
            type='box',pos='0 0 .45',size='1.15 1.15 .45',rgba='.35 .35 .35 1',
            contype='1',conaffinity='1',group='0')
    elif name=='blocked_egress':
        for side in (-1,1):
            ET.SubElement(root.find('worldbody'),'geom',name=f'safety_fixture_egress_blocker_{side}',
                type='box',pos=f'{side*5} {-side*1.65} .45',size='1 .08 .45',
                rgba='.35 .35 .35 1',contype='1',conaffinity='1',group='0')
    sim=MatchSimulation(render=False,model_xml=ET.tostring(root,encoding='unicode'))
    nav={r:MatchNavigationPolicy() for r in sim.robot_ids};evidence=MatchEvidence(sim)
    commands={};i=0;drop_start=None;drop_end=None
    while sim.time<seconds-1e-8:
        if i%50==0:
            for rid in sim.robot_ids:
                o=sim.observe(rid,False)
                if name=='sensor_dropout' and rid.endswith('sentry') and 5.<=sim.time<7.:
                    o=replace(o,ranges=(),range_angles=())
                    if rid=='red_sentry' and drop_start is None:drop_start=o.odom_xyyaw[:2]
                elif name=='sensor_dropout' and rid=='red_sentry' and sim.time>=7. and drop_end is None:
                    drop_end=o.odom_xyyaw[:2]
                d=nav[rid].decide(o);commands[rid]=d.command
                if d.purchase_bundles:sim.judge.purchase_ammo(rid,d.purchase_bundles,episode=o.episode)
        sim.step(commands);evidence.tick(sim);i+=1
    out=evidence.snapshot(sim,nav);out['scenario']=name;out['physics_seconds']=sim.time
    if name=='occupied_center':
        out['pass']=all(nav[r].opening.arrived_at is None for r in ('red_sentry','blue_sentry')) and not evidence.contacts
        out['expected']='Blocked center remains unclaimed by opening supervisor; safe stopping/recovery, no collisions'
    elif name=='blocked_egress':
        out['pass']=all(nav[r].opening.arrived_at is None for r in ('red_sentry','blue_sentry')) and not evidence.contacts
        out['expected']='A blocked starting corridor may hold indefinitely; rushing never overrides obstacle safety'
    elif name=='sensor_dropout':
        drift=math.dist(drop_start,drop_end) if drop_start and drop_end else None
        out['dropout_coast_distance_m']=drift
        out['pass']=drift is not None and drift<.8 and all(nav[r].opening.arrived_at is not None for r in ('red_sentry','blue_sentry')) and not evidence.contacts
        out['expected']='Brake during missing ranges, resume when measurements return; no teleport or body collision'
    else:
        out['pass']=all(p.metrics.goal_reached for p in nav.values()) and not evidence.contacts
        out['expected']='All six reach their own stations without a collision'
    out['contacts']=evidence.contacts
    sim.close();return out


def phase_case():
    sim=MatchSimulation(render=False);p=MatchNavigationPolicy();rid='red_sentry'
    sim.step({rid:Command(force_y=-1)})
    flags=[]
    for phase in ('preparing','countdown','paused','finished'):
        sim.set_phase(phase);o=sim.observe(rid,False);d=p.decide(o);t=sim.time
        for _ in range(100):sim.step({rid:Command(force_y=-50,fire=True)})
        flags.append(d.command==Command() and sim.time==t and not any(sim.data.ctrl))
    sim.reset();o=sim.observe(rid,False);d=p.decide(o)
    flags.append(p.opening.started_at==0 and p.nav.intent.target_point==(0.,0.))
    sim.close()
    return dict(scenario='phase_interruptions_and_reset',pass_all=all(flags),checks=flags,**{'pass':all(flags)})


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=Path('artifacts/navigation_safety_matrix.json'))
    args=p.parse_args();args.out.parent.mkdir(parents=True,exist_ok=True)
    results=[]
    for name in ('nominal','occupied_center','blocked_egress','sensor_dropout'):
        r=scenario(name);results.append(r);print(name,r['pass'],flush=True)
        args.out.write_text(dumps(results,indent=2),encoding='utf-8')
    results.append(phase_case());args.out.write_text(dumps(results,indent=2),encoding='utf-8')
    if not all(r['pass'] for r in results):raise SystemExit(1)
if __name__=='__main__':main()
