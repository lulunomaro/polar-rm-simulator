from dataclasses import replace
import ast,hashlib,math
from pathlib import Path
import pytest
from rm_match.contracts import Command
from rm_match.opening_strategy import OpeningRushSupervisor
from rm_match.match_controllers import MatchNavigationPolicy
from rm_match.original_decision_adapter import OriginalRuleAdapter,visible_contacts
from test_match_controllers import obs


def sentry(**kwargs):
    return obs(role='sentry',hp=400,ammo=750,**kwargs)


def test_first_running_tick_has_center_intent_without_tactical_call():
    p=MatchNavigationPolicy()
    p.original_rule.decide=lambda _:pytest.fail('Opening waited for tactical service')
    o=sentry(xy=(-2.,-2.))
    d=p.decide(o)
    assert d.mode=='opening_rush'
    assert p.nav.intent.target_point==(0.,0.)
    assert p.opening.started_at==0.
    assert p.original_rule.calls==0
    assert d.command.force_x!=0 or d.command.force_y!=0


@pytest.mark.parametrize('phase',['preparing','countdown','paused','finished','unknown'])
def test_nonrunning_phase_stops_and_clears_route(phase):
    p=MatchNavigationPolicy();p.decide(sentry(xy=(-2.,-2.)))
    d=p.decide(replace(sentry(t=.1),match_phase=phase))
    assert d.command==Command() and d.purchase_bundles==0
    assert p.nav.intent is None and not p.nav.path


@pytest.mark.parametrize('change',[dict(own_hp=0),dict(emergency_stop=True)])
def test_death_and_emergency_stop_override_opening(change):
    p=MatchNavigationPolicy()
    assert p.decide(replace(sentry(),**change)).command==Command()
    assert p.opening.started_at is None


def test_preparation_resume_and_terminal_latch_are_distinct():
    p=OpeningRushSupervisor()
    assert not p.decide(replace(sentry(t=0),match_phase='preparing')).enabled
    assert p.started_at is None
    assert p.decide(sentry(t=1)).intent.target_point==(0.,0.)
    assert not p.decide(replace(sentry(t=2),match_phase='paused')).enabled
    assert p.decide(sentry(t=3)).intent.target_point==(0.,0.)
    assert p.started_at==1
    assert not p.decide(replace(sentry(t=4),match_phase='finished')).enabled
    assert not p.decide(sentry(t=5)).enabled  # stale RUNNING cannot restart terminal
    assert p.decide(sentry(episode=1)).enabled and p.started_at==0


def test_arrival_hands_off_to_original_rule_and_low_hp_recovers():
    p=MatchNavigationPolicy();p.decide(sentry(xy=(-2.,-2.)))
    d=p.decide(sentry(t=2,xy=(-.65,-.65)))
    assert d.mode=='occupation'
    assert p.opening.arrived_at==2
    assert p.original_rule.calls==1
    assert p.original_rule.last_record['source']=='original_rule_decide_offline_rmul_profile'
    assert p.original_rule.last_record['llm_called'] is False
    assert not p.original_rule.last_record['input']['enemies']
    d=p.decide(replace(sentry(t=3,xy=(-.65,-.65)),own_hp=90))
    assert d.mode=='supply' and p.nav.intent.behavior=='RETREAT'


def test_upstream_function_is_exact_original_not_similar_reimplementation():
    from rm_match import upstream_rule
    root=Path(__file__).resolve().parents[1]
    original=(root/'upstream_reference/sentry_decide_server.py').read_text(encoding='utf-8')
    copied=Path(upstream_rule.__file__).read_text(encoding='utf-8')
    def fn(s):
        return ast.get_source_segment(s,next(n for n in ast.parse(s).body if isinstance(n,ast.FunctionDef) and n.name=='rule_decide'))
    assert fn(original)==fn(copied)
    # The imported integration cannot call HTTP, inspect credentials or import an LLM.
    assert all(n.name not in ('llm_chat','Handler') for n in ast.parse(copied).body if isinstance(n,(ast.FunctionDef,ast.ClassDef)))


def test_original_rule_receives_only_own_feedback_and_pixels():
    p=OriginalRuleAdapter();o=replace(sentry(xy=(0.,0.)),own_hp=100)
    assert p.decide(o)['behavior']=='RETREAT'
    assert p.last_record['input']['allies']==[]
    assert p.last_record['input']['enemies']==[]
    assert visible_contacts(o)==[]


def test_engine_clears_cached_motion_during_phase_and_emergency_gates():
    from rm_match.match_engine import MatchSimulation
    s=MatchSimulation(render=False)
    try:
        s.step({'red_sentry':Command(force_y=-20,fire=True)})
        s.set_phase('paused');t=s.time
        s.step({'red_sentry':Command(force_y=-50,fire=True)})
        assert s.time==t and not any(s.data.ctrl)
        assert s.commands['red_sentry']==Command()
        s.set_phase('running')
        assert s.observe('red_sentry',False).match_phase=='running'
        s.emergency_stop=True;s.step({'red_sentry':Command(force_y=-50)})
        assert s.time==t and not any(s.data.ctrl)
    finally:s.close()


def test_opening_cannot_force_through_obstacle_or_override_stuck_recovery():
    p=MatchNavigationPolicy()
    # Anonymous nearest surfaces all around the body, with no enemy identities.
    o=replace(sentry(xy=(-2.,-2.)),ranges=(.38,)*64)
    for t in (0.,.5,1.,1.5,2.,2.5,3.):
        d=p.decide(replace(o,sim_time=t))
        assert d.command.force_x==0 and d.command.force_y==0
        assert p.nav.intent.target_point==(0.,0.)
        assert p.original_rule.calls==0
    assert p.metrics.recovery_count==0
    assert p.nav.last_status=='blocked_no_safe_escape'


def test_occupied_center_is_not_declared_arrived():
    p=MatchNavigationPolicy()
    # Ray endpoint at center inflates and blocks the requested goal.
    o=replace(sentry(xy=(-2.,0.)),ranges=(2.,),range_angles=(0.,))
    d=p.decide(o)
    assert p.nav.last_status=='blocked'
    assert d.command==Command()
    assert p.opening.arrived_at is None


def test_egress_blocking_and_missing_scan_keep_zero_force():
    p=MatchNavigationPolicy()
    for ranges in ((),(.2,)*64):
        o=replace(sentry(),ranges=ranges,range_angles=() if not ranges else sentry().range_angles)
        d=p.decide(o)
        assert d.command.force_x==0 and d.command.force_y==0
        assert p.nav.intent.target_point==(0.,0.)
