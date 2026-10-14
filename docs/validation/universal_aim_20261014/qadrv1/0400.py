"""Headless v5 qualification: clocks, fire transport, real launch, UID census.

No renderer, source process, model download, or external service is used. Actor
responses in transport tests are explicit test doubles, not source validation.
Run: python -m pytest -q tests/test_timing_match_v5.py
"""
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import mujoco
import numpy as np
import pytest

from rm_match.contracts import Command
from rm_match.match_model import make_match_xml
from rm_match.timing.fire_level_delay import FireLevelDelay, FireDelayProtocolError
from rm_match.timing.plant import AuditedJudge, AuditedMatchSimulation
from rm_match.timing.transport import MatchFireTransport


@pytest.fixture
def sim():
    root = ET.fromstring(make_match_xml())
    root.find('option').set('timestep', '0.0005')
    world = AuditedMatchSimulation(render=False, model_xml=ET.tostring(root, encoding='unicode'))
    try:
        yield world
    finally:
        world.close()


def transport_fixture():
    robot = SimpleNamespace(alive=True, weak=False)
    obs = SimpleNamespace(odom_vxyw=(0., 0., 0.), odom_xyyaw=(0., 0., 0.), own_qpos=(0.,)*5)
    world = SimpleNamespace(episode=0, time=0., physics_step=0,
        judge=SimpleNamespace(robots={'red_sentry': robot}, terminal=False),
        paused=False, phase='running', emergency_stop=False, fire_context={})
    world.observe = lambda *args: obs
    source = SimpleNamespace(client=object(), error=None,
        gate=SimpleNamespace(active=True, anchor=(0., 0.)),
        latest_response={'tracking': True, 'should_shoot': True,
                         'observation_shoot_allowed': True, 'target_age_s': 0.,
                         'direction': [1., 0., 0.], 'control_time_ns': 0},
        last_accepted_s=0., last_actuator_saturated=False, raw_ref=(0., 0.),
        segment=1, last_control_ns=0, last_response_time_s=0.)
    return world, source, obs, MatchFireTransport('red_sentry')


def apply_at(world, source, transport, step, *, decision=None, desired=(0., 0.), command=None):
    world.time = step * .0005
    world.physics_step = step
    return transport.apply(world, step, command or Command(), source, desired, decision=decision)


@pytest.mark.parametrize('width_steps', [20, 40, 60])
def test_transport_true_and_false_edges_both_shift_exactly_40ms(width_steps):
    world, source, _, transport = transport_fixture()
    observed = []
    for step in range(80 + width_steps + 1):
        decision = True if step == 0 else False if step == width_steps else None
        observed.append(apply_at(world, source, transport, step, decision=decision).fire)
    assert observed == [80 <= step < 80 + width_steps for step in range(len(observed))]
    released = [e for a in transport.events for e in a['released_events']]
    assert [e['level'] for e in released] == [True, False]
    assert all(e['release_ns'] - e['decision_ns'] == 40_000_000 for e in released)


