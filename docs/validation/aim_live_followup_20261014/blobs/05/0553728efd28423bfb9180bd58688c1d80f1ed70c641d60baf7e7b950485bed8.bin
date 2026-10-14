"""Actual loopback strict SDK protocol; the backend here is explicitly synthetic."""
import copy
import threading
import unittest
from unittest.mock import patch
from .client import PlatformClient,ClientError
from .control import CHANNELS
from .runtime import PlatformRuntime
from .server import PlatformHTTPServer,TransportConfig
from .test_runtime import FakeBackend
from .test_control import Clock
from .test_support_admission import fixture_policy,OPERATOR_CREDENTIAL

class StrictClientTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.r=PlatformRuntime(FakeBackend(),clock=self.clock);self.server=PlatformHTTPServer(TransportConfig(port=0,admission_policy=fixture_policy(self.r.control.robot_ids)),self.r)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start()
        self.c=PlatformClient('http://127.0.0.1:'+str(self.server.server_address[1]),control_profile='server_window_v1',admission_credential=OPERATOR_CREDENTIAL)
        self.reply=self.c.open('operator');self.c.claim('alpha',list(CHANNELS))
    def tearDown(self):
        self.c.close();self.server.shutdown();self.server.server_close();self.thread.join(1);self.r.close()
    def test_strict_roundtrip_and_receipt(self):
        self.assertEqual(self.reply['control_profile'],'server_window_v1');w=self.c.control_window('alpha',list(CHANNELS));ack=self.c.control('alpha','fire',{'fire':True},window_id=w['window_id']);self.assertEqual(ack['input_expires'],w['expires_wall'])
        self.r.step_once();self.assertTrue(self.r.backend.targets['alpha']['fire'])
    def test_no_window_is_not_silently_legacy(self):
        with self.assertRaisesRegex(ClientError,'window required'):self.c.control('alpha','fire',{'fire':True})
        with self.assertRaisesRegex(ClientError,'invalid_window_id'):self.c._request('/v2/control',dict(robot_id='alpha',channel='fire',lease_epoch=1,seq=0,value={'fire':True},valid_for_s=.15))
    def test_delayed_received_packet_is_rejected_over_http(self):
        w=self.c.control_window('alpha',list(CHANNELS));self.clock.now=w['expires_wall']
        with self.assertRaisesRegex(ClientError,'expired_control_window'):self.c.control('alpha','fire',{'fire':True},window_id=w['window_id'])
        self.assertFalse(self.c.uncertain);self.assertIsNone(self.r.control.snapshot()['leases']['alpha']['fire']['input'])
    def test_malformed_window_ack_latches_uncertain(self):
        w=self.c.control_window('alpha',list(CHANNELS))
        for change in [dict(window_id=True),dict(window_id=w['window_id']),dict(expires_wall=w['expires_wall']+1),dict(session_id='other'),dict(lease_epochs={'fire':True}),dict(valid_for_s=.5)]:
            self.c.uncertain=False;bad=copy.deepcopy(w);bad.update(change)
            with patch.object(self.c,'_request',return_value=bad):
                with self.assertRaises(ClientError):self.c.control_window('alpha',list(CHANNELS))
            self.assertTrue(self.c.uncertain)
    def test_malformed_control_deadline_ack_latches_uncertain(self):
        w=self.c.control_window('alpha',list(CHANNELS));bad=dict(accepted=True,robot_id='alpha',channel='fire',lease_epoch=1,seq=0,window_id=w['window_id'],input_expires=w['expires_wall']+1)
        with patch.object(self.c,'_request',return_value=bad):
            with self.assertRaises(ClientError):self.c.control('alpha','fire',{'fire':True},window_id=w['window_id'])
        self.assertTrue(self.c.uncertain)
    def test_open_requires_negotiation(self):
        c=PlatformClient(self.c.url,control_profile='server_window_v1');response=dict(self.reply,token='synthetic-token');response.pop('control_window_version')
        with patch.object(c,'_request',return_value=response):
            with self.assertRaisesRegex(ClientError,'profile unavailable'):c.open('operator')
        self.assertTrue(c.uncertain)
    def test_bind_and_unbind_clear_local_window(self):
        w=self.c.control_window('alpha',list(CHANNELS));self.c.bind('alpha','aim','aim_hold_test_v1');self.c.unbind('alpha','aim')
        with self.assertRaisesRegex(ClientError,'window required'):self.c.control('alpha','fire',{'fire':True},window_id=w['window_id'])

if __name__=='__main__':unittest.main()
