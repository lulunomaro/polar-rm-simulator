"""Run/record a real shared-world 3v3 episode under verified-subset UL rules."""
import argparse,os,sys,time,json
from pathlib import Path
from dataclasses import asdict,replace
if sys.platform.startswith('linux') and not os.environ.get('DISPLAY'):
    os.environ.setdefault('MUJOCO_GL','egl');os.environ.setdefault('EGL_PLATFORM','surfaceless')
    os.environ.setdefault('MESA_SHADER_CACHE_DISABLE','true')
import numpy as np
from PIL import Image,ImageDraw
from .match_engine import MatchSimulation
from .match_pixel_aim import MatchPixelAim
from .contracts import Command
from .serialization import dumps
from .match_controllers import MatchNavigationPolicy

def build_policies(sim):
    nav={r:MatchNavigationPolicy() for r in sim.robot_ids}
    aim={r:MatchPixelAim() for r in sim.robot_ids}
    return nav,aim

def control_tick(sim,nav,aim,include_rgb=True,actual_ids=()):
    commands={};observations={};statuses={}
    for rid in sim.robot_ids:
        obs=sim.observe(rid,include_rgb=include_rgb);observations[rid]=obs
        decision=nav[rid].decide(obs)
        if decision.purchase_bundles:
            sim.judge.purchase_ammo(rid,bundles=decision.purchase_bundles)
        allowed=obs.match_phase=='running' and not obs.emergency_stop and obs.own_hp>0
        ac=Command() if rid in actual_ids or not allowed else aim[rid].act(obs)
        commands[rid]=replace(ac,force_x=decision.command.force_x,force_y=decision.command.force_y,yaw_torque=decision.command.yaw_torque)
        statuses[rid]=dict(aim=aim[rid].status,estimated_range=getattr(aim[rid],"range_estimate",None))
    return commands,observations,statuses

