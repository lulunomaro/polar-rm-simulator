"""CLI lifecycle mocks only: no physics, WSL, ROS, GL or navigation algorithm."""
import contextlib
import copy
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
            def __init__(self,*,robot_ids):
                check('sensor_config');self.robot_ids=tuple(robot_ids)
                created['sensor_robot_ids']=self.robot_ids
            def identity(self):return {'profile':'fixture_only','robot_ids':list(self.robot_ids)}
        class Registry:
            def __init__(self):self.catalog=[]
            def plugin_catalog(self):return copy.deepcopy(self.catalog)
        def registry(**kw):
            created['registry_kwargs']=kw;check('registry')
            created['registry']=Registry();return created['registry']
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
    def generic_args(self,extra=()):
        return ['--admission-manifest','fixture-admission.json','--robotio-plugins-json','fixture-robotio.json',
                '--max-wall-seconds','1',*extra]
    def setup_robotio(self,events,created,*,robots=('red_infantry','blue_sentry'),categories=('navigation','decision'),
                      fail=None,cleanup_fail=None,prepare=False):
        """Trusted registered-metadata/lifecycle fixtures, not protocol bypasses."""
        def checked(name):
            events.append(name)
            if fail==name:raise ValueError(name+'_failed')
        class Pool:
            def __init__(self,category):self.category=category
            def close_unclaimed(self,*,deadline):
                name=self.category+'_pool_close';events.append(name)
                created.setdefault('pool_close_deadlines',[]).append((self.category,deadline))
                if cleanup_fail==name:raise RuntimeError(name+'_failed')
        pools={category:Pool(category) for category in categories} if prepare else {}
        def prepare_resources(path,*,repo_root,shared_root):
            created['robotio_prepare_args']=dict(path=path,repo_root=repo_root,shared_root=shared_root)
            checked('robotio_prepare');return pools
        def register_resources(reg,path,*,wsl_prepared):
            created['robotio_registration_args']=dict(path=path,wsl_prepared=wsl_prepared)
            checked('robotio_registration')
            reg.catalog=[dict(category=category,plugin_id='custom_fixture_'+category,supported_robots=list(robots))
                         for category in categories]
            return dict(schema='polar.sim.robotio-plugins.v1',manifest_sha256='f'*64,
                        registered_adapter_ids=['custom_fixture_'+category for category in categories],
                        navigation_robots=list(robots) if 'navigation' in categories else [])
        stack=contextlib.ExitStack();self.addCleanup(stack.close)
        stack.enter_context(patch('rm_match.deployment.robotio_plugin.prepare_robotio_resources',side_effect=prepare_resources))
        stack.enter_context(patch('rm_match.deployment.robotio_plugin.register_robotio_plugins',side_effect=register_resources))
        created['robotio_pools']=pools
    def test_session_prepared_before_any_backend_and_existing_runtime_limits(self):
        events,created=self.setup();cli.main(self.args())
        self.assertLess(events.index('session_prepare'),events.index('backend'))
        self.assertLess(events.index('registration'),events.index('sensor_config'))
        self.assertEqual(created['manifest'],'fixture-wsl.json')
        self.assertEqual(created['repo_root'],Path(cli.__file__).resolve().parents[2])
        self.assertIsNotNone(created['backend_kwargs']['navigation_sensors'])
        self.assertEqual(created['sensor_robot_ids'],('red_sentry',))
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
        self.assertEqual(created['sensor_robot_ids'],('red_sentry',))
        self.assertNotIn('session_create',events)

    def test_generic_navigation_scope_is_exact_manifest_union_without_legacy_sentry(self):
        events,created=self.setup();self.setup_robotio(events,created)
        cli.main(self.generic_args())
        self.assertEqual(created['sensor_robot_ids'],('blue_sentry','red_infantry'))
        self.assertNotIn('red_sentry',created['sensor_robot_ids'])
        self.assertNotIn('session_create',events);self.assertNotIn('robotio_prepare',events)
        startup=json.loads(created['stdout'].getvalue())
        self.assertEqual(startup['navigation_sensor_profile']['robot_ids'],['blue_sentry','red_infantry'])
        self.assertEqual(set(startup['robotio_plugins']['navigation_robots']),{'red_infantry','blue_sentry'})

    def test_generic_navigation_and_legacy_pb_scopes_merge_explicitly(self):
        events,created=self.setup();self.setup_robotio(events,created)
        cli.main(self.args(['--robotio-plugins-json','fixture-robotio.json']))
        self.assertEqual(created['sensor_robot_ids'],('blue_sentry','red_infantry','red_sentry'))
        self.assertLess(events.index('session_prepare'),events.index('backend'))
        self.assertIn('session_close',events)

    def test_generic_aim_catalog_without_camera_rejected_before_backend(self):
        events,created=self.setup();self.setup_robotio(events,created,categories=('aim',))
        with self.assertRaises(SystemExit):cli.main(self.generic_args())
        self.assertIn('robotio_registration',events)
        self.assertNotIn('sensor_config',events);self.assertNotIn('backend',events)
        self.assertNotIn('camera',events);self.assertNotIn('runtime',events)

    def test_generic_prepare_failure_stops_before_registration_or_backend(self):
        events,created=self.setup()
        self.setup_robotio(events,created,fail='robotio_prepare',prepare=True)
        with self.assertRaisesRegex(ValueError,'robotio_prepare_failed'):
            cli.main(self.generic_args(['--prepare-robotio-plugins']))
        self.assertNotIn('robotio_registration',events);self.assertNotIn('backend',events)
        self.assertEqual(created['robotio_prepare_args']['repo_root'],Path(cli.__file__).resolve().parents[2])
        self.assertEqual(created['robotio_prepare_args']['shared_root'],Path(cli.__file__).resolve().parents[2]/'artifacts/robotio-wsl')

    def test_generic_prepared_resources_share_cleanup_after_registration_or_late_failure(self):
        for stage in ('robotio_registration','server'):
            with self.subTest(stage=stage):
                events,created=self.setup(fail=stage if stage=='server' else None)
                self.setup_robotio(events,created,fail=stage if stage=='robotio_registration' else None,prepare=True)
                with patch.object(cli.time,'perf_counter',return_value=100.),self.assertRaisesRegex(ValueError,stage+'_failed'):
                    cli.main(self.generic_args(['--prepare-robotio-plugins']))
                self.assertIn('navigation_pool_close',events);self.assertIn('decision_pool_close',events)
                self.assertEqual(created['pool_close_deadlines'],[('navigation',101.5),('decision',101.5)])
                self.assertLess(events.index('robotio_prepare'),events.index('robotio_registration'))
                if stage=='server':self.assertIn('runtime_close',events)

    def test_generic_pool_cleanup_failure_still_closes_other_pool_and_preserves_cause(self):
        events,created=self.setup(fail='server')
        self.setup_robotio(events,created,prepare=True,cleanup_fail='navigation_pool_close')
        with patch.object(cli.time,'perf_counter',return_value=100.),self.assertRaisesRegex(RuntimeError,'navigation_pool_close_failed') as result:
            cli.main(self.generic_args(['--prepare-robotio-plugins']))
        self.assertIsInstance(result.exception.__cause__,ValueError)
        self.assertEqual(str(result.exception.__cause__),'server_failed')
        self.assertIn('decision_pool_close',events);self.assertIn('runtime_close',events)
        self.assertEqual(created['pool_close_deadlines'],[('navigation',101.5),('decision',101.5)])

    def test_generic_prepare_flags_require_manifest_and_windows_before_registry(self):
        events,created=self.setup()
        with self.assertRaises(SystemExit):
            cli.main(['--admission-manifest','fixture-admission.json','--prepare-robotio-plugins'])
        self.assertNotIn('registry',events)
        with patch.object(cli.sys,'platform','linux'),self.assertRaises(SystemExit):
            cli.main(self.generic_args(['--prepare-robotio-plugins']))
        self.assertNotIn('registry',events)


if __name__=='__main__':unittest.main()
