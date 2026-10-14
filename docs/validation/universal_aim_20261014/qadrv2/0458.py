"""Prepare pinned PB2025 source-context overlays; never build or run algorithms."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
COMMIT='df1892c48f90093f86a2f7b02af6441a80aa2d97'
REPOSITORY='https://github.com/SMBU-PolarBear-Robotics-Team/pb2025_rm_vision'
PACKAGES=('armor_detector_opencv','armor_tracker','projectile_motion')
MODEL_SHA='b3250176ea8fdbe6d1585be954363757ff6a8245a81e8797f16cea601976d47a'
LABEL_SHA='8cc04e2a54c7ee1c39925c9ca8e6eebe2d1015ee9dab77ab3befd8095be74411'

def digest(raw):return hashlib.sha256(raw).hexdigest()
def once(text,old,new):
    if text.count(old)!=1:raise ValueError('PB adapter source anchor changed: '+old[:100])
    return text.replace(old,new,1)
def all_exact(text,old,new,count):
    if text.count(old)!=count:raise ValueError('PB adapter type count changed: '+old)
    return text.replace(old,new)

def detector_overlay(source,header):
    h=once(header,'#include <memory>','#include <memory>\n#include "polar_pb_aim_interfaces/msg/source_image.hpp"\n#include "polar_pb_aim_interfaces/msg/source_armors.hpp"\n#include "pb_aim_source.hpp"')
    h=once(h,'  void imageCallback(const sensor_msgs::msg::Image::ConstSharedPtr img_msg);',
        '  void imageCallback(const polar_pb_aim_interfaces::msg::SourceImage::ConstSharedPtr source_msg);')
    h=once(h,'rclcpp::Publisher<auto_aim_interfaces::msg::Armors>',
        'rclcpp::Publisher<polar_pb_aim_interfaces::msg::SourceArmors>')
    h=once(h,'rclcpp::Subscription<sensor_msgs::msg::Image>','rclcpp::Subscription<polar_pb_aim_interfaces::msg::SourceImage>')
    h=once(h,'  // Armor Detector','  std::unique_ptr<polar_pb_aim::SourceGate> pb_source_;\n\n  // Armor Detector')
    cpp=once(source,'  // Detector','  pb_source_=std::make_unique<polar_pb_aim::SourceGate>(*this);\n\n  // Detector')
    cpp=once(cpp,'this->create_publisher<auto_aim_interfaces::msg::Armors>',
        'this->create_publisher<polar_pb_aim_interfaces::msg::SourceArmors>')
    start=cpp.index('  cam_info_sub_ = this->create_subscription<sensor_msgs::msg::CameraInfo>(')
    end=cpp.index('  img_sub_ = this->create_subscription<sensor_msgs::msg::Image>(',start)
    original=cpp[start:end]
    if original.count('pnp_solver_ = std::make_unique<PnPSolver>')!=1:raise ValueError('PB one-shot CameraInfo anchor changed')
    cpp=once(cpp,original,'  // Calibrated CameraInfo travels in the exact same source carrier.\n\n')
    cpp=once(cpp,'this->create_subscription<sensor_msgs::msg::Image>',
        'this->create_subscription<polar_pb_aim_interfaces::msg::SourceImage>')
    cpp=once(cpp,'void ArmorDetectorOpencvNode::imageCallback(const sensor_msgs::msg::Image::ConstSharedPtr img_msg)\n{',
        '''void ArmorDetectorOpencvNode::imageCallback(const polar_pb_aim_interfaces::msg::SourceImage::ConstSharedPtr source_msg)
{
  const auto source=pb_source_->check(source_msg->source_context,source_msg->header);
  polar_pb_aim::check_headers(source_msg->header,source_msg->image.header);
  polar_pb_aim::check_headers(source_msg->header,source_msg->camera_info.header);
  const auto &input=source_msg->image;const auto &info=source_msg->camera_info;
  if(input.header.frame_id!="camera_optical" || (input.encoding!="rgb8" && input.encoding!="bgr8")
      || input.width==0 || input.height==0 || input.step!=input.width*3U
      || input.data.size()!=size_t(input.step)*input.height || info.width!=input.width || info.height!=input.height
      || info.distortion_model!="plumb_bob" || info.d.size()!=5)
    throw std::runtime_error("pb_aim_source_image_or_calibration");
  for(auto value:info.k)if(!std::isfinite(value))throw std::runtime_error("pb_aim_calibration_finite");
  for(auto value:info.d)if(!std::isfinite(value))throw std::runtime_error("pb_aim_calibration_finite");
  if(!pnp_solver_) {
    cam_center_=cv::Point2f(info.k[2],info.k[5]);
    cam_info_=std::make_shared<sensor_msgs::msg::CameraInfo>(info);
    pnp_solver_=std::make_unique<PnPSolver>(info.k,info.d);
  } else if(cam_info_->k!=info.k || cam_info_->d!=info.d || cam_info_->width!=info.width || cam_info_->height!=info.height)
    throw std::runtime_error("pb_aim_calibration_generation_changed");
  const sensor_msgs::msg::Image::ConstSharedPtr img_msg(source_msg,&source_msg->image);''')
    cpp=once(cpp,'    armors_pub_->publish(armors_msg_);','''    polar_pb_aim_interfaces::msg::SourceArmors sourced;
    sourced.header=armors_msg_.header;sourced.source_context=source.dump();sourced.armors=armors_msg_;
    armors_pub_->publish(sourced);''')
    cpp=once(cpp,'#include <algorithm>','#include <algorithm>\n#include <cmath>')
    return cpp,h

def tracker_overlay(source,header):
    h=once(header,'#include <memory>','#include <memory>\n#include "polar_pb_aim_interfaces/msg/source_armors.hpp"\n#include "polar_pb_aim_interfaces/msg/source_target.hpp"\n#include "pb_aim_source.hpp"')
    h=all_exact(h,'message_filters::Subscriber<auto_aim_interfaces::msg::Armors>',
        'message_filters::Subscriber<polar_pb_aim_interfaces::msg::SourceArmors>',1)
    h=all_exact(h,'tf2_ros::MessageFilter<auto_aim_interfaces::msg::Armors>',
        'tf2_ros::MessageFilter<polar_pb_aim_interfaces::msg::SourceArmors>',1)
    h=once(h,'  void armorsCallback(const auto_aim_interfaces::msg::Armors::SharedPtr armors_ptr);',
        '  void armorsCallback(const polar_pb_aim_interfaces::msg::SourceArmors::SharedPtr source_msg);')
    h=once(h,'rclcpp::Publisher<auto_aim_interfaces::msg::Target>',
        'rclcpp::Publisher<polar_pb_aim_interfaces::msg::SourceTarget>')
    h=once(h,'  // Armor tracker','  std::unique_ptr<polar_pb_aim::SourceGate> pb_source_;\n\n  // Armor tracker')
    cpp=once(source,'  // Maximum allowable armor distance in the XOY plane',
        '  pb_source_=std::make_unique<polar_pb_aim::SourceGate>(*this);\n\n  // Maximum allowable armor distance in the XOY plane')
    cpp=once(cpp,'this->create_publisher<auto_aim_interfaces::msg::Target>',
        'this->create_publisher<polar_pb_aim_interfaces::msg::SourceTarget>')
    cpp=once(cpp,'void ArmorTrackerNode::armorsCallback(const auto_aim_interfaces::msg::Armors::SharedPtr armors_msg)\n{',
        '''void ArmorTrackerNode::armorsCallback(const polar_pb_aim_interfaces::msg::SourceArmors::SharedPtr source_msg)
{
  const auto source=pb_source_->check(source_msg->source_context,source_msg->header);
  polar_pb_aim::check_headers(source_msg->header,source_msg->armors.header);
  auto armors_msg=std::make_shared<auto_aim_interfaces::msg::Armors>(source_msg->armors);''')
    cpp=once(cpp,'  target_pub_->publish(target_msg);','''  polar_pb_aim_interfaces::msg::SourceTarget sourced;
  sourced.header=target_msg.header;sourced.source_context=source.dump();sourced.target=target_msg;
  target_pub_->publish(sourced);''')
    return cpp,h

def projectile_overlay(source,header):
    h=once(header,'#include <cstdint>','#include <cstdint>\n#include "polar_pb_aim_interfaces/msg/source_target.hpp"\n#include "pb_aim_source.hpp"')
    h=all_exact(h,'tf2_ros::MessageFilter<auto_aim_interfaces::msg::Target>',
        'tf2_ros::MessageFilter<polar_pb_aim_interfaces::msg::SourceTarget>',1)
    h=all_exact(h,'message_filters::Subscriber<auto_aim_interfaces::msg::Target>',
        'message_filters::Subscriber<polar_pb_aim_interfaces::msg::SourceTarget>',1)
    h=once(h,'  void targetCallback(const auto_aim_interfaces::msg::Target::SharedPtr msg);',
        '  void targetCallback(const polar_pb_aim_interfaces::msg::SourceTarget::SharedPtr source_msg);')
    h=once(h,'  void publishGimbalCommand(double hit_pitch, double hit_yaw, uint8_t shoot);',
        '  void publishGimbalCommand(double hit_pitch, double hit_yaw, uint8_t shoot, const polar_pb_aim::Json & source);')
    h=once(h,'  void calculateTargetPosition(', '  bool calculateTargetPosition(')
    h=once(h,'  double offset_x_;','  std::unique_ptr<polar_pb_aim::SourceGate> pb_source_;\n  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr pb_result_;\n  double offset_x_;')
    cpp=once(source,'  offset_pitch_ = this->declare_parameter',
        '  pb_source_=std::make_unique<polar_pb_aim::SourceGate>(*this);\n  pb_result_=this->create_publisher<std_msgs::msg::String>("polar/pb/aim_result",rclcpp::QoS(1).reliable());\n  offset_pitch_ = this->declare_parameter')
    cpp=once(cpp,'void ProjectileMotionNode::targetCallback(const auto_aim_interfaces::msg::Target::SharedPtr msg)\n{',
        '''void ProjectileMotionNode::targetCallback(const polar_pb_aim_interfaces::msg::SourceTarget::SharedPtr source_msg)
{
  const auto source=pb_source_->check(source_msg->source_context,source_msg->header);
  polar_pb_aim::check_headers(source_msg->header,source_msg->target.header);
  auto msg=std::make_shared<auto_aim_interfaces::msg::Target>(source_msg->target);''')
    cpp=once(cpp,'    // Stop shooting','    polar_pb_aim::publish_result(pb_result_,source,"no_target");\n    // Stop shooting')
    cpp=once(cpp,'  publishGimbalCommand(hit_pitch, hit_yaw, 1);','  publishGimbalCommand(hit_pitch, hit_yaw, 1, source);')
    cpp=once(cpp,'  calculateTargetPosition(msg, center_position, center_velocity, cur_yaw_, hit_yaw, hit_pitch);',
        '''  if(!calculateTargetPosition(msg, center_position, center_velocity, cur_yaw_, hit_yaw, hit_pitch)) {
    polar_pb_aim::publish_result(pb_result_,source,"pending_result");
    return;
  }''')
    cpp=once(cpp,'void ProjectileMotionNode::calculateTargetPosition(', 'bool ProjectileMotionNode::calculateTargetPosition(')
    cpp=once(cpp,'  solver_->solve(target_predict_position.head(2).norm(), target_predict_position.z(), target_pitch);',
        '''  const bool solved=solver_->solve(target_predict_position.head(2).norm(), target_predict_position.z(), target_pitch);
  if(!solved)return false; // source_safety_hook: never read an unwritten pitch.''')
    cpp=once(cpp,'  publishHitYawMarker(hit_yaw, hit_pitch);','  publishHitYawMarker(hit_yaw, hit_pitch);\n  return true;')
    cpp=once(cpp,'void ProjectileMotionNode::publishGimbalCommand(double hit_pitch, double hit_yaw, uint8_t shoot)',
        'void ProjectileMotionNode::publishGimbalCommand(double hit_pitch, double hit_yaw, uint8_t shoot, const polar_pb_aim::Json & source)')
    cpp=once(cpp,'  gimbal_cmd_publisher_->publish(gimbal_cmd);',
        '  gimbal_cmd_publisher_->publish(gimbal_cmd);\n  polar_pb_aim::publish_result(pb_result_,source,"gimbal_target",gimbal_cmd.position.yaw,gimbal_cmd.position.pitch);')
    return cpp,h

INTERFACES={
 'SourceImage.msg':'std_msgs/Header header\nstring source_context\nsensor_msgs/Image image\nsensor_msgs/CameraInfo camera_info\n',
 'SourceArmors.msg':'std_msgs/Header header\nstring source_context\nauto_aim_interfaces/Armors armors\n',
 'SourceTarget.msg':'std_msgs/Header header\nstring source_context\nauto_aim_interfaces/Target target\n'}

def prepare(source,out):
    source=Path(source).absolute();out=Path(out).absolute()
    if out.exists() or source==out or source.is_relative_to(out) or out.is_relative_to(source):raise ValueError('Fresh independent owned output required')
    git=lambda *args:subprocess.run(['git','-c','core.autocrlf=true','-c','core.filemode=false','-C',str(source),*args],
        check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout
    if git('rev-parse','HEAD').decode().strip()!=COMMIT:raise ValueError('Pinned PB source commit required')
    if git('status','--porcelain','--untracked-files=no'):raise ValueError('Pristine pinned PB source required')
    tracked=git('ls-tree','-rz','--name-only',COMMIT).decode().split('\0')
    config_rel='pb2025_vision_bringup/params/simulation/vision_params.yaml'
    selected=[p for p in tracked if p and (p.split('/')[0] in PACKAGES or p in ('LICENSE','NOTICE','dependencies.repos',config_rel))]
    originals={};copied_bytes={}
    # Validate all copied bytes against fixed Git commit/LFS OIDs before creating output.
    for rel in selected:
        path=source/rel
        if path.is_symlink() or not path.is_file():raise ValueError('PB input symlink or missing: '+rel)
        raw=path.read_bytes();blob=git('show',COMMIT+':'+rel)
        if blob.startswith(b'version https://git-lfs.github.com/spec/v1\n'):
            oid=next(line.split(b':',1)[1].decode() for line in blob.splitlines() if line.startswith(b'oid sha256:'))
            if digest(raw)!=oid:raise ValueError('Pinned model LFS bytes mismatch: '+rel)
        elif raw!=blob:
            text_file=path.suffix in ('.cpp','.hpp','.h','.py','.md','.txt','.xml','.yaml','.repos','.svg') or path.name in (
                'LICENSE','NOTICE','.clang-format','.clang-tidy','.gitignore','.gitattributes')
            if not text_file or raw.replace(b'\r\n',b'\n')!=blob:raise ValueError('Pinned source bytes differ: '+rel)
        originals[rel]=dict(checkout_sha256=digest(raw),git_blob_sha256=digest(blob))
        copied_bytes[rel]=raw
    for rel,wanted in (('armor_detector_opencv/model/mlp.onnx',MODEL_SHA),('armor_detector_opencv/model/label.txt',LABEL_SHA)):
        if digest((source/rel).read_bytes())!=wanted:raise ValueError('Original classifier asset mismatch')
    out.mkdir(parents=True);src=out/'src';src.mkdir()
    try:
        for rel in selected:
            destination=(src/rel) if rel.split('/')[0] in PACKAGES else out/'upstream_notices'/rel
            destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(copied_bytes[rel])
        transformations=(('armor_detector_opencv','detector_node',detector_overlay),
            ('armor_tracker','tracker_node',tracker_overlay),('projectile_motion','projectile_motion_node',projectile_overlay))
        hooks={}
        for package,node,transform in transformations:
            cpp=src/package/'src'/f'{node}.cpp';header=src/package/'include'/package/f'{node}.hpp'
            c,h=transform(cpp.read_text(encoding='utf-8'),header.read_text(encoding='utf-8'))
            cpp.write_bytes(c.encode());header.write_bytes(h.encode())
            for name in ('pb_aim_source.hpp','pb_request_context.hpp'):
                raw=(ROOT/'rm_match/integrations'/name).read_bytes()
                (src/package/'include'/name).write_bytes(raw);hooks[name]=digest(raw)
            cmake=src/package/'CMakeLists.txt'
            text=cmake.read_text(encoding='utf-8')
            text=once(text,'ament_auto_find_build_dependencies()',
                'ament_auto_find_build_dependencies()\nfind_package(nlohmann_json REQUIRED)')
            text=once(text,'rclcpp_components_register_node(',
                'target_link_libraries(${PROJECT_NAME} nlohmann_json::nlohmann_json)\n\nrclcpp_components_register_node(')
            cmake.write_bytes(text.encode())
            xml=src/package/'package.xml';text=xml.read_text(encoding='utf-8')
            text=once(text,'  <export>',
                '  <depend>polar_pb_aim_interfaces</depend>\n  <depend>std_msgs</depend>\n\n  <export>')
            xml.write_bytes(text.encode())
        interface=src/'polar_pb_aim_interfaces';(interface/'msg').mkdir(parents=True)
        for name,contents in INTERFACES.items():(interface/'msg'/name).write_bytes(contents.encode())
        (interface/'package.xml').write_bytes(b'''<?xml version="1.0"?>
<package format="3"><name>polar_pb_aim_interfaces</name><version>0.1.0</version>
<description>Exact capture source carriers, adapter only</description>
<maintainer email="simulator@example.invalid">Simulator</maintainer><license>Apache-2.0</license>
<buildtool_depend>ament_cmake</buildtool_depend><buildtool_depend>rosidl_default_generators</buildtool_depend>
<depend>std_msgs</depend><depend>sensor_msgs</depend><depend>auto_aim_interfaces</depend>
<exec_depend>rosidl_default_runtime</exec_depend><member_of_group>rosidl_interface_packages</member_of_group>
<export><build_type>ament_cmake</build_type></export></package>
''')
        (interface/'CMakeLists.txt').write_bytes(b'''cmake_minimum_required(VERSION 3.8)
project(polar_pb_aim_interfaces)
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(auto_aim_interfaces REQUIRED)
rosidl_generate_interfaces(${PROJECT_NAME} "msg/SourceImage.msg" "msg/SourceArmors.msg" "msg/SourceTarget.msg" DEPENDENCIES std_msgs sensor_msgs auto_aim_interfaces)
ament_export_dependencies(rosidl_default_runtime)
ament_package()
''')
        # Preserve the literal parameter snapshot. The actual ROS launch uses
        # its standard YAML loader and only these explicit adapter frame/time
        # overrides. Preparation does not invent a partial YAML parser.
        (out/'PB_AIM_PARAMS.yaml').write_bytes(copied_bytes[config_rel])
        (out/'pb_aim_launch.py').write_bytes(b'''"""Owned source-context pipeline only; no hardware driver or fake TF."""
import os
import yaml
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
def generate_launch_description():
    names=('namespace','run_uuid','calibration_id')
    arguments=[DeclareLaunchArgument(name) for name in names]
    namespace=LaunchConfiguration('namespace')
    context={'pb.run_uuid':LaunchConfiguration('run_uuid'),'pb.calibration_id':LaunchConfiguration('calibration_id')}
    params=os.path.join(os.path.dirname(__file__),'PB_AIM_PARAMS.yaml')
    with open(params,encoding='utf-8') as stream:settings=yaml.safe_load(stream)
    for package in ('armor_detector_opencv','armor_tracker','projectile_motion'):
        settings[package]['ros__parameters']['use_sim_time']=True
    settings['armor_tracker']['ros__parameters']['target_frame']='gimbal_aim_origin'
    settings['projectile_motion']['ros__parameters']['projectile']['target_frame']='shooter_link'
    nodes=[Node(package=package,executable=package+'_node',name=package,namespace=namespace,
        parameters=[settings[package]['ros__parameters'],context],remappings=[('/tf','tf'),('/tf_static','tf_static'),('/clock','clock')],
        output='screen',respawn=False) for package in ('armor_detector_opencv','armor_tracker','projectile_motion')]
    return LaunchDescription(arguments+nodes)
''')
        generated={str(p.relative_to(out)).replace('\\','/'):digest(p.read_bytes()) for p in out.rglob('*') if p.is_file()}
        result=dict(schema='polar.pb-aim-source-overlay.v1',repository=REPOSITORY,commit=COMMIT,original_inputs=originals,
            generator_sha256=digest(Path(__file__).read_bytes()),source_hooks_sha256=hooks,generated_sha256=generated,
            adapter_sources_sha256={rel:digest((ROOT/rel).read_bytes()) for rel in (
                'rm_match/integrations/pb_aim_contract.py','rm_match/integrations/pb_aim_ros_peer.py',
                'rm_match/integrations/pb_aim_configure.py','rm_match/integrations/pb_aim_stack.py',
                'rm_match/integrations/pb_aim_engine.py',
                'rm_match/integrations/aim_jsonl_peer.py','tools/prepare_pb_aim_stack.py',
                'rm_match/integrations/aim_camera_codec.py','rm_match/integrations/ros2_bridge.py',
                'rm_match/platform_v2/aim_contracts.py','rm_match/platform_v2/contracts.py')},
            packages=list(PACKAGES)+['polar_pb_aim_interfaces'],build_executed=False,inference_executed=False,
            algorithm_change='source carriers and failed-solve safety boundary; successful detector/tracker/solver mathematics unchanged',
            source_safety_hook=dict(reason='Original ignored false solver result may read unwritten target_pitch',
                original_cpp_sha256=originals['projectile_motion/src/projectile_motion_node.cpp']['checkout_sha256'],
                generated_cpp_sha256=generated['src/projectile_motion/src/projectile_motion_node.cpp'],
                unique_anchor='solver_->solve(target_predict_position.head(2).norm(), target_predict_position.z(), target_pitch);',
                failure='pending_result with original source context and null angles; no gimbal command'),
            startup_protocol='Actual unconfigured model nodes before prepare ACK; original reset context arms once after three matching source-node ACKs',
            original_classifier_sha256=MODEL_SHA,required_dependencies=['auto_aim_interfaces','pb_rm_interfaces',
                'rmoss_projectile_motion','nlohmann_json','ROS2 Humble cv_bridge/message_filters/tf2/ament/python3-yaml'],
            feedback_scope='capture-own gimbal feedback and frozen simulated muzzle calibration, stationary-first',
            fire_authority='manual_only; cmd_shoot topic never connected to platform')
        if git('rev-parse','HEAD').decode().strip()!=COMMIT:raise ValueError('Pinned source changed during prepare')
        for rel,row in originals.items():
            if digest((source/rel).read_bytes())!=row['checkout_sha256']:raise ValueError('Pinned input changed during prepare: '+rel)
        (out/'SOURCE_MANIFEST.json').write_bytes((json.dumps(result,indent=2)+'\n').encode())
        return result
    except BaseException as exc:
        (out/'PREPARE_FAILED.json').write_bytes((json.dumps(dict(error_type=type(exc).__name__,error=str(exc)))+'\n').encode())
        raise

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(argv);result=prepare(args.source,args.out)
    print(json.dumps(dict(schema=result['schema'],commit=result['commit'],packages=result['packages'],build_executed=False)))
    return 0
if __name__=='__main__':raise SystemExit(main())