@pytest.mark.parametrize('hazard', [
    'dead', 'weak', 'paused', 'terminal', 'estop', 'phase', 'disconnected',
    'source_error', 'lost_tracking', 'negative_observation', 'motion_request',
    'chassis_motion', 'origin_drift', 'visual_expired', 'saturated', 'unaligned',
    'invalid_command', 'invalid_direction', 'zero_direction', 'invalid_reference',
    'invalid_own_pose', 'invalid_own_velocity', 'invalid_desired_velocity', 'stale_target',
])
def test_safety_on_due_tick_wins_and_recovery_does_not_replay(hazard):
    world, source, obs, transport = transport_fixture()
    for step in range(80):
        assert not apply_at(world, source, transport, step, decision=True if step == 0 else None).fire
    desired = (0., 0.)
    command = Command()
    if hazard == 'dead': world.judge.robots['red_sentry'].alive = False
    elif hazard == 'weak': world.judge.robots['red_sentry'].weak = True
    elif hazard == 'paused': world.paused = True
    elif hazard == 'terminal': world.judge.terminal = True
    elif hazard == 'estop': world.emergency_stop = True
    elif hazard == 'phase': world.phase = 'preparing'
    elif hazard == 'disconnected': source.client = None
    elif hazard == 'source_error': source.error = 'test disconnect'
    elif hazard == 'lost_tracking': source.latest_response['tracking'] = False
    elif hazard == 'negative_observation': source.latest_response['observation_shoot_allowed'] = False
    elif hazard == 'motion_request': desired = (.01, 0.)
    elif hazard == 'chassis_motion': obs.odom_vxyw = (.031, 0., 0.)
    elif hazard == 'origin_drift': obs.odom_xyyaw = (.026, 0., 0.)
    elif hazard == 'visual_expired': source.last_accepted_s = -.041
    elif hazard == 'saturated': source.last_actuator_saturated = True
    elif hazard == 'unaligned': source.raw_ref = (.051, 0.)
    elif hazard == 'invalid_command': command = Command(gimbal_yaw=float('nan'))
    elif hazard == 'invalid_direction': source.latest_response['direction'] = [float('nan'), 0., 0.]
    elif hazard == 'zero_direction': source.latest_response['direction'] = [0., 0., 0.]
    elif hazard == 'invalid_reference': source.raw_ref = (float('nan'), 0.)
    elif hazard == 'invalid_own_pose': obs.own_qpos = (0., 0., 0., float('nan'), 0.)
    elif hazard == 'invalid_own_velocity': obs.odom_vxyw = (float('nan'), 0., 0.)
    elif hazard == 'invalid_desired_velocity': desired = (float('nan'), 0.)
    elif hazard == 'stale_target': source.latest_response['target_age_s'] = .081
    assert not apply_at(world, source, transport, 80, decision=True, desired=desired, command=command).fire
    cleared = transport.delay.snapshot()
    assert cleared['pending_count'] == 0 and cleared['active_event'] is None
    assert not cleared['safe'] and not cleared['applied_level']
    # Recovery carries no authority to replay either the old queued True or the
    # True received on the safety boundary. Use a fresh source fixture only.
    healthy_world, healthy_source, _, _ = transport_fixture()
    healthy_source.last_accepted_s = .04
    healthy_source.latest_response['control_time_ns'] = 40_000_000
    healthy_source.last_control_ns = 40_000_000
    healthy_source.last_response_time_s = .04
    for step in range(81, 161):
        assert not apply_at(healthy_world, healthy_source, transport, step,
                            decision=True if step == 81 else None).fire
    assert apply_at(healthy_world, healthy_source, transport, 161).fire


def test_lost_safety_clears_already_active_level_immediately():
    world, source, _, transport = transport_fixture()
    for step in range(81):
        command = apply_at(world, source, transport, step, decision=True if step == 0 else None)
    assert command.fire
    source.client = None
    assert not apply_at(world, source, transport, 81).fire
    assert transport.delay.snapshot()['active_event'] is None


def test_delay_clock_fault_is_fail_closed_and_zero_delay_is_identity():
    line = FireLevelDelay(0, step_ns=500_000)
    for step, level in enumerate([True, False, True, True, False]):
        assert line.advance(step, level, safe=True)['applied_level'] is level
    with pytest.raises(FireDelayProtocolError) as error:
        line.advance(2, True, safe=True)
    assert error.value.snapshot['active_event'] is None
    assert not error.value.snapshot['applied_level']


def test_integer_physics_clock_freezes_on_pause_and_resets(sim):
    for step in range(1, 21):
        sim.step()
        assert sim.physics_step == step
        assert sim.time == step / 2000
        assert sim.data.time == pytest.approx(sim.time, abs=1e-12)
    sim.paused = True
    sim.step({'red_sentry': Command(fire=True)})
    assert sim.physics_step == 20 and not sim.launches
    sim.reset()
    assert sim.physics_step == 0 and sim.time == 0 and sim.episode == 1


def test_all_six_launch_from_current_muzzle_pose_and_own_velocity(sim):
    expected = {}
    for index, rid in enumerate(sim.robot_ids):
        sim.judge.robots[rid].ammo = 5
        qidx, vidx = sim.qindices[rid], sim.vindices[rid]
        sim.data.qpos[qidx[3]] = .10 + index*.03
        sim.data.qpos[qidx[4]] = -.03 + index*.01
        sim.data.qvel[vidx] = [.02, -.01, .005, .4, -.2]
    mujoco.mj_forward(sim.model, sim.data)
    for rid in sim.robot_ids:
        site = sim.model.site(rid+'__muzzle').id
        jacp = np.zeros((3, sim.model.nv)); jacr = np.zeros_like(jacp)
        mujoco.mj_jacSite(sim.model, sim.data, jacp, jacr, site)
        speed = 12. if sim.roles[rid] == 'hero' else 22.5
        expected[rid] = (sim.data.site_xpos[site].copy(),
            speed*sim.data.site_xmat[site].reshape(3, 3)[:, 0] + jacp@sim.data.qvel)
        sim._fire(rid)
    assert {x['owner'] for x in sim.launches} == set(sim.robot_ids)
    assert len(sim.launches) == len({x['uid'] for x in sim.launches}) == 6
    for launch in sim.launches:
        position, velocity = expected[launch['owner']]
        np.testing.assert_allclose(launch['position'], position, atol=1e-12)
        np.testing.assert_allclose(launch['velocity'], velocity, atol=1e-12)
        assert launch['caliber'] == ('42mm' if sim.roles[launch['owner']] == 'hero' else '17mm')
        assert launch['launch_ns'] == 0
    assert sim.terminal_uid_audit()['launched'] == 6


