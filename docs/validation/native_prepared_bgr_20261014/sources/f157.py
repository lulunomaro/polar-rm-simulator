import copy
import http.client
import json
import threading
import unittest

from .control import ControlPlane
from .runtime import PlatformRuntime
from .server import PlatformHTTPServer, TransportConfig
from .state_projection import project_state
from .test_control import Clock
from .test_runtime import FakeBackend


def display_fixture():
    robots = []
    for rid, team in [('alpha', 'red'), ('beta', 'blue')]:
        robots.append(dict(robot_id=rid, team=team, role='sentry', hp=91 if rid == 'alpha' else 27,
                           max_hp=100, heat=2, heat_max=100, ammo=9, alive=True,
                           gimbal_yaw=.2, gimbal_pitch=.1,
                           xy=[314159., 271828.], x=314159., y=271828.,
                           yaw=1.5, odom_xyyaw=['ODOM_TRUTH'],
                           future_truth='ROBOT_FUTURE_TRUTH'))
    return dict(source='simulator_truth_display_only', algorithm_input=False,
                display_schema='polar.sim.display.v2', episode=0, sim_time=.1,
                sample_sim_time=.1, phase='running', remaining_seconds=299.9,
                duration_seconds=300., winner=None, robots=robots,
                future_world='TOP_FUTURE_TRUTH', victory_points={'blue':271828.},
                applied_commands={'alpha':{'foreign':'OTHER_COMMAND'}},
                motion_feedback={'beta':{'foreign':'OTHER_FEEDBACK'}},
                algorithm_status={'beta':{'aim':'OTHER_STATUS'}},
                applied_targets={'alpha':{'motion':dict(frame='base_link', vx_mps=.25,
                                                       vy_mps=0., wz_rps=0., future='TARGET_TRUTH'),
                                          'gimbal':{'foreign':'OTHER_GIMBAL'}, 'fire':False},
                                 'beta':{'motion':{'foreign':'OTHER_COMMAND'}}},
                manual_consumption_receipts={'beta':{'foreign':'OTHER_RECEIPT'}})


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.control = ControlPlane(['alpha','beta'], clock=self.clock)
        self.a = self.control.open_session('operator')
        self.b = self.control.open_session('operator')
        self.raw = display_fixture()

    def project(self):
        control = self.control.snapshot(self.a['token'])
        value = dict(copy.deepcopy(self.raw), control=control, applied_sample_is_historical=True)
        return project_state(value, control, session_id=self.a['session_id'], role='operator')

    def claim(self):
        return self.control.claim(self.a['token'], 'alpha', ['motion'])['lease_epochs']

    def test_watch_without_claim_gets_static_roster_only(self):
        self.control.watch(self.a['token'], 'beta')
        state = self.project()
        self.assertEqual(state['source'], 'operator_limited_display')
        self.assertIs(state['algorithm_input'], False)
        for row in state['robots']:
            self.assertEqual(set(row), {'robot_id','team','role'})
        self.assertEqual(state['phase'], 'running')
        self.assertEqual(state['remaining_seconds'], 299.9)

    def test_owned_hud_enemy_and_unknown_truth_are_stripped(self):
        self.claim()
        state = self.project()
        own, enemy = state['robots']
        self.assertEqual(own['hp'], 91)
        self.assertEqual(own['gimbal_yaw'], .2)
        self.assertEqual(set(enemy), {'robot_id','team','role'})
        wire = json.dumps(state)
        for secret in ('314159', '271828', 'TRUTH', 'OTHER_COMMAND', 'OTHER_RECEIPT',
                       'OTHER_FEEDBACK', 'OTHER_STATUS', 'OTHER_GIMBAL', 'odom', 'chassis_yaw'):
            self.assertNotIn(secret, wire)
        self.assertNotIn('victory_points', state)
        self.assertNotIn('manual_consumption_receipts', state)

    def test_other_session_controls_and_binding_config_do_not_cross(self):
        own = self.claim()
        other = self.control.claim(self.b['token'], 'alpha', ['gimbal'])['lease_epochs']
        self.control.control(self.a['token'], 'alpha', 'motion', own['motion'], 0,
                             dict(frame='base_link', vx_mps=.25, vy_mps=0., wz_rps=0.), .15)
        self.control.bind(self.b['token'], 'alpha', 'aim', other, 'secret_other_adapter',
                          {'private':'OTHER_BINDING_CONFIG'})
        state = self.project()
        leases = state['control']['leases']['alpha']
        self.assertEqual(leases['motion']['owner'], self.a['session_id'])
        self.assertEqual(leases['motion']['input']['vx_mps'], .25)
        self.assertEqual(leases['gimbal']['owner'], 'occupied')
        self.assertIs(leases['gimbal']['occupied'], True)
        self.assertNotIn('input', leases['gimbal'])
        wire = json.dumps(state)
        for secret in (self.b['session_id'], 'OTHER_BINDING_CONFIG', 'secret_other_adapter'):
            self.assertNotIn(secret, wire)

    def test_owned_binding_is_metadata_only(self):
        epochs = self.claim()
        self.control.bind(self.a['token'], 'alpha', 'navigation', epochs, 'nav',
                          {'world_goal': [314159.,271828.]})
        binding = self.project()['control']['bindings']['alpha']['navigation']
        self.assertEqual(binding['adapter_id'], 'nav')
        self.assertEqual(binding['lease_epochs'], epochs)
        self.assertNotIn('config', binding)

    def test_release_and_expiry_revoke_dynamic_hud_without_new_physics(self):
        for expire in (False, True):
            with self.subTest(expire=expire):
                epochs = self.claim()
                self.assertIn('hp', self.project()['robots'][0])
                if expire:
                    self.clock.advance(self.control.lease_ttl)
                else:
                    self.control.release(self.a['token'], 'alpha', epochs)
                state = self.project()
                self.assertNotIn('hp', state['robots'][0])
                self.assertNotIn('alpha', state['applied_targets'])

    def test_cached_previous_owner_target_is_not_relabelled_as_own(self):
        epochs = self.claim()
        self.raw['manual_consumption_receipts']['alpha'] = {
            'manual_inputs': {'motion': {'owner':self.b['session_id'], 'epoch':epochs['motion']}}}
        self.assertEqual(self.project()['applied_targets'], {})
        self.raw['manual_consumption_receipts']['alpha']['manual_inputs']['motion']['owner'] = self.a['session_id']
        target = self.project()['applied_targets']['alpha']['motion']
        self.assertEqual(target['vx_mps'], .25)
        self.assertNotIn('future', target)
        self.control.release(self.a['token'], 'alpha', epochs)
        self.claim()
        self.assertEqual(self.project()['applied_targets'], {})

    def test_future_truth_nested_under_known_key_is_not_copied(self):
        self.claim()
        self.raw['robots'][0]['hp'] = {'xy': [314159.,271828.]}
        self.raw['winner'] = {'future_world':'TOP_FUTURE_TRUTH'}
        state = self.project()
        self.assertNotIn('hp', state['robots'][0])
        self.assertNotIn('winner', state)

    def test_spectator_snapshot_preserves_full_audit_and_is_a_copy(self):
        control = self.control.snapshot()
        original = dict(self.raw, control=control, applied_sample_is_historical=True)
        result = project_state(original, control, session_id='observer', role='spectator')
        self.assertEqual(result, original)
        result['robots'][0]['xy'][0] = -1
        self.assertEqual(original['robots'][0]['xy'][0], 314159.)


