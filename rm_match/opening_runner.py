"""Reproducible opening navigation and full shared-world observer recording."""
import argparse,os,sys,time,json,hashlib
from pathlib import Path
from dataclasses import asdict,replace
if sys.platform.startswith('linux') and not os.environ.get('DISPLAY'):
    os.environ.setdefault('MUJOCO_GL','egl');os.environ.setdefault('EGL_PLATFORM','surfaceless')
    os.environ.setdefault('MESA_SHADER_CACHE_DISABLE','true')
import numpy as np
from PIL import Image
from .timing.plant import AuditedMatchSimulation as MatchSimulation
from .timing.transport import MatchFireTransport
from .match_runner import build_policies,control_tick,configure_actual_aim
from .match_evidence import MatchEvidence
from .broadcast import Broadcast
from .spectator_effects import SpectatorEffects
from .contracts import Command
from .serialization import dumps


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--mode',choices=['navigation','match'],default='match')
    p.add_argument('--max-seconds',type=float,default=300.)
    p.add_argument('--out',type=Path,default=Path('artifacts/opening_match'))
    p.add_argument('--no-video',action='store_true')
    p.add_argument('--resilient-recording',action='store_true',help='Observer-only fragmented MP4, resource log and durable checkpoints')
    p.add_argument('--no-rgb',action='store_true')
    p.add_argument('--aim',choices=['baseline','actual-sentry','original-rmcs-stop','rmcs-stop'],default='baseline')
    p.add_argument('--rmcs-spec',type=Path)
    p.add_argument('--armor-profile',choices=['baseline','emissive','infantry_v22','role_v23'],default='baseline')
    p.add_argument('--aim-adapter-module',default='upper_aim.adapter')
    p.add_argument('--aim-source',type=Path);p.add_argument('--detector',type=Path);p.add_argument('--policy',type=Path)
    p.add_argument('--detector-profile',choices=['shenzhen_0526','shenzhen_0708'],default='shenzhen_0526')
    args=p.parse_args()
    if args.aim=='original-rmcs-stop':
        p.error('timing-v5 supports only frozen 40f7 --aim rmcs-stop; the legacy original-rmcs-stop protocol is unsupported in this runner')
    if args.no_rgb and not args.no_video:p.error('--no-rgb requires --no-video')
    if args.aim=='actual-sentry' and (args.no_rgb or not all([args.aim_source,args.detector,args.policy])):
        p.error('Explicit actual source/model paths and RGB required')
    if args.aim in ('original-rmcs-stop','rmcs-stop') and (args.no_rgb or args.mode!='match' or not args.rmcs_spec):
        p.error('Original RMCS requires --rmcs-spec, RGB and match mode')
    args.out.mkdir(parents=True,exist_ok=True)
    from .match_model import make_match_xml
    xml=make_match_xml(armor_profile=args.armor_profile)
    import xml.etree.ElementTree as ET
    root=ET.fromstring(xml);root.find('option').set('timestep','0.0005');xml=ET.tostring(root,encoding='unicode')
    if args.aim in ('original-rmcs-stop','rmcs-stop'):
        from .rmcs_stop_aim import configure_native_camera
        from .timing.aim import TimingMatchAim as RMCSStopAim
        xml=configure_native_camera(xml)
    (args.out/'scene.xml').write_text(xml)
    sim=MatchSimulation(render=not args.no_rgb,spectator_effects=SpectatorEffects(),model_xml=xml)
    nav,aim=build_policies(sim);actual_ids=configure_actual_aim(sim,aim,args)
    source=None;fire_transport=None
    if args.aim in ('original-rmcs-stop','rmcs-stop'):
        source=RMCSStopAim(sim,args.rmcs_spec,args.out/('rmcs_original_source' if args.aim=='original-rmcs-stop' else 'rmcs_source'))
        if args.aim=='original-rmcs-stop' and source.repaired:
            raise ValueError('Use --aim rmcs-stop for the repaired candidate; never label it original')
        actual_ids=['red_sentry'];fire_transport=MatchFireTransport('red_sentry')
        sim.actual_aim_description='RED: '+source.source_label+', STOPPED ONLY'
    evidence=MatchEvidence(sim)
    screen=None if args.no_video else Broadcast(sim)
    writer=None;camera_writer=None;camera_view=None
    from .recording_health import RecordingHealth,FRAGMENTED_MP4_ARGS
    health=RecordingHealth(args.out,args.resilient_recording)
    if screen:
        import imageio.v2 as imageio
        writer=imageio.get_writer(args.out/('opening_navigation.mp4' if args.mode=='navigation' else 'full_match.mp4'),fps=10,codec='libx264',quality=8,macro_block_size=1,ffmpeg_params=FRAGMENTED_MP4_ARGS if args.resilient_recording else None)
    if screen:
        from .timing.camera_view import CameraObserver
        camera_view=CameraObserver(sim)
        camera_writer=imageio.get_writer(args.out/'red_sentry_camera.mp4',fps=10,codec='libx264',quality=8,macro_block_size=1,ffmpeg_params=FRAGMENTED_MP4_ARGS if args.resilient_recording else None)
    import gzip
    sim.trajectory_file=gzip.open(args.out/'projectile_trajectories.jsonl.gz','wt',compresslevel=3)
    commands={};observations={};statuses={};frames=0;i=0;start=time.perf_counter()
    replay=[];state_frames=[]
    limit=min(300.,args.max_seconds)
    try:
        with (args.out/'controller_telemetry.jsonl').open('w',encoding='utf-8') as telemetry:
            while sim.time<limit-1e-9 and not sim.judge.terminal:
                if i%200==0:
                    if args.mode=='match':
                        commands,observations,statuses=control_tick(sim,nav,aim,not args.no_rgb,actual_ids)
                    else:
                        observations={r:sim.observe(r,include_rgb=(not args.no_rgb and r.endswith('sentry'))) for r in sim.robot_ids}
                        commands={}
                        for rid,o in observations.items():
                            # Navigation-only run excludes visual tactical contacts.
                            d=nav[rid].decide(replace(o,rgb=np.empty((0,0,3),dtype=np.uint8)))
                            commands[rid]=d.command
                            if d.purchase_bundles:sim.judge.purchase_ammo(rid,d.purchase_bundles,episode=o.episode)
                    for rid,o in observations.items():
                        telemetry.write(dumps(dict(episode=o.episode,robot_id=rid,sim_time=o.sim_time,
                            own_odom=o.odom_xyyaw,own_hp=o.own_hp,own_ammo=o.ammo,own_heat=o.own_heat,
                            phase=o.match_phase,mode=nav[rid].mode,intent=asdict(nav[rid].nav.intent) if nav[rid].nav.intent else None,
                            command=asdict(commands[rid]),navigation_desired_velocity=nav[rid].desired_velocity,
                            original_rule_calls=nav[rid].original_rule.calls))+'\n')
                    snap=sim.judge.snapshot()
                    replay.append(dict(time=sim.time,vp=snap['vp'],owner=snap['control_owner'],robots={r:dict(xy=observations[r].odom_xyyaw[:2],hp=observations[r].own_hp,ammo=observations[r].ammo,mode=nav[r].mode) for r in sim.robot_ids}))
                    state_frames.append(dict(t=sim.time,qpos=sim.data.qpos.tolist(),qvel=sim.data.qvel.tolist(),judge=snap))
                    if writer:
                        if source:
                            sim.source_aim_state=source.status
                            sim.source_camera_active=source.client is not None and source.latest_rgb is not None
                            if sim.source_camera_active:
                                observations['red_sentry']=replace(observations['red_sentry'],rgb=np.asarray(Image.fromarray(source.latest_rgb).resize((320,240))))
                        fr=screen.frame(sim,observations,nav,evidence,label='navigation only; firing disabled' if args.mode=='navigation' else 'all 6: pixel aim baseline')
                        writer.append_data(fr);frames+=1
                        camera_writer.append_data(camera_view.frame(sim,source))
                        if frames==1:Image.fromarray(fr).save(args.out/'preview.png')
                        if i in (20000,40000,80000):Image.fromarray(fr).save(args.out/f'frame_{sim.time:06.1f}s.png')
                    health.tick(sim,state_frames[-1],frames)
                    if i%20000==0:
                        print(f'sim={sim.time:.1f}s VP={sim.judge.vp} wall={time.perf_counter()-start:.1f}s',flush=True)
                        telemetry.flush()
                        if source:source.io.flush()
                        sim.trajectory_file.flush()
                if source and i%25==0:
                    source.capture_tick(sim.observe('red_sentry',False,False))
                decision=None
                if actual_ids and args.mode=='match' and i%20==0:
                    for rid in actual_ids:
                        o=sim.observe(rid,include_rgb=False if source else i%100==0,include_ranges=False)
                        ac=source.act(o,nav[rid].mode,nav[rid].desired_velocity) if source else (aim[rid].act(o) if o.match_phase=='running' and o.own_hp>0 and not o.emergency_stop else Command())
                        if source and source.error:
                            sim.set_phase('paused')
                            raise RuntimeError('Original source failed; stopped without fallback: '+source.error)
                        drive=commands.get(rid,Command())
                        commands[rid]=replace(ac,force_x=drive.force_x,force_y=drive.force_y,yaw_torque=drive.yaw_torque)
                        decision=bool(ac.fire)
                if source:
                    commands['red_sentry']=fire_transport.apply(sim,i,commands.get('red_sentry',Command()),source,nav['red_sentry'].desired_velocity,decision=decision)
                sim.step(commands);evidence.tick(sim);i+=1
            if source:
                source.act(sim.observe('red_sentry',False,False),'finished',(0.,0.))
                fire_transport.apply(sim,i,Command(),source,(0.,0.),decision=False)
            if writer:
                observations={r:sim.observe(r) for r in sim.robot_ids}
                if source:
                    if sim.judge.terminal:
                        # Clear the native process at the terminal boundary,
                        # before drawing the observer's frozen terminal card.
                        source.act(observations['red_sentry'],'finished',(0.,0.))
                    sim.source_aim_state=source.status
                    sim.source_camera_active=source.client is not None and source.latest_rgb is not None
                    if sim.source_camera_active:
                        observations['red_sentry']=replace(observations['red_sentry'],
                            rgb=np.asarray(Image.fromarray(source.latest_rgb).resize((320,240))))
                fr=screen.frame(sim,observations,nav,evidence,label='navigation only' if args.mode=='navigation' else 'all 6: pixel aim baseline')
                writer.append_data(fr);camera_writer.append_data(camera_view.frame(sim,source));frames+=1;Image.fromarray(fr).save(args.out/'final_frame.png')
                # Freeze the terminal card for legibility, separate from physics.
                if sim.judge.terminal:
                    for _ in range(29):
                        writer.append_data(fr);camera_writer.append_data(camera_view.frame(sim,source));frames+=1
            summary={**sim.judge.snapshot(),**evidence.snapshot(sim,nav),
                'complete_episode':bool(sim.judge.terminal),'physics_seconds':sim.time,'mode':args.mode,
                'recorded_frames':frames,'fps':10,'wall_seconds':time.perf_counter()-start,
                'video_terminal_hold_s':3 if sim.judge.terminal else 0,
                'user_aim_integrated':bool(actual_ids),'actual_aim_integrated':bool(actual_ids),'actual_aim_robot_ids':actual_ids,
                'aim_backend':source.spec['id']+'_stationary_only' if source else ('actual-sentry' if actual_ids else 'colour_pixel_baseline_NOT_user_autoaim'),
                'rmcs_source_segments':source.segment if source else None,
                'rmcs_source_control_ticks':source.source_calls if source else None,
                'rmcs_source_native_frames':source.delivered_frames if source else None,
                'rmcs_source_tracking_ticks':source.tracking_ticks if source else None,
                'rmcs_source_fire_permission_ticks':source.fire_ticks if source else None,
                'metrics':sim.judge.metrics()}
            summary['protocol_id']='rmcs-full-match-timing-v5'
            summary['physics_hz']=2000
            summary['source_capture_hz']=80
            summary['source_detector_hz']=36
            summary['source_control_hz']=100
            summary['fire_delay_ms']=40
            summary['source_captures']=source.captured_frames if source else 0
            summary['uid_audit']=sim.terminal_uid_audit()
            summary['scope_limits']=['SIMULATION ONLY; not real robots','Red sentry stationary-only real 40f7 RMCS; five pixel baselines','provisional chassis and armor; optical domain uncalibrated','verified subset rules, not full official compliance','source executor benchmark 40ms/120deg/preaim true; not deployed 0ms/60deg/false','native exposure pose retained; no current-muzzle source backport','terminal bullets censored, no settlement damage after match cutoff']
            summary['resilient_recording']=bool(args.resilient_recording)
            summary['armor_optical_profile']=args.armor_profile
            summary['scene_sha256']=hashlib.sha256(xml.encode()).hexdigest()
            files={'launches.json':sim.launches,'uid_resolutions.json':sim.resolutions,'fire_transport.json':fire_transport.events if fire_transport else [],'summary.json':summary,'referee_events.json':sim.judge.events,
                'projectile_contacts.json':sim.contact_events,'chassis_contacts.json':evidence.contacts,
                'navigation_events.json':{r:nav[r].events+nav[r].opening.events+nav[r].metrics.events for r in sim.robot_ids},
                'judge_replay.json':sim.judge.export_replay(),'spectator_replay.json':replay,
                'physics_replay.json':state_frames}
            for name,data in files.items():(args.out/name).write_text(dumps(data,indent=2),encoding='utf-8')
            print(dumps({k:summary[k] for k in ['complete_episode','terminal_reason','winner','vp','physics_seconds','wall_seconds','chassis_contact_episodes','robots']}),flush=True)
    finally:
        if fire_transport:
            fire_transport.delay.advance(sim.physics_step,safe=False,reasons=['runner_closed'])
        if writer:writer.close()
        if camera_writer:camera_writer.close()
        if camera_view:camera_view.close()
        if sim.trajectory_file:sim.trajectory_file.close()
        health.close()
        if screen:screen.close()
        if source:source.close()
        sim.close()
if __name__=='__main__':main()
