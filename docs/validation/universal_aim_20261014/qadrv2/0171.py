"""Create owned interface/compute-hook sources from fixed upstream git objects."""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

LIVOX_COMMIT='524e14a1ec714e427bde729a8f869bb7acd8507d'
CONTROLLER_COMMIT='0b95c800e61f8abbdddfcf6b07f8838b842724c3'
LIVOX_HASHES={'msg/CustomMsg.msg':'f42d6709db951b1fa307e929e742c0593cbf0d1b0ff977d2ed63ad8d7cee0a96',
    'msg/CustomPoint.msg':'b64b31a8edc8c8b3765d82b5d3ccd2d2e1f217b9525ef7007ab918674c619c59'}
CONTROLLER_HASHES={'src/omni_pid_pursuit_controller.cpp':'40fffeb2c3a70a2f92024aad528126e96d414cb48006f85ed75a9dd9796856b0',
    'include/pb_omni_pid_pursuit_controller/omni_pid_pursuit_controller.hpp':'026ad1eaed238a101fc2f577472cd5379b39b8b986b3f09061890a7c1802dc75',
    'package.xml':'2fcd82729a38a72e939a092b26771f5b4dc76154f6abc1f32574ec39c5ffc8a2'}


def sha(raw):return hashlib.sha256(raw).hexdigest()


def git_snapshot(source,commit,paths=()):
    source=Path(source)
    actual=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    if actual!=commit:raise ValueError('pb_upstream_commit_mismatch')
    # git archive otherwise applies this Windows checkout's core.autocrlf.
    # Commit identity means original Git-object bytes, not a platform rewrite.
    raw=subprocess.check_output(['git','-c','core.autocrlf=false','-C',str(source),'archive','--format=tar',commit,*paths])
    if len(raw)>10*1024*1024:raise ValueError('pb_source_archive_oversized')
    files={}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive:
            p=PurePosixPath(member.name)
            if p.is_absolute() or '..' in p.parts or '\\' in member.name or not member.isdir() and not member.isfile():raise ValueError('pb_source_archive_unsafe')
            if member.isfile():files[str(p)]=archive.extractfile(member).read()
    return files


def verify(files,hashes):
    for name,expected in hashes.items():
        if name not in files or sha(files[name])!=expected:raise ValueError('pb_frozen_source_hash_mismatch')


def replace_once(raw,old,new):
    old=old.encode();new=new.encode()
    if raw.count(old)!=1:raise ValueError('pb_overlay_anchor_mismatch')
    return raw.replace(old,new,1)


def controller_overlay(files,header,request_header=None):
    verify(files,CONTROLLER_HASHES);files=dict(files)
    name='src/omni_pid_pursuit_controller.cpp';raw=files[name]
    marker='  heading_pid_ = std::make_shared<PID>(\n    control_duration_, v_angular_max_, v_angular_min_, rotation_kp_, rotation_kd_, rotation_ki_);'
    raw=replace_once(raw,marker,marker+'\n  polar_sourced_.configure(node, costmap_ros_->getBaseFrameID());')
    for marker,addition in [('  curvature_points_pub_.reset();','\n  polar_sourced_.cleanup();'),
        ('  curvature_points_pub_->on_activate();','\n  polar_sourced_.activate();'),
        ('  curvature_points_pub_->on_deactivate();','\n  polar_sourced_.deactivate();')]:raw=replace_once(raw,marker,marker+addition)
    marker='  std::lock_guard<std::mutex> lock_reinit(mutex_);\n\n  nav2_costmap_2d::Costmap2D * costmap = costmap_ros_->getCostmap();'
    raw=replace_once(raw,marker,'  std::lock_guard<std::mutex> lock_reinit(mutex_);\n  const auto polar_request = polar_sourced_.begin(pose);\n\n  nav2_costmap_2d::Costmap2D * costmap = costmap_ros_->getCostmap();')
    raw=replace_once(raw,'  return cmd_vel;','  polar_sourced_.finish(polar_request, pose, cmd_vel);\n  return cmd_vel;');files[name]=raw
    name='include/pb_omni_pid_pursuit_controller/omni_pid_pursuit_controller.hpp'
    raw=replace_once(files[name],'#include <memory>','#include <memory>\n#include "pb_omni_pid_pursuit_controller/polar_controller_context.hpp"')
    files[name]=replace_once(raw,'private:\n  /**\n   * @brief Applies curvature',
        'private:\n  polar_pb::ControllerContext polar_sourced_;\n  /**\n   * @brief Applies curvature')
    files['include/pb_omni_pid_pursuit_controller/polar_controller_context.hpp']=header
    if request_header is None:request_header=Path(__file__).with_name('pb_request_context.hpp').read_bytes()
    files['include/pb_omni_pid_pursuit_controller/pb_request_context.hpp']=request_header
    files['package.xml']=replace_once(files['package.xml'],'  <depend>geometry_msgs</depend>',
        '  <depend>geometry_msgs</depend>\n  <depend>std_msgs</depend>\n  <depend>nav_msgs</depend>\n  <build_depend>nlohmann_json</build_depend>')
    files['CMakeLists.txt']=replace_once(files['CMakeLists.txt'],'ament_auto_find_build_dependencies()',
        'ament_auto_find_build_dependencies()\nfind_package(nlohmann_json 3.2.0 REQUIRED)')
    files['CMakeLists.txt']=replace_once(files['CMakeLists.txt'],'if(BUILD_TESTING)',
        'target_link_libraries(${PROJECT_NAME} nlohmann_json::nlohmann_json)\n\nif(BUILD_TESTING)')
    return files


