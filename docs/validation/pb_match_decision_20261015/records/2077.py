"""Trusted scenario baseline auto-resupply, never an HTTP or algorithm capability.

Mirrors the procurement request thresholds/cadence in MatchNavigationPolicy.
The unchanged judge alone owns costs, grants and all competition eligibility.
This policy does not move a robot, grant ammunition directly or request fire.
"""
from __future__ import annotations
import copy
import math

class VirtualResupply:
    def __init__(self,policy='disabled'):
        if type(policy) is not str or policy not in ('disabled','v1-baseline'):
            raise ValueError('Unknown virtual-resupply scenario policy')
        self._policy=policy
        self._episode=None
        self._last_attempt={}
        self._attempts=0
        self._purchases=0
        self._last_results={}

    def apply(self,sim,allowed):
        if self._policy=='disabled':return
        if self._episode!=sim.episode:
            self._episode=sim.episode;self._last_attempt.clear()
            self._attempts=self._purchases=0;self._last_results.clear()
        if sim.judge.episode!=sim.episode:return
        now=float(sim.time)
        if not math.isfinite(now) or now<1.:return
        candidates=[]
        for rid in sim.robot_ids:
            r=sim.judge.robots[rid]
            limit={'hero':1,'infantry':10}.get(r.role)
            if (limit is not None and allowed(rid) and r.ammo<=limit
                    and now-self._last_attempt.get(rid,-math.inf)>=1.
                    and rid in sim.judge._supply):
                candidates.append(rid)
        if not candidates:return
        # MatchSimulation updates zones at each physics step. Cached contact can
        # lag by one step, so refresh actual current physical contact before any
        # purchase. An entering robot may wait one tick; a leaving robot cannot
        # buy using stale presence. This remains on the physics authority thread.
        sim._update_zones()
        for rid in candidates:
            if not allowed(rid) or rid not in sim.judge._supply:continue
            r=sim.judge.robots[rid]
            before_ammo=r.ammo;before_coins=sim.judge.coins[r.team]
            self._last_attempt[rid]=now;self._attempts+=1
            accepted=bool(sim.judge.purchase_ammo(rid,bundles=5,episode=sim.episode))
            self._purchases+=int(accepted)
            self._last_results[rid]=dict(episode=sim.episode,sim_time=now,bundles=5,
                accepted=accepted,ammo_before=before_ammo,ammo_after=r.ammo,
                coins_before=before_coins,coins_after=sim.judge.coins[r.team])

    def status(self):
        return dict(policy=self._policy,source='simulation_baseline_automatic_virtual_resupply',
            official_full_rules_qualified=False,configured_via='trusted_startup_only',
            episode=self._episode,attempts=self._attempts,purchases=self._purchases,
            last_results=copy.deepcopy(self._last_results))
