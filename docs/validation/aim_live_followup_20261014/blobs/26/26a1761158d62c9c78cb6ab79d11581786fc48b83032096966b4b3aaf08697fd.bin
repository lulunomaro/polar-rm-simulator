"""Actual RGB/Isaac scenario evaluation; evaluator truth never enters the actor."""
import argparse,os,sys,json,math,time,hashlib,importlib
from pathlib import Path
from dataclasses import asdict,replace
import numpy as np
if sys.platform.startswith('linux') and not os.environ.get('DISPLAY'):
    os.environ.setdefault('MUJOCO_GL','egl');os.environ.setdefault('EGL_PLATFORM','surfaceless')
    os.environ.setdefault('MESA_SHADER_CACHE_DISABLE','true')
from .serialization import dumps
from .aim_scenarios import SCENARIOS,ROSTER,make_fixture,target_command,evaluate_truth
from .match_engine import MatchSimulation
from .contracts import Command
from .sensor_schedule import SensorSchedule
from .camera_profile import SourceCameraProfile,SourceLensWarp


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--detector',type=Path,required=True);p.add_argument('--policy',type=Path,required=True)
    p.add_argument('--adapter-module',default='upper_aim.adapter')
    p.add_argument('--visual-module',default='rm_match.armor_visual_v21')
    p.add_argument('--profile',choices=['shenzhen_0526','shenzhen_0708'],default='shenzhen_0526')
    p.add_argument('--scenario',choices=list(SCENARIOS),required=True);p.add_argument('--seed',type=int,default=0)
    p.add_argument('--seconds',type=float,default=6.);p.add_argument('--variant',required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--no-video',action='store_true')
    p.add_argument('--trails',action='store_true')
    p.add_argument('--detector-hz',type=int,choices=[36,80],default=36)
    p.add_argument('--camera-overscan',type=int,choices=[0,64],default=0)
    p.add_argument('--hold-gimbal',action='store_true',help='Detector diagnostic: evaluate actual policy but apply zero fixed-gimbal/no-fire command')
    args=p.parse_args()
    if (args.out.parent/"PAUSE_EVALUATION").exists():
        p.error("Evaluation batch paused for diagnostic review")
    if not math.isfinite(args.seconds) or args.seconds<=0:p.error('positive finite duration required')
    # Supported optout BEFORE any inference session is constructed.
    if os.environ.get("ORT_DISABLE_TELEMETRY") != "1":
        p.error("Launch with ORT_DISABLE_TELEMETRY=1 before Python initialization")
    import onnxruntime as ort
    ort.disable_telemetry_events()
    from PIL import Image,ImageDraw,ImageFont
    import mujoco
    profile=SourceCameraProfile(overscan_pixels=args.camera_overscan);warp=SourceLensWarp(profile)
    xml,spawns,visual=make_fixture(args.scenario,args.visual_module)
    import xml.etree.ElementTree as ET
    tree=ET.fromstring(xml);tree.find('option').set('timestep','.0005')
    tree.find('visual/global').set('offwidth',str(profile.render_width));tree.find('visual/global').set('offheight',str(profile.render_height))
    tree.find('.//camera[@name="red_sentry__aim"]').set('fovy',str(profile.ideal_fovy_degrees))
    xml=ET.tostring(tree,encoding='unicode')
    sim=MatchSimulation(model_xml=xml,roster=ROSTER,spawns=spawns)
    schedule=SensorSchedule(detector_hz=args.detector_hz)
    sensor=mujoco.Renderer(sim.model,profile.render_height,profile.render_width)
    args.out.mkdir(parents=True,exist_ok=True);(args.out/'scene.xml').write_text(xml)
    module=importlib.import_module(args.adapter_module)
    import platform
    implementation_hashes={name:hashlib.sha256(Path(importlib.import_module(name).__file__).read_bytes()).hexdigest()
        for name in [args.adapter_module,'rm_match.aim_evaluation','rm_match.aim_scenarios','rm_match.match_engine','rm_match.ballistics',
                     'rm_match.competition_judge','rm_match.camera_profile','rm_match.sensor_schedule','rm_match.spectator_effects',
                     'rm_match.armor_visual_v2','rm_match.armor_visual_v21','rm_match.armor_visual_v22']}
    adapter=module.make_moving_isaac_adapter(source_directory=args.source,detector_path=args.detector,policy_path=args.policy,
        camera_intrinsics=profile.adapter_intrinsics(),detector_profile=args.profile,
        bullet_speed_mps=22.5,camera_offset=(.24,0,.06),muzzle_offset=(.38,0,0),yaw_origin_height=.65,target_colour='blue')
    effect=None
    if args.trails:
        from .spectator_effects import SpectatorEffects
        effect=SpectatorEffects()
        sim.spectator_effects=effect
    observer=mujoco.Renderer(sim.model,480,640)
    writer=None
    if not args.no_video:
        import imageio.v2 as imageio
        writer=imageio.get_writer(args.out/'evaluation.mp4',fps=30,codec='libx264',macro_block_size=1)
    font=ImageFont.load_default(size=15)
    camera=np.zeros((profile.height,profile.width,3),dtype=np.uint8);ticks=0;captures=0;frames=0;next_video=0.;commands={}
    pending_frame=None;pending_pose=None;pending_odom=None;pending_time=None;last_delivered_time=None;capture_times=[];delivery_ages=[]
    raw_detection_frames=0;saved_capture_labels=set();previous_tracking=False
    true_errors=[];occluded=0;fire_ticks=0;detection_frames=0;statuses={};start=time.perf_counter()
    try:
        with (args.out/'actor_ticks.jsonl').open('w') as actor_log,(args.out/'evaluation_truth.jsonl').open('w') as truth_log:
            while sim.time<args.seconds-1e-9:
                step=round(sim.time/sim.model.opt.timestep)
                if schedule.capture(step):
                    captured=sim.observe('red_sentry',include_rgb=False,include_ranges=False)
                    sensor.update_scene(sim.data,camera='red_sentry__aim');sim.draw_projectiles(sensor.scene)
                    camera=warp.apply(sensor.render());pending_frame=camera
                    pending_pose=captured.own_qpos;pending_odom=captured.odom_xyyaw;pending_time=sim.time
                    captures+=1;capture_times.append(sim.time)
                if schedule.control(step):
                    capture=schedule.process(step) and pending_time != last_delivered_time
                    o=sim.observe('red_sentry',include_rgb=False,include_ranges=False)
                    if capture:
                        o=replace(o,rgb=pending_frame,camera_sim_time=pending_time,
                            camera_own_qpos=pending_pose,camera_odom_xyyaw=pending_odom)
                        delivery_ages.append(sim.time-pending_time);last_delivered_time=pending_time
                    ac=adapter.act(o);commands['red_sentry']=Command() if args.hold_gimbal else ac;ticks+=1;fire_ticks+=ac.fire
                    telemetry=dict(adapter.telemetry);statuses[adapter.status]=statuses.get(adapter.status,0)+1
                    detection_frames+=bool(capture and telemetry.get('detections',0)>0)
                    raw_detection_frames+=bool(capture and telemetry.get('raw_detections',0)>0)
                    if capture:
                        labels=['initial'] if not saved_capture_labels else []
                        if telemetry.get('detections',0)>0:labels.append('first_team_accepted')
                        if telemetry.get('raw_detections',0)>0 and not telemetry.get('detections',0):labels.append('first_team_rejected')
                        if previous_tracking and not telemetry.get('tracking',False):labels.append('first_tracking_loss')
                        for label in labels:
                            if label not in saved_capture_labels:
                                Image.fromarray(pending_frame).save(args.out/f'raw_{label}.png');saved_capture_labels.add(label)
                        previous_tracking=telemetry.get('tracking',False)
                    actor_log.write(dumps(dict(sim_time=sim.time,source_variant=args.variant,camera_frame=capture,
                        status=adapter.status,telemetry=telemetry,command=asdict(ac),applied_command=asdict(commands['red_sentry']),own_qpos=o.own_qpos))+'\n')
                    truth=evaluate_truth(sim)
                    from .aim_scenarios import project_armor_pixels
                    truth['projected_armor_pixels']=project_armor_pixels(sim,profile)
                    truth_log.write(dumps(dict(sim_time=sim.time,**truth))+'\n')
                    error=truth['min_visible_instantaneous_los_error_deg']
                    if error is not None:true_errors.append(error)
                    else:occluded+=1
                commands['blue_infantry']=target_command(sim,args.scenario,args.seed)
                if effect:effect.update(sim.time,sim.projectiles,sim.contact_events)
                if writer and sim.time>=next_video-1e-9:
                    observer.update_scene(sim.data,camera='arena_overview');sim.draw_projectiles(observer.scene)
                    if effect:effect.draw(observer.scene)
                    overview=observer.render().copy()
                    observer.update_scene(sim.data,camera='armor_detail');detail=observer.render().copy()
                    canvas=Image.new('RGB',(1280,800),'#111722');canvas.paste(Image.fromarray(overview),(0,100))
                    canvas.paste(Image.fromarray(detail),(640,100));canvas.paste(Image.fromarray(camera).resize((320,240)),(480,560))
                    draw=ImageDraw.Draw(canvas)
                    hits=sum(e.get('damage_applied',False) for e in sim.contact_events)
                    raw=sum('__armor_' in e['geom'] for e in sim.contact_events)
                    draw.text((12,8),f'ACTUAL {args.profile} + Isaac v13 | {args.variant} | {args.scenario} seed{args.seed}',font=font,fill='white')
                    draw.text((12,30),f'Visual {visual}; approximate materials/plant; not hardware accuracy. Spectator30fps / capture80Hz / detector{args.detector_hz}Hz / policy100Hz',font=font,fill='#ffcc77')
                    draw.text((12,52),f't={sim.time:.2f}s shots={sim.projectile_counter} armor contacts={raw} valid damage hits={hits} target HP={sim.judge.robots["blue_infantry"].hp:.0f}',font=font,fill='white')
                    draw.text((12,74),'LEFT: physics spectator. RIGHT: armor detail. BELOW: actual unannotated actor camera input.',font=font,fill='white')
                    if effect:draw.multiline_text((12,590),'Trails and impact marks:\nspectator-only auxiliary display\nof recorded physics events.',font=font,fill='#ffbb55')
                    writer.append_data(np.asarray(canvas));frames+=1;next_video+=1/30
                    if frames in (1,91):canvas.save(args.out/f'preview_{frames:04d}.png')
                sim.step(commands)
                if effect:effect.update(sim.time,sim.projectiles,sim.contact_events)
            events=sim.judge.events
            shots=[e for e in events if e['type']=='fire' and e['robot_id']=='red_sentry']
            contacts=[e for e in sim.contact_events if e['owner']=='red_sentry']
            armor=[e for e in contacts if '__armor_' in e['geom']]
            valid=[e for e in contacts if e['damage_applied']]
            visible_array=np.asarray(true_errors)
            summary=dict(case_id=f'{args.scenario}_seed{args.seed}_{args.profile}_{args.variant}',scenario=args.scenario,seed=args.seed,
                implementation_hashes_at_start=implementation_hashes,runtime=dict(python=platform.python_version(),platform=platform.platform(),
                    mujoco=mujoco.__version__,numpy=np.__version__,onnxruntime=ort.__version__),
                source_variant=args.variant,hold_gimbal_diagnostic=args.hold_gimbal,visual_profile=visual,camera_profile=profile.manifest(),
                warp_black_border_fraction=warp.outside_fraction,seconds=sim.time,wall_seconds=time.perf_counter()-start,
                total_fired=len(shots),geometric_armor_contacts=len(armor),judge_valid_damage_hits=len(valid),
                valid_hit_fraction_per_fired=len(valid)/len(shots) if shots else None,
                target_damage=sim.judge.attack_damage['red'],target_deaths=sim.judge.robots['blue_infantry'].deaths,
                target_final_hp=sim.judge.robots['blue_infantry'].hp,
                requested_fire_ticks=fire_ticks,raw_detector_positive_frames=raw_detection_frames,team_accepted_detector_frames=detection_frames,detector_positive_frames=detection_frames,camera_frames=captures,control_ticks=ticks,
                timing=dict(physics_hz=2000,capture_hz=80,detector_service_hz=args.detector_hz,policy_hz=100,
                    capture_intervals_s=sorted(set(round(b-a,10) for a,b in zip(capture_times,capture_times[1:]))),
                    maximum_capture_delivery_age_s=max(delivery_ages,default=0),
                    detector_profile_basis='36 Hz historical source comment, ideal fixed service schedule; not current hardware benchmark' if args.detector_hz==36 else 'ideal 80 Hz processed comparison',
                    exposure_model='instantaneous capture; exposure blur and sensor noise uncalibrated',queued_frame_policy='newest frame at processing opportunity; older frames discarded'),
                actual_detector_calls=adapter.pipeline.detector.calls,actual_policy_calls=adapter.pipeline.policy.calls,statuses=statuses,
                video_frames=frames,video_fps=30,
                evaluator_only_visible_los_error_deg=dict(count=len(true_errors),median=float(np.median(visible_array)) if len(visible_array) else None,
                    p90=float(np.quantile(visible_array,.9)) if len(visible_array) else None),
                no_visible_armor_center_ticks=occluded,
                hashes={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in {'scene':args.out/'scene.xml','pipeline':args.source/'autoaim_pipeline.py',
                    'tuning':args.source/'autoaim_tuning.py','detector':args.detector,'actor':args.policy,'visual_module':Path(importlib.import_module(args.visual_module).__file__)}.items()},
                limitations=['Synthetic fixture, uncalibrated optical/motor properties, box armor collider despite visual chamfer.',
                    'Truth LOS error is instantaneous angle to visible armor centre, not lead/gravity compensated accuracy.',
                    'Fixed deterministic scenario seed controls motion direction, not a statistical generalization sample.',
                    'Dead/invulnerable contacts remain in raw-contact count but never count as valid damage.',
                    'Source thresholds are unchanged; candidate is only the declared pitch-gate patch.'])
            (args.out/'capture_timestamps.json').write_text(dumps(capture_times))
            (args.out/'summary.json').write_text(dumps(summary,indent=2));(args.out/'contacts.json').write_text(dumps(contacts,indent=2))
            (args.out/'referee_events.json').write_text(dumps(events,indent=2));print(dumps(summary,indent=2))
    finally:
        if writer:writer.close()
        sensor.close();observer.close();sim.close()
if __name__=='__main__':main()
