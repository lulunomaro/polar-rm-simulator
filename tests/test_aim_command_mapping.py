"""Protocol/rotation mechanics only; no detector, ROS, NN or live qualification."""
import copy
from dataclasses import FrozenInstanceError
import json
import math
from pathlib import Path

import pytest

from rm_match.deployment.aim_plugin import CAPABILITIES
from rm_match.integrations.aim_camera_codec import prepare_aim_input
from rm_match.integrations.aim_command_mapping import (
    COMMAND_ORIGIN, MAPPING_SCHEMA, RESULT_SCHEMA,
    load_command_mapping, map_aim_result,
)
from rm_match.platform_v2.contracts import ContractError, IDENTITY
from rm_match.platform_v2.test_contracts import sample


def declaration(**changes):
    return dict(schema=MAPPING_SCHEMA, angle_unit='rad', yaw_sign=1, pitch_sign=1,
                yaw_offset_rad=0., pitch_offset_rad=0., input_frame='base_link', **changes)


def mapping(**changes):
    d = declaration()
    d.update(changes)
    return load_command_mapping(d)


def fixture(capture_yaw=0., current_yaw=0.):
    o = sample(True)
    o['sensors']['camera']['capture_sim_time'] = .98
    o['sensors']['camera']['own_odom_at_capture'][2] = capture_yaw
    o['own']['odom_xyyaw'][2] = current_yaw
    return prepare_aim_input(o)


def result(bundle, status='tracking', **changes):
    r = dict(schema=RESULT_SCHEMA, status=status, source_context=bundle.source_context)
    if status == 'tracking':
        r.update(yaw=.4, pitch=.2, confidence=None, command_origin=COMMAND_ORIGIN)
    r.update(changes)
    return r


def convert(m, r, o, b, **kwargs):
    return map_aim_result(m, r, o, b, capabilities=copy.deepcopy(CAPABILITIES), **kwargs)


def test_local_declaration_is_frozen_and_caller_mutation_detached():
    d = declaration()
    m = load_command_mapping(d)
    d['yaw_sign'] = -1
    assert m.yaw_sign == 1
    with pytest.raises(FrozenInstanceError):
        m.yaw_sign = -1


@pytest.mark.parametrize('field,value', [
    ('schema', 'unknown'), ('angle_unit', 'degrees'), ('input_frame', 'Target'),
    ('yaw_sign', True), ('pitch_sign', 1.), ('yaw_sign', 0),
    ('yaw_offset_rad', float('nan')), ('pitch_offset_rad', float('inf')),
    ('yaw_offset_rad', True), ('pitch_offset_rad', 4),
])
def test_invalid_local_mapping_rejected(field, value):
    d = declaration()
    d[field] = value
    with pytest.raises(ContractError):
        load_command_mapping(d)


def test_unknown_mapping_fields_and_type_subclasses_rejected():
    d = declaration();d['team'] = 'any_team'
    with pytest.raises(ContractError):load_command_mapping(d)
    class Unit(str):pass
    d = declaration();d['angle_unit'] = Unit('rad')
    with pytest.raises(ContractError):load_command_mapping(d)


def test_independent_radian_degree_opposite_axis_wrappers_are_equivalent():
    o, b = fixture(.1, .3)
    radians = convert(mapping(), result(b, yaw=.7, pitch=-.25), o, b)
    degrees = convert(mapping(angle_unit='deg', yaw_sign=-1, pitch_sign=-1),
                      result(b, yaw=-math.degrees(.7), pitch=math.degrees(.25)), o, b)
    assert radians['command']['yaw_rad'] == pytest.approx(.5)
    assert radians['command']['pitch_rad'] == pytest.approx(-.25)
    assert degrees['command'] == pytest.approx(radians['command'])
    assert all(type(radians[k]) is type(o[k]) and radians[k] == o[k] for k in IDENTITY)
    assert radians['command']['confidence'] is None
    assert radians['command']['fire_permission'] is False


def test_offsets_are_radians_after_sign_and_unit_conversion():
    o, b = fixture()
    a = convert(mapping(angle_unit='deg', yaw_sign=-1, yaw_offset_rad=.3, pitch_offset_rad=-.1),
                result(b, yaw=30., pitch=10.), o, b)
    assert a['command']['yaw_rad'] == pytest.approx(.3-math.pi/6)
    assert a['command']['pitch_rad'] == pytest.approx(math.pi/18-.1)


@pytest.mark.parametrize('capture,current,angle', [(1.2, -.6, .2), (3., -3., .4), (-2.9, 2.9, -.5)])
def test_exposure_base_and_inertial_paths_agree_with_cartesian_rotation(capture, current, angle):
    o, b = fixture(capture, current)
    world = (math.cos(capture+angle), math.sin(capture+angle))
    # Independent Cartesian world-to-current-base rotation oracle.
    x = math.cos(current)*world[0] + math.sin(current)*world[1]
    y = -math.sin(current)*world[0] + math.cos(current)*world[1]
    expected = math.atan2(y, x)
    base = convert(mapping(), result(b, yaw=angle), o, b)
    inertial = convert(mapping(input_frame='inertial'), result(b, yaw=math.atan2(world[1], world[0])), o, b)
    assert base['command']['yaw_rad'] == pytest.approx(expected)
    assert inertial['command']['yaw_rad'] == pytest.approx(expected)


