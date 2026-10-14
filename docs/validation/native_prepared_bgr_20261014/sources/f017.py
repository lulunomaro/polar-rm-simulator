"""Deterministic RMUL 2026 V1.2.0 verified-subset judge.

NOT full competition conformance, NOT complete 2027 rules. Numeric provenance:
https://bbs.robomaster.com/wiki/20204847/809872, printed pages 16-20, 28-36.
No wall-clock, middleware, hardware, network or MuJoCo dependency.

Simulator policies (not official): actions at the 300s boundary are excluded;
control drains on global integer-second boundaries; equal-time first arrivals
use robot ID ordering; friendly fire is rejected; damage credit is HP actually
removed; simultaneous zero VP is an unresolved result. Use apply_hit_batch for
simultaneous impacts. 42mm debounce uses a conservative 0.2s test policy because
the official text only specifies a variable interval up to 0.2s.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable
import math

SOURCE = 'https://bbs.robomaster.com/wiki/20204847/809872'
MANIFEST = {
    'schema_version': 1, 'preset': 'rmul2026-v1.2.0-verified-subset',
    'full_competition_conformance': False, 'source': SOURCE,
    'implemented': {
        'UL-DURATION': [16], 'UL-ROSTER-ATTRIBUTES': [16,17,18,19,20],
        'UL-ARMOR-DAMAGE': [28,29], 'UL-HEAT-COOLING': [29,30],
        'UL-MUZZLE-SPEED-LOCK': [29], 'UL-SUPPLY-RESPAWN': [34],
        'UL-COINS-AMMO': [34,35], 'UL-HERO-DEAD-SHIELD': [35],
        'UL-CONTROL-VP': [35], 'UL-WIN-ORDER': [35,36],
    },
    'unimplemented': ['chassis power and capacitor enforcement',
        'module offline penalties', 'referee cards and manual penalties',
        'RFID geometry certification', 'physical projectile sensor calibration',
        'illegal firing detection (commands are safely gated instead)',
        '2027 complete numeric robot attributes and complete rulebook',
        'RMUC 7v7 base/outpost/economy and victory rules'],
    'explicit_simulator_policies': [
        'global integer-second control drain and respawn accounting',
        '100ms supply healing integration', '300s actions excluded',
        'equal-time control arrivals resolved by robot ID',
        'friendly fire rejected pending authoritative interpretation',
        'attack damage credited as actual HP removed',
        '42mm per-armor debounce 0.2s conservative test policy',
        'simultaneous zero VP unresolved, no invented official winner',
        'heat Q2 equality rejects shot pending text/diagram reconciliation'],
}

@dataclass
class RobotState:
    robot_id: str
    team: str
    role: str
    max_hp: float
    heat_max: float
    cooling_per_s: float
    muzzle_speed_limit: float
    caliber: str
    ammo: int
    hp: float = 0
    heat: float = 0
    deaths: int = 0
    weak: bool = False
    invulnerable_until: float = 0
    respawn_at: float | None = None
    death_time: float | None = None
    heat_locked: bool = False
    permanent_heat_lock: bool = False
    speed_locked_until: float = 0

    @property
    def alive(self):
        return self.hp > 0


class MatchJudge:
    """Standalone match state. All public event times are simulation seconds.

    Presence sets represent verified RFID contact, not guessed zone geometry.
    ``episode`` is optional for local calls but external adapters MUST pass it.
    The projectile ID must identify one physical projectile, not one contact.
    """
    duration_s = 300.0

    def __init__(self, *, episode=0, require_full_conformance=False,
                 infantry_hp_profile='power', infantry_heat_profile='burst'):
        if require_full_conformance:
            raise ValueError('Full competition conformance unavailable; inspect MANIFEST')
        if infantry_hp_profile not in ('power','hp') or infantry_heat_profile not in ('burst','cooling'):
            raise ValueError('Unknown official infantry attribute profile')
        self._profiles = (infantry_hp_profile, infantry_heat_profile)
        self.episode = episode
        self.sim_time = 0.0
        self.paused = False
        self.terminal = False
        self.winner = None
        self.terminal_reason = None
        self.vp = {'red': 200, 'blue': 200}
        self.coins = {'red': 0, 'blue': 0}
        self.attack_damage = {'red': 0.0, 'blue': 0.0}
        self.robots = {}
        for team in ('red','blue'):
            for role in ('hero','infantry','sentry'):
                values = {'hero':(350,200,24,12,'42mm',0),
                          'sentry':(400,260,30,25,'17mm',750),
                          'infantry':(300 if infantry_hp_profile=='power' else 350,
                                      230 if infantry_heat_profile=='burst' else 88,
                                      14 if infantry_heat_profile=='burst' else 24,25,'17mm',0)}[role]
                rid = f'{team}_{role}'
                self.robots[rid] = RobotState(rid,team,role,*values,hp=values[0])
        self.projectile_damage = {
            rid:dict(revision=0,total_damage=0.,last_event_sequence=-1)
            for rid in self.robots}
        self.events = []
        self.commands = []
        self._shots = {}
        self._resolved = set()
        self._last_armor_hit = {}
        self._control = set()
        self._supply = set()
        self._arrival = {}
        self._loss_at = {}
        self.control_owner = None
        self._clock_tick = 0
        self._catchup_awards = {'red':set(), 'blue':set()}
        self._hero_shield = {'red':False, 'blue':False}
        self._event('reset')

    def _event(self, kind, **data):
        self.events.append(dict(sequence=len(self.events), episode=self.episode,
                                sim_time=round(self.sim_time,9), type=kind, **data))

    def _command(self, method, **kwargs):
        self.commands.append({'method':method, 'kwargs':kwargs})

    def _eligible(self, episode):
        return (episode is None or episode == self.episode) and not self.terminal and not self.paused

    def pause(self, paused=True):
        self._command('pause', paused=paused)
        self.paused = bool(paused)
        self._event('pause', paused=self.paused)

    def reset(self, *, episode=None):
        new_episode = self.episode+1 if episode is None else episode
        if new_episode == self.episode:
            raise ValueError('Reset requires a new episode ID')
        self.__init__(episode=new_episode, infantry_hp_profile=self._profiles[0],
                      infantry_heat_profile=self._profiles[1])

    def tick(self, sim_time, *, episode=None):
        self._command('tick', sim_time=sim_time, episode=episode)
        if episode is not None and episode != self.episode:
            return False
        if not math.isfinite(sim_time) or sim_time < self.sim_time-1e-9:
            raise ValueError('Simulation time must be finite and nondecreasing')
        if self.paused or self.terminal:
            return False
        target = min(float(sim_time), self.duration_s)
        # Fixed referee sampling, independent of physics timestep and rendering.
        while (self._clock_tick+1)/10 <= target+1e-9 and not self.terminal:
            self._clock_tick += 1
            self.sim_time = self._clock_tick/10
            self._sample()
        if not self.terminal:
            self.sim_time = target
        return True

    def _sample(self):
        t = self.sim_time
        for r in self.robots.values():
            r.heat = max(0.0, r.heat-r.cooling_per_s/10)
            if r.heat < 1e-8:
                r.heat = 0.0
                r.heat_locked = False
            if not r.alive and r.respawn_at is not None and t+1e-9 >= r.respawn_at:
                r.hp = r.max_hp*.2
                r.weak = True
                r.invulnerable_until = t+30
                r.respawn_at = None
                self._event('respawn', robot_id=r.robot_id, hp=r.hp, weak=True)
            if r.alive and r.robot_id in self._supply:
                if r.weak or r.invulnerable_until > t:
                    self._event('supply_clears_weakness', robot_id=r.robot_id)
                r.weak = False
                r.invulnerable_until = 0
                r.hp = min(r.max_hp, r.hp+r.max_hp*.25/10)
        self._update_hero_shields()
        self._refresh_owner()
        if self._clock_tick % 10 == 0:
            if int(t) in (1,61,121,181,241):
                amount = 200 if t < 181 else 300
                for team in self.coins:
                    self.coins[team] += amount
                self._event('coins_periodic', amount=amount)
            if self.control_owner:
                enemy = self._enemy(self.control_owner)
                self.vp[enemy] = max(0,self.vp[enemy]-1)
                self._event('control_drain', owner=self.control_owner, team=enemy, vp=self.vp[enemy])
        self._catchup()
        self._check_terminal()

    @staticmethod
    def _enemy(team):
        return 'blue' if team=='red' else 'red'

    def update_zone_presence(self, control: Iterable[str]=(), supply: Iterable[str]=(), *, episode=None):
        control, supply = sorted(set(control)), sorted(set(supply))
        self._command('update_zone_presence', control=control, supply=supply, episode=episode)
        if not self._eligible(episode):
            return False
        if not (set(control)|set(supply)) <= self.robots.keys():
            raise ValueError('Unknown robot in RFID presence')
        now = set(control)
        for rid in now-self._control:
            # Preserve first arrival if RFID reconnects inside the two-second grace.
            if rid not in self._arrival:
                self._arrival[rid] = self.sim_time
            self._loss_at.pop(rid,None)
        for rid in self._control-now:
            self._loss_at[rid] = self.sim_time+2
        self._control, self._supply = now, set(supply)
        for rid in self._supply:
            r = self.robots[rid]
            if r.alive:
                r.weak = False
                r.invulnerable_until = 0
        self._refresh_owner()
        self._event('presence', control=control, supply=supply)
        return True

    def _refresh_owner(self):
        for rid in list(self._arrival):
            if not self.robots[rid].alive or self.robots[rid].weak or (
                    rid not in self._control and self.sim_time+1e-9 >= self._loss_at.get(rid,0)):
                self._arrival.pop(rid,None)
                self._loss_at.pop(rid,None)
        # A weak robot already on the zone becomes eligible only once weakness clears.
        for rid in sorted(self._control):
            r = self.robots[rid]
            if r.alive and not r.weak and rid not in self._arrival:
                self._arrival[rid] = self.sim_time
        candidates = sorted(self._arrival, key=lambda rid:(self._arrival[rid],rid))
        owner = self.robots[candidates[0]].team if candidates else None
        if owner != self.control_owner:
            self.control_owner = owner
            self._event('control_owner', owner=owner)

    def purchase_ammo(self, robot_id, bundles=1, *, episode=None):
        self._command('purchase_ammo', robot_id=robot_id, bundles=bundles, episode=episode)
        if not self._eligible(episode):
            return False
        r = self.robots[robot_id]
        if not isinstance(bundles,int) or isinstance(bundles,bool) or bundles<=0:
            raise ValueError('Bundles must be a positive integer')
        if r.role=='sentry' or not r.alive or robot_id not in self._supply or self.coins[r.team]<10*bundles:
            return False
        self.coins[r.team] -= 10*bundles
        r.ammo += bundles*(1 if r.caliber=='42mm' else 10)
        self._update_hero_shields()
        self._event('ammo_purchase', robot_id=robot_id, bundles=bundles, ammo=r.ammo)
        return True

    def can_fire(self, robot_id):
        r = self.robots[robot_id]
        return bool(self._eligible(None) and r.alive and not r.weak and r.ammo>0
                    and not r.heat_locked and not r.permanent_heat_lock
                    and self.sim_time >= r.speed_locked_until)

    def fire(self, robot_id, projectile_uid, sim_time, muzzle_speed=None, *, episode=None):
        self._command('fire', robot_id=robot_id, projectile_uid=projectile_uid,
                      sim_time=sim_time, muzzle_speed=muzzle_speed, episode=episode)
        if not self._eligible(episode):
            return False
        self.tick(sim_time, episode=episode)
        if not self.can_fire(robot_id) or projectile_uid in self._shots or projectile_uid in self._resolved:
            return False
        r = self.robots[robot_id]
        if muzzle_speed is not None and (not math.isfinite(muzzle_speed) or muzzle_speed<0):
            raise ValueError('Muzzle speed must be finite and nonnegative')
        increment = 100 if r.caliber=='42mm' else 10
        q2 = r.heat_max+(200 if r.caliber=='42mm' else 100)
        if abs(r.heat+increment-q2)<1e-8:
            self._event('unsupported_heat_equality', robot_id=robot_id)
            return False
        r.ammo -= 1
        r.heat += increment
        r.heat_locked = r.heat > r.heat_max
        r.permanent_heat_lock = r.heat > q2
        if muzzle_speed is not None and muzzle_speed > r.muzzle_speed_limit:
            delta = muzzle_speed-r.muzzle_speed_limit
            if r.caliber=='17mm':
                seconds = 15 if delta<5 else 20 if delta<10 else self.duration_s+1
            else:
                ratio = muzzle_speed/r.muzzle_speed_limit
                seconds = 15 if ratio<=1.1 else 20 if ratio<=1.2 else self.duration_s+1
            r.speed_locked_until = self.sim_time+seconds
        self._shots[projectile_uid] = dict(shooter_id=robot_id, caliber=r.caliber, episode=self.episode)
        self._event('fire', projectile_uid=projectile_uid, robot_id=robot_id, caliber=r.caliber, ammo=r.ammo, heat=r.heat)
        return True

    def apply_hit(self, projectile_uid, shooter_id, target_id, armor_id, normal_speed,
                  sim_time, caliber='17mm', *, episode=None):
        return self.apply_hit_batch([dict(projectile_uid=projectile_uid, shooter_id=shooter_id,
            target_id=target_id, armor_id=armor_id, normal_speed=normal_speed, caliber=caliber)],
            sim_time, episode=episode)[0]

    def apply_hit_batch(self, hits, sim_time, *, episode=None):
        """Commit simultaneous impacts using pre-batch life eligibility.

        Input order must not determine winner; damage/deaths commit after all hits.
        armor_id must be a nonempty string for real armor, None for body/terrain.
        Unregistered or stale projectiles cannot score.
        """
        hits = [dict(h) for h in hits]
        self._command('apply_hit_batch', hits=hits, sim_time=sim_time, episode=episode)
        if not self._eligible(episode):
            return [False]*len(hits)
        self.tick(sim_time, episode=episode)
        if not self._eligible(episode):
            return [False]*len(hits)
        alive_before = {rid:r.alive for rid,r in self.robots.items()}
        pending = {}
        results = [False]*len(hits)
        for index,h in sorted(enumerate(hits),key=lambda pair:str(pair[1]['projectile_uid'])):
            uid = h['projectile_uid']
            shooter, target = h['shooter_id'], h['target_id']
            caliber = h.get('caliber','17mm')
            reason = None
            credited = 0.
            shot = self._shots.get(uid)
            if uid in self._resolved:
                reason = 'duplicate_projectile'
            elif shot is None or shot != dict(shooter_id=shooter, caliber=caliber, episode=self.episode):
                reason = 'unregistered_or_mismatched_projectile'
            else:
                self._resolved.add(uid)
                if target not in self.robots or not h.get('armor_id'):
                    reason = 'non_armor_contact'
                elif not alive_before[target]:
                    reason = 'dead_target'
                elif self.robots[shooter].team == self.robots[target].team:
                    reason = 'friendly_fire_simulator_policy'
                elif self.robots[target].invulnerable_until > self.sim_time:
                    reason = 'invulnerable_target'
                elif not math.isfinite(h['normal_speed']) or h['normal_speed'] <= (10 if caliber=='42mm' else 12):
                    reason = 'normal_speed_below_strict_threshold'
                elif caliber=='42mm' and self._hero_shielded(self.robots[shooter].team):
                    reason = 'hero_dead_42mm_shield'
                else:
                    key = (target,h['armor_id'],caliber)
                    interval = .2 if caliber=='42mm' else .05
                    if self.sim_time-self._last_armor_hit.get(key,-math.inf)<interval-1e-9:
                        reason = 'armor_debounce'
                    else:
                        self._last_armor_hit[key] = self.sim_time
                        damage = 200 if caliber=='42mm' else 20
                        remaining = max(0,self.robots[target].hp-sum(d for _,d in pending.get(target,[])))
                        credited = min(remaining,damage)
                        pending.setdefault(target,[]).append((self.robots[shooter].team,credited))
                        results[index] = True
            self._event('impact', projectile_uid=uid, shooter_id=shooter,target_id=target,
                        armor_id=h.get('armor_id'), geometric_armor_contact=bool(h.get('armor_id')),
                        valid_damage=results[index], credited_damage=credited, reason=reason)
            if credited > 0:
                counter=self.projectile_damage[target]
                counter['revision'] += 1
                counter['total_damage'] += credited
                counter['last_event_sequence'] = self.events[-1]['sequence']
        for target, damages in sorted(pending.items()):
            r = self.robots[target]
            r.hp = max(0,r.hp-sum(d for _,d in damages))
            for team,damage in damages:
                self.attack_damage[team] += damage
            if not r.alive:
                self._death(r)
        self._refresh_owner()
        self._catchup()
        self._check_terminal()
        return results

    def _update_hero_shields(self):
        for team in self._hero_shield:
            hero = self.robots[f'{team}_hero']
            if hero.alive and hero.ammo > 0:
                self._hero_shield[team] = False
            elif not hero.alive and hero.death_time is not None and self.sim_time >= hero.death_time+3:
                self._hero_shield[team] = True

    def _hero_shielded(self, attacking_team):
        self._update_hero_shields()
        return self._hero_shield[attacking_team]

    def _death(self,r):
        r.deaths += 1
        r.death_time = self.sim_time
        r.respawn_at = self.sim_time+5*r.deaths
        r.heat = 0
        r.heat_locked = False
        self.vp[r.team] = max(0,self.vp[r.team]-20)
        self._event('death', robot_id=r.robot_id, respawn_at=r.respawn_at, vp=self.vp[r.team])

    def _catchup(self):
        for team in ('red','blue'):
            gap = self.vp[self._enemy(team)]-self.vp[team]
            for threshold in (70,140):
                if gap>=threshold and threshold not in self._catchup_awards[team]:
                    self._catchup_awards[team].add(threshold)
                    self.coins[team] += 200
                    self._event('coins_catchup', team=team, threshold=threshold, amount=200)

    def _check_terminal(self):
        if self.terminal:
            return
        zero = [team for team in self.vp if self.vp[team]<=0]
        if zero:
            self.terminal = True
            self.winner = self._enemy(zero[0]) if len(zero)==1 else None
            self.terminal_reason = 'vp_zero' if len(zero)==1 else 'unresolved_simultaneous_zero_vp'
        elif self.sim_time>=self.duration_s:
            hp = {team:sum(r.hp for r in self.robots.values() if r.team==team) for team in self.vp}
            self.terminal = True
            for reason,values in [('time_vp',self.vp),('time_attack_damage',self.attack_damage),('time_remaining_hp',hp)]:
                if values['red'] != values['blue']:
                    self.winner = max(values,key=values.get)
                    self.terminal_reason = reason
                    break
            else:
                self.terminal_reason = 'draw'
        if self.terminal:
            self._event('match_end', winner=self.winner, reason=self.terminal_reason)

    def metrics(self):
        """Auditable outcomes, deliberately no invented aggregate match score."""
        impacts = [e for e in self.events if e['type']=='impact']
        return {
            'shots_fired': sum(e['type']=='fire' for e in self.events),
            'contact_reports': len(impacts),
            'geometric_armor_contacts': sum(e['geometric_armor_contact'] for e in impacts),
            'valid_damage_hits': sum(e['valid_damage'] for e in impacts),
            'deaths': {rid:r.deaths for rid,r in self.robots.items()},
            'team_attack_damage': dict(self.attack_damage),
            'victory_points': dict(self.vp),
            'simulation_duration_s': self.sim_time,
            'winner': self.winner, 'terminal_reason': self.terminal_reason,
            'full_competition_conformance': False,
        }

    def snapshot(self):
        return dict(episode=self.episode, sim_time=self.sim_time, paused=self.paused,
                    terminal=self.terminal, winner=self.winner, terminal_reason=self.terminal_reason,
                    vp=dict(self.vp), coins=dict(self.coins), attack_damage=dict(self.attack_damage),
                    control_owner=self.control_owner,
                    robots={rid:dict(asdict(r),alive=r.alive,can_fire=self.can_fire(rid)) for rid,r in self.robots.items()},
                    manifest=MANIFEST)

    def export_replay(self):
        return dict(version=1, episode=self.episode, profiles=list(self._profiles), commands=list(self.commands))

    @classmethod
    def replay(cls, recording):
        judge = cls(episode=recording['episode'], infantry_hp_profile=recording['profiles'][0],
                    infantry_heat_profile=recording['profiles'][1])
        # Internal tick commands are included too; repeated same-time ticks are idempotent.
        for command in recording['commands']:
            getattr(judge,command['method'])(**command['kwargs'])
        return judge
