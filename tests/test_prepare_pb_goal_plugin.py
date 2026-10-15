"""Configuration writer tests; no Linux asset/build or readiness claim."""
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import pytest

from tools.prepare_pb_goal_plugin import prepare, PIPELINE_ID, SPEC_SCHEMA
from rm_match.deployment.wsl_jsonl import mounted_path
from rm_match.deployment.profile import read_json_snapshot
from rm_match.platform_v2.contracts import ContractError


def setup(tmp_path):
    root=tmp_path/'repo';root.mkdir();(root/'artifacts').mkdir()
    (root/'tests/fixtures').mkdir(parents=True)
    (root/'tests/fixtures/decision_navigation_feedback_v2.py').write_text('# Synthetic config-only placeholder\n')
    (root/'owned.py').write_text('# Config-only source fixture\n')
    environment=root/'artifacts/environment.json'
    environment.write_text(json.dumps(dict(venv_python='/root/fixture/bin/python',
        process_environment=dict(LD_LIBRARY_PATH='/root/fixture/lib')))+'\n')
    ref=dict(path=mounted_path(environment),sha256=hashlib.sha256(environment.read_bytes()).hexdigest())
    config=root/'artifacts/stack.json'
    config.write_text(json.dumps(dict(schema='polar.pb-stack-config.v2',repo_root=mounted_path(root),
        controller_result_profile='follow_path_uuid_v2',environment=ref,
        provenance=dict(goal_controller_source={},goal_controller_build={})))+'\n')
    return root,root/'artifacts/fresh',config,environment


def test_writer_pins_exact_sources_refs_graph_and_does_not_start_resources(tmp_path):
    root,out,config,env=setup(tmp_path)
    with patch('subprocess.Popen',side_effect=AssertionError('writer must not start a process')):
        result=prepare(root,out,config,env,run_uuid='a'*32,source_files=['owned.py'])
    spec,spec_sha=read_json_snapshot(out/'PEER_SPEC.json')
    assert spec['schema']==SPEC_SCHEMA and spec_sha==result['spec_sha256']
    assert spec['namespace']=='/polar_sil_'+'a'*32+'/red_sentry'
    assert spec['source_sha256']=={'owned.py':hashlib.sha256((root/'owned.py').read_bytes()).hexdigest()}
    assert result['pipeline_id']==PIPELINE_ID and not result['resources_started']
    assert result['sensor_frames']==result['physics_steps']==0
    assert not Path(result['peer_evidence_dir']).exists()
    nav=json.loads((out/'navigation.json').read_bytes())['adapters'][0]
    assert nav['capabilities']['schema']=='polar.sim.navigation-plugin.capabilities.v3'
    assert nav['command'][-1]==spec_sha and len(nav['command'])<=32
    assert nav['supported_robots']==['red_sentry'] and nav['transport']=='wsl_jsonl_v1'
    assert json.loads((out/'decision.json').read_bytes())['adapters'][0]['capabilities']['sensor_profile']=='own_referee_navigation_v2'
    with pytest.raises(ContractError,match='fresh'):prepare(root,out,config,env,source_files=['owned.py'])


@pytest.mark.parametrize('mutation',[
    lambda cfg:cfg.update(schema='polar.pb-stack-config.v1'),
    lambda cfg:cfg.update(controller_result_profile='scan_v1'),
    lambda cfg:cfg.update(repo_root='/wrong/repository'),
    lambda cfg:cfg['environment'].update(sha256='0'*64),
    lambda cfg:cfg['provenance'].pop('goal_controller_build'),
])
def test_unreviewed_profile_refs_never_create_output(tmp_path,mutation):
    root,out,config,env=setup(tmp_path)
    value=json.loads(config.read_bytes());mutation(value);config.write_text(json.dumps(value))
    with pytest.raises(ContractError):prepare(root,out,config,env,source_files=['owned.py'])
    assert not out.exists()


@pytest.mark.parametrize('names',[[],['owned.py','owned.py'],['../owned.py'],['/owned.py']])
def test_source_roster_is_local_unique_and_nonempty(tmp_path,names):
    root,out,config,env=setup(tmp_path)
    with pytest.raises(ContractError):prepare(root,out,config,env,source_files=names)
    assert not out.exists()
