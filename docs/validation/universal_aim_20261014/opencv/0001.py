"""Pure build planning/actual-source copy tests: no subprocess, ROS or NN."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import os
from unittest.mock import patch
import pytest
from tools import build_pb_aim_plugins as tool

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'artifacts/pb2025-aim-source-20261014-03'
DEPENDENCIES=ROOT/'artifacts/pb2025-aim-dependency-compat-20261014-03'

def have_sources():
    if not SOURCE.exists() or not DEPENDENCIES.exists():pytest.skip('Pinned PB03 source artifacts not present')

def test_exact_seven_real_source_packages_copied_without_algorithm_or_model_execution(tmp_path):
    have_sources();out=tmp_path/'fresh'
    record=tool.copy_sources(SOURCE,DEPENDENCIES,out)
    assert set(record['packages'])==set(tool.PACKAGES) and record['originals_unchanged']
    assert record['model_loaded'] is False and record['source_patch_executed'] is False
    for rel,row in record['copied_files'].items():
        assert hashlib.sha256((out/rel).read_bytes()).hexdigest()==row['sha256']
    assert tool.digest((out/'src/armor_detector_opencv/model/mlp.onnx').read_bytes())==tool.MODEL
    with pytest.raises(ValueError,match='fresh_owned'):tool.copy_sources(SOURCE,DEPENDENCIES,out)

def test_actual_owned_source_drift_rejected_before_new_workspace(tmp_path):
    have_sources();source=tmp_path/'source';shutil.copytree(SOURCE,source)
    file=source/'src/projectile_motion/src/projectile_motion_node.cpp'
    file.write_bytes(file.read_bytes()+b'\n// accidental change\n')
    with pytest.raises(ValueError,match='input_sha_changed'):tool.copy_sources(source,DEPENDENCIES,tmp_path/'new')
    assert not (tmp_path/'new').exists()

def test_manifest_path_escape_rejected_without_copy_or_process(tmp_path):
    source=tmp_path/'bad';source.mkdir()
    manifest=dict(commit='df1892c48f90093f86a2f7b02af6441a80aa2d97',source_safety_hook={},generated_sha256={'../escape':'0'*64})
    raw=json.dumps(manifest).encode();(source/'SOURCE_MANIFEST.json').write_bytes(raw)
    with patch.dict(tool.PINS,source=tool.digest(raw)):
        with pytest.raises(ValueError,match='manifest_relative_path'):tool.manifest_files(source,'source')

def test_json_duplicates_and_nonfinite_never_silently_validate():
    with pytest.raises(ValueError,match='duplicate_json'):tool.literal_json(b'{"hash":"first","hash":"other"}')
    with pytest.raises(ValueError,match='nonfinite'):tool.literal_json(b'{"value":NaN}')

def test_command_selects_real_venv_merge_install_seven_package_closure_and_bounded_jobs():
    env,python=tool.build_environment(dict(venv_python='/root/polar-humble-ext4-20261014-01/venv/bin/python',
        process_environment={'CMAKE_PREFIX_PATH':'/owned','AMENT_PREFIX_PATH':'/owned','LD_LIBRARY_PATH':'/owned','PKG_CONFIG_PATH':'/owned'}))
    command=tool.build_command(Path('/root/polar-pb-aim-build-test'),python)
    assert command[:2]==[python,'/usr/bin/colcon']
    assert '--merge-install' in command and command[command.index('--executor')+1]=='sequential'
    assert command[command.index('--packages-up-to')+1:command.index('--cmake-args')]==['armor_detector_opencv','armor_tracker','projectile_motion']
    assert '-DPython3_EXECUTABLE='+python in command and '-DPYTHON_EXECUTABLE='+python in command
    assert env['MAKEFLAGS']=='-j1' and env['CMAKE_BUILD_PARALLEL_LEVEL']=='1'
    assert env['ROS_DISTRO']=='humble' and 'PYTHONHOME' not in env and 'PYTHONPATH' not in env
    with pytest.raises(ValueError,match='pth_required'):
        tool.build_environment(dict(venv_python=python,process_environment={'PYTHONPATH':'/unreviewed'}))

def test_mount_table_distinguishes_owned_ext4_from_shared_ntfs_without_executing_stat():
    table='1 2 8:0 / / rw - ext4 /dev/sda rw\n3 1 0:10 / /mnt/c rw - 9p C: rw\n'
    assert tool.filesystem_type('/root/polar-pb-aim-build-test',table)=='ext4'
    assert tool.filesystem_type('/mnt/c/fresh',table)=='9p'

def test_preflight_checks_cpp_rosidl_python_dependencies_without_starting_nodes(tmp_path):
    have_sources();record=tool.copy_sources(SOURCE,DEPENDENCIES,tmp_path/'fresh')
    probe,packages=tool.preflight_files(tmp_path/'fresh',record)
    assert {'OpenCV','Eigen3','nlohmann_json','cv_bridge','rosidl_default_generators'}<=set(packages)
    assert not set(tool.PACKAGES)&set(packages)
    python=(probe/'python_probe.py').read_text()
    assert 'rosidl_adapter' in python and 'rosidl_parser' in python and 'sys.prefix!=sys.base_prefix' in python
    assert 'rclpy.init' not in python and 'readNet' not in python and 'onnx' not in python

def test_absolute_tool_entry_extra_prefix_import_from_real_external_cwd(tmp_path):
    """Actual Python child, synthetic prefix; no apt/build/ROS subprocess."""
    from tests.test_pb_aim_system_dependencies import fixture_prefix
    prefix,manifest,sha,_=fixture_prefix(tmp_path)
    env=dict(os.environ);env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
    code='''import json,runpy,sys
namespace=runpy.run_path(sys.argv[1],run_name="outer_cwd_fixture")
old={key:"/old" for key in ("CMAKE_PREFIX_PATH","AMENT_PREFIX_PATH","LD_LIBRARY_PATH","PKG_CONFIG_PATH")}
new,ref=namespace["add_extra_prefix"](old,sys.argv[2],sys.argv[3])
assert new["CMAKE_PREFIX_PATH"].endswith(":/old")
assert ref["sha256"]==sys.argv[3]
import tools.prepare_pb_aim_system_dependencies as dep
print(json.dumps(dict(module=dep.__file__,prefix=ref["prefix"],model_loaded=False)))
'''
    child=subprocess.Popen([sys.executable,'-c',code,str(ROOT/'tools/build_pb_aim_plugins.py'),str(manifest),sha],
        cwd=tmp_path,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:stdout,stderr=child.communicate(timeout=10.)
    except BaseException:child.kill();child.wait();raise
    assert child.returncode==0,stderr.decode()
    value=json.loads(stdout)
    assert Path(value['module']).resolve()==ROOT/'tools/prepare_pb_aim_system_dependencies.py'
    assert value['prefix']==str(prefix) and value['model_loaded'] is False and child.poll()==0

def opencv_fixture(tmp_path):
    usr=tmp_path/'usr';directory=usr/'lib/x86_64-linux-gnu/cmake/opencv4';directory.mkdir(parents=True)
    include=usr/'include/opencv4/opencv2';include.mkdir(parents=True)
    (directory/'OpenCVConfig.cmake').write_bytes(b'# pure config fixture, not an installed OpenCV')
    (directory/'OpenCVModules-release.cmake').write_bytes(b'# actual import-file fixture')
    (include/'core.hpp').write_bytes(b'// immutable header fixture')
    (usr/'lib/x86_64-linux-gnu/libopencv_core.so.4.5.4d').write_bytes(b'pure library bytes; no ELF is executed')
    return directory,include

def test_explicit_opencv_snapshot_binds_all_export_header_library_bytes_before_after(tmp_path):
    directory,include=opencv_fixture(tmp_path)
    before=tool.opencv_snapshot(directory)
    assert {value['kind'] for value in before['files'].values()}=={'exports','headers','libraries'}
    assert len(before['files'])==4 and before==tool.opencv_snapshot(directory)
    for path in (directory/'OpenCVModules-release.cmake',include/'core.hpp',directory.parents[1]/'libopencv_core.so.4.5.4d'):
        old=path.read_bytes();path.write_bytes(old+b'changed')
        assert tool.opencv_snapshot(directory)['asset_sha256']!=before['asset_sha256']
        path.write_bytes(old)
    assert tool.opencv_snapshot(directory)==before

def test_opencv_missing_headers_or_libraries_rejected_without_fake_fallback(tmp_path):
    directory,include=opencv_fixture(tmp_path)
    library=directory.parents[1]/'libopencv_core.so.4.5.4d';library.unlink()
    with pytest.raises(ValueError,match='complete_asset_groups'):tool.opencv_snapshot(directory)
    with pytest.raises(ValueError,match='system_layout'):tool.opencv_snapshot(tmp_path)

def test_cmake_and_colcon_use_explicit_opencv_dir_over_partial_extra_prefix(tmp_path):
    directory,_=opencv_fixture(tmp_path);snapshot=tool.opencv_snapshot(directory)
    original=['cmake','-S','source','-B','owned']
    assert tool.select_opencv(original,snapshot)==original+['-DOpenCV_DIR='+str(directory)]
    assert original==['cmake','-S','source','-B','owned']
    command=tool.select_opencv(tool.build_command(Path('/root/polar-pb-aim-build-test'),'/root/owned/venv/bin/python'),snapshot)
    assert command[-1]=='-DOpenCV_DIR='+str(directory) and '--merge-install' in command
