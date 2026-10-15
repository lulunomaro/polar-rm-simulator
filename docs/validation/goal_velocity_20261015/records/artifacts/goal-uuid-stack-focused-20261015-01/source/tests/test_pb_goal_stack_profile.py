"""Explicit local profile/build selection; not a native build or navigation."""
import copy
import hashlib
import json
from unittest.mock import patch
import pytest
from tools.pb_navigation_stack import controller_result_settings


def fixture(tmp_path):
    original=tmp_path/'original';original.write_bytes(b'original ELF fixture, not executable')
    source=tmp_path/'source.json';source.write_bytes(b'{}\n')
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    new=dict(path=str(tmp_path/'new'),sha256='a'*64)
    build=dict(schema='polar.nav2.goal-controller-build.v1',passed=True,
        upstream_revision='a097086719c88f781aa59788eca29ac6ca5e56db',source_manifest_sha256=sha(source),
        executable=new,original_controller_server=dict(path=str(original),sha256=sha(original)))
    report=tmp_path/'build.json'
    def config():
        report.write_bytes((json.dumps(build)+'\n').encode())
        return dict(schema='polar.pb-stack-config.v2',controller_result_profile='follow_path_uuid_v2',
            assets=dict(controller_server=copy.deepcopy(new)),provenance=dict(
                goal_controller_source=dict(path=str(source),sha256=sha(source)),
                goal_controller_build=dict(path=str(report),sha256=sha(report))))
    return build,config,original,report


def test_legacy_is_explicit_and_cannot_hide_goal_profile():
    assert controller_result_settings(dict(schema='polar.pb-stack-config.v1'))==dict(
        result_profile='scan_v1',controller_id='pb_controller_sourced_v1')
    with pytest.raises(ValueError,match='requires_v2'):
        controller_result_settings(dict(schema='polar.pb-stack-config.v1',controller_result_profile='follow_path_uuid_v2'))


def test_valid_build_bound_profile_does_not_mutate_input(tmp_path):
    _,make,_,_=fixture(tmp_path);value=make();before=copy.deepcopy(value)
    assert controller_result_settings(value)==dict(result_profile='follow_path_uuid_v2',controller_id='nav2_server_pb_pid_goal_v1')
    assert value==before


@pytest.mark.parametrize('field,value',[
    ('schema','wrong'),('passed',1),('passed',False),('upstream_revision','other'),
    ('source_manifest_sha256','f'*64),('executable',dict(path='other',sha256='a'*64))])
def test_wrong_build_cannot_select_profile(tmp_path,field,value):
    build,make,_,_=fixture(tmp_path);build[field]=value
    with pytest.raises(ValueError,match='build_mismatch'):controller_result_settings(make())


def test_changed_original_server_refuses_profile(tmp_path):
    _,make,original,_=fixture(tmp_path);value=make();original.write_bytes(b'changed')
    with pytest.raises(ValueError,match='original_changed'):controller_result_settings(value)


def test_build_parser_and_digest_use_the_same_single_snapshot(tmp_path):
    _,make,_,report=fixture(tmp_path);value=make()
    from rm_match.deployment.profile import read_json_snapshot
    original=read_json_snapshot
    def snapshot(path,limit):
        decoded,digest=original(path,limit)
        report.write_bytes(b'{"schema":"different replacement"}\n')
        return decoded,digest
    # The validated metadata and SHA are from one original read. Replacement
    # must not become the SHA for another parsed object; later launch rechecks
    # independently reject changed referenced input.
    with patch('rm_match.deployment.profile.read_json_snapshot',side_effect=snapshot) as read:
        assert controller_result_settings(value)['result_profile']=='follow_path_uuid_v2'
        assert read.call_count==1


def test_missing_provenance_never_falls_back_to_legacy(tmp_path):
    _,make,_,_=fixture(tmp_path);value=make();value['provenance'].pop('goal_controller_source')
    with pytest.raises(ValueError,match='provenance_required'):controller_result_settings(value)
