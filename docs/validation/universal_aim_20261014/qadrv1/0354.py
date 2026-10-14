"""State-level egress regressions; synthetic scans, never a physics/log replay."""
from dataclasses import replace
import math

import numpy as np
import pytest

from rm_match.contracts import Command, Observation
from rm_match.match_controllers import MatchNavigationPolicy


def observation(team='red', *, t=0., xy=(-5.25, 2.15), role='sentry',
                hp=400, ammo=750, episode=0):
    side = 1 if team == 'red' else -1
    return Observation(
        episode, t, np.empty((0, 0, 3), dtype=np.uint8), 50., (0.,)*5,
        (0.,)*5, hp, ammo, robot_id=team+'_'+role,
        odom_xyyaw=(side*xy[0], side*xy[1], 0. if side == 1 else math.pi),
        odom_vxyw=(0., 0., 0.), ranges=(8.,)*64,
        range_angles=tuple(np.linspace(-math.pi, math.pi, 64, endpoint=False)),
        team=team, role=role, remaining_seconds=300-t,
    )


def spy_navigation(policy, monkeypatch):
    calls = []
    command = Command(force_x=3., force_y=7.)

    def act(o):
        calls.append(o)
        policy.nav.last_velocity_target = (.1, .2)
        return command

    monkeypatch.setattr(policy.nav, 'act', act)
    return calls, command


@pytest.mark.parametrize('team', ['red', 'blue'])
def test_initial_sentry_egress_keeps_existing_command_and_center_intent(team):
    p = MatchNavigationPolicy()
    side = 1 if team == 'red' else -1
    d = p.decide(observation(team))
    assert d.mode == 'opening_egress'
    assert d.command == Command(force_y=-36.*side)
    assert p.desired_velocity == (0., -float(side))
    assert p.nav.intent.target_point == (0., 0.)
    assert p.original_rule.calls == 0


@pytest.mark.parametrize('team', ['red', 'blue'])
@pytest.mark.parametrize('exit_xy', [(-3.95, 2.15), (-5.25, -1.7), (-3.9, -1.8)])
def test_first_corridor_exit_cannot_reenter_before_center(team, exit_xy, monkeypatch):
    p = MatchNavigationPolicy()
    p.decide(observation(team))
    calls, command = spy_navigation(p, monkeypatch)
    p.decide(observation(team, t=1., xy=exit_xy))
    assert p.opening.arrived_at is None
    d = p.decide(observation(team, t=1.1))
    assert len(calls) == 2
    assert d.mode == 'opening_rush'
    assert d.command == command
    assert p.desired_velocity == (.1, .2)


@pytest.mark.parametrize('team', ['red', 'blue'])
def test_center_arrival_then_supply_return_does_not_rearm_opening(team, monkeypatch):
    p = MatchNavigationPolicy()
    p.decide(observation(team, t=12.4, xy=(0., 0.)))
    calls, command = spy_navigation(p, monkeypatch)
    assert p.decide(observation(team, t=30., hp=90)).mode == 'supply'
    d = p.decide(observation(team, t=42.6))
    assert p.opening.arrived_at == 12.4
    assert len(calls) == 2
    assert d.mode == 'occupation'
    assert d.command == command


@pytest.mark.parametrize('team', ['red', 'blue'])
def test_exit_during_supply_before_center_is_still_latched(team, monkeypatch):
    p = MatchNavigationPolicy()
    p.decide(observation(team))
    calls, command = spy_navigation(p, monkeypatch)
    assert p.decide(observation(team, t=1., xy=(-4.6, -1.8), hp=90)).mode == 'supply'
    assert p.opening.arrived_at is None
    d = p.decide(observation(team, t=2.))
    assert len(calls) == 2
    assert d.mode == 'opening_rush'
    assert d.command == command


@pytest.mark.parametrize('team', ['red', 'blue'])
def test_recovery_boundary_crossing_does_not_reverse_after_opening(team, monkeypatch):
    """Use logged boundary coordinates with deliberately stubbed route/clearance.

    The old run has no saved scans here, so this proves controller ownership,
    not physical escape, new match performance, or replay equivalence.
    """
    p = MatchNavigationPolicy()
    side = 1 if team == 'red' else -1
    p.decide(observation(team, t=12.4, xy=(0., 0.)))
    # Force a reproducible unavailable route while leaving the real inflated
    # static-map recovery-direction checks and 0.8-second recovery logic intact.
    monkeypatch.setattr(p.nav.grid, 'plan', lambda start, goal: [])
    monkeypatch.setattr(p.nav, '_clearance',
                        lambda o, direction: 8. if side*direction[1] > .99 else 1.)
    for t in (53.5, 54., 54.5, 55., 55.5):
        p.decide(observation(team, t=t, xy=(-4.633474872773091, -1.7112767519712175)))
    assert p.nav.metrics.recovery_count == 1
    assert p.nav.last_status == 'recovering'
    assert p.desired_velocity[1] == pytest.approx(.4*side)
    # Logged red location at 56.2s crosses the old y=-1.7 predicate while
    # recovery remains active until 56.3s. Blue uses the exact mirrored state.
    d = p.decide(observation(team, t=56.2, xy=(-4.633496299948871, -1.6794550870810712)))
    assert d.mode != 'opening_egress'
    assert p.nav.last_time == 56.2
    assert p.nav.last_status == 'recovering'
    assert p.desired_velocity[1] == pytest.approx(.4*side)
    assert d.command.force_y*side > 0
    # Recovery expiration and further boundary crossings cannot rearm egress.
    for t, y in ((56.4, -1.68), (56.5, -1.74), (56.6, -1.68)):
        assert p.decide(observation(team, t=t, xy=(-4.6335, y))).mode != 'opening_egress'


