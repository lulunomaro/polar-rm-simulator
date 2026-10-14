"""Coverage of verified rules and explicitly labelled simulator edge policies."""
import pytest
from rm_match.competition_judge import MatchJudge, MANIFEST


def shot(j, uid, target='blue_infantry', armor='front', time=0, shooter='red_sentry', speed=20):
    assert j.fire(shooter,uid,time)
    return j.apply_hit(uid,shooter,target,armor,speed,time,caliber=j.robots[shooter].caliber)


def test_manifest_refuses_full_or_2027_conformance():
    assert MANIFEST['full_competition_conformance'] is False
    with pytest.raises(ValueError): MatchJudge(require_full_conformance=True)
    assert MANIFEST['unimplemented']


def test_roster_and_official_ammo():
    j = MatchJudge()
    assert len(j.robots)==6
    assert j.robots['red_hero'].hp==350
    assert j.robots['red_infantry'].hp==300
    assert j.robots['red_sentry'].ammo==750
    assert j.robots['red_hero'].ammo==0
    assert not j.fire('red_hero','h',0)
    alternate = MatchJudge(infantry_hp_profile='hp',infantry_heat_profile='cooling')
    assert alternate.robots['blue_infantry'].hp==350
    assert alternate.robots['blue_infantry'].heat_max==88


def test_clock_pause_reset_stale_event():
    j=MatchJudge(); j.tick(.27)
    assert j.sim_time==.27
    j.pause(); j.tick(4)
    assert j.sim_time==.27
    assert not j.fire('red_sentry','p',.27)
    j.pause(False); j.tick(1)
    assert j.coins['red']==200
    j.reset()
    assert j.sim_time==0 and j.episode==1
    assert not j.fire('red_sentry','old',0,episode=0)
    assert not j.tick(500,episode=0)
    assert not j.update_zone_presence(['red_sentry'],episode=0)
    with pytest.raises(ValueError): j.tick(-1)


def test_geometry_dedup_and_strict_hit_speed():
    j=MatchJudge()
    assert shot(j,'p')
    assert j.robots['blue_infantry'].hp==280
    assert not j.apply_hit('p','red_sentry','blue_infantry','rear',20,0)
    assert not shot(j,'body',armor=None)
    assert not j.apply_hit('body','red_sentry','blue_infantry','rear',20,0)
    assert not shot(j,'slow',speed=12)
    assert not shot(j,'friendly',target='red_infantry')
    assert not j.apply_hit('unknown','red_sentry','blue_infantry','front',20,0)
    assert j.attack_damage['red']==20


def test_armor_debounce():
    j=MatchJudge()
    assert shot(j,'a')
    assert not shot(j,'b',time=.049)
    assert shot(j,'c',time=.05)
    assert shot(j,'d',armor='rear',time=.05)


def test_fixed_heat_sampling_and_lock_until_zero():
    j=MatchJudge()
    for i in range(27): assert j.fire('red_sentry',str(i),0)
    assert j.robots['red_sentry'].heat==270
    assert not j.can_fire('red_sentry')
    j.tick(.099)
    assert j.robots['red_sentry'].heat==270
    j.tick(.1)
    assert j.robots['red_sentry'].heat==267
    j.tick(8.9)
    assert not j.can_fire('red_sentry')
    j.tick(9)
    assert j.can_fire('red_sentry')


def test_muzzle_speed_lock_independent_of_heat():
    j=MatchJudge()
    assert j.fire('red_sentry','p',0,muzzle_speed=26)
    j.tick(14.9); assert not j.can_fire('red_sentry')
    j.tick(15); assert j.can_fire('red_sentry')
    assert j.fire('red_sentry','p2',15,muzzle_speed=35)
    j.tick(100); assert not j.can_fire('red_sentry')


def test_coin_schedule_purchase_and_sentry_cannot_replenish():
    j=MatchJudge(); j.update_zone_presence(supply=['red_hero','red_infantry','red_sentry'])
    assert not j.purchase_ammo('red_hero')
    j.tick(1)
    assert j.purchase_ammo('red_hero',2)
    assert j.purchase_ammo('red_infantry',3)
    assert j.robots['red_hero'].ammo==2
    assert j.robots['red_infantry'].ammo==30
    assert j.coins['red']==150
    assert not j.purchase_ammo('red_sentry')
    assert not j.purchase_ammo('blue_hero')
    j.tick(241)
    assert j.coins['blue']==1200


def test_control_first_arrival_contest_and_two_second_grace():
    j=MatchJudge()
    j.update_zone_presence(['red_infantry'])
    j.tick(.5); j.update_zone_presence(['red_infantry','blue_sentry'])
    assert j.control_owner=='red'
    j.tick(1)
    assert j.vp=={'red':200,'blue':199}
    j.update_zone_presence(['blue_sentry'])
    j.tick(2.9); assert j.control_owner=='red'
    j.tick(3); assert j.control_owner=='blue'
    assert j.vp=={'red':199,'blue':198}


