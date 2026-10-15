"""Synthetic launcher race boundaries only; no child process or native execution."""
from copy import deepcopy
import json
from unittest.mock import Mock, patch

import pytest

from rm_match.deployment import launcher
from rm_match.platform_v2.admission import AdmissionPolicy
from rm_match.platform_v2.native_robot_scope import load_native_robot_scope
from test_deployment import args


def scope_file(tmp_path):
    path = tmp_path / 'scope.json'
    path.write_text(json.dumps(dict(schema='polar.sim.native-robot-scope.v1', robots=[
        dict(robot_id='red_infantry', team='red', role='infantry', referee_id=1)])), encoding='utf8')
    return path


def deployment_plan(tmp_path, path):
    with patch.object(launcher, 'client_patch_identity', return_value={}):
        return launcher.plan(args(out=tmp_path / 'launch', native_robot_scope=path))


def doctor_report(path):
    return dict(ready_to_attempt=True, checks=[
        dict(name='native_robot_scope', ok=True, detail=load_native_robot_scope(path).declaration()),
        dict(name='own_t2_native_assets', ok=True, detail=dict(spec_sha256='a'))])


def ready_message(plan):
    return dict(event='ready', profile=launcher.PROFILE, url=plan['url'], spec_sha256='a',
        admission_policy_sha256=plan['admission_policy_sha256'], native_registered=True,
        transport='loopback_only', automatic_binding=False, fire_authority='manual_only',
        adapter_ids=['aim_native_rmcs_v1'])


@pytest.mark.parametrize('change', ['valid_replacement', 'raw_bytes_only'])
def test_doctor_scope_change_blocks_launch_before_output_or_process(tmp_path, change):
    path = scope_file(tmp_path)
    plan = deployment_plan(tmp_path, path)
    report = doctor_report(path)

    def checked_then_replaced(_):
        if change == 'raw_bytes_only':
            path.write_bytes(path.read_bytes() + b' ')
        else:
            value = json.loads(path.read_text(encoding='utf8'))
            value['robots'][0]['referee_id'] = 3
            path.write_text(json.dumps(value), encoding='utf8')
        return report

    with patch.object(launcher, 'doctor', side_effect=checked_then_replaced), \
            patch('rm_match.deployment.enrollment.provision_operator') as provision, \
            patch.object(launcher.subprocess, 'Popen') as popen:
        with pytest.raises(ValueError, match='native_robot_scope_changed_after_doctor'):
            launcher.launch(plan)
        provision.assert_not_called()
        popen.assert_not_called()
    assert not (tmp_path / 'launch').exists()


def test_scope_change_after_initial_pin_blocks_popen_and_keeps_admission_separate(tmp_path):
    path = scope_file(tmp_path)
    plan = deployment_plan(tmp_path, path)
    report = doctor_report(path)
    policy = Mock(manifest_sha256='b' * 64)

    def change_during_environment_setup():
        path.write_bytes(path.read_bytes() + b' ')
        return {}

    with patch.object(launcher, 'doctor', return_value=report), \
            patch.object(AdmissionPolicy, 'from_manifest', return_value=policy), \
            patch('rm_match.deployment.enrollment.provision_operator', return_value='synthetic') as provision, \
            patch.object(launcher, 'clean_environment', side_effect=change_during_environment_setup), \
            patch.object(launcher.subprocess, 'Popen') as popen:
        assert launcher.launch(plan) == 2
        popen.assert_not_called()
        provision.assert_called_once_with(plan['admission_manifest'], ['red_sentry'])
    saved = json.loads((tmp_path / 'launch' / 'plan.json').read_text())
    assert saved['native_robot_scope_declaration'] == report['checks'][0]['detail']
    assert saved['automatic_binding'] is False
    result = json.loads((tmp_path / 'launch' / 'launch_result.json').read_text())
    assert result['reason'] == 'launch_error'
    assert 'native_robot_scope_changed' in result['error']


@pytest.mark.parametrize('change', ['missing', 'sha256', 'robot_id', 'bool_referee', 'integer_stationary', 'extra'])
def test_explicit_ready_requires_complete_typed_doctor_declaration(tmp_path, change):
    path = scope_file(tmp_path)
    plan = deployment_plan(tmp_path, path)
    plan.update(admission_policy_sha256='b' * 64,
        native_robot_scope_declaration=load_native_robot_scope(path).declaration())
    ready = ready_message(plan)
    ready['native_robot_scope'] = deepcopy(plan['native_robot_scope_declaration'])
    launcher.verify_ready(ready, plan, 'a')
    if change == 'missing':
        ready.pop('native_robot_scope')
    elif change == 'sha256':
        ready['native_robot_scope']['sha256'] = 'c' * 64
    elif change == 'robot_id':
        ready['native_robot_scope']['robots'][0]['robot_id'] = 'blue_infantry'
    elif change == 'bool_referee':
        ready['native_robot_scope']['robots'][0]['referee_id'] = True
    elif change == 'integer_stationary':
        ready['native_robot_scope']['stationary_only'] = 1
    else:
        ready['native_robot_scope']['extra'] = None
    with pytest.raises(ValueError, match='scope differs from doctor pin'):
        launcher.verify_ready(ready, plan, 'a')


def test_explicit_ready_without_doctor_pin_rejected_but_legacy_ready_is_compatible(tmp_path):
    path = scope_file(tmp_path)
    plan = deployment_plan(tmp_path, path)
    plan['admission_policy_sha256'] = 'b' * 64
    ready = ready_message(plan)
    ready['native_robot_scope'] = load_native_robot_scope(path).declaration()
    with pytest.raises(ValueError, match='scope differs from doctor pin'):
        launcher.verify_ready(ready, plan, 'a')
    legacy = dict(plan, native_robot_scope=None)
    ready.pop('native_robot_scope')
    launcher.verify_ready(ready, legacy, 'a')
