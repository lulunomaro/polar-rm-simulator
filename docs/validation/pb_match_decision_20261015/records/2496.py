"""Explicit TEST profile, not RMUC/RMUL 2026 match judging."""
from dataclasses import dataclass, field

@dataclass
class TestJudge:
    __test__ = False
    hp: int = 200
    ammo: int = 100
    damage: int = 10
    events: list = field(default_factory=list)
    resolved: set = field(default_factory=set)
    last_fire: float = -1.

    def can_fire(self, sim_time):
        return self.ammo > 0 and sim_time-self.last_fire >= .15-1e-9

    def fired(self, uid, sim_time):
        if not self.can_fire(sim_time): return False
        self.ammo -= 1
        self.last_fire = sim_time
        self.events.append(dict(type='fire', projectile=uid, sim_time=sim_time))
        return True

    def impact(self, uid, geom, sim_time, position):
        if uid in self.resolved: return False
        self.resolved.add(uid)
        valid = geom == 'target_armor' and self.hp > 0
        if valid: self.hp = max(0, self.hp-self.damage)
        self.events.append(dict(type='impact', projectile=uid, geom=geom,
            sim_time=sim_time, position=list(position), valid_armor=valid, hp=self.hp))
        return valid
