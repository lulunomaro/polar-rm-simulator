"""HTTP and SDK admission, robot scope and operator camera data-plane tests."""
import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from .admission import AdmissionPolicy
from .client import PlatformClient,ClientError
from .control import Rejected
from .runtime import PlatformRuntime
from .server import PlatformHTTPServer,TransportConfig
from .state_projection import operator_camera_display
from .test_control import Clock
from .test_runtime import FakeBackend
from .test_state_projection import display_fixture
from .test_support_admission import OPERATOR_CREDENTIAL,AUDIT_CREDENTIAL


def scope_policy():
    return AdmissionPolicy([
        dict(credential_sha256=hashlib.sha256(OPERATOR_CREDENTIAL.encode()).hexdigest(),
             role='operator',allowed_robots=['alpha'],audit_authorized=False),
        dict(credential_sha256=hashlib.sha256(AUDIT_CREDENTIAL.encode()).hexdigest(),
             role='spectator',allowed_robots=[],audit_authorized=True)])


def camera_fixture():
    return dict(available=True,reason='available',source='simulated_raw_camera_display_jpeg',
                algorithm_input=False,robot_id='alpha',episode=0,watch_epoch=1,frame_seq=2,
                capture_sim_time=.1,capture_wall_monotonic=1000.,encode_completed_wall_monotonic=1000.01,
                age_wall_s=.01,max_frame_age_wall_s=2.5,full_frame=True,
                own_qpos_at_capture=['OWN_WORLD_POSE'],own_qvel_at_capture=['OWN_WORLD_SPEED'],
                own_odom_at_capture=['OWN_WORLD_ODOM'],future_pose='FUTURE_POSE',
                image=dict(encoding='jpeg',width=1,height=1,data_base64='QUJD',future='IMAGE_TRUTH'),
                calibration=dict(intrinsics=dict(fx=2.,fy=2.,cx=.5,cy=.5,distortion_model='brown_conrady_5',
                    distortion=[0.]*5,future='INTRINSIC_TRUTH'),
                    extrinsics=dict(parent_frame='gimbal_link',calibration_id='static_test',
                    translation_m=[.24,0.,.06],rotation_xyzw=[0.,0.,0.,1.],world_pose='EXTRINSIC_TRUTH'),
                    profile=dict(future='PROFILE_WORLD_POSE')))


class FakeDisplayCamera:
    max_views=2
    def display_frame(self,*args):return camera_fixture()
    def stop(self):pass
    def status(self):return dict(available=True)


class AdmissionHTTPTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.runtime=PlatformRuntime(FakeBackend(),clock=self.clock)
        self.runtime.cached=display_fixture();self.runtime._episode=0
        self.server=PlatformHTTPServer(TransportConfig(port=0,admission_policy=scope_policy()),self.runtime)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True)
        self.thread.start();self.url='http://127.0.0.1:'+str(self.server.server_address[1])
        self.clients=[]
    def tearDown(self):
        for client in self.clients:
            try:client.close()
            except ClientError:pass
        self.server.shutdown();self.server.server_close();self.thread.join(1);self.runtime.close()
    def request(self,path,body=None,token=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=2.)
        headers={}
        if token:headers['Authorization']='Bearer '+token
        if body is not None:headers['Content-Type']='application/json'
        try:
            connection.request('GET' if body is None else 'POST',path,
                               None if body is None else json.dumps(body),headers)
            response=connection.getresponse();return response.status,json.loads(response.read())
        finally:connection.close()
    def operator(self):
        client=PlatformClient(self.url,admission_credential=OPERATOR_CREDENTIAL)
        self.clients.append(client);client.open('operator');return client

    def test_missing_wrong_credential_and_role_escalation_are_denied(self):
        for role in ('operator','spectator'):
            status,_=self.request('/v2/sessions',{'role':role});self.assertEqual(status,401)
        status,_=self.request('/v2/sessions',{'role':'operator','credential':'x'*40});self.assertEqual(status,401)
        status,_=self.request('/v2/sessions',{'role':'spectator','credential':OPERATOR_CREDENTIAL});self.assertEqual(status,403)
        status,_=self.request('/v2/sessions',{'role':'operator','credential':AUDIT_CREDENTIAL});self.assertEqual(status,403)

    def test_network_body_cannot_choose_scope_audit_or_trusted_admin(self):
        for key,value in [('allowed_robots',['beta']),('audit_authorized',True),('trusted_admin',True)]:
            status,_=self.request('/v2/sessions',dict(role='operator',credential=OPERATOR_CREDENTIAL,**{key:value}))
            self.assertEqual(status,400)

    def test_state_roster_capabilities_and_catalog_are_scoped(self):
        client=self.operator()
        self.assertEqual(client.allowed_robots,('alpha',));self.assertFalse(client.audit_authorized)
        self.assertEqual(client.robots()['robot_ids'],['alpha'])
        self.assertEqual([r['robot_id'] for r in client.state()['robots']],['alpha'])
        caps=client._request('/v2/capabilities')
        self.assertEqual([r['robot_id'] for r in caps['robots']],['alpha'])
        self.assertEqual([r['robot_id'] for r in client.adapters()['robots']],['alpha'])

    def test_every_robot_authority_endpoint_checks_scope(self):
        client=self.operator();token=client._token
        common=dict(robot_id='beta')
        cases=[('/v2/watch',common),('/v2/claim',dict(common,channels=['motion'])),
               ('/v2/renew',dict(common,lease_epochs={'motion':0})),
               ('/v2/release',dict(common,lease_epochs={'motion':0})),
               ('/v2/control_window',dict(common,lease_epochs={'motion':0})),
               ('/v2/bind',dict(common,kind='navigation',lease_epochs={'motion':0},adapter_id='nav_stop_test_v1',config={})),
               ('/v2/unbind',dict(common,kind='navigation',lease_epochs={'motion':0})),
               ('/v2/adapter_input',dict(common,kind='navigation',lease_epochs={'motion':0},binding_epoch=0,
                                       seq=0,window_id=0,valid_for_s=.1)),
               ('/v2/control',dict(common,channel='motion',lease_epoch=0,seq=0,valid_for_s=.1,
                                  value=dict(frame='base_link',vx_mps=0.,vy_mps=0.,wz_rps=0.)))]
        for path,body in cases:
            with self.subTest(path=path):
                status,error=self.request(path,body,token)
                self.assertEqual(status,403);self.assertEqual(error['error'],'robot_scope_forbidden')

    def test_scope_check_cannot_be_bypassed_by_matching_lease_owner(self):
        client=self.operator();plane=self.runtime.control
        # Trusted fixture deliberately corrupts ownership to test scope as an
        # independent defense. HTTP does not have this mutation capability.
        plane.leases['beta','motion'].owner=client.session_id
        plane.leases['beta','motion'].epoch=1
        plane.leases['beta','motion'].expires=self.clock()+1.
        with self.assertRaisesRegex(Rejected,'robot_scope_forbidden'):
            plane.control(client._token,'beta','motion',1,0,
                          dict(frame='base_link',vx_mps=0.,vy_mps=0.,wz_rps=0.),.1)

    def test_unclaimed_operator_camera_is_pixels_without_any_pose(self):
        self.runtime.camera=FakeDisplayCamera();client=self.operator();client.watch('alpha')
        frame=client.frame()
        self.assertEqual(frame['source'],'operator_camera_display_v1')
        self.assertEqual(frame['image']['data_base64'],'QUJD')
        self.assertEqual(frame['calibration']['extrinsics']['translation_m'],[.24,0.,.06])
        self.assertEqual(frame['capture_wall_monotonic'],1000.)
        self.assertNotIn('hp',client.state()['robots'][0])
        wire=json.dumps(frame)
        for sentinel in ('OWN_WORLD','FUTURE_POSE','IMAGE_TRUTH','INTRINSIC_TRUTH','EXTRINSIC_TRUTH','PROFILE_WORLD_POSE'):
            self.assertNotIn(sentinel,wire)
        for key in ('own_qpos_at_capture','own_qvel_at_capture','own_odom_at_capture','profile'):
            self.assertNotIn(key,wire)

    def test_explicit_audit_grant_preserves_spectator_truth(self):
        self.runtime.camera=FakeDisplayCamera()
        audit=PlatformClient(self.url,admission_credential=AUDIT_CREDENTIAL);self.clients.append(audit)
        audit.open('spectator');self.assertTrue(audit.audit_authorized)
        audit.watch('alpha')
        self.assertEqual(audit.frame()['own_odom_at_capture'],['OWN_WORLD_ODOM'])
        self.assertIn('xy',audit.state()['robots'][1])
        with self.assertRaisesRegex(ClientError,'read only'):audit.claim('alpha',['motion'])

    def test_credentials_are_absent_from_session_reply_state_and_repr(self):
        client=self.operator()
        reply=client.state()
        wire=json.dumps(reply)+repr(client)+repr(self.server.config.admission_policy)
        self.assertNotIn(OPERATOR_CREDENTIAL,wire);self.assertNotIn(AUDIT_CREDENTIAL,wire)
        client.close();opened=client.open('operator')
        self.assertNotIn('token',opened);self.assertNotIn('credential',opened)
        self.assertNotIn(OPERATOR_CREDENTIAL,json.dumps(opened))

    def test_missing_policy_denies_enrollment_even_on_loopback(self):
        server=PlatformHTTPServer(TransportConfig(port=0),self.runtime)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
        try:
            client=PlatformClient('http://127.0.0.1:'+str(server.server_address[1]),admission_credential=OPERATOR_CREDENTIAL)
            with self.assertRaisesRegex(ClientError,'admission_policy_required'):client.open('operator')
        finally:server.shutdown();server.server_close();thread.join(1)


