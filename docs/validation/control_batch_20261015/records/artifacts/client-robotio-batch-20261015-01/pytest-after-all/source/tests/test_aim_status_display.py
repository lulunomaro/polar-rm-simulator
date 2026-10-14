"""Synthetic own-client state/clock checks; no GUI, DDS or detector."""
import copy
import unittest
from platform_v2_fixtures import state
from test_platform_control_windows import WindowClient
from rm_client.sim_platform_transport import PlatformTransport

class StatusDisplayTests(unittest.TestCase):
    def setUp(self):
        self.now=[100.];self.c=WindowClient();self.t=PlatformTransport(role='operator',clock=lambda:self.now[0],client=self.c)
        self.t.connect_once();self.t.watch_robot='red_infantry'
        self.t.plan={'aim':{'adapter_id':'custom_independent_aim','config':{}}}
        self.t._bindings={'aim':{'binding_epoch':2}}
    def message(self,status='no_target'):
        data=state(owner=self.c.session_id)
        data['control']['bindings']['red_infantry']['aim']=dict(owner=self.c.session_id,epoch=2,adapter_id='custom_independent_aim')
        data['algorithm_status_context']={'red_infantry':{'aim':dict(episode=0,binding_epoch=2,
            adapter_id='custom_independent_aim',status=status,observed_seq=1,wall_deadline=100.08,source_frame_id=1)}}
        return data
    def test_no_target_and_result_available_are_not_physical_confirmation(self):
        self.t.install_state(self.message());self.assertIn('no target',self.t.adapter_feedback())
        self.t.install_state(self.message('result_available'));shown=self.t.adapter_feedback()
        self.assertIn('physical application unconfirmed',shown);self.assertNotIn('last applied',shown)
        self.assertIsNone(self.t._window);self.assertFalse(self.t._focus)
    def test_received_and_later_expired_status_cannot_be_displayed(self):
        self.now[0]=100.09
        self.t.install_state(self.message(),request_started=100.)
        self.assertNotIn('no target',self.t.adapter_feedback())
        self.now[0]=100.;self.t.install_state(self.message(),request_started=100.)
        self.now[0]=100.081;self.assertNotIn('no target',self.t.adapter_feedback())
    def test_epoch_episode_owner_and_truth_fields_reject(self):
        for key,value in [('binding_epoch',3),('episode',1),('episode',True),('adapter_id','custom_other'),('status','enemy_xy'),('xy',[1,2])]:
            with self.subTest(key=key,value=value):
                raw=self.message();raw['algorithm_status_context']['red_infantry']['aim'][key]=value
                with self.assertRaises(ValueError):self.t.install_state(raw)
        raw=self.message();raw['control']['leases']['red_infantry']['gimbal']['owner']='other'
        with self.assertRaises(ValueError):self.t.install_state(raw)
    def test_other_robot_or_channel_is_not_a_display_shortcut(self):
        for rid,kind in [('blue_sentry','aim'),('red_infantry','navigation')]:
            raw=self.message();context=raw['algorithm_status_context']['red_infantry']['aim']
            raw['algorithm_status_context']={rid:{kind:context}}
            with self.subTest(rid=rid,kind=kind),self.assertRaises(ValueError):self.t.install_state(raw)

if __name__=='__main__':unittest.main()
