"""Native MuJoCo live viewer; Windows default is GLFW, no EGL override."""
import argparse,time,math
import mujoco
import mujoco.viewer
from .engine import Simulation
from .controllers import PixelBaseline

def main():
    parser=argparse.ArgumentParser(description='Phase A provisional live harness, not full match')
    parser.add_argument('--no-wall',action='store_true')
    parser.add_argument('--navigate',action='store_true')
    args=parser.parse_args()
    sim=Simulation(occluder=not args.no_wall);policy=PixelBaseline();policy.reset(sim.episode)
    nav=None
    def reset_nav():
        nonlocal nav
        if args.navigate:
            from .navigation import NavigationBaseline
            nav=NavigationBaseline();nav.reset(sim.episode)
            nav.set_intent({"behavior":"PATROL","target_point":{"x":5.,"y":1.},"reason":"offline obstacle test"})
    reset_nav()
    pending=[];camera_mode=0;step_count=0;command=None
    def key(code):pending.append(code)
    print('PHASE A BASELINE ONLY. C: free/follow/agent/spectator camera. P: pause. R: reset. Esc: close.')
    try:
        with mujoco.viewer.launch_passive(sim.model,sim.data,key_callback=key) as viewer:
            viewer.cam.azimuth=135;viewer.cam.elevation=-35;viewer.cam.distance=12
            viewer.cam.lookat[:]=[3,0,.5]
            while viewer.is_running():
                started=time.perf_counter()
                while pending:
                    code=pending.pop(0)
                    if code in (ord('P'),ord('p')):sim.paused=not sim.paused
                    if code in (ord('R'),ord('r')):
                        sim.reset();policy.reset(sim.episode);reset_nav();step_count=0;command=None
                    if code in (ord('C'),ord('c')):
                        camera_mode=(camera_mode+1)%4
                        if camera_mode==0:viewer.cam.type=mujoco.mjtCamera.mjCAMERA_FREE
                        elif camera_mode==1:
                            viewer.cam.type=mujoco.mjtCamera.mjCAMERA_TRACKING
                            viewer.cam.trackbodyid=sim.model.body('robot').id
                        else:
                            viewer.cam.type=mujoco.mjtCamera.mjCAMERA_FIXED
                            viewer.cam.fixedcamid=sim.model.camera('aim' if camera_mode==2 else 'spectator').id
                if not sim.paused:
                    if step_count%20==0:
                        observation=sim.observe();command=policy.act(observation)
                        if nav is not None:
                            drive=nav.act(observation)
                            command=__import__("dataclasses").replace(command,force_x=drive.force_x,force_y=drive.force_y,yaw_torque=drive.yaw_torque)
                    sim.step(command,target_motion=.45*math.sin(sim.time*1.1));step_count+=1
                with viewer.lock():
                    viewer.user_scn.ngeom=0
                    sim.draw_projectiles(viewer.user_scn)
                viewer.sync()
                time.sleep(max(0.,sim.model.opt.timestep-(time.perf_counter()-started)))
    finally:sim.close()
if __name__=='__main__':main()
