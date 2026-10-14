"""Mocked owned-supervisor lifecycle; no actual WSL/ROS/algorithm qualification."""
import copy
import io
import json
from pathlib import Path
import time
from unittest.mock import Mock, patch
import pytest
from rm_match.deployment.robotio_wsl import (create_wsl_plugin, PreparedWslPlugins,
    WslNavigationPluginAdapter, WslDecisionPluginAdapter)
from rm_match.deployment.navigation_plugin import CAPABILITIES as NAV_CAPS
from rm_match.deployment.decision_plugin import CAPABILITIES as DECISION_CAPS
from rm_match.deployment.json_adapter import SCHEMA
from rm_match.deployment.profile import digest
from rm_match.platform_v2.contracts import ContractError


def row(kind='navigation', aid='custom_owned_navigation'):
    linux=dict(distribution='Ubuntu',python='/usr/bin/python3',command=['/usr/bin/python3','/owned/peer.py'],
        cwd='/owned',process_env={})
    return dict(adapter_id=aid,label='Mock supervisor lifecycle',kind=kind,transport='wsl_jsonl_v1',
        capabilities=copy.deepcopy(NAV_CAPS if kind=='navigation' else DECISION_CAPS),
        supported_robots=['red_infantry','blue_sentry'],required_sensors=['pointcloud','imu'] if kind=='navigation' else [],
        command=linux['command'],cwd=linux['cwd'],linux=linux)


def instance(tmp_path,kind='navigation'):
    path=tmp_path/'manifest.json';r=row(kind)
    path.write_text(json.dumps(r),encoding='utf8')
    a=create_wsl_plugin(r,manifest=path,manifest_sha=digest(path),repo_root=tmp_path,shared_root=tmp_path)
    return a,path


def mock_owner(a):
    child=Mock();child.poll.return_value=None
    child.stdin=io.BytesIO();child.stdout=io.BytesIO()
    owner=Mock();owner.child=child
    owner.cleanup.return_value=dict(clean=True,reaped=True,group_empty=True,linux={'clean':True},windows={'clean':True})
    operations=[]
    def open_peer():
        a._owned_process=owner;a.process=child
    def exchange(packet,timeout):
        operations.append((copy.deepcopy(packet),timeout))
        result=dict(schema=SCHEMA,op=packet['op'],ok=True)
        if packet['op']=='reset' or (packet['op']=='prepare' and type(a) is WslDecisionPluginAdapter):
            result['capabilities']=copy.deepcopy(a.registration['capabilities'])
        a._validate_response(result,packet)
        return result
    a._open_owned_process=Mock(side_effect=open_peer)
    a._exchange=Mock(side_effect=exchange)
    return owner,operations


@pytest.mark.parametrize('kind,cls',[('navigation',WslNavigationPluginAdapter),('decision',WslDecisionPluginAdapter)])
def test_explicit_prepare_has_no_sensor_and_real_reset_caps_once(tmp_path,kind,cls):
    a,path=instance(tmp_path,kind);assert type(a) is cls
    owner,ops=mock_owner(a);context=dict(robot_id='blue_sentry',episode=4,binding_epoch=8)
    with pytest.raises(ContractError,match='fresh_local_preparation'):a.reset(context)
    assert not ops
    a.prepare(startup_timeout=3.)
    assert ops[0][0]==dict(op='prepare',config={}) and 0<ops[0][1]<=3.
    a.reset(context,deadline=time.perf_counter()+1.)
    assert ops[-1][0]==dict(op='reset',context=context,config={}) and 0<ops[-1][1]<=1.
    assert a.claimed
    with pytest.raises(ContractError):a.reset(context)
    with pytest.raises(ContractError):a.prepare()
    a.close();assert a.shutdown_status['clean'] is True
    owner.cleanup.assert_called_once()


def test_start_uses_owned_supervisor_original_cancel_and_env(tmp_path):
    a,path=instance(tmp_path)
    with patch('rm_match.deployment.robotio_wsl.OwnedWslJsonProcess',return_value='owner') as spawn:
        env={'SAFE':'value'}
        assert a._start_owned_process(env)=='owner'
        spawn.assert_called_once_with(a.registration,repo_root=tmp_path,shared_root=tmp_path,
            stop_event=a._cancelled,env=env)


def test_prepared_open_preserves_resource_and_checks_spec_not_hello_ready(tmp_path):
    a,path=instance(tmp_path);owner=Mock();child=Mock();child.poll.return_value=None
    a._owned_process=owner;a.process=child;a.prepared=True
    a._open_owned_process();owner.verify_unchanged.assert_called_once()
    child.poll.return_value=0
    with pytest.raises(ContractError,match='unavailable'):a._open_owned_process()
    child.poll.return_value=None;path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ContractError,match='manifest_changed'):a._open_owned_process()


