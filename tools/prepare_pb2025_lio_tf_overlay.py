"""Generate owned Point-LIO/TF sources from fixed pristine PB2025 git blobs.

No upstream scripts, build, system installation, or source mutation is performed.
The target must be fresh. Local working bytes must match canonical blobs (CRLF
checkout differences are accepted); HEAD, all anchors and edited SHA are fixed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = Path(__file__).with_name('pb2025_overlay')
HEADS = {'pb2025_sentry_nav': 'cb97fb07ace54fcc617ddb884227ef85fe4b8f85', 'point_lio2025': '641424bf9d924f5ba0bd87ca9d91a4f148384925'}
EDIT_SHA = {
 'sensor_scan_generation/src/sensor_scan_generation.cpp': 'cb6a4f81568de22a8a83cf977f63afb71c563bc5c6cdd4ce89be7047c1e0e7a2',
 'sensor_scan_generation/include/sensor_scan_generation/sensor_scan_generation.hpp': '52341f6806609205f38138c7f2f784369de484c614b0b8311a5f0f05fd2787f6',
 'loam_interface/src/loam_interface.cpp': 'e564e850847994f622408d8d0d84c76bfa8b011dc436f3efe85842455188edd6',
 'loam_interface/include/loam_interface/loam_interface.hpp': '67b9e0676f6852d96ddf414b947c1313f7f7b0cf2ac63fee5e229c5740492a86',
 'src/laserMapping.cpp': '411240dda869824b0e3cfcde8f7e2c7b7995835f0f72eff2e4ac1499ef789139',
 'src/li_initialization.cpp': '422fd636b9417b0f705803e3cef4818a024ccb72eaa8bd4ffeb2cd53b39c5398',
 'src/li_initialization.h': '7bd6129ceb9a0d2b3da176d02fd3ee811a7fbe12b1be54d9c1ea57bc09a2c6fe',
 'include/common_lib.h': 'b60ab7ffa402e0eb7dc72cfaf4c5e5efe988e88883ce253f4c40fc8056f4f230',
 'CMakeLists.txt': '1dd779626f52fc69e82064e92b94f5ca896a0ffd1c0ca55ca0b271a4b0d953d7',
 'package.xml': 'b0ee7790647660655a295bf9e379ca85018f745ad55085a1199d32b96e51e4dd',
}

def sha(data): return hashlib.sha256(data).hexdigest()
def command(repo, *args): return subprocess.check_output(['git', *args], cwd=repo)
def replace_once(text, old, new):
    if text.count(old) != 1: raise ValueError('pb_overlay_anchor_not_unique')
    return text.replace(old, new, 1)

def transform(name, text):
    if sha(text.encode()) != EDIT_SHA[name]: raise ValueError('pb_overlay_original_sha')
    if name.endswith('sensor_scan_generation.hpp'):
        text=replace_once(text,'sync_policies/approximate_time.h','sync_policies/exact_time.h')
        text=replace_once(text,'sync_policies::ApproximateTime<','sync_policies::ExactTime<')
        text=replace_once(text,'#include <string>','#include <string>\n#include "pb_sim_stamp.hpp"')
        text=replace_once(text,'  tf2::Transform tf_lidar_to_robot_base_;','  tf2::Transform tf_lidar_to_robot_base_;\n  tf2::Transform previous_transform_;\n  polar_pb::SimStampSequence stamp_sequence_;')
    elif name.endswith('sensor_scan_generation.cpp'):
        text=replace_once(text,'#include "pcl_ros/transforms.hpp"','#include "pcl_ros/transforms.hpp"\n#include <cmath>')
        text=replace_once(text,'    SyncPolicy(100),','    SyncPolicy(8),')
        text=replace_once(text,'  tf2::Transform tf_lidar_to_chassis;', '''  if (odometry_msg->header.stamp != pcd_msg->header.stamp ||
      odometry_msg->header.frame_id != "odom" || pcd_msg->header.frame_id != "odom" ||
      odometry_msg->child_frame_id != lidar_frame_) {
    RCLCPP_WARN(this->get_logger(), "pb_exact_scan_pair_rejected"); return;
  }
  tf2::Transform tf_lidar_to_chassis;''')
        old='''  tf_lidar_to_robot_base_ = getTransform(lidar_frame_, robot_base_frame_, pcd_msg->header.stamp);
  tf_lidar_to_chassis = getTransform(lidar_frame_, base_frame_, pcd_msg->header.stamp);'''
        text=replace_once(text,old,'''  try {
    tf_lidar_to_robot_base_ = getTransform(lidar_frame_, robot_base_frame_, pcd_msg->header.stamp);
    tf_lidar_to_chassis = getTransform(lidar_frame_, base_frame_, pcd_msg->header.stamp);
  } catch (const tf2::TransformException &) {
    RCLCPP_WARN(this->get_logger(), "pb_missing_calibration_tf"); return;
  }
  const auto &p = tf_odom_to_lidar.getOrigin();
  const auto &q = tf_odom_to_lidar.getRotation();
  if (!std::isfinite(p.x()) || !std::isfinite(p.y()) || !std::isfinite(p.z()) ||
      !std::isfinite(q.length2()) || std::abs(q.length2()-1.0) > 1e-6) return;
  double dt;
  if (!stamp_sequence_.accept(rclcpp::Time(pcd_msg->header.stamp).nanoseconds(), dt)) return;''')
        text=replace_once(text,'time, rclcpp::Duration::from_seconds(0.5)','rclcpp::Time(0, 0, RCL_ROS_TIME), rclcpp::Duration::from_seconds(0.0)')
        text=replace_once(text,'    tf2::Transform transform;\n    tf2::fromMsg(transform_stamped.transform, transform);', '''    (void)time;
    if (rclcpp::Time(transform_stamped.header.stamp).nanoseconds() != 0)
      throw tf2::InvalidArgumentException("pb_mount_must_be_static");
    tf2::Transform transform;
    tf2::fromMsg(transform_stamped.transform, transform);
    const auto &p = transform.getOrigin(); const auto &q = transform.getRotation();
    if (!std::isfinite(p.x()) || !std::isfinite(p.y()) || !std::isfinite(p.z()) ||
        !std::isfinite(q.length2()) || std::abs(q.length2()-1.0) > 1e-6)
      throw tf2::InvalidArgumentException("pb_mount_invalid");''')
        text=replace_once(text,'    RCLCPP_WARN(this->get_logger(), "TF lookup failed: %s. Returning identity.", ex.what());\n    return tf2::Transform::getIdentity();','    (void)ex;\n    throw;')
        old=text[text.index('  static tf2::Transform previous_transform;'):text.index('  pub_chassis_odometry_->publish(out);')]
        new='''  // Stamp sequence was accepted once in the exact cloud/odom callback.
  // One node is owned by one episode/binding; stack reset creates a fresh node.
  const int64_t current_ns = rclcpp::Time(stamp).nanoseconds();
  static_cast<void>(current_ns);
  static_cast<void>(parent_frame);
  if (previous_stamp_ns_ > 0) {
    const double dt = static_cast<double>(current_ns - previous_stamp_ns_) * 1e-9;
    const auto rotation_to_body = transform.getRotation().inverse();
    const auto world_v = (transform.getOrigin() - previous_transform_.getOrigin()) / dt;
    const auto body_v = tf2::quatRotate(rotation_to_body, world_v);
    auto q_diff = transform.getRotation() * previous_transform_.getRotation().inverse();
    if (q_diff.w() < 0) q_diff = tf2::Quaternion(-q_diff.x(), -q_diff.y(), -q_diff.z(), -q_diff.w());
    const auto world_w = q_diff.getAxis() * q_diff.getAngle() / dt;
    const auto body_w = tf2::quatRotate(rotation_to_body, world_w);
    out.twist.twist.linear.x = body_v.x(); out.twist.twist.linear.y = body_v.y(); out.twist.twist.linear.z = body_v.z();
    out.twist.twist.angular.x = body_w.x(); out.twist.twist.angular.y = body_w.y(); out.twist.twist.angular.z = body_w.z();
  }
  previous_transform_ = transform;
  previous_stamp_ns_ = current_ns;

'''
        text=replace_once(text,old,new)
    elif name.endswith('loam_interface.hpp'):
        text=replace_once(text,'  bool base_frame_to_lidar_initialized_;','  bool ensureCalibration(const rclcpp::Time &stamp);\n  bool base_frame_to_lidar_initialized_;')
    elif name.endswith('loam_interface.cpp'):
        text=replace_once(text,'#include "pcl_ros/transforms.hpp"','#include "pcl_ros/transforms.hpp"\n#include <cmath>')
        text=replace_once(text,'  // NOTE: Input point cloud message', '''  if (msg->header.frame_id != "camera_init" || !ensureCalibration(msg->header.stamp)) return;
  // NOTE: Input point cloud message''')
        start=text.index('  if (!base_frame_to_lidar_initialized_) {',text.index('void LoamInterfaceNode::odometryCallback'))
        end=text.index('  // Transform the odometry_msg', start)
        text=replace_once(text,text[start:end],'''  if (msg->header.frame_id != "camera_init" || msg->child_frame_id != "body" ||
      !ensureCalibration(msg->header.stamp)) return;

''')
        method='''bool LoamInterfaceNode::ensureCalibration(const rclcpp::Time &stamp)
{
  if (base_frame_to_lidar_initialized_) return true;
  try {
    (void)stamp;
    auto calibrated = tf_buffer_->lookupTransform(base_frame_, lidar_frame_, rclcpp::Time(0, 0, RCL_ROS_TIME),
      rclcpp::Duration::from_seconds(0.0));
    // Reviewed deployment only publishes this mount as static TF.
    if (rclcpp::Time(calibrated.header.stamp).nanoseconds() != 0) return false;
    tf2::Transform value; tf2::fromMsg(calibrated.transform, value);
    const auto &p = value.getOrigin(); const auto &q = value.getRotation();
    if (!std::isfinite(p.x()) || !std::isfinite(p.y()) || !std::isfinite(p.z()) ||
        !std::isfinite(q.length2()) || std::abs(q.length2()-1.0) > 1e-6) return false;
    tf_odom_to_lidar_odom_ = value; base_frame_to_lidar_initialized_ = true; return true;
  } catch (const tf2::TransformException &) {
    RCLCPP_WARN(this->get_logger(), "pb_missing_static_calibration"); return false;
  }
}

'''
        text=replace_once(text,'void LoamInterfaceNode::odometryCallback',method+'void LoamInterfaceNode::odometryCallback')
    elif name == 'include/common_lib.h':
        text=replace_once(text,'struct MeasureGroup  //', '#include "pb_scan_source.hpp"\n\nstruct MeasureGroup  //')
        text=replace_once(text,'  double lidar_beg_time;','  std::shared_ptr<const polar_pb::Json> pb_context;\n  double lidar_beg_time;')
    elif name == 'src/li_initialization.h':
        text=replace_once(text,'extern std::deque<double> time_buffer;', 'extern std::deque<double> time_buffer;\nextern polar_pb::ScanSource pb_scan_source;\nextern std::deque<std::shared_ptr<const polar_pb::Json>> pb_context_buffer;')
    elif name == 'src/li_initialization.cpp':
        text=replace_once(text,'std::deque<double> time_buffer;', 'std::deque<double> time_buffer;\npolar_pb::ScanSource pb_scan_source;\nstd::deque<std::shared_ptr<const polar_pb::Json>> pb_context_buffer;')
        text=replace_once(text,'  // mtx_buffer.lock();\n  double preprocess_start_time = omp_get_wtime();', '''  // Context is captured before preprocessing, not selected at pose publication.
  if (con_frame || cut_frame_init || lidar_buffer.size() >= 8 ||
      msg->header.frame_id != "livox_frame" || msg->point_num != msg->points.size()) return;
  auto bound = pb_scan_source.bind(rclcpp::Time(msg->header.stamp).nanoseconds(), msg->timebase);
  if (!bound) { RCLCPP_WARN(rclcpp::get_logger("li_initialization"), "pb_unassociated_raw_scan"); return; }
  double preprocess_start_time = omp_get_wtime();''')
        ingress = text.index('void livox_pcl_cbk(')
        text = text[:ingress] + replace_once(text[ingress:],'        lidar_buffer.emplace_back(ptr);\n        time_buffer.emplace_back(rclcpp::Time(msg->header.stamp).seconds());', '        lidar_buffer.emplace_back(ptr);\n        time_buffer.emplace_back(rclcpp::Time(msg->header.stamp).seconds());\n        pb_context_buffer.emplace_back(std::move(bound));')
        # Both source assignments and both queue pops remain aligned with one actual scan.
        if text.count('meas.lidar = lidar_buffer.front();') != 2: raise ValueError('pb_measure_anchor')
        text=text.replace('meas.lidar = lidar_buffer.front();','meas.lidar = lidar_buffer.front();\n          meas.pb_context = pb_context_buffer.front();')
        if text.count('lidar_buffer.pop_front();') != 3: raise ValueError('pb_pop_anchor')
        # There are two active pops and one upstream commented-out pop.
        text=replace_once(text,'        lidar_buffer.pop_front();\n        lidar_pushed', '        lidar_buffer.pop_front();\n        pb_context_buffer.pop_front();\n        lidar_pushed')
        text=replace_once(text,'    lidar_buffer.pop_front();\n    time_buffer.pop_front();', '    lidar_buffer.pop_front();\n    pb_context_buffer.pop_front();\n    time_buffer.pop_front();')
        text=replace_once(text,'bool sync_packages(MeasureGroup & meas)\n{','bool sync_packages(MeasureGroup & meas)\n{\n  if (pb_context_buffer.size() != lidar_buffer.size() || time_buffer.size() != lidar_buffer.size())\n    throw std::runtime_error("pb_scan_queue_alignment");')
        text=replace_once(text,'''  msg->header.stamp = get_ros_time(
    get_time_sec(msg_in->header.stamp) - timediff_imu_wrt_lidar - time_lag_IMU_wtr_lidar);''', '''  if (timediff_imu_wrt_lidar != 0.0 || time_lag_IMU_wtr_lidar != 0.0 ||
      msg_in->header.frame_id != "livox_frame") return;
  msg->header.stamp = msg_in->header.stamp;  // Exact original simulator sample stamp.''')
        text=replace_once(text,'  imu_deque.emplace_back(msg);', '''  if (imu_deque.size() >= 4096) {
    RCLCPP_ERROR(rclcpp::get_logger("li_initialization"), "pb_imu_buffer_overflow_stop");
    throw std::runtime_error("pb_imu_buffer_overflow_stop");
  }
  imu_deque.emplace_back(msg);''')
    elif name == 'src/laserMapping.cpp':
        text=replace_once(text,'#include <nav_msgs/msg/path.hpp>', '#include <nav_msgs/msg/path.hpp>\n#include <std_msgs/msg/string.hpp>')
        text=replace_once(text,'imu_topic, rclcpp::SensorDataQoS(), imu_cbk', 'imu_topic, rclcpp::SensorDataQoS().keep_last(1024), imu_cbk')
        text=replace_once(text,'nav_msgs::msg::Odometry odomAftMapped;', 'nav_msgs::msg::Odometry odomAftMapped;\nrclcpp::Publisher<std_msgs::msg::String>::SharedPtr pb_localization_publisher;')
        text=replace_once(text,'  set_posestamp(odomAftMapped.pose.pose);', '''  set_posestamp(odomAftMapped.pose.pose);
  try {
    auto source = polar_pb::localization_event(Measures.pb_context,
      rclcpp::Time(odomAftMapped.header.stamp).nanoseconds());
    std_msgs::msg::String event; event.data = source.dump();
    pb_localization_publisher->publish(event);
  } catch (const std::exception &) {
    RCLCPP_WARN(LOGGER, "pb_unassociated_estimated_pose"); return;
  }''')
        text=replace_once(text,'  readParameters(nh);', '''  readParameters(nh);
  if (lidar_type != AVIA || con_frame || cut_frame || cut_frame_init ||
      publish_odometry_without_downsample || !imu_en || time_diff_lidar_to_imu != 0.0)
    throw std::runtime_error("pb_owned_lio_configuration_required");
  const auto robot = nh->declare_parameter<std::string>("pb.expected_robot_id", "red_sentry");
  const auto episode = nh->declare_parameter<int64_t>("pb.expected_episode", 0);
  const auto epoch = nh->declare_parameter<int64_t>("pb.expected_binding_epoch", 1);
  pb_scan_source.configure(robot, episode, epoch);
  pb_localization_publisher = nh->create_publisher<std_msgs::msg::String>("/polar/pb/localization", rclcpp::QoS(8).reliable());
  auto pb_request_subscription = nh->create_subscription<std_msgs::msg::String>(
    "/polar/pb/request", rclcpp::QoS(1).reliable(), [](std_msgs::msg::String::ConstSharedPtr msg) {
      try { pb_scan_source.install(msg->data); }
      catch (const polar_pb::GenerationFault &) { RCLCPP_ERROR(LOGGER, "pb_generation_changed_stop"); throw; }
      catch (const std::exception &) { RCLCPP_WARN(LOGGER, "pb_request_context_rejected"); }
    });''')
    elif name == 'CMakeLists.txt':
        text=replace_once(text,'find_package(ament_cmake REQUIRED)', 'find_package(ament_cmake REQUIRED)\nfind_package(std_msgs REQUIRED)\nfind_package(nlohmann_json REQUIRED)')
        text=replace_once(text,'ament_target_dependencies(pointlio_mapping\n', 'target_link_libraries(pointlio_mapping nlohmann_json::nlohmann_json)\nament_target_dependencies(pointlio_mapping\n  std_msgs\n')
    elif name == 'package.xml':
        text=replace_once(text,'  <depend>rclcpp</depend>', '  <depend>rclcpp</depend>\n  <depend>std_msgs</depend>\n  <depend>nlohmann-json-dev</depend>')
    return text

def generate(source_root: Path, out: Path, *, namespace='red_sentry', episode=0, binding_epoch=1):
    if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}', namespace): raise ValueError('pb_namespace')
    if type(episode) is not int or type(binding_epoch) is not int or min(episode,binding_epoch)<0: raise ValueError('pb_generation')
    if out.exists(): raise ValueError('pb_output_must_be_fresh')
    prepared = {}; originals = {}
    for repo_name, head in HEADS.items():
        repo=source_root/repo_name
        if command(repo,'rev-parse','HEAD').decode().strip()!=head: raise ValueError('pb_source_head')
        if command(repo,'status','--porcelain=v1'): raise ValueError('pb_source_not_pristine')
        names=command(repo,'ls-tree','-r','--name-only','HEAD').decode().splitlines()
        for name in names:
            if repo_name=='pb2025_sentry_nav' and not name.startswith(('loam_interface/','sensor_scan_generation/')): continue
            # Runtime log destinations are not algorithm inputs and cannot be
            # included as immutable source artifacts that the native LIO writes.
            if repo_name=='point_lio2025' and name.startswith('Log/') and name.endswith('.txt'): continue
            # Point-LIO is small and its existing install/log paths are preserved.
            raw=command(repo,'show','HEAD:'+name)
            local=repo/name
            if local.is_file():
                working = local.read_bytes()
                if working != raw and working.replace(b'\r\n',b'\n') != raw:
                    raise ValueError('pb_working_bytes_changed')
            target=name if repo_name=='pb2025_sentry_nav' else 'point_lio/'+name
            value=transform(name,raw.decode('utf-8')).encode() if name in EDIT_SHA else raw
            # Additional member accompanies the stamp clock added to the fixed header.
            if name.endswith('sensor_scan_generation.hpp'):
                value=replace_once(value.decode(),'  polar_pb::SimStampSequence stamp_sequence_;','  polar_pb::SimStampSequence stamp_sequence_;\n  int64_t previous_stamp_ns_ = 0;').encode()
            prepared[target]=value; originals[target]=sha(raw)
    for pkg in ('point_lio','sensor_scan_generation'):
        extra=['pb_scan_source.hpp'] if pkg=='point_lio' else ['pb_sim_stamp.hpp']
        for name in extra: prepared[pkg+'/include/'+name]=(TEMPLATES/name).read_bytes()
    prepared['point_lio/include/pb_request_context.hpp']=(ROOT/'rm_match/integrations/pb_request_context.hpp').read_bytes()
    prepared['owned_lio.launch.py']=launch_text(namespace,episode,binding_epoch).encode()
    manifest={'schema':'polar.pb2025.lio-tf-overlay.v1','upstream':HEADS,'namespace':namespace,'base_frame':'base_link','lidar_frame':'livox_frame','episode':episode,'binding_epoch':binding_epoch,'build_executed':False,'source_root':str(source_root.resolve()),'files':{n:{'original_sha256':originals.get(n),'sha256':sha(v)} for n,v in prepared.items()},'generator_sha256':sha(Path(__file__).read_bytes())}
    out.mkdir(parents=True)
    for name,value in prepared.items():
        p=out/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(value)
    (out/'OVERLAY_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf8')
    return manifest

def launch_text(namespace,episode,epoch):
    params={'use_sim_time':True,'common.lid_topic':'livox/lidar','common.imu_topic':'livox/imu','common.con_frame':False,'common.cut_frame':False,'common.time_diff_lidar_to_imu':0.0,'preprocess.lidar_type':1,'preprocess.scan_line':4,'preprocess.timestamp_unit':3,'mapping.imu_time_inte':0.002,'mapping.acc_norm':9.81,'mapping.extrinsic_est_en':False,'mapping.extrinsic_T':[0.0,0.0,0.0],'mapping.extrinsic_R':[1.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0],'mapping.gravity_init':[0.0,0.0,-9.81],'prior_pcd.enable':False,'odometry.publish_odometry_without_downsample':False,'publish.scan_publish_en':True,'publish.tf_send_en':False,'runtime_pos_log_enable':False,'pcd_save.pcd_save_en':False,'pb.expected_robot_id':namespace,'pb.expected_episode':episode,'pb.expected_binding_epoch':epoch}
    return f'''# Owned sensing/localization only. No Gazebo, hardware driver, fakeVel or controller.
from launch import LaunchDescription
from launch_ros.actions import Node
def generate_launch_description():
    return LaunchDescription([
        Node(package='point_lio', executable='pointlio_mapping', namespace={namespace!r}, parameters=[{params!r}], output='screen'),
        Node(package='loam_interface', executable='loam_interface_node', namespace={namespace!r}, parameters=[{{'use_sim_time':True,'state_estimation_topic':'aft_mapped_to_init','registered_scan_topic':'cloud_registered','odom_frame':'odom','base_frame':'base_link','lidar_frame':'livox_frame'}}], output='screen'),
        Node(package='sensor_scan_generation', executable='sensor_scan_generation_node', namespace={namespace!r}, parameters=[{{'use_sim_time':True,'base_frame':'base_link','robot_base_frame':'base_link','lidar_frame':'livox_frame'}}], output='screen'),
    ])
'''

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--namespace',default='red_sentry');p.add_argument('--episode',type=int,default=0);p.add_argument('--binding-epoch',type=int,default=1)
    a=p.parse_args(argv);m=generate(a.source_root,a.out,namespace=a.namespace,episode=a.episode,binding_epoch=a.binding_epoch)
    print(json.dumps({'out':str(a.out.resolve()),'file_count':len(m['files']),'build_executed':False}))
    return 0
if __name__=='__main__': raise SystemExit(main())
