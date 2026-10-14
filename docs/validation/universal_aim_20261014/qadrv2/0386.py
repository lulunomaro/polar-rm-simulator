"""CLI resource lifecycle mocks; no WSL, GL, model or physical acceptance."""
import contextlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from rm_match.platform_v2 import __main__ as cli

class AimPreparationCliTests(unittest.TestCase):
    def setup_fixture(self,fail=None,cleanup_fail=None):
        # Reuse the existing CLI's backend/thread fixture without collecting its
        # test class twice or starting any process.
        path=Path(__file__).with_name('test_platform_wsl_navigation_cli.py')
        spec=importlib.util.spec_from_file_location('_aim_cli_lifecycle_fixture',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        events,created=module.CliLifecycleTests.setup(self,fail=fail,cleanup_fail=cleanup_fail)
        class Pool:
            def __init__(self,path,**kwargs):
                events.append('aim_prepare');created['aim_pool']=self;self.instances={'example':object()}
            def close_unclaimed(self):
                events.append('aim_close')
                if cleanup_fail=='aim_close':raise RuntimeError('aim_close_failed')
        def register(registry,path,*,wsl_prepared=None):
            events.append('aim_register');created['aim_registration_pool']=wsl_prepared
        stack=contextlib.ExitStack();self.addCleanup(stack.close)
        stack.enter_context(patch('rm_match.deployment.wsl_jsonl.PreparedWslAimPlugins',Pool))
        stack.enter_context(patch('rm_match.deployment.aim_plugin.register_aim_plugins',side_effect=register))
        return events,created
    def args(self):
        return ['--admission-manifest','fixture.json','--camera','--max-wall-seconds','1',
                '--aim-plugins-json','fixture-aim.json','--prepare-aim-plugins']
    def test_explicit_prepare_precedes_backend_and_registry_receives_same_pool(self):
        events,created=self.setup_fixture();cli.main(self.args())
        self.assertLess(events.index('aim_prepare'),events.index('backend'))
        self.assertIs(created['aim_registration_pool'],created['aim_pool'])
        self.assertIn('runtime_close',events);self.assertIn('aim_close',events)
        self.assertEqual(json.loads(created['stdout'].getvalue())['prepared_aim_plugin_count'],1)
    def test_backend_or_run_failure_closes_unclaimed_resources(self):
        for stage in ('backend','server','run'):
            with self.subTest(stage=stage):
                events,_=self.setup_fixture(fail=stage)
                with self.assertRaisesRegex(ValueError,stage+'_failed'):cli.main(self.args())
                self.assertIn('aim_close',events)
    def test_cleanup_failure_retains_original_error(self):
        events,_=self.setup_fixture(fail='backend',cleanup_fail='aim_close')
        with self.assertRaisesRegex(RuntimeError,'aim_close_failed') as error:cli.main(self.args())
        self.assertIsInstance(error.exception.__cause__,ValueError)
        self.assertIn('aim_close',events)
    def test_without_explicit_prepare_does_not_create_pool(self):
        events,created=self.setup_fixture();cli.main(self.args()[:-1])
        self.assertNotIn('aim_prepare',events);self.assertIsNone(created['aim_registration_pool'])
    def test_invalid_prepare_host_or_missing_manifest_is_rejected_before_initialization(self):
        events,_=self.setup_fixture()
        with patch.object(cli.sys,'platform','linux'),self.assertRaises(SystemExit):cli.main(self.args())
        self.assertNotIn('registry',events)

    def test_wsl_native_is_prepared_before_physics_and_closed_on_backend_failure(self):
        from unittest.mock import Mock
        for fail in (None,'backend'):
            with self.subTest(fail=fail):
                events,created=self.setup_fixture(fail=fail)
                registry=Mock()
                registry.prepare_native.side_effect=lambda:events.append('native_prepare')
                registry.close.side_effect=lambda:events.append('native_close')
                args=['--admission-manifest','fixture.json','--camera','--wsl-native-spec','native.json',
                    '--native-out','owned-artifacts','--wsl-native-transport','wsl_async_bgr_v3',
                    '--private-native-pixels','--max-wall-seconds','1']
                with patch('rm_match.deployment.wsl_registry.own_wsl_registry',return_value=registry) as make:
                    if fail:
                        with self.assertRaisesRegex(ValueError,'backend_failed'):cli.main(args)
                    else:cli.main(args)
                self.assertLess(events.index('native_prepare'),events.index('backend'))
                self.assertIn('native_close',events)
                self.assertEqual(make.call_args.kwargs['transport'],'wsl_async_bgr_v3')
                if not fail:self.assertTrue(json.loads(created['stdout'].getvalue())['wsl_native_registered'])
        with self.assertRaises(SystemExit):cli.main(['--admission-manifest','fixture.json','--prepare-aim-plugins'])
        self.assertNotIn('registry',events)