def test_death_control_respawn_invulnerability_and_supply_clear():
    j=MatchJudge(); j.update_zone_presence(['blue_infantry'])
    for i in range(15): assert shot(j,str(i),time=i*.05)
    r=j.robots['blue_infantry']
    assert not r.alive and r.deaths==1 and r.heat==0
    assert j.vp['blue']==180 and j.control_owner is None
    assert not shot(j,'dead',time=.8)
    j.tick(5.7)
    assert r.alive and r.hp==60 and r.weak
    assert j.control_owner is None and not j.can_fire(r.robot_id)
    assert not shot(j,'immune',time=5.7)
    j.update_zone_presence(supply=[r.robot_id])
    assert not r.weak and r.invulnerable_until==0
    j.tick(5.8); assert r.hp==67.5
    assert shot(j,'after_supply',time=5.8)


def test_mutual_death_batch_order_independent():
    def run(reverse):
        j=MatchJudge()
        # Explicit unit fixture: both targets have exactly one shot of remaining HP.
        j.robots['red_sentry'].hp=j.robots['blue_sentry'].hp=20
        assert j.fire('red_sentry','r',0)
        assert j.fire('blue_sentry','b',0)
        hits=[dict(projectile_uid='r',shooter_id='red_sentry',target_id='blue_sentry',armor_id='front',normal_speed=20),
              dict(projectile_uid='b',shooter_id='blue_sentry',target_id='red_sentry',armor_id='front',normal_speed=20)]
        assert j.apply_hit_batch(hits[::-1] if reverse else hits,0)==[True,True]
        return j.snapshot()
    assert run(False)==run(True)


def test_terminal_vp_and_time_hierarchy_no_uc_base_rules():
    j=MatchJudge(); j.update_zone_presence(['red_sentry']); j.tick(200)
    assert j.terminal and j.winner=='red' and j.terminal_reason=='vp_zero'
    assert not j.fire('red_sentry','late',200)
    j=MatchJudge(); j.tick(300)
    assert j.terminal_reason=='draw'
    j=MatchJudge(); shot(j,'one'); j.tick(300)
    assert j.winner=='red' and j.terminal_reason=='time_attack_damage'
    j=MatchJudge(); j.robots['red_hero'].hp=349; j.tick(300)
    assert j.winner=='blue' and j.terminal_reason=='time_remaining_hp'
    j=MatchJudge(); assert not j.fire('red_sentry','boundary',300)
    assert j.terminal_reason=='draw'


def test_replay_exact_state_and_events():
    j=MatchJudge(); j.update_zone_presence(['red_sentry'],['red_hero'])
    j.tick(1); assert j.purchase_ammo('red_hero',2)
    assert j.fire('red_hero','h',1,muzzle_speed=12)
    assert j.apply_hit('h','red_hero','blue_sentry','front',11,1,caliber='42mm')
    j.tick(6); j.pause(); j.tick(7); j.pause(False); j.tick(8)
    restored=MatchJudge.replay(j.export_replay())
    assert restored.snapshot()==j.snapshot()
    assert restored.events==j.events


def test_inflight_projectile_survives_shooter_death():
    j=MatchJudge(); j.robots['red_sentry'].hp=20
    assert j.fire('red_sentry','outgoing',0)
    assert shot(j,'incoming',target='red_sentry',shooter='blue_sentry')
    assert not j.robots['red_sentry'].alive
    assert j.apply_hit('outgoing','red_sentry','blue_sentry','front',20,.1)


def test_simultaneous_vp_zero_reports_unresolved_not_fake_official_draw():
    j=MatchJudge(); j.vp={'red':20,'blue':20}
    j.robots['red_sentry'].hp=j.robots['blue_sentry'].hp=20
    hits=[]
    for team,other in [('red','blue'),('blue','red')]:
        assert j.fire(f'{team}_sentry',team,0)
        hits.append(dict(projectile_uid=team,shooter_id=f'{team}_sentry',target_id=f'{other}_sentry',armor_id='front',normal_speed=20))
    assert j.apply_hit_batch(hits,0)==[True,True]
    assert j.terminal and j.winner is None
    assert j.terminal_reason=='unresolved_simultaneous_zero_vp'


def test_clock_partition_independent():
    j=MatchJudge(); k=MatchJudge()
    for instance in (j,k):
        instance.update_zone_presence(['red_infantry'])
        instance.fire('red_sentry','p',0)
    j.tick(100)
    for i in range(1,10001): k.tick(i*.01)
    assert j.snapshot()==k.snapshot()
    assert j.events==k.events


def test_catchup_awards_once_per_threshold():
    j=MatchJudge(); j.update_zone_presence(['red_sentry']); j.tick(140)
    assert j.coins['blue']==1000  # 600 periodic + two verified 200 catch-up awards.
    assert j.coins['red']==600
    j.tick(141)
    assert j.coins['blue']==1000


def test_hero_shield_latches_until_alive_and_ammo_positive():
    j=MatchJudge(); h=j.robots['red_hero']
    h.hp=20
    assert shot(j,'kill',target='red_hero',shooter='blue_sentry')
    j.tick(2.9); assert not j._hero_shielded('red')
    j.tick(3); assert j._hero_shielded('red')
    j.tick(5); assert h.alive and h.ammo==0 and j._hero_shielded('red')
    j.update_zone_presence(supply=['red_hero'])
    assert j.purchase_ammo('red_hero')
    assert not j._hero_shielded('red')


def test_replay_after_episode_reset():
    j=MatchJudge(); j.tick(5); j.reset(); j.tick(2)
    copy=MatchJudge.replay(j.export_replay())
    assert copy.snapshot()==j.snapshot() and copy.events==j.events
