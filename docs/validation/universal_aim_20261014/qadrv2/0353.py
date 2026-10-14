import math
import numpy as np
import pytest
from rm_match.navigation import NavObservation, NavigationBaseline, OccupancyGrid
from rm_match.contracts import NavigationIntent


def observation(t=0., xy=(0.,0.), ranges=None, angles=None, episode=0, yaw=0., alive=True):
    return NavObservation(episode,'blue_sentry',t,(*xy,yaw),(0.,0.),
        tuple(ranges if ranges is not None else [8.]*64),
        tuple(angles if angles is not None else np.linspace(-math.pi,math.pi,64,endpoint=False)),8.,alive)


def baseline(goal=(3.,0.)):
    n=NavigationBaseline(); n.reset(0); n.set_intent(NavigationIntent('PATROL',goal)); return n


def test_repository_intent_shape_and_bounds():
    n=baseline();n.set_intent({'behavior':'HOLD','target_point':{'x':2,'y':1},'reason':'recorded'})
    assert n.intent.target_point == (2,1)
    with pytest.raises(ValueError):n.set_intent({'behavior':'HOLD','target_point':{'x':math.nan,'y':0}})
    with pytest.raises(ValueError):n.set_intent(NavigationIntent('PATROL',(100.,0.)))


def test_astar_obstacle_and_no_corner_cutting():
    g=OccupancyGrid(bounds=(-4,4,-4,4))
    g.blocked={g.cell((.125,y)) for y in np.arange(-2.,2.,.25)}
    p=g.plan((-2.,0.),(2.,0.))
    assert p and max(abs(y) for x,y in p)>=2.
    assert all(g.free(g.cell(x)) for x in p)
    s=g.cell((-2.,0.));g.blocked={ (s[0]+1,s[1]),(s[0],s[1]+1)}
    p=g.plan(g.center(s),g.center((s[0]+1,s[1]+1)))
    assert len(p)>2


def test_limited_sensors_replan_and_stop():
    n=baseline();n.velocity(observation());p1=list(n.path)
    # Visible wall 1m ahead spanning the direct path; no world/map truth passed.
    angles=np.linspace(-.9,.9,40); ranges=1/np.cos(angles)
    n.velocity(observation(.7,ranges=ranges,angles=angles))
    assert n.metrics.replans==2 and n.path!=p1
    assert n.grid.hits
    # Emergency close anonymous surface blocks forward velocity.
    assert n._clearance(observation(ranges=[.3],angles=[0.]),(1.,0.)) == 0


def test_goal_reached_and_event_identity():
    n=baseline((.1,0.));assert n.velocity(observation())==(0.,0.)
    assert n.metrics.goal_reached
    event=next(e for e in n.metrics.events if e['type']=='goal_reached')
    assert event['episode']==0 and event['robot_id']=='blue_sentry' and event['sim_time']==0


def test_stuck_recovery_and_episode_reset():
    n=baseline()
    for t in np.arange(0,2.3,.1):n.velocity(observation(float(t)))
    assert n.metrics.recovery_count==1
    assert any(e['type']=='stuck_recovery' for e in n.metrics.events)
    assert n.velocity(observation(0.,episode=1))==(0.,0.)
    assert n.intent is None and not n.grid.hits and n.metrics.recovery_count==0


def test_bad_sensors_dead_robot_and_time_fail_safe():
    n=baseline(); assert n.velocity(observation(ranges=[],angles=[]))==(0.,0.)
    assert n.velocity(observation(alive=False))==(0.,0.)
    with pytest.raises(ValueError):n.velocity(observation(ranges=[1.],angles=[]))
    n.velocity(observation(1.))
    with pytest.raises(ValueError):n.velocity(observation(.5))


def test_sensor_angles_body_to_world():
    n=baseline();o=observation(ranges=[1.],angles=[0.],yaw=math.pi/2)
    n.grid.update(o)
    assert n.grid.cell((0.,1.)) in n.grid.hits
    assert n._clearance(o,(0.,1.))<.6
    assert n._clearance(o,(1.,0.))==8.


def test_force_is_bounded_and_no_physics_reference():
    n=baseline();c=n.act(observation())
    assert 0 < c.force_x <= 60 and abs(c.force_y)<=60
    assert not hasattr(n,'data') and not hasattr(n,'model')


def test_mujoco_reaches_goal_using_physical_motors():
    from rm_match.engine import Simulation
    s=Simulation(render=False)
    n=NavigationBaseline();n.reset(s.episode);n.set_intent(NavigationIntent('PATROL',(1.5,-1.8)))
    try:
        for tick in range(4000):
            if tick%20==0:c=n.act(s.observe(include_rgb=False))
            s.step(c)
        assert n.metrics.goal_reached
        assert math.dist(s.observe(include_rgb=False).odom_xyyaw[:2],(1.5,-1.8))<.35
        assert n.metrics.distance_travelled_m>1.
    finally:s.close()


def test_mujoco_obstacle_detour_no_chassis_contact():
    from rm_match.engine import Simulation
    s=Simulation(render=False)
    n=NavigationBaseline();n.reset(s.episode);n.set_intent(NavigationIntent('PATROL',(5.,1.)))
    try:
        for tick in range(4500):
            if tick%20==0:c=n.act(s.observe(include_rgb=False))
            s.step(c)
            for contact in s.data.contact:
                names={s.model.geom(int(i)).name for i in contact.geom}
                assert names != {'chassis','occluder'}
        assert n.metrics.goal_reached
        assert n.metrics.replans>1
        assert n.metrics.min_observed_clearance_m>0
        assert math.dist(s.observe(include_rgb=False).odom_xyyaw[:2],(5.,1.))<.35
    finally:s.close()


def test_observed_dynamic_obstacle_clears_and_replans():
    n=baseline();n.velocity(observation(ranges=[1.],angles=[0.]))
    assert n.grid.hits
    n.velocity(observation(.7,ranges=[8.],angles=[0.]))
    assert not n.grid.hits and n.metrics.replans>=2
