import argparse,json,math,os,sys
from pathlib import Path
# Headless Linux uses software-capable EGL. Windows keeps native GLFW default.
if sys.platform.startswith('linux') and not os.environ.get('DISPLAY'):
    os.environ.setdefault('MUJOCO_GL','egl');os.environ.setdefault('EGL_PLATFORM','surfaceless')
    os.environ.setdefault('MESA_SHADER_CACHE_DISABLE','true')
from .engine import Simulation
from .controllers import PixelBaseline
import imageio.v2 as imageio
from PIL import Image,ImageDraw

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--seconds',type=float,default=12.)
    parser.add_argument('--out',type=Path,default=Path('artifacts'))
    parser.add_argument('--no-wall',action='store_true')
    parser.add_argument('--navigate',action='store_true',help='Use the explicit offline navigation baseline')
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    sim=Simulation(occluder=not args.no_wall)
    policy=PixelBaseline();policy.reset(sim.episode)
    nav=None
    if args.navigate:
        from .navigation import NavigationBaseline
        nav=NavigationBaseline();nav.reset(sim.episode)
        nav.set_intent({"behavior":"PATROL","target_point":{"x":1.5,"y":-1.8},"reason":"synthetic integration test"})
    writer=imageio.get_writer(args.out/'phase_a_harness.mp4',fps=25,codec='libx264',macro_block_size=1)
    command=None;telemetry=[]
    try:
        steps=round(args.seconds/sim.model.opt.timestep)
        for i in range(steps):
            if i%20==0:
                obs=sim.observe();command=policy.act(obs)
                if nav is not None:
                    drive=nav.act(obs)
                    command=__import__("dataclasses").replace(command,force_x=drive.force_x,force_y=drive.force_y,yaw_torque=drive.yaw_torque)
                spectator=sim.image('spectator');frame=Image.new('RGB',(640,290))
                frame.paste(Image.fromarray(spectator),(0,50));frame.paste(Image.fromarray(obs.rgb),(320,50))
                draw=ImageDraw.Draw(frame)
                draw.text((8,5),'PHASE A TEST HARNESS - NOT OFFICIAL MATCH / NOT USER AIM OR RL',fill='white')
                draw.text((8,23),f'Sim {sim.time:.2f}s | target HP {sim.judge.hp} | ammo {sim.judge.ammo} | spectator / RGB aim',fill='white')
                telemetry.append(dict(episode=sim.episode,sim_time=sim.time,own_qpos=list(obs.own_qpos),command=__import__("dataclasses").asdict(command),ammo=sim.judge.ammo,target_hp=sim.judge.hp,active_projectiles=len(sim.projectiles)))
                writer.append_data(__import__('numpy').asarray(frame))
                if i==0: frame.save(args.out/'preview.png')
            sim.step(command,target_motion=.45*math.sin(sim.time*1.1))
        (args.out/'telemetry.json').write_text(json.dumps(telemetry,indent=2))
        (args.out/'events.json').write_text(json.dumps(sim.judge.events,indent=2))
        summary=dict(label='Phase A provisional integration harness',sim_seconds=sim.time,
          hp=sim.judge.hp,shots=sim.shot_counter,hits=sum(e.get('valid_armor',False) for e in sim.judge.events),
          navigation_baseline=args.navigate,real_mujoco=True,official_rules=False,user_aim_integrated=False,user_rl_integrated=False)
        (args.out/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))
    finally:writer.close();sim.close()
if __name__=='__main__':main()
