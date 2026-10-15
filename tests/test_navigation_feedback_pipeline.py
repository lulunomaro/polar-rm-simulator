"""Composed source-bound feedback tests with two synthetic owned peers."""
import copy
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch
import pytest

from rm_match.deployment.navigation_plugin import FEEDBACK_CAPABILITIES, GOAL_CAPABILITIES, MANIFEST_SCHEMA as NAV_SCHEMA
from rm_match.deployment.decision_plugin import NAVIGATION_CAPABILITIES, CAPABILITIES as OLD_DEC_CAPS, MANIFEST_SCHEMA as DEC_SCHEMA
from rm_match.deployment.robotio_plugin import SCHEMA, register_robotio_plugins, load_robotio_plugins
from rm_match.platform_v2.adapters import Registry
from rm_match.platform_v2.contracts import ContractError, IDENTITY
from test_navigation_plugin import observation


def graph(tmp_path,*,nav_caps=None,dec_caps=None):
    fixture=Path(__file__).parent/'fixtures'
    nav=dict(adapter_id='custom_feedback_navigation',label='Synthetic staged navigation',
        command=[sys.executable,'-u',str((fixture/'staged_navigation_feedback_fixture.py').resolve())],
        cwd=str(fixture.resolve()),supported_robots=['blue_sentry'],transport='jsonl_v1',
        capabilities=copy.deepcopy(FEEDBACK_CAPABILITIES if nav_caps is None else nav_caps))
    dec=dict(adapter_id='custom_feedback_decision',label='Synthetic estimate-based policy',
        command=[sys.executable,'-u',str((fixture/'decision_navigation_feedback_v2.py').resolve())],
        cwd=str(fixture.resolve()),supported_robots=['blue_sentry'],transport='jsonl_v1',
        capabilities=copy.deepcopy(NAVIGATION_CAPABILITIES if dec_caps is None else dec_caps))
    (tmp_path/'navigation.json').write_text(json.dumps(dict(schema=NAV_SCHEMA,adapters=[nav])))
    (tmp_path/'decision.json').write_text(json.dumps(dict(schema=DEC_SCHEMA,adapters=[dec])))
    path=tmp_path/'robotio.json'
    path.write_text(json.dumps(dict(schema=SCHEMA,manifests=dict(navigation='navigation.json',decision='decision.json',aim=None),
        pipelines=[dict(adapter_id='custom_feedback_pipeline',label='Synthetic feedback pipeline',
            navigation_plugin_id=nav['adapter_id'],decision_plugin_id=dec['adapter_id'],supported_robots=['blue_sentry'])])))
    return path


def test_feedback_decision_requires_explicit_staged_navigation_before_spawn(tmp_path):
    path=graph(tmp_path,nav_caps=GOAL_CAPABILITIES)
    with pytest.raises(ContractError,match='requires_navigation_feedback'):load_robotio_plugins(path)
    registry=Registry()
    with pytest.raises(ContractError):register_robotio_plugins(registry,path)
    assert registry.descriptors()==[]


def test_legacy_decision_can_explicitly_select_staged_navigation(tmp_path):
    path=graph(tmp_path,dec_caps=OLD_DEC_CAPS)
    # Its old observation stays own/referee only. The staged sensor operation
    # still exists; no observation capability is silently negotiated as v2.
    registry=Registry();register_robotio_plugins(registry,path)
    assert registry.get('custom_feedback_pipeline').descriptor['navigation_plugin_capabilities']==FEEDBACK_CAPABILITIES


def test_actual_registered_peers_observe_decide_act_with_one_original_deadline(tmp_path):
    path=graph(tmp_path);registry=Registry();register_robotio_plugins(registry,path)
    pipeline=registry.create('custom_feedback_pipeline',{});o=observation()
    packets=[]
    try:
        pipeline.reset({k:o[k] for k in ('episode','robot_id','binding_epoch')})
        def trace(name,callback):
            def exchange(packet,**kwargs):
                packets.append((name,copy.deepcopy(packet)))
                return callback(packet,**kwargs)
            return exchange
        pipeline.navigation._exchange=trace('navigation',pipeline.navigation._exchange)
        pipeline.decision._exchange=trace('decision',pipeline.decision._exchange)
        o['wall_deadline']=time.perf_counter()+.15
        action=pipeline.act(o)
        assert [row[1]['op'] for row in packets]==['observe','act','act']
        assert [row[0] for row in packets]==['navigation','decision','navigation']
        observed=packets[0][1]['observation'];decision=packets[1][1]['observation'];final=packets[2][1]
        assert observed==o and decision['schema']=='polar.sim.decision-observation.v2'
        assert decision['navigation']['source']=={k:o[k] for k in IDENTITY}
        assert decision['navigation']['navigation']['position_m']==[0.,0.,0.]
        assert 'observation' not in final and final['source']=={k:o[k] for k in IDENTITY}
        for value in (decision,final['intent'],action):
            assert all(type(value[k]) is type(o[k]) and value[k]==o[k] for k in IDENTITY)
        assert action['command']['vx_mps']==.2
        assert pipeline.navigation.last_goal_result['controller_goal_uuid'] is not None
    finally:pipeline.close()
    assert pipeline.shutdown_status['clean']
    assert all(row['clean'] for row in pipeline.shutdown_status['peers'].values())
