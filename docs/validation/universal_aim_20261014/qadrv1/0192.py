"""Native live 3v3 viewer using the SAME MatchSimulation as recordings."""
import argparse,time
from pathlib import Path
from dataclasses import replace
import mujoco,mujoco.viewer
from .match_engine import MatchSimulation
from .match_runner import build_policies,control_tick,configure_actual_aim
from .contracts import Command

def main():
    p=argparse.ArgumentParser(description='Live RMUL fallback verified-subset world; provisional chassis')
    p.add_argument('--aim',choices=['baseline','actual-sentry'],default='baseline')
    p.add_argument('--armor-profile',choices=['baseline','role_v23'],default='role_v23')
    p.add_argument('--aim-adapter-module',default='upper_aim.adapter')
    p.add_argument('--aim-source',type=Path);p.add_argument('--detector',type=Path);p.add_argument('--policy',type=Path)
    p.add_argument('--detector-profile',choices=['shenzhen_0526','shenzhen_0708'],default='shenzhen_0526')
    args=p.parse_args()
    if args.aim=='actual-sentry' and not all([args.aim_source,args.detector,args.policy]):p.error('Explicit actual source/model paths required')
    from .match_model import make_match_xml
    s=MatchSimulation(model_xml=make_match_xml(args.armor_profile));nav,aim=build_policies(s);actual_ids=configure_actual_aim(s,aim,args)
    pending=[];mode=3;selected=2;i=0;commands={};announced=False;force_recontrol=False
    print('C: free/follow/agent/overview. N: next robot. P: pause. R: reset. Esc: close.')
    print('2026 UL verified-subset fallback; incomplete2027. Provisional chassis. Aim mode:',args.aim)
    try:
        with mujoco.viewer.launch_passive(s.model,s.data,key_callback=pending.append) as viewer:
            def camera():
                rid=s.robot_ids[selected]
                if mode==0:
                    viewer.cam.type=mujoco.mjtCamera.mjCAMERA_FREE
                    viewer.cam.lookat[:]=[0,0,0];viewer.cam.distance=14;viewer.cam.elevation=-55
                elif mode==1:
                    viewer.cam.type=mujoco.mjtCamera.mjCAMERA_TRACKING;viewer.cam.trackbodyid=s.body_ids[rid];viewer.cam.distance=3
                else:
                    viewer.cam.type=mujoco.mjtCamera.mjCAMERA_FIXED
                    viewer.cam.fixedcamid=s.model.camera(rid+'__aim' if mode==2 else 'broadcast_overview').id
            camera()
            while viewer.is_running():
                start=time.perf_counter()
                while pending:
                    key=pending.pop(0)
                    if key in (ord('C'),ord('c')):mode=(mode+1)%4;camera()
                    if key in (ord('N'),ord('n')):selected=(selected+1)%len(s.robot_ids);camera();print('Selected',s.robot_ids[selected])
                    if key in (ord('P'),ord('p')) and not s.judge.terminal:
                        s.set_phase('running' if s.paused else 'paused')
                        commands={};force_recontrol=True
                    if key in (ord('R'),ord('r')):
                        s.reset();nav,aim=build_policies(s);actual_ids=configure_actual_aim(s,aim,args)
                        i=0;commands={};announced=False
                if not s.paused and not s.judge.terminal:
                    if i%50==0 or force_recontrol:
                        commands,_,_=control_tick(s,nav,aim,True,actual_ids);force_recontrol=False
                    if i%5==0:
                        for rid in actual_ids:
                            ac=aim[rid].act(s.observe(rid,include_rgb=i%25==0,include_ranges=False));drive=commands.get(rid,Command())
                            commands[rid]=replace(ac,force_x=drive.force_x,force_y=drive.force_y,yaw_torque=drive.yaw_torque)
                    s.step(commands);i+=1
                if s.judge.terminal and not announced:
                    print('TERMINAL',s.judge.terminal_reason,'winner',s.judge.winner,'VP',s.judge.vp);announced=True
                with viewer.lock():viewer.user_scn.ngeom=0;s.draw_projectiles(viewer.user_scn)
                viewer.sync()
                time.sleep(max(0.,s.model.opt.timestep-(time.perf_counter()-start)))
    finally:s.close()
if __name__=='__main__':main()