def frame(sim,observations,statuses):
    canvas=Image.new('RGB',(960,580),(18,20,25));draw=ImageDraw.Draw(canvas)
    overview=Image.fromarray(sim.image()).resize((640,480))
    canvas.paste(overview,(0,80))
    for k,rid in enumerate(['red_sentry','blue_sentry']):
        image=Image.fromarray(observations[rid].rgb)
        canvas.paste(image,(640,80+k*240))
    snap=sim.judge.snapshot()
    draw.text((12,8),'RMUL 2026 VERIFIED-SUBSET 3v3 | 2027 TRANSITION INCOMPLETE | PROVISIONAL ROBOTS',fill='white')
    draw.text((12,26),getattr(sim,'aim_label','RGB colour baseline, NOT USER AIM / RL. Shared MuJoCo physics, collision-driven shots.'),fill=(255,220,120))
    draw.text((12,45),f"SIM {sim.time:6.1f}/300s | VP RED {snap['vp']['red']} BLUE {snap['vp']['blue']} | owner {snap['control_owner']} | {sim.judge.terminal_reason or 'RUNNING'}",fill='white')
    for i,rid in enumerate(sim.robot_ids):
        r=sim.judge.robots[rid]
        draw.text((12+(i//3)*320,82+(i%3)*16),f'{rid}: HP {r.hp:.0f} ammo {r.ammo} heat {r.heat:.0f}',fill='white')
    draw.text((647,83),'RED SENTRY CAMERA INPUT',fill='white')
    draw.text((647,323),'BLUE SENTRY CAMERA INPUT',fill='white')
    return np.asarray(canvas)

def configure_actual_aim(sim,aim,args):
    actual_ids=[]
    if args.aim=='actual-sentry':
        import importlib
        make_moving_isaac_adapter=importlib.import_module(args.aim_adapter_module).make_moving_isaac_adapter
        import math
        f=240/(2*math.tan(math.radians(50)/2))
        aim['red_sentry']=make_moving_isaac_adapter(source_directory=args.aim_source,
            detector_path=args.detector,policy_path=args.policy,
            camera_intrinsics=dict(fx=f,fy=f,cx=159.5,cy=119.5,distortion=np.zeros(5)),
            detector_profile=args.detector_profile,bullet_speed_mps=22.5,
            camera_offset=(.24,0,.06),muzzle_offset=(.38,0,0),yaw_origin_height=.65,target_colour='blue')
        actual_ids=['red_sentry']
        sim.aim_label='RED SENTRY: actual source detector + Isaac v13 via mobile adapter. Other 5: colour baseline.'

    return actual_ids

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--max-seconds',type=float,default=300.)
    p.add_argument('--out',type=Path,default=Path('artifacts/match_3v3'))
    p.add_argument('--no-video',action='store_true')
    p.add_argument('--no-rgb',action='store_true',help='Navigation/referee diagnostic only; disables aim')
    p.add_argument('--aim',choices=['baseline','actual-sentry'],default='baseline')
    p.add_argument('--aim-adapter-module',default='upper_aim.adapter',help='Optional upper-computer adapter package; no fallback')
    p.add_argument('--aim-source',type=Path)
    p.add_argument('--detector',type=Path)
    p.add_argument('--policy',type=Path)
    p.add_argument('--detector-profile',choices=['shenzhen_0526','shenzhen_0708'],default='shenzhen_0526')
    args=p.parse_args()
    if args.aim=='actual-sentry' and (args.no_rgb or not all([args.aim_source,args.detector,args.policy])):
        p.error('actual-sentry requires RGB and explicit --aim-source, --detector, --policy local paths; no fallback')
    if args.no_rgb and not args.no_video:p.error('--no-rgb requires --no-video')
    args.out.mkdir(parents=True,exist_ok=True)
    sim=MatchSimulation(render=not args.no_rgb);nav,aim=build_policies(sim)
    actual_ids=configure_actual_aim(sim,aim,args)
    writer=None
    if not args.no_video:
        import imageio.v2 as imageio
        writer=imageio.get_writer(args.out/'match_3v3.mp4',fps=10,codec='libx264',macro_block_size=1)
    commands={};observations={};statuses={};frames=0;start=time.perf_counter();i=0
    limit=min(300.,args.max_seconds)
    try:
        with (args.out/'observations_commands.jsonl').open('w',encoding='utf-8') as telemetry:
            while sim.time<limit-1e-9 and not sim.judge.terminal:
                if i%50==0:
                    commands,observations,statuses=control_tick(sim,nav,aim,not args.no_rgb,actual_ids)
                    for rid,o in observations.items():
                        telemetry.write(dumps(dict(episode=o.episode,robot_id=rid,sim_time=o.sim_time,
                            own_odom=o.odom_xyyaw,own_hp=o.own_hp,own_ammo=o.ammo,own_heat=o.own_heat,
                            command=asdict(commands[rid]),status=statuses[rid]))+'\n')
                    if writer:
                        fr=frame(sim,observations,statuses);writer.append_data(fr);frames+=1
                        if frames==1:Image.fromarray(fr).save(args.out/'preview.png')
                    if i%5000==0:print(f'sim={sim.time:.1f}s vp={sim.judge.vp}',flush=True)
                if actual_ids and i%5==0:
                    for rid in actual_ids:
                        obs=sim.observe(rid,include_rgb=i%25==0,include_ranges=False)
                        ac=aim[rid].act(obs)
                        drive=commands.get(rid,Command())
                        commands[rid]=replace(ac,force_x=drive.force_x,force_y=drive.force_y,yaw_torque=drive.yaw_torque)
                        telemetry.write(dumps(dict(episode=obs.episode,robot_id=rid,sim_time=obs.sim_time,
                            kind='actual_aim_tick',camera_frame=bool(obs.rgb.size),status=aim[rid].status,
                            telemetry=aim[rid].telemetry,command=asdict(commands[rid])),default=lambda x:x.item() if hasattr(x,'item') else str(x))+'\n')
                sim.step(commands);i+=1
            # Explicit final state frame, showing terminal reason if reached.
            if writer:
                observations={r:sim.observe(r) for r in sim.robot_ids}
                writer.append_data(frame(sim,observations,statuses));frames+=1
            summary=sim.judge.snapshot()
            summary.update(complete_episode=bool(sim.judge.terminal),real_mujoco=True,user_aim_integrated=bool(actual_ids),actual_aim_robot_ids=actual_ids,
                actual_source_moving_adapter_not_realworld_validated=True,
                user_rl_integrated=False,physics_seconds=sim.time,recorded_frames=frames,wall_seconds=time.perf_counter()-start,
                baseline='independent navigation; real actor only on explicitly listed robot IDs; no target truth',
                aim_session_counts={r:dict(detector=getattr(aim[r].pipeline.detector,'calls',None),policy=getattr(aim[r].pipeline.policy,'calls',None)) for r in actual_ids},metrics=sim.judge.metrics())
            (args.out/'summary.json').write_text(dumps(summary,indent=2),encoding='utf-8')
            (args.out/'referee_events.json').write_text(dumps(sim.judge.events,indent=2),encoding='utf-8')
            (args.out/'collision_events.json').write_text(dumps(sim.contact_events,indent=2),encoding='utf-8')
            (args.out/'judge_replay.json').write_text(dumps(sim.judge.export_replay(),indent=2),encoding='utf-8')
            print(dumps({k:summary[k] for k in ['complete_episode','terminal_reason','winner','vp','physics_seconds','wall_seconds','metrics']}))
    finally:
        if writer:writer.close()
        sim.close()
if __name__=='__main__':main()
