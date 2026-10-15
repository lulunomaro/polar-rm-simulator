"""Local scope plumbing and dry-run scenes; no native or moving qualification."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from rm_match.deployment import launcher
from rm_match.platform_v2.contracts import ContractError
from test_deployment import args

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_scope_smoke', ROOT/'tools/smoke_wsl_native_live.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def scope_file(tmp_path):
    path = tmp_path/'scope.json'
    path.write_text(json.dumps(dict(schema='polar.sim.native-robot-scope.v1', robots=[
        dict(robot_id='red_infantry', team='red', role='infantry', referee_id=3),
        dict(robot_id='blue_infantry', team='blue', role='infantry', referee_id=103)])), encoding='utf8')
    return path


@pytest.mark.parametrize('rid,team', [('red_infantry','red'), ('blue_infantry','blue')])
def test_explicit_scope_keeps_scene_actor_and_opposing_target_separate(tmp_path, rid, team):
    path = scope_file(tmp_path)
    plan = smoke.build_plan('wsl_async_bgr_v3', robot_id=rid, native_robot_scope=path)
    config = plan['configuration']
    assert config['robot_id'] == rid
    assert config['native_robot_scope']['team'] == team
    assert config['native_robot_scope']['stationary_only'] is True
    assert config['camera_native_budget_s'] == .08 and config['server_input_window_s'] == .15
    opponent = ('blue' if team == 'red' else 'red')+'_infantry'
    assert set(k for k in plan['scene'] if k.endswith('_xy_m')) == {rid+'_xy_m', opponent+'_xy_m'}
    assert config['active_views'] == 1
    assert plan['scope'].startswith('Bounded public-static-scene')


def test_default_does_not_expand_native_scope_or_change_original_plan():
    assert smoke.build_plan('wsl_stdio_v1') == smoke.PLAN
    with pytest.raises(ContractError, match='unsupported'):
        smoke.build_plan('wsl_stdio_v1', robot_id='blue_infantry')


def test_misdeclared_team_is_rejected_before_resources(tmp_path):
    path = scope_file(tmp_path)
    value = json.loads(path.read_text())
    value['robots'][0]['team'] = 'blue'
    path.write_text(json.dumps(value), encoding='utf8')
    with pytest.raises(ContractError, match='observation_mismatch'):
        smoke.build_plan('wsl_stdio_v1', robot_id='red_infantry', native_robot_scope=path)


def test_launcher_passes_scope_without_granting_extra_robots(tmp_path):
    path = scope_file(tmp_path)
    with patch.object(launcher, 'client_patch_identity', return_value={}):
        plan = launcher.plan(args(native_robot_scope=path))
    command = plan['server_argv']
    assert command[command.index('--native-robot-scope')+1] == str(path.absolute())
    assert plan['admission_scope'] == ['red_sentry']
    assert plan['automatic_binding'] is False
