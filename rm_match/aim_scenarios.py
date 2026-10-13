"""Bounded, declared evaluation fixtures; true target motion is NEVER actor input."""
import copy,math,importlib
import xml.etree.ElementTree as ET
from pathlib import Path
from .contracts import Command

SCENARIOS={
 'stationary_near':dict(distance=2.5,motion='stationary'),
 'stationary_far':dict(distance=5.,motion='stationary'),
 'lateral':dict(distance=3.,motion='lateral'),
 'variable_spin':dict(distance=3.,motion='spin'),
 'occlusion':dict(distance=3.,motion='occlusion'),
}
ROSTER=[('red_sentry','red','sentry'),('blue_infantry','blue','infantry')]

def make_fixture(scenario,visual_module='rm_match.armor_visual_v21'):
    if scenario not in SCENARIOS:raise ValueError('Unknown fixed evaluation scenario')
    module=importlib.import_module(visual_module)
    helper=getattr(module,'add_armor_visual_v21',None) or getattr(module,'add_armor_visual_v2')
    source=ET.fromstring(Path(__file__).with_name('harness.xml').read_text())
    root=ET.Element('mujoco',model='Paired actual-RL evaluation; provisional plant')
    for tag in ('compiler','option','visual','default'):root.append(copy.deepcopy(source.find(tag)))
    root.find('visual/global').set('offwidth','1280');root.find('visual/global').set('offheight','720')
    asset=ET.SubElement(root,'asset');world=ET.SubElement(root,'worldbody');act=ET.SubElement(root,'actuator')
    ET.SubElement(world,'light',pos='0 -1 6',diffuse='.8 .8 .8')
    ET.SubElement(world,'geom',name='fixture_floor',type='box',pos='3 -1.8 -.05',size='7 5 .05',rgba='.24 .27 .30 1')
    ET.SubElement(world,'geom',name='fixture_backwall',type='box',pos='7 -1.8 1',size='.1 4 1',rgba='.32 .35 .39 1')
    ET.SubElement(world,'camera',name='arena_overview',pos='1 -6 3.5',xyaxes='1 0 0 0 .55 .83516465',fovy='48')
    if scenario=='occlusion':
        ET.SubElement(world,'geom',name='fixture_occluder',type='box',pos='1.5 -1.8 .4',size='.06 .25 .4',rgba='.45 .46 .48 1')
    spawns={'red_sentry':(0.,-1.8,0.),'blue_infantry':(SCENARIOS[scenario]['distance'],-1.8,math.pi)}
    template=source.find('worldbody/body[@name="robot"]')
    for rid,team,role in ROSTER:
        body=copy.deepcopy(template);x,y,_=spawns[rid];body.set('pos',f'{x} {y} .25')
        for i,element in enumerate(body.iter()):
            if 'name' in element.attrib:element.set('name',rid+'__'+element.get('name'))
            if element.tag=='geom':
                element.set('rgba','.14 .16 .18 1')
                if 'name' not in element.attrib:element.set('name',rid+'__part_'+str(i))
        for label,pos,yaw in [('front',(.31,0,.1),0.),('back',(-.31,0,.1),math.pi),
                              ('left',(0,.26,.1),math.pi/2),('right',(0,-.26,.1),-math.pi/2)]:
            helper(body,asset=asset,name=rid+'__visual_'+label,team=team,position=pos,yaw=yaw,
                collider_name=rid+'__armor_'+label,number='3',led_emission=.5)
        if rid=='blue_infantry':
            ET.SubElement(body,'camera',name='armor_detail',pos='.61 0 .1',xyaxes='0 1 0 0 0 1',fovy='50')
        world.append(body)
        for element in source.find('actuator'):
            if element.get('name')=='target_motion':continue
            a=copy.deepcopy(element);a.set('name',rid+'__'+a.get('name'));a.set('joint',rid+'__'+a.get('joint'));act.append(a)
    # Only own chassis is fixed for this aim test. Target motion still uses motors.
    equality=ET.SubElement(root,'equality')
    for name in ('base_x','base_y','base_yaw'):
        ET.SubElement(equality,'joint',joint1='red_sentry__'+name,polycoef='0 0 0 0 0')
    return ET.tostring(root,encoding='unicode'),spawns,getattr(module,'PROFILE',visual_module)