@pytest.mark.parametrize('key', [*IDENTITY, 'frame_id', 'capture_sim_time', 'capture_stamp_ns', 'calibration_id'])
def test_original_source_is_never_rebound(key):
    o, b = fixture();r = result(b)
    value = r['source_context'][key]
    r['source_context'][key] = value+'other' if type(value) is str else value+1
    with pytest.raises(ContractError):convert(mapping(), r, o, b)


def test_bool_original_identity_and_different_observation_rejected():
    o, b = fixture();r = result(b);r['source_context']['episode'] = True
    with pytest.raises(ContractError):convert(mapping(), r, o, b)
    other = copy.deepcopy(o);other['observed_seq'] += 1
    with pytest.raises(ContractError):convert(mapping(), result(b), other, b)


@pytest.mark.parametrize('status', ['no_target', 'pending_result'])
def test_no_target_and_pending_are_status_without_fabricated_angles(status):
    o, b = fixture();o['own']['odom_xyyaw'] = None
    output = convert(mapping(), result(b, status), o, b)
    assert output['status'] == status and 'command' not in output
    assert output['wall_deadline'] == o['wall_deadline']
    for key in ('yaw', 'pitch', 'confidence', 'command_origin'):
        with pytest.raises(ContractError):convert(mapping(), result(b, status, **{key:0}), o, b)


@pytest.mark.parametrize('field,value', [
    ('yaw', True), ('pitch', float('nan')), ('confidence', True),
    ('pitch', 2.), ('confidence', 1.1), ('command_origin', 'Target.yaw'),
    ('status', 'false'), ('schema', 'geometry_msgs/Twist'),
])
def test_invalid_actual_result_never_becomes_control(field, value):
    o, b = fixture();r = result(b);r[field] = value
    with pytest.raises(ContractError):convert(mapping(), r, o, b)


def test_bare_ros_messages_unknown_fields_and_automatic_fire_rejected():
    o, b = fixture()
    for raw in ({'yaw':.2}, {'linear':{}, 'angular':{}}, {'header':{}, 'tracking':True}):
        with pytest.raises(ContractError):convert(mapping(), raw, o, b)
    for key in ('fire', 'target_position', 'direction_frame', 'tracking'):
        r = result(b);r[key] = True
        with pytest.raises(ContractError):convert(mapping(), r, o, b)


@pytest.mark.parametrize('frame', ['base_link', 'inertial'])
def test_missing_required_own_pose_rejected(frame):
    o, b = fixture();o['own']['odom_xyyaw'] = None
    with pytest.raises(ContractError):convert(mapping(input_frame=frame), result(b), o, b)
    o, b = fixture();o['own']['odom_vxyw'] = None
    with pytest.raises(ContractError):convert(mapping(input_frame=frame), result(b), o, b)


def test_original_deadline_and_capture_age_not_refreshed_and_input_not_mutated():
    o, b = fixture();r = result(b);before = copy.deepcopy((o,r))
    a = convert(mapping(), r, o, b, host_now=9.99)
    assert a['wall_deadline'] == 10. and (o,r) == before
    with pytest.raises(ContractError):convert(mapping(), r, o, b, host_now=10.)
    with pytest.raises(ContractError):convert(mapping(), r, o, b, host_now=float('nan'))
    late = copy.deepcopy(o);late['sim_time'] = 1.07
    # Full echoed source cannot be relabeled with this new sampling time.
    with pytest.raises(ContractError):convert(mapping(), r, late, b)
    stale = sample(True);stale['sensors']['camera']['capture_sim_time'] = .9
    stale, stale_bundle = prepare_aim_input(stale)
    with pytest.raises(ContractError, match='original_capture_expired'):
        convert(mapping(), result(stale_bundle), stale, stale_bundle)


def test_mapping_does_not_decode_the_same_validated_image_again():
    from unittest.mock import patch
    o, b = fixture()
    # The direct wrapper has already done strict canonical decode exactly once.
    # Mapping verifies the full original source echo and uses its frozen metadata.
    with patch('base64.b64decode', side_effect=AssertionError('unnecessary second image decode')):
        output = convert(mapping(), result(b), o, b)
    assert output['command']['active'] is True


def test_direct_command_capability_and_manual_fire_must_be_supported():
    o, b = fixture()
    for key, value in [('pipeline_level','target_trajectory_v1'),
                       ('source_association','latest_target'), ('fire_authority','automatic')]:
        caps = copy.deepcopy(CAPABILITIES);caps[key] = value
        with pytest.raises(ContractError):
            map_aim_result(mapping(), result(b), o, b, capabilities=caps)


def test_example_is_local_protocol_configuration_not_model_qualification():
    root = Path(__file__).resolve().parents[1]
    m = load_command_mapping(json.loads((root/'examples/aim_command_mapping.json').read_text(encoding='utf8')))
    assert m.angle_unit == 'deg' and m.yaw_sign == -1 and m.input_frame == 'base_link'