@pytest.mark.parametrize('team', ['red', 'blue'])
def test_active_recovery_permanently_takes_ownership_inside_first_bay(team, monkeypatch):
    p = MatchNavigationPolicy()
    p.decide(observation(team))
    calls, command = spy_navigation(p, monkeypatch)
    # A recovery can have started during an early low-HP supply visit without
    # an outside observation. It owns motion even before the first bay exit.
    p.nav.recover_until = 2.
    p.nav.recovery_direction = (0., 1. if team == 'red' else -1.)
    assert p.decide(observation(team, t=.1, hp=90)).mode == 'supply'
    for t in (.2, 2.1):
        d = p.decide(observation(team, t=t))
        assert d.mode == 'opening_rush'
        assert d.command == command
    assert len(calls) == 3


@pytest.mark.parametrize('team', ['red', 'blue'])
@pytest.mark.parametrize('gate', [dict(match_phase='paused'), dict(own_hp=0),
                                  dict(emergency_stop=True)])
def test_temporary_safety_gate_preserves_release_and_episode_reset_rearms(team, gate, monkeypatch):
    p = MatchNavigationPolicy()
    p.decide(observation(team, xy=(-4.6, -1.8)))
    assert p.decide(replace(observation(team, t=.1), **gate)).command == Command()
    calls, command = spy_navigation(p, monkeypatch)
    assert p.decide(observation(team, t=.2)).command == command
    assert len(calls) == 1
    d = p.decide(observation(team, episode=1))
    assert d.mode == 'opening_egress'
    assert all(e['episode'] == 1 for e in p.events)


@pytest.mark.parametrize('team', ['red', 'blue'])
def test_weak_recovery_does_not_rearm_released_corridor(team, monkeypatch):
    p = MatchNavigationPolicy()
    p.decide(observation(team, xy=(-4.6, -1.8)))
    calls, command = spy_navigation(p, monkeypatch)
    assert p.decide(replace(observation(team, t=.1), own_weak=True)).mode == 'supply'
    assert p.decide(observation(team, t=.2)).command == command
    assert len(calls) == 2


@pytest.mark.parametrize('team', ['red', 'blue'])
@pytest.mark.parametrize('role,ammo,hp', [('hero', 5, 350), ('infantry', 50, 300)])
def test_support_departures_remain_repeatable_and_numerically_unchanged(team, role, ammo, hp):
    p = MatchNavigationPolicy()
    side = 1 if team == 'red' else -1
    args = dict(role=role, ammo=ammo, hp=hp)
    initial = p.decide(observation(team, t=2., **args))
    assert initial.mode == 'supply_departure'
    assert initial.command == Command(force_x=27.*side)
    staged = p.decide(observation(team, t=3., xy=(-4.3, 2.15), **args))
    assert staged.mode == 'support_stage' and staged.command == Command()
    p.decide(observation(team, t=15., xy=(-3.9, -1.8), **args))
    repeated = p.decide(observation(team, t=16., **args))
    assert repeated == initial


@pytest.mark.parametrize('team', ['red', 'blue'])
@pytest.mark.parametrize('recover_until', [.1, .2])
def test_expired_or_exact_deadline_recovery_does_not_consume_initial_egress(team, recover_until):
    p = MatchNavigationPolicy()
    p.decide(observation(team))
    p.nav.recover_until = recover_until
    assert p.decide(observation(team, t=.2)).mode == 'opening_egress'


@pytest.mark.parametrize('team', ['red', 'blue'])
def test_terminal_latch_and_new_episode_egress_are_distinct(team):
    p = MatchNavigationPolicy()
    p.decide(observation(team, xy=(-4.6, -1.8)))
    assert p.decide(replace(observation(team, t=.1), match_phase='finished')).mode == 'finished'
    assert p.decide(observation(team, t=.2)).command == Command()
    p.nav.recover_until = 99.  # A stale previous-episode recovery cannot consume the new opening.
    assert p.decide(observation(team, episode=1)).mode == 'opening_egress'


@pytest.mark.parametrize('team', ['red', 'blue'])
def test_recovery_started_by_supply_tick_is_latched_before_next_late_observation(team, monkeypatch):
    p = MatchNavigationPolicy()
    side = 1 if team == 'red' else -1
    xy = (-4.6335, -1.68)
    p.decide(observation(team, xy=xy))
    monkeypatch.setattr(p.nav.grid, 'plan', lambda start, goal: [])
    monkeypatch.setattr(p.nav, '_clearance',
                        lambda o, direction: 8. if side*direction[1] > .99 else 1.)
    for t in (.1, .6, 1.1, 1.6, 2.1):
        assert p.decide(observation(team, t=t, xy=xy, hp=90)).mode == 'supply'
    assert p.nav.metrics.recovery_count == 1
    assert p.nav.last_status == 'recovering'
    assert p.desired_velocity[1] == pytest.approx(.4*side)
    # No additional controller observation until after the recovery deadline.
    # Ownership was transferred when recovery began, not at the next tick.
    assert p.decide(observation(team, t=3., xy=xy)).mode == 'opening_rush'
