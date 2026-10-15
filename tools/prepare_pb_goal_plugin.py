"""Write a local, source-pinned PB generic plugin graph; start no resources.

Actual Linux preparation rechecks referenced assets, loader and build proofs.
This writer does not qualify those assets, DDS, localization or an algorithm.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import secrets
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from rm_match.deployment.profile import read_json_snapshot
from rm_match.deployment.wsl_jsonl import mounted_path, validate_linux_settings, checked_shared_path
from rm_match.deployment.navigation_plugin import FEEDBACK_CAPABILITIES, MANIFEST_SCHEMA as NAV_MANIFEST
from rm_match.deployment.decision_plugin import NAVIGATION_CAPABILITIES, MANIFEST_SCHEMA as DEC_MANIFEST
from rm_match.deployment.robotio_plugin import SCHEMA as GRAPH_SCHEMA, load_robotio_plugins
from rm_match.platform_v2.contracts import ContractError, exact, identity

SPEC_SCHEMA='polar.pb.goal-plugin-peer-spec.v1'
PIPELINE_ID='custom_pb_goal_pipeline'
NAVIGATION_ID='custom_pb_goal_navigation'
DECISION_ID='custom_pb_estimated_decision'
GENERATION=dict(robot_id='red_sentry',episode=0,binding_epoch=1)


def _write(path,value):
    raw=(json.dumps(value,indent=2,allow_nan=False)+'\n').encode()
    with path.open('xb') as stream:stream.write(raw)
    return hashlib.sha256(raw).hexdigest()


def _ref(path,root):
    selected=checked_shared_path(Path(path).absolute(),root)
    value,sha=read_json_snapshot(selected,4*1024*1024)
    return value,dict(path=mounted_path(selected),sha256=sha)


def prepare(root,out,config_path,environment_path,*,diagnostics=True,run_uuid=None,source_files=None):
    root=checked_shared_path(Path(root).absolute(),Path(root).absolute())
    out=checked_shared_path(Path(out).absolute(),root)
    if not out.is_relative_to(root/'artifacts') or out.exists():
        raise ContractError('pb_goal_plugin_fresh_artifacts_output_required')
    if type(diagnostics) is not bool:raise ContractError('pb_goal_plugin_diagnostics')
    run_uuid=secrets.token_hex(16) if run_uuid is None else run_uuid
    if type(run_uuid) is not str or not re.fullmatch('[a-f0-9]{32}',run_uuid):
        raise ContractError('pb_goal_plugin_run_uuid')
    config,config_ref=_ref(config_path,root)
    environment,environment_ref=_ref(environment_path,root)
    if (config.get('schema')!='polar.pb-stack-config.v2'
        or config.get('controller_result_profile')!='follow_path_uuid_v2'
        or config.get('repo_root')!=mounted_path(root)
        or config.get('environment')!=environment_ref
        or not {'goal_controller_source','goal_controller_build'}<=set(config.get('provenance',{}))):
        raise ContractError('pb_goal_plugin_explicit_native_v2_config_required')
    python=environment.get('venv_python');process_env=environment.get('process_environment')
    if type(python) is not str or type(process_env) is not dict:
        raise ContractError('pb_goal_plugin_explicit_environment_required')
    if source_files is None:
        from rm_match.integrations.pb_goal_plugin_peer import SOURCE_FILES
        source_files=SOURCE_FILES
    if (type(source_files) not in (tuple,list) or not source_files
        or any(type(name) is not str or name.startswith('/') or '..' in Path(name).parts for name in source_files)
        or len(source_files)!=len(set(source_files))):
        raise ContractError('pb_goal_plugin_source_roster')
    sources={}
    for name in source_files:
        selected=checked_shared_path(root/name,root)
        sources[name]=hashlib.sha256(selected.read_bytes()).hexdigest()
    exact(GENERATION,('robot_id','episode','binding_epoch'),'pb_goal_plugin_generation')
    identity(dict(GENERATION,observed_seq=0,sim_time=0.,wall_deadline=0.))
    namespace='/polar_sil_'+run_uuid+'/'+GENERATION['robot_id']
    spec_path=out/'PEER_SPEC.json';evidence=out/'peer-evidence'
    spec=dict(schema=SPEC_SCHEMA,run_uuid=run_uuid,namespace=namespace,domain_id=84,
        root_linux=mounted_path(root),out_linux=mounted_path(evidence),config_ref=config_ref,
        environment_ref=environment_ref,source_sha256=sources,
        expected_generation=copy.deepcopy(GENERATION),diagnostics=diagnostics)
    out.mkdir(parents=True)
    spec_sha=_write(spec_path,spec)
    command=[python,'-u','-m','rm_match.integrations.pb_goal_plugin_peer',
        '--spec',mounted_path(spec_path),'--sha256',spec_sha]
    linux=validate_linux_settings(dict(distribution='Ubuntu-22.04',python=python,
        command=command,cwd=mounted_path(root),process_env=copy.deepcopy(process_env)))
    nav=dict(adapter_id=NAVIGATION_ID,label='PB real navigation with source-bound estimated feedback',
        command=command,cwd=linux['cwd'],supported_robots=[GENERATION['robot_id']],transport='wsl_jsonl_v1',
        capabilities=copy.deepcopy(FEEDBACK_CAPABILITIES),wsl={k:linux[k] for k in ('distribution','python','process_env')})
    fixture=root/'tests/fixtures/decision_navigation_feedback_v2.py'
    if not fixture.is_file():raise ContractError('pb_goal_plugin_estimated_policy_fixture_missing')
    decision=dict(adapter_id=DECISION_ID,label='Synthetic estimated-map goal policy; not PB match tree',
        command=[sys.executable,'-u',str(fixture)],cwd=str(root),supported_robots=[GENERATION['robot_id']],
        transport='jsonl_v1',capabilities=copy.deepcopy(NAVIGATION_CAPABILITIES))
    _write(out/'navigation.json',dict(schema=NAV_MANIFEST,adapters=[nav]))
    _write(out/'decision.json',dict(schema=DEC_MANIFEST,adapters=[decision]))
    graph=dict(schema=GRAPH_SCHEMA,manifests=dict(navigation='navigation.json',decision='decision.json',aim=None),
        pipelines=[dict(adapter_id=PIPELINE_ID,label='Real PB navigation / synthetic estimate-based decision',
            decision_plugin_id=DECISION_ID,navigation_plugin_id=NAVIGATION_ID,supported_robots=[GENERATION['robot_id']])])
    graph_sha=_write(out/'robotio.json',graph)
    # Parse all three actual manifests. This declares the graph, not readiness.
    load_robotio_plugins(out/'robotio.json')
    result=dict(schema='polar.pb.goal-plugin-preparation.v1',manifest=str(out/'robotio.json'),
        manifest_sha256=graph_sha,pipeline_id=PIPELINE_ID,peer_evidence_dir=str(evidence),
        spec_sha256=spec_sha,run_uuid=run_uuid,source_sha256=sources,
        resources_started=False,sensor_frames=0,physics_steps=0,
        qualification='configuration_only_not_algorithm_or_live_acceptance')
    _write(out/'PREPARATION.json',result)
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--stack-config',type=Path,required=True)
    p.add_argument('--environment',type=Path,required=True)
    args=p.parse_args(argv)
    result=prepare(ROOT,args.out,args.stack_config,args.environment)
    print(json.dumps({k:result[k] for k in ('manifest','pipeline_id','peer_evidence_dir','resources_started')}))
    return 0


if __name__=='__main__':raise SystemExit(main())
