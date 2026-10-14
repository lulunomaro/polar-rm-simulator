#!/usr/bin/env python3
"""Bounded real MuJoCo sensor evidence; never a navigation algorithm result."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--seconds',type=float,default=10.)
    parser.add_argument('--run',action='store_true')
    args=parser.parse_args(argv)
    if not 1<=args.seconds<=20:parser.error('--seconds within [1,20] required')
    from rm_match.navigation_sensors import NavigationSensorConfig
    config=NavigationSensorConfig()
    profile,profile_sha=config.identity()
    if not args.run:
        print(json.dumps(dict(status='plan_only',profile=profile,profile_sha256=profile_sha,
            scope='Actual 3D ray/IMU sampling only; no ROS, localization, navigation, camera or native inference'),indent=2));return 0
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    source_names=('rm_match/navigation_sensors.py','rm_match/platform_v2/navigation_contracts.py',
        'rm_match/platform_v2/contracts.py','rm_match/platform_v2/backend.py','rm_match/match_engine.py',
        'rm_match/match_model.py','rm_match/arena.py','rm_match/harness.xml','tools/qa_navigation_sensors.py',
        'rm_match/assets/arenas/rmul_2026_rules_v1_2/arena.xml')
    before={name:digest(ROOT/name) for name in source_names}
    from rm_match.platform_v2.backend import MuJoCoBackend
    from rm_match.platform_v2.navigation_contracts import build_navigation_observation
    backend=MuJoCoBackend(navigation_sensors=config)
    targets={r:dict(motion=None,gimbal=None,fire=False) for r in backend.robot_ids}
    rid='red_sentry';rows=[];retained={};step_times=[];validation=[];errors=[];last_frame=-1
    steps=round(args.seconds/backend.timestep);started=time.perf_counter();deadline=started
    try:
        for index in range(steps):
            # Explicit physical excitation for the sensor check, not navigation.
            if backend.sim_time>=.5:targets[rid]['motion']=dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=.1)
            tick=time.perf_counter();backend.step(targets);step_times.append(time.perf_counter()-tick)
            packet=backend.navigation_sensor_packet(rid)
            if packet is not None:
                cloud=packet['sensors']['pointcloud'];fid=cloud['frame_id']
                if fid!=last_frame:
                    observed=time.perf_counter()
                    o=build_navigation_observation(packet,binding_epoch=1,observed_seq=fid+1,wall_deadline=packet['capture_wall']+.15)
                    validation.append(time.perf_counter()-observed)
                    rows.append(dict(frame_id=fid,start_ns=cloud['acquisition_start_ns'],end_ns=cloud['acquisition_end_ns'],
                        point_count=cloud['point_count'],imu_count=len(o['sensors']['imu']['samples']),
                        capture_wall=packet['capture_wall'],observed_wall=observed,delivery_age_s=observed-packet['capture_wall'],
                        sensor_sha256=hashlib.sha256(json.dumps(o['sensors'],sort_keys=True,separators=(',',':')).encode()).hexdigest()))
                    if not retained:retained['first']=o
                    retained['last']=o;last_frame=fid
            deadline+=backend.timestep
            delay=deadline-time.perf_counter()
            if delay>0:time.sleep(delay)
    except BaseException as exc:errors.append(dict(type=type(exc).__name__,message=str(exc)))
    duration=time.perf_counter()-started
    actual_steps=len(step_times)
    backend.close()
    after={name:digest(ROOT/name) for name in source_names}
    def distribution(values):
        if not values:return dict(count=0,p50_ms=None,p95_ms=None,max_ms=None)
        values=sorted(values)
        def pct(q):
            position=(len(values)-1)*q;i=int(position)
            return (values[i]+(values[min(i+1,len(values)-1)]-values[i])*(position-i))*1000
        return dict(count=len(values),p50_ms=pct(.5),p95_ms=pct(.95),max_ms=values[-1]*1000)
    for name,o in retained.items():
        raw=json.dumps(o,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        (out/(name+'_observation.json.gz')).write_bytes(gzip.compress(raw,mtime=0))
    report=dict(schema='polar.navigation-sensor-qa.v1',scope='Actual MuJoCo 3D ray/IMU only; physical excitation is scripted, no own navigation algorithm',
        navigation_qualified=False,full_match_qualified=False,hardware_qualified=False,
        profile=profile,profile_sha256=profile_sha,requested_seconds=args.seconds,
        actual_steps=actual_steps,simulation_seconds=actual_steps*backend.timestep,wall_seconds=duration,
        physics_rtf=actual_steps*backend.timestep/duration,
        attempted_rays=actual_steps*backend._navigation_sensors.rays_per_step,
        completed_clouds=len(rows),returned_points=sum(r['point_count'] for r in rows),
        clouds=rows,step_durations=distribution(step_times),validation_durations=distribution(validation),
        no_orientation_or_ideal_odometry=True,image_budget_80ms_changed=False,control_window_150ms_changed=False,
        source_files_sha256=before,source_unchanged=before==after,errors=errors)
    (out/'RESULT.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    (out/'EVIDENCE_MANIFEST.json').write_text(json.dumps({p.name:digest(p) for p in out.iterdir() if p.is_file()},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('scope','actual_steps','completed_clouds','physics_rtf','source_unchanged','errors')},indent=2))
    return 0 if not errors and before==after and len(rows)>0 and actual_steps==steps else 2


if __name__=='__main__':raise SystemExit(main())