class ManifestAndProjectionTests(unittest.TestCase):
    def test_manifest_is_bounded_exact_and_role_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'admission.local.json'
            row=dict(credential_sha256=hashlib.sha256(OPERATOR_CREDENTIAL.encode()).hexdigest(),
                     role='operator',allowed_robots=['alpha'],audit_authorized=False)
            path.write_text(json.dumps(dict(schema='polar.sim.admission.v1',grants=[row])))
            policy=AdmissionPolicy.from_manifest(path);policy.validate_robots(['alpha'])
            self.assertEqual(policy.authenticate('operator',OPERATOR_CREDENTIAL).allowed_robots,('alpha',))
            with self.assertRaises(ValueError):policy.validate_robots(['beta'])
            for invalid in [dict(row,role='spectator'),dict(row,allowed_robots=[]),dict(row,audit_authorized=True)]:
                with self.subTest(invalid=invalid),self.assertRaises(ValueError):AdmissionPolicy([invalid])
            path.write_text('{"schema":"polar.sim.admission.v1","schema":"bad","grants":[]}')
            with self.assertRaises(ValueError):AdmissionPolicy.from_manifest(path)
            path.write_text('x'*65537)
            with self.assertRaises(ValueError):AdmissionPolicy.from_manifest(path)

    def test_camera_projection_unavailable_has_no_image_pose_or_calibration(self):
        raw=dict(camera_fixture(),available=False,reason='camera_expired')
        projected=operator_camera_display(raw)
        self.assertFalse(projected['available']);self.assertEqual(projected['reason'],'camera_expired')
        self.assertNotIn('image',projected);self.assertNotIn('calibration',projected)
        self.assertNotIn('own_qpos_at_capture',projected)

    def test_direct_sessions_are_explicit_trusted_admin_not_http_grants(self):
        runtime=PlatformRuntime(FakeBackend())
        try:
            direct=runtime.control.open_session('spectator')
            self.assertTrue(runtime.control.sessions[direct['session_id']].trusted_admin)
            self.assertTrue(direct['audit_authorized'])
            with self.assertRaisesRegex(Rejected,'operator_scope_required'):
                runtime.control.open_session('operator',trusted_admin=False)
            with self.assertRaisesRegex(Rejected,'audit_authorization_required'):
                runtime.control.open_session('spectator',trusted_admin=False,audit_authorized=False)
        finally:runtime.close()


if __name__=='__main__':unittest.main()
