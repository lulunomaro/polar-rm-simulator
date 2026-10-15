#!/usr/bin/env python3
"""Offline synthetic commands -> actual MuJoCo guard/actuator regression.

No camera, detector, native aim, SDK admission or live timing qualification.
The optional baseline is trusted local source captured from the parent commit.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def wrap(x):return math.atan2(math.sin(x),math.cos(x))


def run(out,baseline=None):
    from rm_match.platform_v2.backend import MuJoCoBackend
    from rm_match.platform_v2.aim_reference import SourceBaseAim
    from rm_match.platform_v2.contracts import build_observation,action_for
    if baseline is not None:
        spec=importlib.util.spec_from_file_location('rm_match.platform_v2._mechanics_baseline',baseline)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        MuJoCoBackend=module.MuJoCoBackend
    out.mkdir(parents=True,exist_ok=False)
    sources={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT/'rm_match').rglob('*.py')}
    sources[Path(__file__).relative_to(ROOT).as_posix()]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    backend=MuJoCoBackend();clock=lambda:backend.sim_time
    actors={'red_infantry':'base_link','blue_infantry':'inertial_from_source_base_v1'}
    refs={};actions={};snapshots={};receipts=[];checks=[];fire=0;error=None;revoked=set()
    initial={r:backend.own_pose(r) for r in actors}
    world_yaw={r:wrap(initial[r]['yaw']+.6) for r in actors}
    maximum={'command_yaw_error_rad':0.,'ctrl_yaw_error_rad':0.,'pitch_error_rad':0.}
    start=time.perf_counter()
    try:
        for step in range(1000):
            sim_time=backend.sim_time
            # Explicit fresh SYNTHETIC command every 40ms until 1.4s. None
            # of these objects claims to originate from pixels or a detector.
            if step%20==0 and sim_time<1.4:
                for rid,reference in actors.items():
                    raw=backend.sensor_sample(rid)
                    o=build_observation(raw,binding_epoch=1,observed_seq=step//20+1,wall_deadline=sim_time+.08)
                    yaw=.6 if reference=='base_link' else wrap(world_yaw[rid]-o['own']['odom_xyyaw'][2])
                    action=action_for(o,'aim','gimbal_target',dict(frame='base_link',yaw_rad=yaw,pitch_rad=.12,
                        active=True,confidence=None,fire_permission=False))
                    actions[rid]=action;snapshots[rid]=copy.deepcopy(action)
                    refs[rid]=SourceBaseAim.accepted(action,o,None)
            targets={rid:dict(motion=None,gimbal=None,fire=False) for rid in backend.robot_ids}
            for rid in actors:
                targets[rid].update(motion=dict(frame='base_link',vx_mps=0.,vy_mps=0.,wz_rps=.9),
                    # Deliberately stale preparation candidate: final guard must
                    # apply its returned mechanical angle, not only log it.
                    gimbal=copy.deepcopy(actions[rid]['command']))
            final={}
            def guard(rid,command,phase,sampled_wall=None):
                if rid not in actors:return targets[rid]
                now=clock() if sampled_wall is None else sampled_wall
                source=actions[rid];pose=backend.own_pose(rid)
                live=now<source['wall_deadline'] and rid not in revoked
                target=dict(targets[rid],gimbal=None,fire=False);reference_receipt=None
                if live:
                    if actors[rid]=='base_link':target['gimbal']=dict(source['command'])
                    else:target['gimbal'],reference_receipt=refs[rid].target(pose['yaw'])
                    expected_yaw=.6 if actors[rid]=='base_link' else wrap(world_yaw[rid]-pose['yaw'])
                    if abs(wrap(target['gimbal']['yaw_rad']-expected_yaw))>1e-12:
                        raise AssertionError('source/current own frame mismatch')
                else:
                    refs.pop(rid,None);revoked.add(rid)
                # Exercise the same alias mutation shape as runtime's guard.
                targets[rid]=target
                final[rid]=dict(yaw=pose['gimbal_yaw'] if target['gimbal'] is None else target['gimbal']['yaw_rad'],
                    pitch=pose['gimbal_pitch'] if target['gimbal'] is None else target['gimbal']['pitch_rad'])
                receipts.append(dict(step=step,robot_id=rid,phase=phase,sim_time=sim_time,
                    synthetic_clock_s=now,own_yaw_rad=pose['yaw'],active=live,source={k:source[k] for k in
                    ('robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline')},
                    target=copy.deepcopy(target),reference=reference_receipt))
                return target
            backend.guarded_step(targets,guard,clock=clock)
            for rid,expected in final.items():
                actual=backend.last_commands[rid];ctrl=backend._sim.data.ctrl[backend._sim.aindices[rid]]
                errors=(abs(wrap(actual['gimbal_yaw']-expected['yaw'])),
                    abs(wrap(float(ctrl[3])-expected['yaw'])),abs(actual['gimbal_pitch']-expected['pitch']))
                for key,value in zip(maximum,errors):maximum[key]=max(maximum[key],value)
                fire+=bool(actual['fire'])
            if any(actions[r]!=snapshots[r] for r in actors):raise AssertionError('original synthetic action mutated')
        final_pose={r:backend.own_pose(r) for r in actors}
        checks=[all(x<1e-11 for x in maximum.values()),fire==0,revoked==set(actors),
            all(abs(final_pose[r]['yaw']-initial[r]['yaw'])>.5 for r in actors),
            all(refs.get(r) is None for r in actors),backend._sim.time>1.99]
    except Exception as exc:error=type(exc).__name__+':'+str(exc);final_pose={}
    finally:backend.close()
    unchanged=all((ROOT/name).is_file() and hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
        for name,digest in sources.items())
    with (out/'RECEIPTS.jsonl').open('x',encoding='utf8',newline='\n') as stream:
        for row in receipts:stream.write(json.dumps(row,allow_nan=False,separators=(',',':'))+'\n')
    result=dict(schema='polar.aim-reference.mechanics.v1',passed=error is None and all(checks) and unchanged,
        checks=checks,errors=[] if error is None else [error],maximum_errors=maximum,steps=1000,
        synthetic_seconds=2.,elapsed_wall_s=time.perf_counter()-start,initial_own_pose=initial,final_own_pose=final_pose,
        fire_true=fire,source_unchanged=unchanged,source_sha256=sources,
        baseline=None if baseline is None else dict(path=str(baseline),sha256=hashlib.sha256(baseline.read_bytes()).hexdigest()),
        camera_frames=0,native_inferences=0,sdk_requests=0,live_timing_qualified=False,moving_native_aim_qualified=False,
        scope='Offline synthetic commands and own kinematics -> real MuJoCo backend/guard/ctrl; not perception or SDK qualification')
    (out/'RESULT.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
    print(json.dumps({k:result[k] for k in ('passed','errors','maximum_errors','elapsed_wall_s','source_unchanged')}))
    return 0 if result['passed'] else 2


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--baseline-source',type=Path);a=p.parse_args(argv)
    if a.out.exists():p.error('Fresh output directory required')
    return run(a.out.absolute(),None if a.baseline_source is None else a.baseline_source.absolute())


if __name__=='__main__':raise SystemExit(main())
