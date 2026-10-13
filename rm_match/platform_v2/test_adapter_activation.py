"""Synthetic operator authorization checks; no render/native execution."""
import unittest
from .control import ControlPlane,Rejected

class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.now=10.;self.p=ControlPlane(['r'],clock=lambda:self.now)
        self.s=self.p.open_session('operator','server_window_v1');self.t=self.s['token']
        self.e=self.p.claim(self.t,'r',['motion','gimbal','fire'])['lease_epochs']
        self.b=self.p.bind(self.t,'r','navigation',{'motion':self.e['motion']},'nav_rule_v1',{})
        self.w=self.p.control_window(self.t,'r',self.e)
    def pulse(self,seq=0,w=None,ep=None):
        return self.p.adapter_input(self.t,'r','navigation',{'motion':self.e['motion']},self.b['binding_epoch'] if ep is None else ep,seq,self.w['window_id'] if w is None else w,.15)
    def test_initial_inactive(self):
        b=self.p.snapshot()['bindings']['r']['navigation'];self.assertTrue(b['activation_required']);self.assertEqual(-1,b['activation_seq'])
    def test_valid_then_duplicate_rejected(self):
        self.assertTrue(self.pulse()['accepted'])
        with self.assertRaises(Rejected):self.pulse()
    def test_exact_types(self):
        for seq in (True,0.,-1,2**53):
            with self.subTest(seq=seq),self.assertRaises(Rejected):self.pulse(seq)
        self.assertEqual(-1,self.p.snapshot()['bindings']['r']['navigation']['activation_seq'])
    def test_wrong_window_high_seq_does_not_poison(self):
        with self.assertRaises(Rejected):self.pulse(100,w=999)
        self.assertTrue(self.pulse(0)['accepted'])
    def test_same_window_never_extends(self):
        a=self.pulse();self.now+=.05;b=self.pulse(1);self.assertEqual(a['activation_expires'],b['activation_expires'])
    def test_fresh_window_before_expiry_prospective(self):
        a=self.pulse();self.now+=.05;self.w=self.p.control_window(self.t,'r',self.e)
        b=self.pulse(1);self.assertGreater(b['activation_expires'],a['activation_expires'])
    def test_expiry_exact_boundary_revokes_before_new_pulse(self):
        a=self.pulse();self.now=a['activation_expires'];self.w=self.p.control_window(self.t,'r',self.e)
        with self.assertRaises(Rejected):self.pulse(1)
        b=self.p.snapshot()['bindings']['r']['navigation'];self.assertIsNone(b['owner']);self.assertGreater(b['epoch'],self.b['binding_epoch'])
    def test_renew_cannot_extend(self):
        a=self.pulse();self.now+=.1;self.p.renew(self.t,'r',self.e);self.now=a['activation_expires']
        self.assertIsNone(self.p.snapshot()['bindings']['r']['navigation']['owner'])
    def test_second_bind_invalidates_first_window(self):
        self.p.bind(self.t,'r','aim',{'gimbal':self.e['gimbal']},'aim_pixel_baseline_v1',{})
        with self.assertRaises(Rejected):self.pulse()
    def test_bind_unbind_old_window_rejected(self):
        self.p.unbind(self.t,'r','navigation',{'motion':self.e['motion']})
        with self.assertRaises(Rejected):self.pulse()
    def test_manual_channel_conflict_fire_independent(self):
        with self.assertRaises(Rejected):self.p.control(self.t,'r','motion',self.e['motion'],0,dict(vx_mps=0,vy_mps=0,wz_rps=0,frame='base_link'),.15,self.w['window_id'])
        self.assertTrue(self.p.control(self.t,'r','fire',self.e['fire'],0,{'fire':False},.15,self.w['window_id'])['accepted'])
    def test_legacy_binding_unchanged(self):
        p=ControlPlane(['r'],clock=lambda:self.now);t=p.open_session('operator')['token'];e=p.claim(t,'r',['motion'])['lease_epochs'];p.bind(t,'r','navigation',e,'nav_rule_v1',{})
        self.now+=.2;b=p.snapshot()['bindings']['r']['navigation'];self.assertIsNotNone(b['owner']);self.assertFalse(b['activation_required'])