def test_projectile_obeys_gravity_after_real_launch(sim):
    sim._fire('red_sentry')
    bullet = sim.projectiles[0]
    position, velocity = bullet.position.copy(), bullet.velocity.copy()
    sim.step()
    assert bullet.uid in {p.uid for p in sim.projectiles}
    dt = sim.model.opt.timestep
    np.testing.assert_allclose(bullet.position, position+velocity*dt+[0., 0., -4.905*dt*dt], atol=1e-12)
    np.testing.assert_allclose(bullet.velocity, velocity+[0., 0., -9.81*dt], atol=1e-12)


def test_actual_launch_uid_links_to_exact_released_event(sim):
    _, source, _, transport = transport_fixture()
    rid = 'red_sentry'
    source.gate.anchor = tuple(sim.observe(rid, False, False).odom_xyyaw[:2])
    for step in range(81):
        observation = sim.observe(rid, False, False)
        source.raw_ref = observation.own_qpos[3:5]
        source.last_accepted_s = sim.time
        source.latest_response['control_time_ns'] = step*500_000
        command = transport.apply(sim, step,
            Command(gimbal_yaw=source.raw_ref[0], gimbal_pitch=source.raw_ref[1]),
            source, (0., 0.), decision=True if step == 0 else None)
        if step < 80:
            assert not command.fire and not sim.launches
        sim.step({rid: command})
    assert len(sim.launches) == 1
    launch = sim.launches[0]
    event = launch['transport_event']
    assert launch['launch_ns'] == event['release_ns'] == event['due_ns'] == 40_000_000
    assert event['decision_ns'] == 0 and event['payload']['source_segment'] == 1
    assert launch['uid'] in {entry['projectile_uid'] for entry in sim.judge.events if entry['type'] == 'fire'}
    assert sim.terminal_uid_audit()['launched'] == 1


def test_uid_expiry_terminal_censoring_and_no_terminal_damage(sim):
    sim._fire('red_sentry')
    expired_uid = sim.projectiles[0].uid
    sim.projectiles[0].position = np.array([25., 25., 5.])
    sim.step()
    assert sim.resolutions[0]['uid'] == expired_uid
    assert sim.resolutions[0]['kind'] == 'expired_or_out_of_bounds'
    sim._fire('blue_sentry')
    active_uid = sim.projectiles[0].uid
    sim.judge.vp['red'] = 0
    sim.judge._check_terminal()
    assert sim.judge.terminal
    before = (sim.physics_step, len(sim.launches), dict(sim.judge.attack_damage))
    for _ in range(5): sim.step({'red_sentry': Command(fire=True)})
    assert before == (sim.physics_step, len(sim.launches), sim.judge.attack_damage)
    audit = sim.terminal_uid_audit()
    assert audit['launched'] == 2 and audit['resolved'] == 1
    assert audit['active_censored_at_end'] == [active_uid]
    assert audit['hp_removed_by_team'] == {'red': 0., 'blue': 0.}


def test_uid_audit_detects_missing_and_duplicate_accounting(sim):
    sim._fire('red_sentry')
    sim.launches.append(dict(sim.launches[0]))
    with pytest.raises(AssertionError, match='UID partition'):
        sim.terminal_uid_audit()
    sim.launches.pop()
    sim.projectiles.clear()
    with pytest.raises(AssertionError, match='UID partition'):
        sim.terminal_uid_audit()


def test_judge_uid_credit_is_actual_hp_and_duplicate_cannot_erase_it():
    judge = AuditedJudge()
    judge.robots['blue_infantry'].hp = 7
    assert judge.fire('red_sentry', 'audit:0', 0., muzzle_speed=22.5)
    hit = dict(projectile_uid='audit:0', shooter_id='red_sentry', target_id='blue_infantry',
               armor_id='blue_infantry__armor_front', normal_speed=22.5, caliber='17mm')
    assert judge.apply_hit_batch([hit], .01, episode=0) == [True]
    assert judge.damage_by_uid['audit:0'] == judge.attack_damage['red'] == 7
    assert judge.apply_hit_batch([hit], .011, episode=0) == [False]
    assert judge.damage_by_uid['audit:0'] == 7
