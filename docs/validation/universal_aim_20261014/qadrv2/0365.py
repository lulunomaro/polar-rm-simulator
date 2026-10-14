"""Source-overlay/transport contract fixtures only; no ROS or NN execution."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import pytest
from rm_match.integrations.aim_camera_codec import camera_sensor_bundle
from rm_match.integrations.pb_aim_contract import convert_pb_result,RESULT_SCHEMA
from rm_match.integrations.pb_aim_ros_peer import PBAimBridge,PBAimRosTransport,capture_feedback,checked_mount
from rm_match.integrations.ros2_bridge import BridgeSettings,BridgeError
from rm_match.platform_v2.contracts import ContractError,IDENTITY
from rm_match.platform_v2.test_contracts import sample
from tools import prepare_pb_aim_plugin as tool

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'external/pb2025-aim-interface-review'

def result(bundle,status='gimbal_target'):
    return dict(schema=RESULT_SCHEMA,source_context=bundle.source_context,capture_stamp_ns=bundle.capture_stamp_ns,
        status=status,output_frame='chassis_relative_ros_rpy',yaw=.25 if status=='gimbal_target' else None,
        pitch=-.12 if status=='gimbal_target' else None)

def test_original_algorithm_angles_convert_coordinates_without_target_solver_or_fire():
    o=sample(True);bundle=camera_sensor_bundle(o)
    value=convert_pb_result(result(bundle),o,bundle)
    assert all(type(value[k]) is type(o[k]) and value[k]==o[k] for k in IDENTITY)
    assert value['command']==dict(frame='base_link',yaw_rad=.25,pitch_rad=.12,
        active=True,confidence=None,fire_permission=False)
    for status in ('no_target','pending_result'):
        value=convert_pb_result(result(bundle,status),o,bundle)
        assert value['status']==status and 'command' not in value

@pytest.mark.parametrize('key',['robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline',
    'frame_id','capture_sim_time','capture_stamp_ns','calibration_id'])
def test_no_cross_source_latest_identity_or_retimestamped_output(key):
    o=sample(True);b=camera_sensor_bundle(o);bad=result(b)
    value=bad['source_context'][key]
    bad['source_context'][key]=value+'different' if type(value) is str else value+1
    with pytest.raises(ContractError):convert_pb_result(bad,o,b)

@pytest.mark.parametrize('field,value',[('capture_stamp_ns',True),('capture_stamp_ns',1000000001),
    ('yaw',True),('pitch',float('nan')),('output_frame','world'),('status','tracking'),('pitch',10.)])
def test_output_modes_types_and_limits_remain_strict(field,value):
    o=sample(True);b=camera_sensor_bundle(o);bad=result(b);bad[field]=value
    with pytest.raises(ContractError):convert_pb_result(bad,o,b)

def test_body_own_feedback_is_actual_capture_and_local_only():
    o=sample(True);o['own']['qpos'][3:]=[99.,99.]
    o['sensors']['camera']['own_qpos_at_capture'][3:]=[.2,.1]
    b=camera_sensor_bundle(o);mount={'translation_m':[.38,0.,0.],'rotation_xyzw':[0.,0.,0.,1.]}
    feedback=capture_feedback(b,mount)
    assert feedback['stamp_ns']==1_000_000_000
    assert feedback['yaw_rotation_xyzw'][2]==pytest.approx(.0998334166)
    assert feedback['pitch_rotation_xyzw'][1]==pytest.approx(-.04997916927)
    assert not any(k in feedback for k in ('world','odom','enemy','target'))
    feedback['muzzle']['translation_m'][0]=9
    assert mount['translation_m'][0]==.38
    o['sensors']['camera']['own_odom_velocity_at_capture'][0]=.061
    with pytest.raises(ContractError,match='stationary_first'):capture_feedback(camera_sensor_bundle(o),mount)

def test_original_host_deadline_is_opaque_on_ros_clock_and_late_result_not_accepted():
    clock=[100_000.]
    settings=BridgeSettings('custom_pb_aim','aim','fixture','/fixture/input','/fixture/result',85,.08)
    core=PBAimBridge(settings,clock=lambda:clock[0]);o=sample(True)
    core.reset({k:o[k] for k in ('robot_id','episode','binding_epoch')},{})
    core.begin(o);original=core.bundle
    core.receive_pb_result(json.dumps(result(original)))
    accepted=core.poll();assert accepted['wall_deadline']==10. and accepted['command']['fire_permission'] is False
    new=copy.deepcopy(o);new['observed_seq']=2
    new['sim_time']=1.001;new['sensors']['camera']['capture_sim_time']=1.001;new['sensors']['camera']['frame_id']=2
    core.begin(new)
    with pytest.raises(ContractError):core.receive_pb_result(json.dumps(result(original)))
    clock[0]+=.081
    with pytest.raises(BridgeError,match='response_timeout'):core.receive_pb_result(json.dumps(result(core.bundle)))
    core.close()

def test_actual_static_model_mount_is_hash_bound_and_not_hardware_calibration():
    ref=ROOT/'artifacts/aim-mount-calibration-20261014-03/MOUNTS.json'
    if not ref.exists():pytest.skip('Local actual model calibration evidence not present')
    mount,sha=checked_mount(ref,'296aaa073da96fa0dcc0ecf473284e76eb94859dd53006457c9507cdda86bf62','blue_hero')
    assert mount['translation_m']==[.38,0.,0.] and mount['pitch_joint_axis']==[0.,-1.,0.]
    assert mount['kinematics']['yaw_to_pitch_translation_m']==[0.,0.,0.]
    with pytest.raises(ContractError):checked_mount(ref,'0'*64,'blue_hero')
    with pytest.raises(ContractError):checked_mount(ref,sha,'nonexistent_robot')

def test_partial_ros_setup_cleanup_attempts_shutdown_even_on_node_close_error():
    from types import SimpleNamespace
    transport=PBAimRosTransport.__new__(PBAimRosTransport);calls=[]
    def fail():calls.append('destroy');raise RuntimeError('owned fixture close error')
    transport.node=SimpleNamespace(destroy_node=fail)
    transport.rclpy=SimpleNamespace(shutdown=lambda:calls.append('shutdown'));transport._ros_started=True
    with pytest.raises(BridgeError,match='cleanup_failed'):transport.close()
    assert calls==['destroy','shutdown'] and transport._ros_started is False
    # No ROS instance was created by this pure lifecycle fixture.

def test_pinned_source_callbacks_carry_context_in_single_messages_and_math_unchanged():
    if not SOURCE.exists():pytest.skip('Pinned upstream audit checkout not present')
    for package,node,transform in [('armor_detector_opencv','detector_node',tool.detector_overlay),
        ('armor_tracker','tracker_node',tool.tracker_overlay),('projectile_motion','projectile_motion_node',tool.projectile_overlay)]:
        cpp=(SOURCE/package/'src'/f'{node}.cpp').read_text(encoding='utf-8')
        header=(SOURCE/package/'include'/package/f'{node}.hpp').read_text(encoding='utf-8')
        modified,h=transform(cpp,header)
        assert 'source_msg->source_context' in modified and 'pb_source_->check' in modified
        assert 'source_msg->header' in modified and 'pb_aim_source.hpp' in h
        if package=='projectile_motion':
            begin=cpp.index('void ProjectileMotionNode::calculateTargetPosition(')
            end=cpp.index('void ProjectileMotionNode::publishGimbalCommand(',begin)
            new_begin=modified.index('bool ProjectileMotionNode::calculateTargetPosition(')
            new_end=modified.index('void ProjectileMotionNode::publishGimbalCommand(',new_begin)
            guarded=modified[new_begin:new_end].replace('bool ProjectileMotionNode::','void ProjectileMotionNode::',1)
            guarded=guarded.replace('  const bool solved=solver_->solve(target_predict_position.head(2).norm(), target_predict_position.z(), target_pitch);\n  if(!solved)return false; // source_safety_hook: never read an unwritten pitch.',
                '  solver_->solve(target_predict_position.head(2).norm(), target_predict_position.z(), target_pitch);',1)
            guarded=guarded.replace('  return true;\n','',1)
            assert cpp[begin:end]==guarded
            assert 'if(!solved)return false;' in modified
            assert 'publish_result(pb_result_,source,"pending_result");\n    return;' in modified
            assert 'source,"gimbal_target",gimbal_cmd.position.yaw,gimbal_cmd.position.pitch' in modified
            assert 'gimbal_cmd.header.stamp = this->now();' in modified  # ignored for source, not retimed
        elif package=='armor_detector_opencv':
            assert 'SourceImage::ConstSharedPtr' in modified and 'source_msg->camera_info' in modified
            assert 'sourced.source_context=source.dump();sourced.armors=armors_msg_' in modified
            assert 'const sensor_msgs::msg::Image::ConstSharedPtr img_msg(source_msg,&source_msg->image)' in modified
        else:assert 'sourced.source_context=source.dump();sourced.target=target_msg' in modified
        with pytest.raises(ValueError):transform(cpp.replace('Callback(', 'DifferentCallback('),header)

def test_fresh_preparation_never_builds_launches_hardware_or_changes_upstream():
    if not SOURCE.exists():pytest.skip('Pinned upstream audit checkout not present')
    tracked=[SOURCE/package/'src'/node for package,node in [('armor_detector_opencv','detector_node.cpp'),
        ('armor_tracker','tracker_node.cpp'),('projectile_motion','projectile_motion_node.cpp')]]
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
    with tempfile.TemporaryDirectory() as temporary:
        out=Path(temporary)/'owned';manifest=tool.prepare(SOURCE,out)
        assert manifest['commit']==tool.COMMIT and manifest['build_executed'] is False and manifest['inference_executed'] is False
        assert not (out/'install').exists() and not (out/'build').exists()
        assert 'sensor_msgs/CameraInfo camera_info' in (out/'src/polar_pb_aim_interfaces/msg/SourceImage.msg').read_text()
        original_params=(SOURCE/'pb2025_vision_bringup/params/simulation/vision_params.yaml').read_bytes()
        assert (out/'PB_AIM_PARAMS.yaml').read_bytes()==original_params
        launch=(out/'pb_aim_launch.py').read_text()
        assert 'hik_camera' not in launch and 'respawn=False' in launch and "('/clock','clock')" in launch
        assert "settings['armor_tracker']['ros__parameters']['target_frame']='gimbal_aim_origin'" in launch
        assert "settings['projectile_motion']['ros__parameters']['projectile']['target_frame']='shooter_link'" in launch
        assert 'detect_color' not in launch and 'classifier_threshold' not in launch
        with pytest.raises(ValueError):tool.prepare(SOURCE,out)
    assert {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}==before
