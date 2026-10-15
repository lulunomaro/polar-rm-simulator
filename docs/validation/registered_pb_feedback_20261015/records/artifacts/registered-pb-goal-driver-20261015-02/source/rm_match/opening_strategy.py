"""Deterministic start supervisor, independent of slow tactical services.

The immediate center rush is the user's tactic, not an asserted official rule.
All goals are field-centred world metres. This module has no physics/truth/network.
"""
from dataclasses import dataclass
import math
from .contracts import NavigationIntent


@dataclass(frozen=True)
class OpeningDecision:
    mode: str
    intent: NavigationIntent | None
    enabled: bool
    allow_tactical: bool = False


class OpeningRushSupervisor:
    def __init__(self, center=(0., 0.), arrival_radius=1.35):
        if not all(math.isfinite(v) for v in (*center, arrival_radius)) or arrival_radius <= 0:
            raise ValueError('Invalid center/arrival radius')
        self.center=tuple(center)
        self.arrival_radius=arrival_radius
        self.reset(-1)

    def reset(self, episode):
        self.episode=episode
        self.started_at=None
        self.arrived_at=None
        self.terminal_latched=False
        self.events=[]
        self.last_mode=None

    def decide(self, o):
        if o.episode != self.episode:
            self.reset(o.episode)
        phase=getattr(o, 'match_phase', 'unknown')
        if phase in ('finished', 'terminal', 'ended'):
            self.terminal_latched=True
        if self.terminal_latched:
            out=OpeningDecision('finished', None, False)
        elif getattr(o, 'emergency_stop', False):
            out=OpeningDecision('emergency_stop', None, False)
        elif phase != 'running':
            out=OpeningDecision(phase if phase in ('preparing','countdown','paused') else 'unknown_phase',None,False)
        elif o.own_hp <= 0:
            out=OpeningDecision('dead', None, False)
        elif not math.isfinite(o.own_hp) or not math.isfinite(o.sim_time) or o.odom_xyyaw is None or not all(math.isfinite(v) for v in o.odom_xyyaw):
            out=OpeningDecision('invalid_state', None, False)
        elif getattr(o, 'own_weak', False):
            # Newly respawned robots cannot capture; supply recovery has priority.
            out=OpeningDecision('recover_weak', None, True, True)
        else:
            if self.started_at is None:
                self.started_at=o.sim_time
                self.events.append(dict(type='opening_center_intent',episode=o.episode,robot_id=o.robot_id,
                    sim_time=o.sim_time,goal=list(self.center),waited_for_llm=False))
            if self.arrived_at is None and math.dist(o.odom_xyyaw[:2],self.center) <= self.arrival_radius:
                self.arrived_at=o.sim_time
                self.events.append(dict(type='opening_center_arrival',episode=o.episode,robot_id=o.robot_id,
                    sim_time=o.sim_time,arrival_radius_m=self.arrival_radius))
            if self.arrived_at is None:
                out=OpeningDecision('opening_rush',NavigationIntent('INTERCEPT',self.center,
                    'deterministic RUNNING opening: center control; no LLM wait'),True)
            else:
                out=OpeningDecision('occupation',None,True,True)
        if out.mode != self.last_mode:
            self.events.append(dict(type='opening_mode',episode=o.episode,robot_id=o.robot_id,
                sim_time=o.sim_time,mode=out.mode))
            self.last_mode=out.mode
        return out