class HTTPProjectionTests(unittest.TestCase):
    def test_real_state_endpoint_uses_session_role_and_current_lease(self):
        clock = Clock()
        runtime = PlatformRuntime(FakeBackend(), clock=clock)
        # Cache sentinels exercise the actual endpoint without GL or inference.
        runtime.cached = display_fixture()
        a = runtime.control.open_session('operator')
        observer = runtime.control.open_session('spectator')
        server = PlatformHTTPServer(TransportConfig(port=0), runtime)
        thread = threading.Thread(target=server.serve_forever,
                                  kwargs={'poll_interval':.01}, daemon=True)
        thread.start()
        def state(token):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=2.)
            try:
                connection.request('GET', '/v2/state', headers={'Authorization':'Bearer '+token})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                return json.loads(response.read())
            finally:
                connection.close()
        try:
            runtime.control.watch(a['token'], 'alpha')
            self.assertNotIn('hp', state(a['token'])['robots'][0])
            epochs = runtime.control.claim(a['token'], 'alpha', ['motion'])['lease_epochs']
            own = state(a['token'])
            self.assertEqual(own['schema'], 'rm.sim.platform.v2')
            self.assertEqual(own['source'], 'operator_limited_display')
            self.assertEqual(own['robots'][0]['hp'], 91)
            self.assertNotIn('xy', own['robots'][0])
            self.assertNotIn('hp', own['robots'][1])
            audit = state(observer['token'])
            self.assertEqual(audit['source'], 'simulator_truth_display_only')
            self.assertEqual(audit['robots'][1]['xy'], [314159.,271828.])
            runtime.control.release(a['token'], 'alpha', epochs)
            self.assertNotIn('hp', state(a['token'])['robots'][0])
            runtime.control.claim(a['token'], 'alpha', ['motion'])
            clock.advance(runtime.control.lease_ttl)
            self.assertNotIn('hp', state(a['token'])['robots'][0])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2.)
            runtime.close()


if __name__ == '__main__':
    unittest.main()
