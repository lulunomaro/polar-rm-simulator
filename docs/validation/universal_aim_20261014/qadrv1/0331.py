import os
os.environ.setdefault('MUJOCO_GL','egl' if os.name!='nt' else 'glfw')
os.environ.setdefault('EGL_PLATFORM','surfaceless')
import numpy as np
from rm_match.engine import Simulation
from rm_match.contracts import Command
from rm_match.ballistics import sphere_box_toi,Projectile
from rm_match.judge import TestJudge

def test_round_box_no_phantom_corner():
    z=np.zeros(3);r=np.eye(3);s=np.ones(3)
    assert sphere_box_toi(np.array([-2.,1.09,1.09]),np.array([2.,1.09,1.09]),z,z,r,s,.1) is None
    assert sphere_box_toi(np.array([-2.,1.05,1.05]),np.array([2.,1.05,1.05]),z,z,r,s,.1) is not None

def test_fast_sweep_and_moving_box():
    z=np.zeros(3)
    t=sphere_box_toi(np.array([-5.,0,0]),np.array([5.,0,0]),z,z,np.eye(3),np.array([.01,.1,.1]),.0085)
    assert .49<t<.5
    assert sphere_box_toi(z,z,np.array([-1.,0,0]),np.array([1.,0,0]),np.eye(3),np.ones(3)*.1,.01) is not None

def test_judge_unique_hit():
    j=TestJudge();assert j.impact('a','target_armor',0,[0,0,0]);assert not j.impact('a','target_armor',0,[0,0,0]);assert j.hp==190
    assert not j.impact('b','target_body',0,[0,0,0]);assert j.hp==190

def test_physics_motor_pause_reset():
    s=Simulation(render=False)
    for _ in range(100):s.step(Command(force_y=20))
    assert s.data.qpos[1]>.01 and s.data.qvel[1]>0
    t=s.time;s.paused=True;s.step(Command(fire=True));assert s.time==t and s.shot_counter==0
    s.reset();assert s.time==0 and s.episode==1 and s.judge.hp==200 and not s.projectiles

def inject(s,start,velocity):
    s.projectiles=[Projectile('test',np.array(start,dtype=float),np.array(velocity,dtype=float),s.time)]
    for _ in range(160):s.step()

def test_actual_geometry_occludes_projectile():
    s=Simulation(render=False);inject(s,[1,0,.65],[22.5,0,1.])
    assert s.judge.hp==200 and s.judge.events[0]['geom']=='occluder'

def test_actual_armor_hit_without_wall():
    s=Simulation(render=False,occluder=False);inject(s,[4,0,.65],[22.5,0,.39])
    assert s.judge.hp==190 and s.judge.events[0]['valid_armor']

def test_rgb_observation_and_motor_changes_image():
    s=Simulation();a=s.observe()
    assert not hasattr(a,'enemy_position') and a.rgb.shape==(240,320,3)
    for _ in range(500):s.step(Command(force_y=30))
    b=s.observe();assert np.mean(np.abs(a.rgb.astype(float)-b.rgb.astype(float)))>1
    s.close()

def test_navigation_contract_rejects_invalid():
    from rm_match.adapters import parse_navigation_intent
    import pytest
    assert parse_navigation_intent({'behavior':'PATROL','target_point':{'x':1,'y':2}}).target_point==(1.,2.)
    with pytest.raises(ValueError):parse_navigation_intent({'behavior':'PATROL','target_point':{'x':float('nan'),'y':2}})

def test_gimbal_limits_are_radians():
    s=Simulation(render=False)
    assert np.allclose(s.model.jnt_range[s.model.joint('gimbal_pitch').id],[-.4,.5])
    for _ in range(1000):s.step(Command(gimbal_pitch=.2))
    assert s.data.qpos[4]>.1

def test_scan_is_sensor_only_and_world_odometry():
    s=Simulation();o=s.observe()
    assert len(o.ranges)==len(o.range_angles)==64
    assert o.odom_xyyaw==(0.,-1.8,0.)
    assert all(0<=r<=8 for r in o.ranges)
    s.close()

def test_rgb_closed_loop_hits_moving_armor():
    from rm_match.controllers import PixelBaseline
    import math
    s=Simulation(occluder=False);policy=PixelBaseline();command=None
    for i in range(1000):
        if i%20==0:command=policy.act(s.observe())
        s.step(command,target_motion=.45*math.sin(s.time*1.1))
    assert s.shot_counter>0 and s.judge.hp<200
    assert all(e['geom']=='target_armor' for e in s.judge.events if e.get('valid_armor'))
    s.close()

def test_no_camera_capture_is_explicit_empty():
    s=Simulation(render=False)
    assert s.observe(include_rgb=False).rgb.shape==(0,0,3)