def target_command(sim,scenario,seed):
    """Fixture trajectory controller has only target proprioception; no actor output."""
    import numpy as np
    q=sim.data.qpos[sim.qindices['blue_infantry']];v=sim.data.qvel[sim.vindices['blue_infantry']]
    t=sim.time;sign=1. if seed%2==0 else -1.;motion=SCENARIOS[scenario]['motion']
    desired=0.
    if motion=='lateral':desired=sign*.6*math.sin(1.2*t)
    if motion=='occlusion':desired=sign*.85*math.sin(.9*t)
    force=float(np.clip(80*(desired-q[1])-25*v[1],-80,80))
    desired_rate=sign*(3+2*math.sin(1.5*t)) if motion=='spin' else 0.
    torque=float(np.clip(8*(desired_rate-v[2]),-20,20))
    return Command(force_y=force,yaw_torque=torque)


def evaluate_truth(sim):
    """Evaluator-only geometry. Never place this return value in actor Observation."""
    import numpy as np,mujoco
    muzzle=sim.model.site('red_sentry__muzzle').id;camera=sim.model.camera('red_sentry__aim').id
    position=sim.data.site_xpos[muzzle];direction=sim.data.site_xmat[muzzle].reshape(3,3)[:,0]
    cam=sim.data.cam_xpos[camera];samples=[]
    for label in ('front','back','left','right'):
        gid=sim.model.geom('blue_infantry__armor_'+label).id
        center=sim.data.geom_xpos[gid];normal=sim.data.geom_xmat[gid].reshape(3,3)[:,0]
        if (cam-center)@normal<=0:continue
        ray=center-cam;distance=np.linalg.norm(ray)
        hit=np.array([-1],dtype=np.int32)
        mujoco.mj_ray(sim.model,sim.data,cam,ray/distance,None,1,sim.body_ids['red_sentry'],hit)
        visible=int(hit[0])>=0 and sim.model.geom_bodyid[int(hit[0])]==sim.model.geom_bodyid[gid]
        target=center-position;target/=np.linalg.norm(target)
        angle=math.degrees(math.acos(float(np.clip(direction@target,-1,1))))
        samples.append(dict(armor=label,center_visible=visible,instantaneous_los_error_deg=angle,distance_m=float(distance)))
    visible=[s['instantaneous_los_error_deg'] for s in samples if s['center_visible']]
    return dict(armor_samples=samples,visible_armor_centers=len(visible),
        min_visible_instantaneous_los_error_deg=min(visible) if visible else None,
        target_alive=sim.judge.robots['blue_infantry'].alive)


def project_armor_pixels(sim,profile):
    """Truth-only configured-lens corner projection for debugging capture/FOV."""
    import numpy as np,cv2
    camera=sim.model.camera('red_sentry__aim').id
    origin=sim.data.cam_xpos[camera];rotation=sim.data.cam_xmat[camera].reshape(3,3)
    result=[]
    for label in ('front','back','left','right'):
        gid=sim.model.geom('blue_infantry__armor_'+label).id
        center=sim.data.geom_xpos[gid];r=sim.data.geom_xmat[gid].reshape(3,3);size=sim.model.geom_size[gid]
        corners=np.array([center+r@np.array([size[0],y*size[1],z*size[2]]) for y,z in [(-1,-1),(1,-1),(1,1),(-1,1)]])
        gl=(corners-origin)@rotation;opencv=gl*np.array([1,-1,-1])
        if np.any(opencv[:,2]<=0):continue
        pixels,_=cv2.projectPoints(opencv,np.zeros(3),np.zeros(3),profile.K,np.array(profile.distortion))
        pixels=pixels.reshape(-1,2)
        result.append(dict(armor=label,pixels=pixels.tolist(),front_facing=bool((origin-center)@r[:,0]>0),
                           all_corners_in_frame=bool(np.all((pixels[:,0]>=0)&(pixels[:,0]<profile.width)&(pixels[:,1]>=0)&(pixels[:,1]<profile.height)))))
    return result
