"""Authoritative projectile-credit counter, separate from HP telemetry."""
import unittest
from ..competition_judge import MatchJudge
from .protocol import ControlGate,parse_mode_request
from .server import BridgeState
from .test_protocol import Clock

class ProjectileCreditTests(unittest.TestCase):
    def setUp(self):self.j=MatchJudge()
    def hit(self,uid='p0',target='red_infantry',shooter='blue_sentry',when=0.,speed=20.,armor='front'):
        self.assertTrue(self.j.fire(shooter,uid,when))
        return self.j.apply_hit(uid,shooter,target,armor,speed,when,caliber='17mm')
    def test_initial_and_actual_credit(self):
        c=self.j.projectile_damage['red_infantry'];self.assertEqual(c,dict(revision=0,total_damage=0.,last_event_sequence=-1))
        self.assertTrue(self.hit());self.assertEqual(c['revision'],1);self.assertEqual(c['total_damage'],20.)
        event=next(e for e in reversed(self.j.events) if e['type']=='impact')
        self.assertEqual(event['credited_damage'],20.);self.assertEqual(c['last_event_sequence'],event['sequence'])
    def test_fractional_actual_credit_is_preserved(self):
        self.j.robots['red_infantry'].hp=.5
        self.assertTrue(self.hit())
        self.assertEqual(self.j.projectile_damage['red_infantry']['total_damage'],.5)
        self.assertEqual(self.j.projectile_damage['red_infantry']['revision'],1)
    def test_duplicate_does_not_recredit(self):
        self.hit();before=dict(self.j.projectile_damage['red_infantry'])
        self.assertFalse(self.j.apply_hit('p0','blue_sentry','red_infantry','front',20.,0.))
        self.assertEqual(before,self.j.projectile_damage['red_infantry'])
        self.assertEqual(self.j.events[-1]['credited_damage'],0.)
    def test_zero_credit_overkill_does_not_increment(self):
        self.j.robots['red_infantry'].hp=25
        hits=[]
        for i in range(3):
            uid=f'p{i}';self.assertTrue(self.j.fire('blue_sentry',uid,i*.2))
            hits.append(dict(projectile_uid=uid,shooter_id='blue_sentry',target_id='red_infantry',armor_id=f'a{i}',normal_speed=20.,caliber='17mm'))
        self.assertEqual(self.j.apply_hit_batch(hits,.5),[True,True,True])
        c=self.j.projectile_damage['red_infantry'];self.assertEqual(c['revision'],2);self.assertEqual(c['total_damage'],25.)
        impacts=[e for e in self.j.events if e['type']=='impact']
        self.assertEqual([e['credited_damage'] for e in impacts],[20,5,0])
        self.assertEqual(c['last_event_sequence'],impacts[1]['sequence'])
    def test_non_projectile_health_change_does_not_count(self):
        self.j.robots['red_infantry'].hp-=20
        self.assertEqual(self.j.projectile_damage['red_infantry']['revision'],0)
    def test_invalid_impacts_do_not_count(self):
        for target,speed,armor in [('blue_infantry',20.,'front'),('red_infantry',1.,'front'),('red_infantry',20.,None)]:
            self.setUp();self.assertFalse(self.hit(target=target,speed=speed,armor=armor))
            self.assertTrue(all(c['total_damage']==0 for c in self.j.projectile_damage.values()))
    def test_counter_survives_display_event_window(self):
        self.hit()
        for _ in range(30):self.j._event('unrelated')
        self.assertFalse(any(e['type']=='impact' for e in self.j.events[-20:]))
        self.assertEqual(self.j.projectile_damage['red_infantry']['total_damage'],20.)
    def test_episode_reset_and_vehicle_independence(self):
        self.hit();self.assertEqual(self.j.projectile_damage['red_hero']['total_damage'],0.)
        self.j.reset();self.assertEqual(self.j.episode,1)
        self.assertEqual(self.j.projectile_damage['red_infantry'],dict(revision=0,total_damage=0.,last_event_sequence=-1))

class DamageContractTests(unittest.TestCase):
    def test_origin_is_only_an_optional_label(self):
        values=dict(spin_enabled=True,spin_direction='cw',spin_speed_dps=120.,chassis_follow='free')
        self.assertEqual(parse_mode_request(values).spin_origin,'manual')
        self.assertEqual(parse_mode_request(dict(values,spin_origin='on_hit')).spin_origin,'on_hit')
        for bad in ('automatic',None,1):
            with self.assertRaises(ValueError):parse_mode_request(dict(values,spin_origin=bad))
    def test_auto_origin_obeys_same_lease(self):
        clock=Clock();g=ControlGate(wall=clock,monotonic=clock)
        m=dict(session_id=g.session_id,epoch=0,robot_id=g.robot_id,seq=1,sent_at_ms=clock()*1000,
            focus=True,deadman=True,fire=False,vx_mps=0.,vy_mps=0.,yaw_rate_rps=0.,pitch_rate_rps=0.,
            mode_request=dict(spin_enabled=True,spin_direction='cw',spin_speed_dps=120.,chassis_follow='free',spin_origin='on_hit'))
        self.assertTrue(g.accept(m)['accepted']);self.assertEqual(g.active_mode.spin_origin,'on_hit')
        clock.advance(.251);g.sample();self.assertFalse(g.active_mode.spin_enabled);self.assertEqual(g.reason,'control_timeout')
    def test_unavailable_identity_does_not_relabel_damage(self):
        g=ControlGate();s=BridgeState(g);s.publish(dict(session_id=g.session_id,epoch=0,robot_id=g.robot_id,phase='running',own_damage={'total_damage':20.}))
        g.new_epoch();self.assertIsNone(s.snapshot()['own_damage'])
    def test_runtime_reports_selected_own_credit_and_sample_time(self):
        from .runtime import OperatorRuntime
        g=ControlGate();s=BridgeState(g);r=OperatorRuntime(s,render=False)
        try:
            r._operator_command(g.robot_id);r._publish()
            d=s.snapshot()['own_damage'];self.assertEqual(d['total_damage'],0.);self.assertEqual(d['sim_time'],r.sim.time)
            j=r.sim.judge;self.assertTrue(j.fire('blue_sentry','p',0.));self.assertTrue(j.apply_hit('p','blue_sentry',g.robot_id,'front',20.,0.))
            r._publish();d=s.snapshot()['own_damage'];self.assertEqual(d['revision'],1);self.assertEqual(d['total_damage'],20.)
            self.assertEqual(d['robot_id'],g.robot_id);self.assertEqual(d['session_id'],g.session_id)
            self.assertTrue(g.session()['capabilities']['auto_spin_on_hit'])
        finally:r.close()
