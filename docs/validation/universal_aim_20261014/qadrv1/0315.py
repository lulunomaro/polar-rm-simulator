"""Synthetic camera byte/calibration/source association; no ROS or detector."""
import base64
from dataclasses import FrozenInstanceError
from unittest.mock import patch
import builtins
import pytest
from rm_match.integrations.aim_camera_codec import camera_sensor_bundle,validate_source_echo,ros_camera_messages
from rm_match.platform_v2.contracts import ContractError
from rm_match.platform_v2.test_contracts import sample

def test_pixels_calibration_capture_own_and_original_clock_are_preserved():
    o=sample(True);o['sensors']['camera']['capture_sim_time']=.987654321
    o['own']['qpos'][3]=.7;o['sensors']['camera']['own_qpos_at_capture'][3]=.2
    b=camera_sensor_bundle(o);c=b.camera
    assert b.pixels==base64.b64decode(o['sensors']['camera']['image']['data_base64'])
    assert b.capture_stamp_ns==987654321 and b.source_context['wall_deadline']==o['wall_deadline']
    assert c['own_qpos_at_capture'][3]==.2 and c['intrinsics']==o['sensors']['camera']['intrinsics']
    c['own_qpos_at_capture'][3]=99;ctx=b.source_context;ctx['episode']=99
    assert b.camera['own_qpos_at_capture'][3]==.2 and b.source_context['episode']==o['episode']
    with pytest.raises(FrozenInstanceError):b.pixels=b'fake'

@pytest.mark.parametrize('field',['robot_id','episode','binding_epoch','observed_seq','sim_time',
    'wall_deadline','frame_id','capture_sim_time','capture_stamp_ns','calibration_id'])
def test_no_latest_or_cross_generation_source_binding(field):
    b=camera_sensor_bundle(sample(True));ctx=b.source_context
    ctx[field]=ctx[field]+'other' if type(ctx[field]) is str else ctx[field]+1
    with pytest.raises(ContractError,match='source_context_mismatch'):validate_source_echo(ctx,b)

def test_bool_identity_and_unstamped_target_cannot_be_accepted():
    b=camera_sensor_bundle(sample(True));ctx=b.source_context;ctx['episode']=True
    with pytest.raises(ContractError):validate_source_echo(ctx,b)
    with pytest.raises(ContractError):validate_source_echo({'header':{'stamp':987654321}},b)
    assert validate_source_echo(b.source_context,b)==b.source_context

def test_missing_ros_types_is_explicit_and_never_stubs_messages():
    original=builtins.__import__
    def missing(name,*args,**kwargs):
        if name.startswith('sensor_msgs'):raise ImportError('fixture optional dependency absent')
        return original(name,*args,**kwargs)
    with patch('builtins.__import__',side_effect=missing),pytest.raises(ContractError,match='types_unavailable'):
        ros_camera_messages(camera_sensor_bundle(sample(True)))
