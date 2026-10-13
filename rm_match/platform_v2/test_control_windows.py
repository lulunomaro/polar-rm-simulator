"""Server-monotonic manual windows, deterministic clocks; no synchronized host clocks."""
import unittest
from .control import ControlPlane,Rejected
from .test_control import Clock

class WindowTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.p=ControlPlane(['a','b'],clock=self.clock)
        self.s=self.p.open_session('operator','server_window_v1');self.t=self.s['token']
        self.e=self.p.claim(self.t,'a',['motion','gimbal','fire'])['lease_epochs']
    def window(self):return self.p.control_window(self.t,'a',self.e)
    def send(self,w,seq=0,channel='fire',value=None):
        return self.p.control(self.t,'a',channel,self.e[channel],seq,value or {'fire':True},.25,w['window_id'])
    def test_original_deadline_survives_renew_and_new_window(self):
        w=self.window();self.clock.advance(.1);ack=self.send(w);self.assertEqual(ack['input_expires'],w['expires_wall'])
        self.p.renew(self.t,'a',self.e);self.window();self.assertEqual(self.p.snapshot()['leases']['a']['fire']['input_expires'],w['expires_wall'])
        self.clock.advance(.05);self.assertIsNone(self.p.snapshot()['leases']['a']['fire']['input'])
    def test_delayed_packet_and_exact_boundary_rejected(self):
        w=self.window();self.clock.now=w['expires_wall']
        with self.assertRaisesRegex(Rejected,'expired_control_window'):self.send(w)
        self.assertIsNone(self.p.snapshot()['leases']['a']['fire']['input'])
    def test_superseded_window_cannot_admit_new_command(self):
        old=self.window();new=self.window()
        with self.assertRaisesRegex(Rejected,'stale_control_window'):self.send(old)
        self.assertTrue(self.send(new)['accepted'])
    def test_duplicate_sequence_is_not_replayed(self):
        w=self.window();self.send(w)
        with self.assertRaisesRegex(Rejected,'stale_seq'):self.send(w)
    def test_wrong_session_and_robot(self):
        w=self.window();b=self.p.open_session('operator','server_window_v1');be=self.p.claim(b['token'],'b',['fire'])['lease_epochs'];self.p.control_window(b['token'],'b',be)
        with self.assertRaisesRegex(Rejected,'lease_mismatch'):self.p.control(b['token'],'a','fire',self.e['fire'],0,{'fire':True},.1,w['window_id'])
        with self.assertRaises(Rejected):self.p.control(self.t,'b','fire',be['fire'],0,{'fire':True},.1,w['window_id'])
    def test_release_reclaim_cannot_reuse_window(self):
        w=self.window();self.p.release(self.t,'a',self.e);self.e=self.p.claim(self.t,'a',list(self.e))['lease_epochs']
        with self.assertRaisesRegex(Rejected,'stale_control_window'):self.send(w)
    def test_bind_unbind_without_lease_change_revokes_window_and_input(self):
        w=self.window();self.send(w);epoch=self.e['gimbal']
        self.p.bind(self.t,'a','aim',{'gimbal':epoch},'test',{});self.p.unbind(self.t,'a','aim',{'gimbal':epoch})
        self.assertEqual(self.p.leases['a','gimbal'].epoch,epoch)
        with self.assertRaisesRegex(Rejected,'stale_control_window'):self.send(w,1)
        self.assertIsNone(self.p.snapshot()['leases']['a']['fire']['input'])
    def test_strict_missing_invalid_window_rejected(self):
        self.window()
        for wid in [None,True,1.,float('nan'),-1,2**53]:
            with self.assertRaises(Rejected):self.p.control(self.t,'a','fire',self.e['fire'],0,{'fire':True},.1,wid)
    def test_spectator_and_legacy_cannot_issue(self):
        for role,profile,reason in [('spectator','server_window_v1','read_only'),('operator','legacy_v2','lease_mismatch')]:
            t=self.p.open_session(role,profile)['token']
            with self.assertRaisesRegex(Rejected,reason):self.p.control_window(t,'a',self.e)
        legacy=self.p.open_session('operator')['token'];e=self.p.claim(legacy,'b',['fire'])['lease_epochs']
        with self.assertRaisesRegex(Rejected,'profile_required'):self.p.control_window(legacy,'b',e)
        self.assertTrue(self.p.control(legacy,'b','fire',e['fire'],0,{'fire':True},.25)['accepted'])
    def test_bounded_storage_and_nonwrapping_id(self):
        for _ in range(100):self.window()
        self.assertEqual(len(self.p.sessions[self.s['session_id']].windows),1)
        self.p.sessions[self.s['session_id']].next_window_id=2**53-1
        with self.assertRaisesRegex(Rejected,'exhausted'):self.window()
    def test_window_subset_cannot_control_other_channel(self):
        w=self.p.control_window(self.t,'a',{'motion':self.e['motion']})
        with self.assertRaisesRegex(Rejected,'lease_mismatch'):self.send(w)
    def test_lease_expiry_and_episode_revoke(self):
        w=self.window();self.p.reset_episode()
        with self.assertRaisesRegex(Rejected,'lease_mismatch'):self.send(w)
    def test_expiry_during_validation_is_rechecked(self):
        w=self.window();self.clock.advance(.149)
        class Expiring(dict):
            def __getitem__(inner,key):
                self.clock.advance(.002);return super().__getitem__(key)
        with self.assertRaisesRegex(Rejected,'expired_control_window'):self.send(w,value=Expiring(fire=True))

if __name__=='__main__':unittest.main()
