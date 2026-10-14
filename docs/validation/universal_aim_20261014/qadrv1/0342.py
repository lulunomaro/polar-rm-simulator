import os
os.environ.setdefault('MUJOCO_GL','egl' if os.name!='nt' else 'glfw')
os.environ.setdefault('EGL_PLATFORM','surfaceless')
import numpy as np
from rm_match.match_engine import MatchSimulation
from rm_match.contracts import Command
from rm_match.ballistics import swept_rotating_box_toi

def test_six_robots_safe_spawn_and_isolated_observation():
    s=MatchSimulation(render=False)
    assert len(s.robot_ids)==6 and s.model.nu==30 and s.data.ncon==0
    o=s.observe('blue_sentry',False)
    assert o.robot_id=='blue_sentry' and o.team=='blue' and o.own_hp==400 and o.ammo==750
    assert not hasattr(o,'enemy_pose') and not hasattr(o,'other_robots')
    assert len(o.own_qpos)==5 and len(o.ranges)==64

def test_commands_physically_move_only_named_robot_and_reset():
    s=MatchSimulation(render=False)
    initial={r:s.data.xpos[s.body_ids[r]].copy() for r in s.robot_ids}
    for _ in range(500):s.step({'red_hero':Command(force_y=-20)})
    assert s.data.xpos[s.body_ids['red_hero']][1]<initial['red_hero'][1]-.2
    assert np.linalg.norm(s.data.xpos[s.body_ids['blue_hero']]-initial['blue_hero'])<1e-4
    t=s.time;s.paused=True;s.step();assert s.time==t
    s.reset();assert s.episode==1 and s.time==0 and s.judge.episode==1

def test_match_terminal_freezes_physics():
    s=MatchSimulation(render=False);s.judge.tick(300)
    assert s.judge.terminal
    s.step({'red_sentry':Command(force_x=100,fire=True)})
    assert s.time==0 and not s.projectiles

def test_rotating_box_no_phantom_collision():
    angle=.2;r=np.array([[np.cos(angle),-np.sin(angle),0],[np.sin(angle),np.cos(angle),0],[0,0,1.]])
    assert swept_rotating_box_toi(np.array([-2.,3,0]),np.array([2.,3,0]),np.zeros(3),np.zeros(3),np.eye(3),r,np.ones(3),.01) is None
    assert swept_rotating_box_toi(np.array([-2.,0,0]),np.array([2.,0,0]),np.zeros(3),np.zeros(3),np.eye(3),r,np.ones(3),.01) is not None

def test_match_camera_is_actual_per_robot_view():
    s=MatchSimulation()
    a=s.observe('red_sentry');b=s.observe('blue_sentry')
    assert a.rgb.shape==b.rgb.shape==(240,320,3)
    assert not np.array_equal(a.rgb,b.rgb)
    s.close()

def test_rotating_armor_grazing_does_not_abort():
    import math
    for a in [1e-4,1e-7]:
        r=np.array([[math.cos(a),-math.sin(a),0],[math.sin(a),math.cos(a),0],[0,0,1.]])
        result=swept_rotating_box_toi(np.array([-.05,.1284,0]),np.array([-.005,.1284,0]),
            np.zeros(3),np.zeros(3),np.eye(3),r,np.array([.025,.12,.065]),.0084)
        assert result is None or 0<=result<=1

def test_rotating_near_graze_has_bounded_work():
    import math,time
    a=1e-7;r=np.array([[math.cos(a),-math.sin(a),0],[math.sin(a),math.cos(a),0],[0,0,1.]])
    started=time.perf_counter()
    result=swept_rotating_box_toi(np.array([-.02,.128400012,0]),np.array([.02,.128400012,0]),
        np.zeros(3),np.zeros(3),np.eye(3),r,np.array([.025,.12,.065]),.0084)
    assert result is None
    assert time.perf_counter()-started<2

def test_scene_collision_registry_covers_all_physical_shapes():
    import mujoco
    s=MatchSimulation(render=False)
    physical={g for g in range(s.model.ngeom) if s.model.geom_contype[g]}
    assert physical==set(s.colliders)
    assert all(s.model.geom_type[g]==mujoco.mjtGeom.mjGEOM_BOX for g in physical)

def test_world_clocks_pause_no_purchase_or_fire_advance():
    s=MatchSimulation(render=False)
    s.paused=True
    for _ in range(100):s.step({'red_sentry':Command(fire=True)})
    assert s.judge.sim_time==s.time==0
    assert s.judge.robots['red_sentry'].ammo==750
    assert s.judge.coins=={'red':0,'blue':0}

def test_new_unhandled_collision_geometry_fails_closed(monkeypatch):
    import pytest
    import rm_match.match_engine as engine
    original=engine.make_match_xml
    monkeypatch.setattr(engine,'make_match_xml',lambda:original().replace('</worldbody>',
        '<geom name="unsupported_sphere" type="sphere" size=".1" pos="0 0 2"/></worldbody>'))
    with pytest.raises(NotImplementedError,match='unsupported_sphere'):
        engine.MatchSimulation(render=False)

def test_spectator_effects_cannot_be_requested_on_actor_output():
    import pytest
    from rm_match.spectator_effects import SpectatorEffects
    effects=SpectatorEffects();s=MatchSimulation(spectator_effects=effects)
    before=s.observe('red_sentry').rgb
    s.image(show_effects=True)
    after=s.observe('red_sentry').rgb
    assert np.array_equal(before,after)
    with pytest.raises(ValueError,match='forbidden'):
        s.image('red_sentry__aim',show_effects=True)
    s.reset();s.close()