def test_manifest_and_linux_command_mismatch_or_bare_wsl_fail_before_spawn(tmp_path):
    a,path=instance(tmp_path);r=row()
    for change in ('hash','cwd','bare','secret'):
        bad=copy.deepcopy(r);sha=digest(path)
        if change=='hash':sha='0'*64
        if change=='cwd':bad['cwd']='/other'
        if change=='bare':bad['command'][0]='/usr/bin/wsl.exe'
        if change=='secret':bad['linux']['process_env']['ADMISSION_CREDENTIAL']='not_allowed'
        with patch('rm_match.deployment.robotio_wsl.OwnedWslJsonProcess') as spawn:
            with pytest.raises(ContractError):create_wsl_plugin(bad,manifest=path,manifest_sha=sha,repo_root=tmp_path,shared_root=tmp_path)
            spawn.assert_not_called()


@pytest.mark.parametrize('budget',[True,float('nan'),float('inf'),0.,15.01])
def test_invalid_prepare_budget_does_not_spawn(tmp_path,budget):
    a,path=instance(tmp_path)
    with patch.object(a,'_open_owned_process') as spawn:
        with pytest.raises(ContractError):a.prepare(startup_timeout=budget)
        spawn.assert_not_called()


def test_pool_take_transfers_once_closes_only_unclaimed_under_shared_deadline(tmp_path):
    first,path=instance(tmp_path);owner1,ops1=mock_owner(first)
    second,_=instance(tmp_path,'decision');owner2,ops2=mock_owner(second)
    # Both factories refer to this one manifest, as a trusted composer pool.
    with patch('rm_match.deployment.robotio_wsl.create_wsl_plugin',side_effect=[first,second]):
        pool=PreparedWslPlugins([row(aid='custom_first'),row('decision','custom_second')],
            manifest=path,manifest_sha=digest(path),repo_root=tmp_path,shared_root=tmp_path)
    claimed=pool.take('custom_first',pool.sha);assert claimed is first
    with pytest.raises(ContractError,match='claimed'):pool.take('custom_first',pool.sha)
    limit=time.perf_counter()+.5
    pool.close_unclaimed(deadline=limit)
    assert pool.instances=={} and second.shutdown_status['clean']
    owner1.cleanup.assert_not_called()
    assert owner2.cleanup.call_args.args[0]<=limit
    claimed.close();assert first.shutdown_status['clean']


def test_cancel_or_changed_source_cannot_transfer_resource(tmp_path):
    a,path=instance(tmp_path);owner,ops=mock_owner(a);a.prepare()
    pool=PreparedWslPlugins.__new__(PreparedWslPlugins)
    pool.path=path;pool.sha=digest(path);pool.instances={'custom_owned':a};pool.cleanup_status={}
    a._cancelled.set()
    with pytest.raises(ContractError,match='cancelled'):pool.take('custom_owned',pool.sha)
    a._cancelled.clear();owner.verify_unchanged.side_effect=ContractError('changed_source')
    with pytest.raises(ContractError,match='changed_source'):pool.take('custom_owned',pool.sha)
    assert pool.instances['custom_owned'] is a
    owner.verify_unchanged.side_effect=None
    pool.close_unclaimed()


def test_unsafe_cleanup_proof_is_retained_not_cleaned_by_pop(tmp_path):
    a,path=instance(tmp_path);owner,ops=mock_owner(a);a.prepare()
    owner.cleanup.return_value=dict(clean=False,reaped=True,group_empty=False,errors=['linux_unknown'])
    pool=PreparedWslPlugins.__new__(PreparedWslPlugins)
    pool.path=path;pool.sha=digest(path);pool.instances={'custom_owned':a};pool.cleanup_status={}
    with pytest.raises(RuntimeError,match='cleanup unproved'):pool.close_unclaimed()
    assert pool.instances['custom_owned'] is a
    assert pool.cleanup_status['custom_owned']['clean'] is False
    assert pool.cleanup_status['custom_owned']['ownership']['group_empty'] is False


def test_partial_prepare_failure_reclaims_all_pool_resources(tmp_path):
    first,path=instance(tmp_path);owner1,ops=mock_owner(first)
    second,_=instance(tmp_path,'decision');owner2,ops=mock_owner(second)
    second._exchange.side_effect=RuntimeError('actual_prepare_failed')
    with patch('rm_match.deployment.robotio_wsl.create_wsl_plugin',side_effect=[first,second]):
        with pytest.raises(RuntimeError,match='actual_prepare_failed'):
            PreparedWslPlugins([row(aid='custom_one'),row('decision','custom_two')],manifest=path,
                manifest_sha=digest(path),repo_root=tmp_path,shared_root=tmp_path)
    assert first.shutdown_status['clean'] and second.shutdown_status['clean']
    owner1.cleanup.assert_called_once();owner2.cleanup.assert_called_once()