def write_owned(out,files,metadata):
    out=Path(out).absolute()
    if out.exists():raise ValueError('pb_owned_output_already_exists')
    # Reject link ancestors before any writes into this explicitly named root.
    if any(p.is_symlink() for p in (out,*out.parents)):raise ValueError('pb_owned_output_link')
    for name in files:
        p=PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts or '\\' in name:raise ValueError('pb_owned_file_path')
    out.mkdir(parents=True)
    for name,raw in files.items():
        target=out/Path(name);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    manifest=dict(metadata,files={k:dict(bytes=len(v),sha256=sha(v)) for k,v in sorted(files.items())})
    (out/'SOURCE_IDENTITY.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf8')
    return manifest


def prepare_interfaces(source,out):
    snapshot=git_snapshot(source,LIVOX_COMMIT,('msg/CustomMsg.msg','msg/CustomPoint.msg','LICENSE.txt'));verify(snapshot,LIVOX_HASHES)
    files={f'msg/{Path(k).name}':snapshot[k] for k in LIVOX_HASHES}
    files['CMakeLists.txt']=b'''cmake_minimum_required(VERSION 3.8)
project(livox_ros_driver2)
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
rosidl_generate_interfaces(${PROJECT_NAME} "msg/CustomMsg.msg" "msg/CustomPoint.msg" DEPENDENCIES std_msgs)
ament_export_dependencies(rosidl_default_runtime)
ament_package()
'''
    files['package.xml']=b'''<?xml version="1.0"?><package format="3">
<name>livox_ros_driver2</name><version>0.0.0</version><description>Owned interfaces-only build, not the Livox hardware driver</description>
<maintainer email="local@example.invalid">Local simulator</maintainer><license>MIT</license>
<buildtool_depend>ament_cmake</buildtool_depend><build_depend>rosidl_default_generators</build_depend>
<exec_depend>rosidl_default_runtime</exec_depend><depend>std_msgs</depend><member_of_group>rosidl_interface_packages</member_of_group>
</package>
'''
    if 'LICENSE.txt' in snapshot:files['UPSTREAM_LICENSE']=snapshot['LICENSE.txt']
    return write_owned(out,files,dict(schema='polar.sim.pb-owned-source.v1',upstream_commit=LIVOX_COMMIT,
        upstream_message_sha256=LIVOX_HASHES,interfaces_only=True,hardware_driver=False,
        qualification='message_abi_only_not_navigation_or_driver_acceptance'))


def prepare_controller(source,out):
    original=git_snapshot(source,CONTROLLER_COMMIT);verify(original,CONTROLLER_HASHES)
    header=Path(__file__).with_name('pb_controller_context.hpp').read_bytes()
    return write_owned(out,controller_overlay(original,header),dict(schema='polar.sim.pb-owned-source.v1',
        upstream_commit=CONTROLLER_COMMIT,upstream_files={k:sha(v) for k,v in sorted(original.items())},
        overlay_header_sha256=sha(header),qualification='source_overlay_unbuilt_unqualified',
        lifecycle='requires_fresh_stack_single_explicit_generation',algorithm='original_pb_omni_pid_no_fallback'))