class RuntimeActivationTests(unittest.TestCase):
    def setUp(self):
        from .runtime import PlatformRuntime
        from .test_runtime import FakeBackend,TestRegistry
        self.now=20.;self.runtime=PlatformRuntime(FakeBackend(('r',)),registry=TestRegistry(),clock=lambda:self.now)
        self.runtime._episode=0;self.p=self.runtime.control;self.t=self.p.open_session('operator','server_window_v1')['token']
        self.e=self.p.claim(self.t,'r',['motion'])['lease_epochs'];self.b=self.runtime.bind(self.t,'r','navigation',self.e,'nav',{})
        class Slot:
            dropped=0;lifecycle_error=None
            def __init__(self):self.jobs=[];self.result=None
            def submit(self,job):self.jobs.append(job)
            def poll(self):r=self.result;self.result=None;return r
            def close(self):pass
        self.slot=Slot();self.runtime.slots['r','navigation']=self.slot
    def tearDown(self):self.runtime.close()
    def pulse(self,seq=0):
        w=self.p.control_window(self.t,'r',self.e)
        return self.p.adapter_input(self.t,'r','navigation',self.e,self.b['binding_epoch'],seq,w['window_id'],.15)
    def test_inactive_binding_does_not_schedule(self):
        self.runtime._schedule(self.p.snapshot(),0.);self.assertEqual([],self.slot.jobs)
    def test_schedule_capped_at_original_authorization(self):
        a=self.pulse();self.runtime._schedule(self.p.snapshot(),0.);job=self.slot.jobs[-1]
        self.assertEqual(job['observation']['wall_deadline'],a['activation_expires'])
        self.assertEqual(job['operator_authorization']['activation_window_id'],a['window_id'])
    def test_late_old_result_cannot_borrow_new_authorization(self):
        from .contracts import action_for
        a=self.pulse();self.runtime._schedule(self.p.snapshot(),0.);job=self.slot.jobs[-1]
        result=action_for(job['observation'],'navigation','velocity_body',dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=0.))
        self.now+=.1;new=self.pulse(1);self.assertGreater(new['activation_expires'],a['activation_expires'])
        self.now=a['activation_expires'];self.slot.result=dict(job=job,value=result,error=None,completed=self.now)
        self.runtime._collect(self.p.snapshot(),0.)
        self.assertNotIn(('r','navigation'),self.runtime.outputs)
        self.assertIsNone(self.runtime._targets(self.p.snapshot(),0.)['r']['motion'])
    def test_already_collected_output_cannot_borrow_new_authorization(self):
        from .contracts import action_for
        a=self.pulse();self.runtime._schedule(self.p.snapshot(),0.);job=self.slot.jobs[-1]
        result=action_for(job['observation'],'navigation','velocity_body',dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=0.))
        self.slot.result=dict(job=job,value=result,error=None,completed=self.now);self.runtime._collect(self.p.snapshot(),0.)
        self.assertIsNotNone(self.runtime._targets(self.p.snapshot(),0.)['r']['motion'])
        self.now+=.1;self.pulse(1);self.now=a['activation_expires']
        self.assertIsNone(self.runtime._targets(self.p.snapshot(),0.)['r']['motion'])

class HttpActivationTests(unittest.TestCase):
    def setUp(self):
        import threading
        from .runtime import PlatformRuntime
        from .server import PlatformHTTPServer,TransportConfig
        from .client import PlatformClient
        from .test_runtime import FakeBackend
        self.now=30.;self.runtime=PlatformRuntime(FakeBackend(),clock=lambda:self.now)
        self.server=PlatformHTTPServer(TransportConfig(port=0),self.runtime)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start()
        self.c=PlatformClient('http://127.0.0.1:'+str(self.server.server_address[1]),control_profile='server_window_v1');self.c.open('operator');self.c.claim('alpha',['motion','gimbal','fire'])
    def tearDown(self):
        self.c.close();self.server.shutdown();self.server.server_close();self.thread.join(1);self.runtime.close()
    def bound(self):return self.c.bind('alpha','navigation','nav_stop_test_v1',{})
    def test_real_http_catalog_and_inactive_bind(self):
        c=self.c.adapters();self.assertEqual(c['adapter_activation_version'],1)
        b=self.bound();self.assertTrue(b['activation_required']);self.runtime.step_once();self.assertEqual({},self.runtime.slots)
    def test_real_http_authorization_then_expiry(self):
        b=self.bound();w=self.c.control_window('alpha',['motion','gimbal','fire']);a=self.c.adapter_input('alpha','navigation',b['binding_epoch'],window_id=w['window_id'])
        self.assertEqual(a['activation_expires'],w['expires_wall']);self.now=w['expires_wall'];self.runtime.step_once()
        self.assertIsNone(self.runtime.control.snapshot()['bindings']['alpha']['navigation']['owner'])
    def test_malformed_ack_uncertain(self):
        from unittest.mock import patch
        from .client import ClientError
        b=self.bound();w=self.c.control_window('alpha',['motion','gimbal','fire'])
        bad=dict(accepted=True,robot_id='alpha',kind='navigation',binding_epoch=b['binding_epoch'],seq=0,window_id=w['window_id'],activation_expires=w['expires_wall']+1)
        with patch.object(self.c,'_request',return_value=bad),self.assertRaises(ClientError):self.c.adapter_input('alpha','navigation',b['binding_epoch'],window_id=w['window_id'])
        self.assertTrue(self.c.uncertain)
    def test_http_bool_sequence_rejected_without_watermark_change(self):
        from .client import ClientError
        b=self.bound();w=self.c.control_window('alpha',['motion','gimbal','fire'])
        with self.assertRaises(ClientError):self.c._request('/v2/adapter_input',dict(robot_id='alpha',kind='navigation',lease_epochs={'motion':1},binding_epoch=b['binding_epoch'],seq=True,window_id=w['window_id'],valid_for_s=.15))
        self.assertEqual(-1,self.runtime.control.snapshot()['bindings']['alpha']['navigation']['activation_seq'])

if __name__=='__main__':unittest.main()
