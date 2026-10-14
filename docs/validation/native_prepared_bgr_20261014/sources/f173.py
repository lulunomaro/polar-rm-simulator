"""Full-match UID audit. No target state is exposed to actor inputs."""
import gzip,json
import numpy as np
from ..match_engine import MatchSimulation
from ..competition_judge import MatchJudge

class AuditedJudge(MatchJudge):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.damage_by_uid={}
    def apply_hit_batch(self,hits,sim_time,*,episode=None):
        hits=[dict(h) for h in hits];self.tick(sim_time,episode=episode)
        before={r:s.hp for r,s in self.robots.items()}
        results=super().apply_hit_batch(hits,sim_time,episode=episode)
        for i,h in sorted(enumerate(hits),key=lambda pair:str(pair[1]['projectile_uid'])):
            credit=0.
            if results[i]:
                target=h['target_id'];credit=min(before[target],200 if h.get('caliber','17mm')=='42mm' else 20);before[target]-=credit
            uid=h['projectile_uid']
            if results[i] or uid not in self.damage_by_uid:self.damage_by_uid[uid]=credit
        return results

class AuditedMatchSimulation(MatchSimulation):
    physics_hz=2000;step_ns=500000
    @property
    def time(self):return self.physics_step/self.physics_hz
    def reset(self):
        self.physics_step=0;super().reset()
        self.judge=AuditedJudge(episode=self.episode);self._update_zones()
        self.launches=[];self.resolutions=[];self.fire_context={};self.trajectory_file=None
    def _fire(self,rid):
        before=len(self.projectiles);super()._fire(rid)
        if len(self.projectiles)>before:
            p=self.projectiles[-1]
            self.launches.append(dict(uid=p.uid,owner=rid,caliber=p.caliber,launch_ns=self.physics_step*self.step_ns,
                time_s=self.time,position=p.position.tolist(),velocity=p.velocity.tolist(),
                transport_event=self.fire_context.get(rid,{}).get('active_event'),
                feeder_interval_s=1. if self.roles[rid]=='hero' else 1/6))
            self._sample(p,'launch',self.time)
    def _sample(self,p,kind,t,position=None):
        if self.trajectory_file:
            self.trajectory_file.write(json.dumps(dict(uid=p.uid,owner=p.owner,time_s=t,kind=kind,
                position=(p.position if position is None else position).tolist(),velocity=p.velocity.tolist()),separators=(',',':'))+'\n')
    def step(self,commands=None):
        if self.paused or self.judge.terminal or self.phase!='running' or self.emergency_stop:
            return super().step(commands)
        # Base uses self.time after mj_step; advance integer clock exactly there.
        return super().step(commands)
    def _advance_projectiles(self,before,rot0,dt):
        self.physics_step+=1
        if abs(self.data.time-self.time)>1e-7:raise ValueError('Physics clock drift')
        prior={p.uid:p for p in self.projectiles};n=len(self.contact_events)
        super()._advance_projectiles(before,rot0,dt)
        current={p.uid for p in self.projectiles};contacts={c['projectile']:c for c in self.contact_events[n:]}
        for p in self.projectiles:self._sample(p,'step',self.time)
        for uid in sorted(prior.keys()-current):
            p=prior[uid];c=contacts.get(uid);when=c['sim_time'] if c else self.time
            point=np.array(c['position']) if c else p.position
            self._sample(p,'contact' if c else 'expired_or_out_of_bounds',when,point)
            self.resolutions.append(dict(uid=uid,owner=p.owner,time_s=when,kind='contact' if c else 'expired_or_out_of_bounds',
                geometric_armor_contact=bool(c and '__armor_' in c['geom']),
                judge_valid_damage=bool(c and c['damage_applied']),hp_removed=self.judge.damage_by_uid.get(uid,0.),geom=c['geom'] if c else None))
    def terminal_uid_audit(self):
        # Match ends immediately: bullets still in flight are censored, not misses.
        launched={x['uid'] for x in self.launches};resolved={x['uid'] for x in self.resolutions};active={p.uid for p in self.projectiles}
        if len(launched)!=len(self.launches) or len(resolved)!=len(self.resolutions) or resolved&active or launched!=resolved|active:
            raise AssertionError('UID partition failure')
        damage={team:sum(x['hp_removed'] for x in self.resolutions if self.teams[x['owner']]==team) for team in ('red','blue')}
        if any(abs(damage[t]-self.judge.attack_damage[t])>1e-7 for t in damage):raise AssertionError('UID damage differs from judge')
        return dict(passed=True,launched=len(launched),resolved=len(resolved),active_censored_at_end=sorted(active),
            hp_removed_by_team=damage,judge_attack_damage=self.judge.attack_damage,terminal_censoring='Unresolved at match cutoff; never scored as misses')
