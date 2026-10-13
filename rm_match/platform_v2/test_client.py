import threading
import unittest
from .client import PlatformClient,ClientError
from .server import PlatformHTTPServer,TransportConfig
from .runtime import PlatformRuntime
from .test_runtime import FakeBackend
from .test_control import Clock

class ClientTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.backend=FakeBackend();self.runtime=PlatformRuntime(self.backend,clock=self.clock)
        self.server=PlatformHTTPServer(TransportConfig(port=0),self.runtime);self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start()
        url='http://127.0.0.1:'+str(self.server.server_address[1]);self.a=PlatformClient(url);self.b=PlatformClient(url);self.w=PlatformClient(url)
        self.a.open('operator');self.b.open('operator');self.w.open('spectator')
    def tearDown(self):
        for c in (self.a,self.b,self.w):
            try:c.close()
            except ClientError:pass
        self.server.shutdown();self.server.server_close();self.thread.join(1);self.runtime.close()
    def test_two_operators_and_observer_over_actual_http(self):
        self.a.claim('alpha',['motion']);self.b.claim('beta',['motion'])
        self.a.control('alpha','motion',dict(frame='base_link',vx_mps=.5,vy_mps=0.,wz_rps=0.))
        self.b.control('beta','motion',dict(frame='base_link',vx_mps=-.2,vy_mps=0.,wz_rps=0.))
        self.runtime.step_once();state=self.w.state();self.assertEqual(state['applied_targets']['alpha']['motion']['vx_mps'],.5);self.assertEqual(state['applied_targets']['beta']['motion']['vx_mps'],-.2)
        with self.assertRaises(ClientError):self.w.claim('alpha',['fire'])
        with self.assertRaises(ClientError):self.b.claim('alpha',['motion'])
    def test_disconnect_and_timeout_are_per_robot(self):
        for client,rid in ((self.a,'alpha'),(self.b,'beta')):
            client.claim(rid,['motion']);client.control(rid,'motion',dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=0.))
        self.a.close();self.runtime.step_once();self.assertIsNone(self.backend.targets['alpha']['motion']);self.assertIsNotNone(self.backend.targets['beta']['motion'])
        self.clock.advance(.2);self.runtime.step_once();self.assertIsNone(self.backend.targets['beta']['motion'])
    def test_session_secret_not_returned_or_repr(self):
        self.a.close();result=self.a.open('operator');self.assertNotIn('token',result);self.assertNotIn(self.a._token,repr(self.a))
    def test_release_reclaim_uses_new_epoch_and_no_old_sequence(self):
        first=self.a.claim('alpha',['motion'])['lease_epochs']['motion'];self.a.release('alpha',['motion']);second=self.a.claim('alpha',['motion'])['lease_epochs']['motion'];self.assertGreater(second,first)
        with self.assertRaises(ClientError):self.a._request('/v2/control',dict(robot_id='alpha',channel='motion',lease_epoch=first,seq=99,value=dict(frame='base_link',vx_mps=.9,vy_mps=0.,wz_rps=0.),valid_for_s=.1))
    def test_no_lan_or_external_url_or_credentials(self):
        for url in ('http://0.0.0.0:8000','http://192.168.1.8:8000','https://127.0.0.1:8000','http://x:y@127.0.0.1:8000','http://127.0.0.1:8000/other'):
            with self.assertRaises(ValueError):PlatformClient(url)
    def test_timeout_sends_once_and_blocks_renew_or_bind(self):
        from unittest.mock import patch
        self.a.claim("alpha",["motion"])
        with patch.object(self.a._opener,"open",side_effect=TimeoutError("synthetic")) as send:
            with self.assertRaises(ClientError):self.a.control("alpha","motion",dict(frame="base_link",vx_mps=.2,vy_mps=0.,wz_rps=0.))
            self.assertEqual(send.call_count,1)
        with self.assertRaises(ClientError):self.a.renew("alpha",["motion"])
        with self.assertRaises(ClientError):self.a.bind("alpha","navigation","nav_stop_test_v1")
    def test_oversize_and_redirect_success_are_uncertain(self):
        import io
        from unittest.mock import patch
        from .client import MAX_RESPONSE_BYTES
        self.a.claim('alpha',['motion'])
        for result in (io.BytesIO(b'x'*(MAX_RESPONSE_BYTES+1)),ClientError('Redirect forbidden')):
            self.a.uncertain=False
            options={'side_effect':result} if isinstance(result,Exception) else {'return_value':result}
            with patch.object(self.a._opener,'open',**options):
                with self.assertRaises(ClientError):self.a.control('alpha','motion',dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=0.))
            self.assertTrue(self.a.uncertain)
            with self.assertRaises(ClientError):self.a.renew('alpha',['motion'])
    def test_unverified_control_ack_cannot_authorize_more_commands(self):
        import io,json
        from unittest.mock import patch
        self.a.claim('alpha',['motion'])
        response=dict(schema='rm.sim.platform.v2',accepted=True,robot_id='other',channel='motion',lease_epoch=1,seq=0)
        with patch.object(self.a._opener,'open',return_value=io.BytesIO(json.dumps(response).encode())):
            with self.assertRaises(ClientError):self.a.control('alpha','motion',dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=0.))
        self.assertTrue(self.a.uncertain)
    def test_malformed_open_and_claim_mark_uncertain(self):
        from unittest.mock import patch
        c=PlatformClient(self.a.url)
        with patch.object(c,'_request',return_value={'schema':'rm.sim.platform.v2'}):
            with self.assertRaises(ClientError):c.open('operator')
        self.assertTrue(c.uncertain)
        with patch.object(self.a,'_request',return_value={'schema':'rm.sim.platform.v2','robot_id':'alpha','lease_epochs':{'motion':True}}):
            with self.assertRaises(ClientError):self.a.claim('alpha',['motion'])
        self.assertTrue(self.a.uncertain)
    def test_explicit_http_conflict_is_known_rejection(self):
        self.a.claim('alpha',['motion'])
        with self.assertRaises(ClientError):self.b.claim('alpha',['motion'])
        self.assertFalse(self.b.uncertain)
    def test_uncertain_command_no_automatic_replay(self):
        self.a.claim('alpha',['motion']);self.a.uncertain=True
        with self.assertRaises(ClientError):self.a.control('alpha','motion',dict(frame='base_link',vx_mps=.9,vy_mps=0.,wz_rps=0.))
        self.runtime.step_once();self.assertIsNone(self.backend.targets['alpha']['motion'])
if __name__=='__main__':unittest.main()
