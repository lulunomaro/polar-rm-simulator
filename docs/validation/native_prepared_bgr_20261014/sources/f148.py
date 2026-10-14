"""CPU fixtures may set isolated judge balances/HP; real qualification never does."""
import unittest
from types import SimpleNamespace
import numpy as np
from ..competition_judge import MatchJudge
from ..match_engine import MatchSimulation
from .resupply import VirtualResupply

class FakeSim:
    _update_zones=MatchSimulation._update_zones
    def __init__(self):
        self.episode=0;self.judge=MatchJudge(episode=0);self.time=0.
        self.robot_ids=tuple(self.judge.robots)
        self.teams={r:self.judge.robots[r].team for r in self.robot_ids}
        self.body_ids={r:i for i,r in enumerate(self.robot_ids)}
        self.data=SimpleNamespace(xpos=np.zeros((len(self.robot_ids),3)))
        self.phase='running';self.paused=False;self.emergency_stop=False
        self.place('red_infantry',-5.25,3.);self._update_zones()
    def place(self,r,x,y):self.data.xpos[self.body_ids[r],:2]=(x,y)
    def advance(self,t):self.time=t;self.judge.tick(t,episode=self.episode)
    def allowed(self,r):
        return self.phase=='running' and not self.paused and not self.emergency_stop and not self.judge.terminal and self.judge.robots[r].alive

class ResupplyTests(unittest.TestCase):
    def setUp(self):self.s=FakeSim();self.p=VirtualResupply('v1-baseline');self.s.advance(1.)
    def apply(self):self.p.apply(self.s,self.s.allowed)
    def test_disabled_default_and_invalid_policy(self):
        VirtualResupply().apply(self.s,self.s.allowed)
        self.assertEqual(self.s.judge.robots['red_infantry'].ammo,0)
        for x in (True,None,'v2',{},0):
            with self.assertRaises(ValueError):VirtualResupply(x)
    def test_infantry_cost_and_grant_from_existing_judge(self):
        self.apply();r=self.s.judge.robots['red_infantry']
        self.assertEqual((r.ammo,self.s.judge.coins['red']),(50,150))
        self.assertEqual(self.s.judge.events[-1]['type'],'ammo_purchase')
        self.assertEqual(self.p.status()['last_results']['red_infantry']['coins_before'],200)
    def test_hero_five_rounds_same_cost_and_sentry_unchanged(self):
        self.s.place('red_infantry',0,0);self.s.place('red_hero',-5.25,3.)
        self.s.place('red_sentry',-5.5,3.);self.s._update_zones();self.apply()
        self.assertEqual(self.s.judge.robots['red_hero'].ammo,5)
        self.assertEqual(self.s.judge.robots['red_sentry'].ammo,750)
        self.assertEqual(self.s.judge.coins['red'],150)
    def test_insufficient_balance_does_not_grant_or_spam(self):
        self.s.judge.coins['red']=49;self.apply()
        for _ in range(100):self.apply()
        self.assertEqual(self.p.status()['attempts'],1)
        self.assertEqual(self.p.status()['purchases'],0)
        self.assertEqual(self.s.judge.coins['red'],49)
        self.assertEqual(self.s.judge.robots['red_infantry'].ammo,0)
        self.s.advance(1.999);self.apply();self.assertEqual(self.p.status()['attempts'],1)
        self.s.advance(2.);self.apply();self.assertEqual(self.p.status()['attempts'],2)
    def test_boundary_outside_rejects_stale_contact(self):
        for x,y in [(-4.5+1e-8,3),(-6-1e-8,3),(-5.25,2-1e-8),(-5.25,4+1e-8)]:
            with self.subTest(x=x,y=y):
                self.s=FakeSim();self.s.advance(1.);self.p=VirtualResupply('v1-baseline')
                self.s.place('red_infantry',x,y)  # Deliberately leave old contact set.
                self.apply();self.assertEqual(self.s.judge.robots['red_infantry'].ammo,0)
                self.assertEqual(self.s.judge.coins['red'],200)
                self.assertEqual(self.p.status()['attempts'],0)
    def test_exact_boundary_uses_unchanged_physical_zone(self):
        self.s.place('red_infantry',-4.5,2.);self.apply()
        self.assertEqual(self.s.judge.robots['red_infantry'].ammo,50)
    def test_dead_pause_finished_emergency_gates(self):
        for gate in ('dead','paused','phase','terminal','emergency'):
            with self.subTest(gate=gate):
                self.s=FakeSim();self.s.advance(1.);self.p=VirtualResupply('v1-baseline')
                if gate=='dead':self.s.judge.robots['red_infantry'].hp=0
                if gate=='paused':self.s.paused=True
                if gate=='phase':self.s.phase='finished'
                if gate=='terminal':self.s.judge.terminal=True
                if gate=='emergency':self.s.emergency_stop=True
                self.apply();self.assertEqual(self.s.judge.robots['red_infantry'].ammo,0)
                self.assertEqual(self.p.status()['attempts'],0)
    def test_old_judge_episode_rejected_then_new_episode_resets_cadence(self):
        self.apply();self.s.episode=1;self.s.judge.robots['red_infantry'].ammo=0
        self.s.advance(1.2);self.apply();self.assertEqual(self.p.status()['attempts'],0)
        self.assertEqual(self.s.judge.robots['red_infantry'].ammo,0)
        self.s.judge=MatchJudge(episode=1);self.s._update_zones();self.s.advance(1.2);self.apply()
        self.assertEqual(self.p.status()['attempts'],1);self.assertEqual(self.s.judge.robots['red_infantry'].ammo,50)
    def test_low_ammo_threshold_and_one_second_cadence(self):
        r=self.s.judge.robots['red_infantry'];r.ammo=11;self.apply()
        self.assertEqual(self.p.status()['attempts'],0)
        r.ammo=10;self.apply();self.assertEqual(r.ammo,60)
        r.ammo=0;self.s.advance(1.5);self.apply();self.assertEqual(r.ammo,0)
        self.s.advance(2.);self.apply();self.assertEqual(r.ammo,50)
    def test_no_procurement_before_one_second(self):
        self.s=FakeSim();self.s.advance(.999999);self.apply()
        self.assertEqual(self.p.status()['attempts'],0)
        self.s.advance(1.);self.apply();self.assertEqual(self.p.status()['purchases'],1)
    def test_judge_pause_and_insufficient_coins_are_final_authority(self):
        self.s.judge.pause();self.apply()
        self.assertEqual(self.p.status()['purchases'],0)
        self.assertEqual(self.s.judge.robots['red_infantry'].ammo,0)
    def test_status_is_copy_and_attempt_state_bounded_by_registry(self):
        self.apply();s=self.p.status();s['last_results']['red_infantry']['ammo_after']=9999
        self.assertEqual(self.p.status()['last_results']['red_infantry']['ammo_after'],50)
        self.assertLessEqual(len(self.p.status()['last_results']),len(self.s.robot_ids))
        self.assertFalse(s['official_full_rules_qualified'])

if __name__=='__main__':unittest.main()
