"""CLI lifecycle mocks only: no physics, WSL, ROS, GL or navigation algorithm."""
import contextlib
import io
import json
from pathlib import Path
import signal
import unittest
from unittest.mock import patch

from rm_match.platform_v2 import __main__ as cli


class CliLifecycleTests(unittest.TestCase):
    def setup(self, fail=None, cleanup_fail=None):
        events=[];created={};handlers={}
        def check(name):
            events.append(name)
            if fail==name:raise ValueError(name+'_failed')
        def closing(name):
            events.append(name)
            if cleanup_fail==name:raise RuntimeError(name+'_failed')
        class Session:
            def __init__(self,*args,**kw):
                check('session_create');created['session']=self;self.namespace='/polar_sil_'+('f'*32)+'/red_sentry'
            def prepare(self):check('session_prepare')
            def request_stop(self):closing('session_stop')
            def close(self):closing('session_close')
        class Backend:
            def __init__(self,**kw):check('backend');self._sim=object();created['backend_kwargs']=kw
            def close(self):closing('backend_close')
        class Runtime:
            def __init__(self,*args,**kw):check('runtime');self.shutdown_status={'clean':True};created['runtime_kwargs']=kw
            def run(self,**kw):
                created['run_kwargs']=kw;check('run')
                if fail=='signal':handlers[signal.SIGTERM]()
            def request_stop(self):closing('runtime_stop')
            def close(self):closing('runtime_close')
        class Server:
            def __init__(self,*args,**kw):check('server');self.server_address=('127.0.0.1',8677)
            def serve_forever(self):pass
            def shutdown(self):closing('http_shutdown');created['http']._alive=False
            def server_close(self):closing('http_close')
        class Thread:
            def __init__(self,*args,**kw):created['http']=self;self._alive=False
            def start(self):check('http_start');self._alive=True
            def join(self,timeout):closing('http_join')
            def is_alive(self):return self._alive
        class Camera:
            def __init__(self,*args,**kw):check('camera')
            def stop(self):closing('camera_stop')
            def wait_closed(self,timeout):closing('camera_close');return cleanup_fail!='camera_unfinished'
        class Sensors:
            def __init__(self):check('sensor_config')
            def identity(self):return {'profile':'fixture_only'}
        def registry(**kw):created['registry_kwargs']=kw;check('registry');return object()
        def register(reg,path,*,repo_root,session_factory,**kw):
            created['manifest']=path;created['repo_root']=repo_root
            session=session_factory();session.prepare();check('registration');return session
        def signum(s,h):handlers[s]=h
        stack=contextlib.ExitStack();self.addCleanup(stack.close)
        for obj,name,value in [(cli.sys,'platform','win32'),(cli,'MuJoCoBackend',Backend),
            (cli,'PlatformRuntime',Runtime),(cli,'PlatformHTTPServer',Server),(cli.threading,'Thread',Thread),
            (cli.signal,'getsignal',lambda s:object()),(cli.signal,'signal',signum)]:stack.enter_context(patch.object(obj,name,value))
        stack.enter_context(patch('rm_match.platform_v2.admission.AdmissionPolicy.from_manifest',return_value=object()))
        stack.enter_context(patch('rm_match.platform_v2.adapters.default_registry',side_effect=registry))
        stack.enter_context(patch('rm_match.integrations.pb_wsl_navigation_registry.register_pb_wsl_navigation',side_effect=register))
        stack.enter_context(patch('rm_match.integrations.pb_wsl_navigation.WslNavigationSession',Session))
        stack.enter_context(patch('rm_match.navigation_sensors.NavigationSensorConfig',Sensors))
        stack.enter_context(patch('rm_match.platform_v2.camera.CameraProvider',Camera))
        created['stdout']=io.StringIO()
        stack.enter_context(contextlib.redirect_stdout(created['stdout']))
        stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        return events,created
    def args(self,extra=()):
        return ['--admission-manifest','fixture-admission.json','--pb-wsl-navigation-manifest','fixture-wsl.json',
                '--max-wall-seconds','1','--real-time-factor','0.8',*extra]
    def test_session_prepared_before_any_backend_and_existing_runtime_limits(self):
        events,created=self.setup();cli.main(self.args())
        self.assertLess(events.index('session_prepare'),events.index('backend'))
        self.assertLess(events.index('registration'),events.index('sensor_config'))
        self.assertEqual(created['manifest'],'fixture-wsl.json')
        self.assertEqual(created['repo_root'],Path(cli.__file__).resolve().parents[2])
        self.assertIsNotNone(created['backend_kwargs']['navigation_sensors'])
        self.assertEqual(created['run_kwargs'],dict(max_wall_seconds=1.,real_time_factor=.8))
        self.assertIn('session_stop',events);self.assertIn('session_close',events)
        startup=json.loads(created['stdout'].getvalue())
        self.assertEqual(startup['pb_wsl_navigation_namespace'],created['session'].namespace)
        self.assertEqual(startup['pb_wsl_navigation_domain'],84)
    def test_failure_at_each_setup_or_run_phase_always_closes_owned_session(self):
        for stage in ('session_prepare','registration','backend','camera','runtime','server','http_start','run'):
            with self.subTest(stage=stage):
                # Per-subtest nested patches restore the previous mocks on exit.
                events,_=self.setup(fail=stage)
                with self.assertRaisesRegex(ValueError,stage+'_failed'):cli.main(self.args(['--camera']))
                self.assertIn('session_stop',events);self.assertIn('session_close',events)
                if stage=='http_start':
                    self.assertNotIn('http_shutdown',events);self.assertIn('http_close',events)
    def test_cleanup_failure_is_not_swallowed_and_original_error_is_cause(self):
        events,_=self.setup(fail='server',cleanup_fail='session_close')
        with self.assertRaisesRegex(RuntimeError,'session_close_failed') as result:cli.main(self.args())
        self.assertIsInstance(result.exception.__cause__,ValueError)
        self.assertEqual(str(result.exception.__cause__),'server_failed')
        self.assertIn('runtime_close',events)
    def test_prepare_failure_does_not_lose_session_cleanup_exception(self):
        events,_=self.setup(fail='session_prepare',cleanup_fail='session_close')
        with self.assertRaisesRegex(RuntimeError,'session_close_failed') as result:cli.main(self.args())
        self.assertEqual(str(result.exception.__cause__),'session_prepare_failed')
        self.assertNotIn('backend',events)
    def test_http_shutdown_failure_still_closes_runtime_and_session(self):
        events,_=self.setup(cleanup_fail='http_shutdown')
        with self.assertRaisesRegex(RuntimeError,'http_shutdown_failed'):cli.main(self.args())
        self.assertIn('http_close',events);self.assertIn('runtime_close',events);self.assertIn('session_close',events)
    def test_camera_join_failure_is_visible_after_session_cleanup(self):
        events,_=self.setup(cleanup_fail='camera_unfinished')
        with self.assertRaisesRegex(RuntimeError,'camera_threads_unfinished'):cli.main(self.args(['--camera']))
        self.assertIn('session_close',events);self.assertIn('camera_stop',events)
    def test_signal_revokes_runtime_and_cancels_session(self):
        events,_=self.setup(fail='signal');cli.main(self.args())
        self.assertGreaterEqual(events.count('session_stop'),2)
        self.assertGreaterEqual(events.count('runtime_stop'),2)
    def test_navigation_manifests_are_mutually_exclusive_before_preparation(self):
        events,_=self.setup()
        with self.assertRaises(SystemExit):cli.main(self.args(['--pb-navigation-manifest','other.json']))
        self.assertNotIn('registry',events);self.assertNotIn('session_create',events)
    def test_windows_option_rejected_on_linux_before_initialization(self):
        events,_=self.setup()
        with patch.object(cli.sys,'platform','linux'),self.assertRaises(SystemExit):cli.main(self.args())
        self.assertFalse(events)
    def test_default_server_has_no_wsl_session_or_navigation_sensors(self):
        events,created=self.setup();cli.main(['--admission-manifest','fixture-admission.json','--max-wall-seconds','1'])
        self.assertNotIn('session_create',events);self.assertIsNone(created['backend_kwargs']['navigation_sensors'])
        startup=json.loads(created['stdout'].getvalue())
        self.assertIsNone(startup['pb_wsl_navigation_namespace']);self.assertIsNone(startup['pb_wsl_navigation_domain'])
    def test_existing_local_navigation_and_native_options_remain_independent(self):
        events,created=self.setup()
        with patch('rm_match.integrations.pb_navigation_adapter.register_pb_navigation') as local:
            cli.main(['--admission-manifest','fixture-admission.json','--pb-navigation-manifest','local.json',
                '--native-spec','native-spec.json','--native-out','native-output','--camera'])
        self.assertEqual(local.call_args.args[1],'local.json')
        self.assertEqual(created['registry_kwargs'],dict(native_spec='native-spec.json',native_out='native-output'))
        self.assertIsNotNone(created['backend_kwargs']['navigation_sensors'])
        self.assertNotIn('session_create',events)


if __name__=='__main__':unittest.main()
