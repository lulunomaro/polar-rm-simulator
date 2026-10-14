"""High-resolution observer output. Raw robot camera images remain untouched."""
import math
from pathlib import Path
import numpy as np
import mujoco
from PIL import Image,ImageDraw,ImageFont

COLORS={'red':(249,82,94),'blue':(72,154,255)}

def font(size):
    choices=['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        'C:/Windows/Fonts/segoeui.ttf','/System/Library/Fonts/Supplemental/Arial.ttf']
    for p in choices:
        if Path(p).exists():return ImageFont.truetype(p,size)
    return ImageFont.load_default(size=size)


class Broadcast:
    width,height=1280,880
    def __init__(self,sim):
        self.renderer=mujoco.Renderer(sim.model,640,960)
        self.fonts={s:font(s) for s in (12,14,16,18,22,28,36)}
        self.camera='broadcast_overview'

    def project(self,sim,p):
        cid=sim.model.camera(self.camera).id
        cam=sim.data.cam_xmat[cid].reshape(3,3).T@(np.asarray(p)-sim.data.cam_xpos[cid])
        if cam[2]>=-.01:return None
        f=640/(2*math.tan(math.radians(float(sim.model.cam_fovy[cid]))/2))
        return (480+f*cam[0]/-cam[2],100+320-f*cam[1]/-cam[2])

    def scene_line(self,a,b,color,width=.025):
        scene=self.renderer.scene
        if scene.ngeom>=scene.maxgeom:return
        g=scene.geoms[scene.ngeom]
        mujoco.mjv_initGeom(g,mujoco.mjtGeom.mjGEOM_CAPSULE,np.zeros(3),np.zeros(3),np.eye(3).ravel(),np.asarray((*color, .8),dtype=np.float32))
        mujoco.mjv_connector(g,mujoco.mjtGeom.mjGEOM_CAPSULE,width,np.asarray((*a,.035)),np.asarray((*b,.035)))
        scene.ngeom+=1

    def frame(self,sim,observations,nav,evidence,*,label='3v3 full match'):
        self.renderer.update_scene(sim.data,camera=self.camera)
        sim.draw_projectiles(self.renderer.scene)
        if sim.spectator_effects:sim.spectator_effects.draw(self.renderer.scene)
        for rid in ('red_sentry','blue_sentry'):
            if rid not in nav:continue
            path=nav[rid].nav.path
            color=tuple(c/255 for c in COLORS[sim.teams[rid]])
            for a,b in zip(path,path[1:]):self.scene_line(a,b,color)
        canvas=Image.new('RGB',(self.width,self.height),(12,17,25));draw=ImageDraw.Draw(canvas)
        canvas.paste(Image.fromarray(self.renderer.render()),(0,100))
        def text(x,y,t,size=16,color=(221,230,240)):
            draw.text((x,y),str(t),font=self.fonts[size],fill=color)
        text(24,14,'ROBOMASTER  /  CONTROL FIRST',22)
        text(24,47,'2026 RMUL subset | Provisional robots',14,(156,174,193))
        text(550,16,f"RED  {sim.judge.vp['red']:03d}",28,COLORS['red'])
        text(790,16,f"{max(0,300-sim.time):05.1f}",28)
        text(1000,16,f"{sim.judge.vp['blue']:03d}  BLUE",28,COLORS['blue'])
        owner=sim.judge.control_owner or 'none'
        text(550,53,f'CONTROL: {owner.upper()}   |   {sim.judge.terminal_reason or "RUNNING"}',16)
        text(18,78,'OBSERVER: paths / trails / impacts. These overlays never enter robot cameras.',12,(149,166,184))
        for rid in sim.robot_ids:
            robot=sim.judge.robots[rid];pos=sim.data.xpos[sim.body_ids[rid]].copy();pos[2]=.8
            pt=self.project(sim,pos)
            if pt:
                x,y=pt
                if 5<x<920 and 110<y<720:
                    color=COLORS[sim.teams[rid]]
                    draw.rounded_rectangle((x-22,y-17,x+28,y+3),radius=3,fill=(10,16,23))
                    text(x-18,y-16,{'hero':'H1','infantry':'I3','sentry':'S7'}[sim.roles[rid]],12,color)
        # These are the exact 320x240 raw sensor frames passed to the policies.
        for k,rid in enumerate(('red_sentry','blue_sentry')):
            y=100+k*290
            rgb=observations[rid].rgb
            if rgb.size:canvas.paste(Image.fromarray(rgb),(960,y+24))
            caption=("RMCS INPUT (1440 -> 320)" if rid=='red_sentry' and getattr(sim,'source_camera_active',False)
                     else rid.upper()+' / RAW CAMERA')
            text(973,y+3,caption,14,COLORS[sim.teams[rid]])
            p=nav[rid]
            text(972,y+266,p.mode or 'waiting',14)
        text(972,674,getattr(sim,'actual_aim_description','6 robots: colour-pixel AIM baseline'),12,(159,181,204))
        text(972,692,'Grid A* baseline / original rules',12,(159,181,204))
        text(972,710,'No live LLM. ROS2/Nav2 unverified.',12,(255,198,105))
        draw.rectangle((0,740,1280,880),fill=(14,22,33))
        for i,rid in enumerate(sim.robot_ids):
            x=12+i*212;robot=sim.judge.robots[rid];c=COLORS[sim.teams[rid]]
            text(x,752,rid.replace('_',' ').upper(),14,c)
            draw.rounded_rectangle((x,778,x+195,789),radius=3,fill=(36,46,60))
            n=max(0,min(195,195*robot.hp/robot.max_hp))
            if n:draw.rounded_rectangle((x,778,x+n,789),radius=3,fill=c)
            text(x,796,f'HP {robot.hp:.0f}/{robot.max_hp:.0f}   AMMO {robot.ammo}',12)
            state=getattr(sim,'source_aim_state',None) if rid=='red_sentry' else None
            labels={'navigation_moving_or_resupply':'MOVING / FIRE OFF','chassis_motion':'MOVING / FIRE OFF','navigation_motion_requested':'MOVING / FIRE OFF',
                    'settling':'WAIT STABLE / FIRE OFF','original_RMCS_tracking_stationary':'ORIGINAL RMCS / TRACK',
                    'original_RMCS_search_stationary':'ORIGINAL RMCS / SEARCH',
                    'repaired_RMCS_tracking_stationary':'REPAIRED RMCS / TRACK','repaired_RMCS_search_stationary':'REPAIRED RMCS / SEARCH','referee_or_emergency_gate':'REFEREE / FIRE OFF'}
            text(x,816,labels.get(state,state) if state else f'{nav[rid].mode} | recover {nav[rid].metrics.recovery_count}',12)
            if sim.roles[rid]=='sentry':
                arrival=nav[rid].opening.arrived_at
                text(x,838,'CENTER '+(f'{arrival:.2f}s' if arrival is not None else 'en route'),12,(171,199,169))
            else:text(x,838,f'HEAT {robot.heat:.0f}   DEATHS {robot.deaths}',12,(159,174,193))
        if sim.judge.terminal:
            draw.rounded_rectangle((235,342,745,458),radius=14,fill=(11,18,27),outline=(126,146,169),width=2)
            text(350,360,(sim.judge.winner or 'draw').upper()+' WINS',36,COLORS.get(sim.judge.winner,(255,255,255)))
            text(302,413,f'{sim.judge.terminal_reason}  |  {sim.time:.2f} simulation seconds',16)
        return np.asarray(canvas)

    def close(self):self.renderer.close()
