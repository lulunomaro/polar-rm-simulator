"""Synthetic deployment/JSON boundaries only. No physics, rendering or native inference."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from rm_match.deployment import profile
from rm_match.deployment import launcher
from rm_match.deployment.json_adapter import (SCHEMA, JsonLineAdapter,
    load_registrations, register_json_adapters)
from rm_match.platform_v2.adapters import Registry
from rm_match.platform_v2.contracts import ContractError
from rm_match.platform_v2.test_contracts import sample

ROOT = Path(__file__).resolve().parents[1]


def hash_bytes(value):
    return hashlib.sha256(value).hexdigest()


@contextmanager
def native_fixture():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        header = bytearray(20); header[:6] = b'\x7fELF\x02\x01'; header[18:20] = (62).to_bytes(2, 'little')
        (root / 'binary').write_bytes(header)
        (root / 'config').write_bytes(b'{}')
        model = root / 'shenzhen-0526.onnx'; model.write_bytes(b'synthetic model, never executed')
        source = dict(base_commit=profile.T2_BASE, patch_sha256=profile.T2_PATCH,
                      is_original_upstream=False, is_baseline_40f7=False)
        build = dict(status='native_build_succeeded', full_clean_compile=True,
                     binary_sha256=profile.digest(root / 'binary'), input_identity={'algorithm_identity': source})
        manifest = root / 'BUILD_MANIFEST.json'; manifest.write_text(json.dumps(build))
        mode = hash_bytes(b'multi_ekf\n')
        value = dict(operator_identity='rmcs-sim-operator-fov-v1', binary=str(root / 'binary'),
            executor_yaml=str(root / 'config'), autoaim_config=str(root / 'config'), model_share=str(root),
            model_sha256=profile.digest(model), source_identity=source,
            sha256=dict(binary=profile.digest(root / 'binary'), executor_yaml=profile.digest(root / 'config'),
                        autoaim_config=profile.digest(root / 'config'), runtime_mode=mode),
            frozen_build=dict(binary_sha256=profile.digest(root / 'binary'), manifest_sha256=profile.digest(manifest)),
            runtime_mode_contents='multi_ekf\n', runtime_mode_sha256=mode)
        path = root / 'operator_source.local.json'; path.write_text(json.dumps(value))
        with patch.object(profile, 'MODEL_SHA256', value['model_sha256']):
            yield root, path, value


def args(**overrides):
    values = dict(port=8766, max_wall_seconds=300., camera_fps=15., real_time_factor=1.,
        client_root=ROOT / 'external/missing-client', out=ROOT / 'artifacts/test-plan',
        native_spec=ROOT / 'missing.local.json', sim_python=Path(sys.executable),
        client_python=Path('/missing/client/python'), adapters_json=None, gl='egl')
    values.update(overrides)
    return SimpleNamespace(**values)


class ProfileTests(unittest.TestCase):
    def test_own_registry_never_contains_baseline(self):
        with native_fixture() as (root, path, _):
            reg = profile.own_registry(path, root / 'out')
            self.assertEqual([r['adapter_id'] for r in reg.descriptors()], ['aim_native_rmcs_v1'])
            d = reg.descriptors()[0]
            self.assertTrue(d['stationary_only']); self.assertEqual(d['fire_authority'], 'manual_only')
            self.assertEqual(d['supported_robots'], ['red_sentry'])
            self.assertEqual(d['source_identity']['patch_sha256'], profile.T2_PATCH)
            with self.assertRaises(ContractError):
                reg.create('aim_pixel_baseline_v1', {})

    def test_rejects_missing_t2_or_baseline_identity(self):
        with native_fixture() as (_, path, value):
            for changes in ({'base_commit': '40f7'}, {'patch_sha256': '0' * 64},
                            {'is_original_upstream': True}, {'is_baseline_40f7': True}):
                v = deepcopy(value); v['source_identity'].update(changes); path.write_text(json.dumps(v))
                with self.assertRaises(ValueError):
                    profile.validate_t2_spec(path)

    def test_requires_matching_build_manifest(self):
        with native_fixture() as (root, path, _):
            (root / 'BUILD_MANIFEST.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'manifest hash'):
                profile.validate_t2_spec(path)

    def test_rejects_model_change(self):
        with native_fixture() as (root, path, _):
            (root / 'shenzhen-0526.onnx').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'model_hash'):
                profile.validate_t2_spec(path)

    def test_rejects_relative_runtime_paths(self):
        with native_fixture() as (_, path, value):
            value['binary'] = 'binary'; path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'absolute'):
                profile.validate_t2_spec(path)

    def test_rechecks_registered_spec_before_binding(self):
        with native_fixture() as (root, path, _):
            reg = profile.own_registry(path, root / 'out')
            path.write_text(path.read_text() + ' ')
            with self.assertRaisesRegex(ValueError, 'changed_after_registration'):
                reg.create('aim_native_rmcs_v1', {})

    def test_duplicate_json_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'manifest'; path.write_text('{"schema":1,"schema":2}')
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                profile.read_json(path)


class LauncherTests(unittest.TestCase):
    def test_plan_starts_nothing_and_defaults_to_own_profile(self):
        with patch('subprocess.Popen') as popen, patch('subprocess.run') as run:
            p = launcher.plan(args())
            self.assertEqual(p['profile'], profile.PROFILE)
            self.assertIn('rm_match.deployment.server', p['server_argv'])
            self.assertIn('--sim-platform-v2', p['client_argv'])
            self.assertFalse(p['automatic_binding'])
            self.assertEqual(p['client_commit'], profile.CLIENT_COMMIT)
            popen.assert_not_called(); run.assert_not_called()

    def test_dry_setup_immutable_pin_no_install_no_submodules(self):
        with tempfile.TemporaryDirectory() as td, patch('subprocess.run') as run:
            value = launcher.setup_client(Path(td) / 'client')
            self.assertEqual(value['commands'][2][-1], profile.CLIENT_COMMIT)
            self.assertEqual(len(profile.CLIENT_COMMIT), 40)
            self.assertIn('polar-rm-client.git', value['repository'])
            self.assertFalse(value['executed']); run.assert_not_called()

    def test_existing_client_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, 'exists'):
                launcher.setup_client(td, run=True)

    def test_preserves_venv_python_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'python'; path.symlink_to(sys.executable)
            self.assertEqual(launcher.executable(path), str(path))
            self.assertNotEqual(launcher.executable(path), str(path.resolve()))

    def test_plan_rejects_unbounded_values(self):
        for overrides in ({'camera_fps': float('nan')}, {'camera_fps': 16},
                          {'real_time_factor': 2}, {'max_wall_seconds': float('inf')}, {'port': 80}):
            with self.assertRaises(ValueError):
                launcher.plan(args(**overrides))

    def test_server_ready_requires_native_identity(self):
        p = launcher.plan(args())
        ready = dict(event='ready', profile=profile.PROFILE, url=p['url'], spec_sha256='a',
                     native_registered=True, transport='loopback_only', automatic_binding=False,
                     fire_authority='manual_only', adapter_ids=['aim_native_rmcs_v1'])
        launcher.verify_ready(ready, p, 'a')
        for changes in ({'profile': 'manual'}, {'native_registered': False}, {'spec_sha256': 'b'},
                        {'automatic_binding': True}, {'fire_authority': 'native'}, {'adapter_ids': []}):
            with self.assertRaises(ValueError):
                launcher.verify_ready(dict(ready, **changes), p, 'a')

    def test_doctor_reports_dependencies_and_still_blocks_nonlinux(self):
        p = launcher.plan(args())
        with patch.object(launcher.sys, 'platform', 'win32'), \
             patch.object(launcher, 'python_probe', return_value={'test': True}), \
             patch.object(launcher, 'check_client', return_value={'commit': profile.CLIENT_COMMIT}), \
             patch.object(launcher, 'run_checked', side_effect=FileNotFoundError('native spec missing')), \
             patch.dict(os.environ, {}, clear=True):
            report = launcher.doctor(p)
        self.assertFalse(report['ready_to_attempt'])
        self.assertTrue(next(c for c in report['checks'] if c['name'] == 'client_python_dependencies')['ok'])
        self.assertFalse(next(c for c in report['checks'] if c['name'] == 'native_host')['ok'])
        self.assertFalse(next(c for c in report['checks'] if c['name'] == 'visible_desktop')['ok'])

    def test_launch_does_not_start_on_failed_doctor(self):
        with patch.object(launcher, 'doctor', return_value={'ready_to_attempt': False}), patch('subprocess.Popen') as popen:
            self.assertEqual(launcher.launch(launcher.plan(args())), 2)
            popen.assert_not_called()


class JsonAdapterTests(unittest.TestCase):
    def adapter(self, kind='navigation'):
        registry = Registry(); path = ROOT / 'examples/adapters.json'
        register_json_adapters(registry, path)
        return registry.create('custom_' + kind + '_example', {})

    def observation(self):
        o = sample(); o['wall_deadline'] = time.monotonic() + 2.
        return o

    def test_json_navigation_and_aim_example(self):
        for kind in ('navigation', 'aim'):
            a = self.adapter(kind)
            try:
                o = self.observation(); a.reset({k: o[k] for k in ('episode', 'robot_id', 'binding_epoch')})
                result = a.act(o)
                self.assertEqual(result['kind'], kind)
                if kind == 'navigation':
                    self.assertEqual(result['command']['vx_mps'], 0.)
                else:
                    self.assertFalse(result['command']['active']); self.assertFalse(result['command']['fire_permission'])
            finally:
                a.close()

    def test_json_deadline_does_not_run_old_observation(self):
        a = self.adapter()
        try:
            o = self.observation(); a.reset({k: o[k] for k in ('episode', 'robot_id', 'binding_epoch')})
            o['wall_deadline'] = time.monotonic() - .01
            with self.assertRaisesRegex(ContractError, 'expired'):
                a.act(o)
        finally:
            a.close()

    def process_fixture(self, code):
        td = tempfile.TemporaryDirectory(); path = Path(td.name) / 'manifest.json'
        row = dict(adapter_id='custom_probe', kind='navigation', label='Synthetic pipe probe',
                   command=[sys.executable, '-u', '-c', code], cwd=td.name, required_sensors=[])
        path.write_text(json.dumps(dict(schema=SCHEMA, adapters=[row])))
        registry = Registry(); register_json_adapters(registry, path)
        return td, registry.create('custom_probe', {})

    def test_custom_timeout_kills_child_no_fallback(self):
        code = "import json,sys,time; r=json.loads(input()); print(json.dumps(dict(schema=r['schema'],op='reset',ok=True)),flush=True); input(); time.sleep(10)"
        td, a = self.process_fixture(code)
        try:
            o = self.observation(); a.reset({k: o[k] for k in ('episode', 'robot_id', 'binding_epoch')})
            child = a.process; o['wall_deadline'] = time.monotonic() + .025
            with self.assertRaises(Exception):
                a.act(o)
            self.assertTrue(a.failed); self.assertIsNotNone(child.poll())
        finally:
            a.close(); td.cleanup()

    def test_custom_oversized_response_is_rejected(self):
        td, a = self.process_fixture("input(); print('x'*70000,flush=True)")
        try:
            with self.assertRaisesRegex(ContractError, 'oversized'):
                a.reset(dict(robot_id='red_sentry', episode=1, binding_epoch=1))
            self.assertTrue(a.failed)
        finally:
            a.close(); td.cleanup()

    def test_custom_duplicate_response_keys_are_rejected(self):
        td, a = self.process_fixture('input(); print(\'{"schema":"polar.sim.adapter.jsonl.v1","op":"reset","ok":true,"ok":true}\',flush=True)')
        try:
            with self.assertRaisesRegex(ContractError, 'duplicate'):
                a.reset(dict(robot_id='red_sentry', episode=1, binding_epoch=1))
        finally:
            a.close(); td.cleanup()

    def test_serialization_cannot_refresh_action_timeout(self):
        a = self.adapter()
        try:
            o = self.observation(); a.reset({k: o[k] for k in ('episode', 'robot_id', 'binding_epoch')})
            with patch.object(a.requests, 'put_nowait', wraps=a.requests.put_nowait) as sent, \
                 patch('rm_match.deployment.json_adapter.time.monotonic', side_effect=[10., 11.]):
                with self.assertRaisesRegex(TimeoutError, 'during_serialization'):
                    a._exchange(dict(op='act', observation=o), timeout=.1)
                self.assertTrue(all(call.args == (None,) for call in sent.call_args_list))
            self.assertTrue(a.failed)
        finally:
            a.close()

    def test_call_boundary_cannot_shift_server_deadline(self):
        a = self.adapter()
        try:
            o = self.observation(); a.reset({k: o[k] for k in ('episode', 'robot_id', 'binding_epoch')})
            o['wall_deadline'] = 10.1
            with patch.object(a.requests, 'put_nowait', wraps=a.requests.put_nowait) as sent, \
                 patch('rm_match.deployment.json_adapter.time.monotonic', side_effect=[10., 10.2, 10.21]):
                with self.assertRaisesRegex(TimeoutError, 'during_serialization'):
                    a.act(o)
                self.assertTrue(all(call.args == (None,) for call in sent.call_args_list))
        finally:
            a.close()

    def test_manifest_cannot_replace_default_native_id(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'a.json'; value = profile.read_json(ROOT / 'examples/adapters.json')
            value['adapters'][0]['adapter_id'] = 'aim_native_rmcs_v1'; path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ContractError, 'custom_adapter_id'):
                load_registrations(path)

    def test_network_config_cannot_supply_executable(self):
        registry = Registry(); register_json_adapters(registry, ROOT / 'examples/adapters.json')
        a = registry.create('custom_navigation_example', {'command': ['not-executed']})
        try:
            o = self.observation(); a.reset({k: o[k] for k in ('episode', 'robot_id', 'binding_epoch')})
            self.assertEqual(a.act(o)['command']['vx_mps'], 0.)
        finally:
            a.close()

    def test_manifest_changed_after_registration_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'a.json'; value = profile.read_json(ROOT / 'examples/adapters.json')
            for row in value['adapters']:
                row['cwd'] = str(ROOT / 'examples')
            path.write_text(json.dumps(value))
            registry = Registry(); register_json_adapters(registry, path); path.write_text(path.read_text() + ' ')
            a = registry.create('custom_navigation_example', {})
            with self.assertRaisesRegex(ContractError, 'changed_after_registration'):
                a.reset(dict(robot_id='red_sentry', episode=1, binding_epoch=1))


class SmokeClassificationTests(unittest.TestCase):
    def classify(self, **overrides):
        from tools.smoke_deployment import classify_result
        values = dict(steps=1, camera={'rendered':1}, counts={'native_request':1,
            'native_result':1,'red_native_gimbal_consumed':1,'fire_outputs_true':0},
            driver={'session_closed':True}, errors=[], resources_closed=True, driver_exit=0, qt_requested=False)
        values.update(overrides)
        return classify_result(**values)

    def test_missing_qt_report_is_incomplete_without_crash(self):
        value = self.classify(qt_requested=True, driver={'session_closed':True,'qt_exit_code':0,'qt_offscreen':None})
        self.assertEqual(value['result'], 'incomplete_or_failed_bounded_smoke')

    def test_nonzero_driver_exit_cannot_pass_cleanup(self):
        value = self.classify(driver_exit=1)
        self.assertFalse(value['clean_shutdown'])
        self.assertEqual(value['result'], 'incomplete_or_failed_bounded_smoke')

    def test_without_qt_success_has_explicit_native_only_scope(self):
        self.assertEqual(self.classify()['result'], 'passed_bounded_native_only_smoke')


if __name__ == '__main__':
    unittest.main()
