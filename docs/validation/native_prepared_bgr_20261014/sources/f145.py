"""Offline lifecycle remains usable through the same scoped HTTP projection."""
from dataclasses import asdict
import json
import threading
import unittest
from .client import PlatformClient
from .offline_contract import PROFILE
from .offline_runtime import OfflineRuntime
from .server import PlatformHTTPServer,TransportConfig
from .test_admission import FakeDisplayCamera,camera_fixture
from .test_control import Clock
from .test_runtime import FakeBackend
from .test_state_projection import display_fixture
from .test_support_admission import fixture_policy,OPERATOR_CREDENTIAL,AUDIT_CREDENTIAL


class OfflineProjectionTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();camera=FakeDisplayCamera()
        camera.display_frame=lambda rid,ep,key,watch:dict(camera_fixture(),robot_id=rid,episode=ep,watch_epoch=watch)
        self.runtime=OfflineRuntime(FakeBackend(('red_sentry','blue_sentry')),camera=camera,
                                    native_factory=lambda:None,clock=self.clock)
        self.runtime._episode=0;self.runtime.origin_ns=0;self.runtime._started=self.clock()
        raw=display_fixture()
        for row,rid in zip(raw['robots'],('red_sentry','blue_sentry')):row['robot_id']=rid
        raw.update(offline_final_state='HALTED',offline_halt_reason='native_error:PRIVATE_NATIVE_PATH',
                   completed_captures=3,clock_profile=dict(kind=PROFILE,label='OFFLINE / SIL',
                   barrier_state='HALTED',simulation_tick=5,simulation_ns=50000000,
                   delays=dict(asdict(self.runtime.timeline),future_pose='DELAY_TRUTH'),
                   future_pose='CLOCK_WORLD_POSE'))
        self.runtime.cached=raw
        policy=fixture_policy(('red_sentry',))
        self.server=PlatformHTTPServer(TransportConfig(port=0,admission_policy=policy),self.runtime)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start()
        url='http://127.0.0.1:'+str(self.server.server_address[1])
        self.operator=PlatformClient(url,admission_credential=OPERATOR_CREDENTIAL);self.operator.open('operator')
        self.audit=PlatformClient(url,admission_credential=AUDIT_CREDENTIAL);self.audit.open('spectator')
    def tearDown(self):
        self.operator.close();self.audit.close();self.server.shutdown();self.server.server_close();self.thread.join(1);self.runtime.close()

    def test_offline_http_lifecycle_is_whitelisted_without_truth_or_error_paths(self):
        self.operator.claim('red_sentry',['gimbal'])
        self.operator.bind('red_sentry','aim','aim_native_rmcs_offline_v1',{})
        state=self.operator.state()
        self.assertEqual(state['source'],'operator_limited_display')
        self.assertEqual(state['offline_final_state'],'HALTED');self.assertEqual(state['completed_captures'],3)
        self.assertEqual(state['offline_halt_code'],'native_error')
        self.assertEqual(state['clock_profile']['barrier_state'],'HALTED')
        self.assertEqual(state['clock_profile']['delays']['max_age_ns'],80000000)
        binding=state['control']['bindings']['red_sentry']['aim']
        self.assertEqual(binding['owner'],self.operator.session_id);self.assertNotIn('config',binding)
        wire=json.dumps(state)
        for value in ('PRIVATE_NATIVE_PATH','CLOCK_WORLD_POSE','DELAY_TRUTH','ODOM_TRUTH','314159','271828'):
            self.assertNotIn(value,wire)
        self.assertNotIn('offline_halt_reason',state);self.assertNotIn('xy',state['robots'][0])
        self.assertEqual([row['robot_id'] for row in state['robots']],['red_sentry'])
        self.operator.release('red_sentry',['gimbal'])
        released=self.operator.state()
        self.assertNotIn('hp',released['robots'][0])
        self.assertEqual(released['offline_final_state'],'HALTED')
        self.assertIsNone(released['control']['bindings']['red_sentry']['aim']['owner'])

    def test_offline_frame_operator_has_no_pose_but_explicit_auditor_keeps_it(self):
        self.operator.watch('red_sentry');self.audit.watch('red_sentry')
        self.assertEqual(self.operator.frame()['source'],'operator_camera_display_v1')
        self.assertNotIn('own_odom_at_capture',self.operator.frame())
        self.assertIn('own_odom_at_capture',self.audit.frame())
        self.assertIn('xy',self.audit.state()['robots'][1])
        self.assertEqual(self.audit.state()['offline_halt_reason'],'native_error:PRIVATE_NATIVE_PATH')


if __name__=='__main__':unittest.main()
