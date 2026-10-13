import unittest
from .control import ControlPlane,Rejected

class Clock:
    def __init__(self):self.now=1000.
    def __call__(self):return self.now
    def advance(self,v):self.now+=v

class ControlTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.p=ControlPlane(['alpha','beta'],clock=self.clock)
        self.a=self.p.open_session('operator')['token'];self.b=self.p.open_session('operator')['token']
        self.s=self.p.open_session('spectator')['token']
    def claim(self,token,rid='alpha',channels=None):return self.p.claim(token,rid,channels or ['motion','gimbal','fire'])['lease_epochs']
    def test_two_robots_are_independent(self):
        a=self.claim(self.a);b=self.claim(self.b,'beta')
        self.p.control(self.a,'alpha','motion',a['motion'],1,dict(vx_mps=1,vy_mps=0,wz_rps=0,frame='base_link'),.2)
        state=self.p.snapshot(self.s)
        self.assertIsNone(state['leases']['beta']['motion']['input'])
        self.assertEqual(state['leases']['alpha']['motion']['input']['vx_mps'],1)
    def test_spectator_is_read_only_even_with_known_epochs(self):
        epochs=self.claim(self.a)
        for fn in [lambda:self.claim(self.s,'beta'),lambda:self.p.release(self.s,'alpha',epochs),
                   lambda:self.p.renew(self.s,'alpha',epochs),
                   lambda:self.p.bind(self.s,'alpha','aim',{'gimbal':epochs['gimbal']},'test',{}),
                   lambda:self.p.control(self.s,'alpha','fire',epochs['fire'],1,{'fire':True},.2)]:
            with self.assertRaisesRegex(Rejected,'read_only'):fn()
        self.assertIn('leases',self.p.snapshot(self.s))
    def test_atomic_claim_refuses_preemption(self):
        self.claim(self.a,channels=['motion'])
        with self.assertRaisesRegex(Rejected,'occupied'):self.claim(self.b,channels=['fire','motion'])
        self.assertIsNone(self.p.snapshot()['leases']['alpha']['fire']['owner'])
    def test_independent_channel_owners(self):
        self.claim(self.a,channels=['motion'])
        e=self.claim(self.b,channels=['gimbal','fire'])
        self.p.bind(self.b,'alpha','aim',{'gimbal':e['gimbal']},'test',{})
        self.p.control(self.b,'alpha','fire',e['fire'],1,{'fire':True},.2)
    def test_expiry_does_not_implicitly_reacquire(self):
        e=self.claim(self.a);self.p.bind(self.a,'alpha','navigation',{'motion':e['motion']},'test',{})
        old=self.p.snapshot()['bindings']['alpha']['navigation']['epoch']
        self.clock.advance(1.01)
        with self.assertRaisesRegex(Rejected,'mismatch'):self.p.renew(self.a,'alpha',e)
        fresh=self.claim(self.b)
        self.assertGreater(fresh['motion'],e['motion'])
        self.assertGreater(self.p.snapshot()['bindings']['alpha']['navigation']['epoch'],old)
        with self.assertRaisesRegex(Rejected,'mismatch'):self.p.control(self.a,'alpha','fire',e['fire'],9,{'fire':True},.2)
    def test_release_neutralizes_and_unbinds(self):
        e=self.claim(self.a);self.p.control(self.a,'alpha','fire',e['fire'],1,{'fire':True},.2)
        self.p.bind(self.a,'alpha','aim',{'gimbal':e['gimbal']},'test',{})
        self.p.release(self.a,'alpha',e)
        state=self.p.snapshot()
        self.assertTrue(all(state['leases']['alpha'][c]['input'] is None for c in e))
        self.assertIsNone(state['bindings']['alpha']['aim']['owner'])
    def test_binding_blocks_manual_except_separate_fire(self):
        e=self.claim(self.a)
        self.p.bind(self.a,'alpha','aim',{'gimbal':e['gimbal']},'test',{})
        with self.assertRaisesRegex(Rejected,'bound'):self.p.control(self.a,'alpha','gimbal',e['gimbal'],1,dict(yaw_rad=0,pitch_rad=0,frame='base_link'),.2)
        self.assertTrue(self.p.control(self.a,'alpha','fire',e['fire'],1,{'fire':True},.2)['accepted'])
    def test_seq_and_nonfinite_rejected_without_mutation(self):
        e=self.claim(self.a)
        self.p.control(self.a,'alpha','fire',e['fire'],4,{'fire':True},.2)
        with self.assertRaisesRegex(Rejected,'stale_seq'):self.p.control(self.a,'alpha','fire',e['fire'],4,{'fire':False},.2)
        with self.assertRaises(Rejected):self.p.control(self.a,'alpha','motion',e['motion'],1,dict(vx_mps=float('nan'),vy_mps=0,wz_rps=0,frame='base_link'),.2)
        self.assertEqual(self.p.snapshot()['leases']['alpha']['motion']['seq'],-1)
    def test_command_expiry_does_not_release_control(self):
        e=self.claim(self.a);self.p.control(self.a,'alpha','fire',e['fire'],1,{'fire':True},.1)
        self.clock.advance(.11);s=self.p.snapshot()['leases']['alpha']['fire']
        self.assertIsNone(s['input']);self.assertIsNotNone(s['owner'])
    def test_binding_epoch_increases_on_rebind_and_unbind(self):
        e=self.claim(self.a);args=(self.a,'alpha','navigation',{'motion':e['motion']},'test',{})
        a=self.p.bind(*args)['binding_epoch'];b=self.p.bind(*args)['binding_epoch']
        c=self.p.unbind(self.a,'alpha','navigation',{'motion':e['motion']})['binding_epoch']
        self.assertLess(a,b);self.assertLess(b,c)
    def test_session_close_revokes_just_owned_channels(self):
        self.claim(self.a);self.claim(self.b,'beta');self.p.close_session(self.a)
        s=self.p.snapshot();self.assertIsNone(s['leases']['alpha']['motion']['owner'])
        self.assertIsNotNone(s['leases']['beta']['motion']['owner'])
    def test_session_capacity_bounded_and_expired_reclaimed(self):
        self.p.max_sessions=3
        with self.assertRaisesRegex(Rejected,'capacity'):self.p.open_session('spectator')
        self.clock.advance(61);self.p.open_session('spectator')
        self.assertEqual(len(self.p.sessions),1)
    def test_scene_registry_is_not_fixed_to_six(self):
        p=ControlPlane([f'robot_{i}' for i in range(14)])
        self.assertEqual(len(p.leases),42)
    def test_shutdown_cannot_be_reopened(self):
        self.claim(self.a);self.p.stop()
        with self.assertRaisesRegex(Rejected,'stopped'):self.claim(self.b,'beta')
        self.assertTrue(self.p.snapshot(self.s)['stopped'])

if __name__=='__main__':unittest.main()
