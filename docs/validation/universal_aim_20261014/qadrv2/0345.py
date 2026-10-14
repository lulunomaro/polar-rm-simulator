from dataclasses import replace
import numpy as np
from rm_match.contracts import Observation,Command
from rm_match.match_controllers import MatchNavigationPolicy,StaticArenaGrid,compose_navigation_and_aim


def obs(role='hero',team='red',t=0.,ammo=0,hp=350,xy=(-5.25,2.15),episode=0):
    return Observation(episode,t,np.empty((0,0,3),dtype=np.uint8),50.,(0.,)*5,(0.,)*5,hp,ammo,
        robot_id=team+'_'+role,odom_xyyaw=(*xy,0.),odom_vxyw=(0.,0.,0.),
        ranges=(8.,)*64,range_angles=tuple(np.linspace(-np.pi,np.pi,64,endpoint=False)),
        team=team,role=role,remaining_seconds=300-t)


def test_purchases_wait_for_coin_tick_and_actual_ammo_confirmation():
    p=MatchNavigationPolicy()
    assert p.decide(obs(t=.9)).purchase_bundles==0
    d=p.decide(obs(t=1.));assert d.purchase_bundles==5 and d.mode=='supply'
    assert p.decide(obs(t=1.1)).purchase_bundles==0
    assert p.decide(obs(t=2.)).purchase_bundles==5  # denied purchase not falsely credited
    assert p.decide(obs(t=2.1,ammo=5)).mode=='supply_departure'


def test_sentry_never_purchases_and_instances_do_not_communicate():
    p=MatchNavigationPolicy();assert p.decide(obs(role='sentry',ammo=0,hp=400)).purchase_bundles==0
    assert p.mode=='opening_egress'
    import pytest
    with pytest.raises(ValueError):p.decide(obs(role='infantry'))


def test_dead_and_recovery_hysteresis():
    p=MatchNavigationPolicy();assert p.decide(obs(hp=0)).command==Command()
    assert p.decide(obs(t=1,hp=80,ammo=5)).mode=='supply'
    assert p.decide(obs(t=2,hp=220,ammo=5)).mode=='supply'
    assert p.decide(obs(t=3,hp=350,ammo=5)).mode=='supply_departure'


def test_known_static_platform_avoided_and_not_erased():
    g=StaticArenaGrid(); assert not g.free(g.cell((-2.5,1.5)))
    path=g.plan((-5.25,2.15),(0.,0.))
    assert path and min(y for x,y in path)<-1.4
    from rm_match.navigation import NavObservation
    g.update(NavObservation.from_observation(obs()))
    assert not g.free(g.cell((-2.5,1.5)))


def test_composition_and_episode_clear():
    p=MatchNavigationPolicy();p.decide(obs(t=1));p.decide(obs(episode=1))
    assert p.last_purchase<0 and all(e['episode']==1 for e in p.events)
    n=Command(force_x=7,force_y=8,yaw_torque=1)
    a=Command(force_x=999,gimbal_yaw=.4,gimbal_pitch=.1,fire=True)
    c=compose_navigation_and_aim(n,a)
    assert c.force_x==7 and c.force_y==8 and c.fire and c.gimbal_yaw==.4


def test_shared_six_robot_world_purchases_and_reaches_assigned_stations_without_truth():
    from rm_match.match_engine import MatchSimulation
    s=MatchSimulation(render=False)
    policies={rid:MatchNavigationPolicy() for rid in s.robot_ids}
    try:
        for tick in range(15000):
            if tick%25==0:
                commands={}
                for rid in s.robot_ids:
                    o=s.observe(rid,include_rgb=False)
                    d=policies[rid].decide(o)
                    commands[rid]=d.command
                    if d.purchase_bundles:
                        s.judge.purchase_ammo(rid,d.purchase_bundles,episode=o.episode)
            s.step(commands)
        assert all(p.metrics.goal_reached for p in policies.values())
        assert all(p.metrics.distance_travelled_m>6 for p in policies.values())
        # The new tactic reserves control entry for sentries. Support stations
        # are deliberately outside the zone, identically on both teams.
        for team in ('red','blue'):
            sentry=policies[team+'_sentry']
            assert sentry.opening.started_at==0.
            assert sentry.opening.arrived_at is not None and sentry.opening.arrived_at<15.
            assert sentry.metrics.recovery_count==0
        assert s.judge.coins=={'red':100,'blue':100}
        for team in ('red','blue'):
            assert s.judge.robots[team+'_hero'].ammo==5
            assert s.judge.robots[team+'_infantry'].ammo==50
            assert s.judge.robots[team+'_sentry'].ammo==750
        assert min(s.judge.vp.values())<200
    finally:s.close()
