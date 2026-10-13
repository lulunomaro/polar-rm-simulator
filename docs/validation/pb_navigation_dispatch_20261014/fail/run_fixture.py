"""Compile and compare fresh actual rclcpp 16.0.19 synthetic DDS processes."""
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
WORK=Path('/root/polar-navigation-humble-e05eb08e/rclcpp_dispatch_fixture_20261014')
SOURCE=REPO/'tests/fixtures/pb_rclcpp_dispatch_test.cpp'
ENV_FILE=REPO/'artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json'
ENV_SHA='d60183ebf62d520c72eb20b84207fa4344d8f17183bb0df8eee92f97b7f981ee'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(argv,env,timeout,name):
    started=time.perf_counter();p=None
    try:
        p=subprocess.Popen(argv,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        stdout,stderr=p.communicate(timeout=timeout)
        result=dict(argv=argv,pid=p.pid,returncode=p.returncode,wall_s=time.perf_counter()-started,
                    stdout=stdout,stderr=stderr,reaped=True)
        (HERE/(name+'.json')).write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
        if p.returncode:raise RuntimeError(name+' failed')
        return result
    finally:
        if p is not None and p.poll() is None:
            os.killpg(p.pid,signal.SIGTERM)
            try:p.communicate(timeout=2)
            except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.communicate(timeout=2)
def main():
    if WORK.exists() or (HERE/'COMMAND.json').exists():raise RuntimeError('fresh fixture execution required')
    if sha(ENV_FILE)!=ENV_SHA:raise RuntimeError('fixed ext4 environment changed')
    env=os.environ.copy();env.update(json.loads(ENV_FILE.read_text())['process_environment'])
    env.update(ROS_DOMAIN_ID='172',ROS_LOCALHOST_ONLY='1',MAKEFLAGS='-j1',CMAKE_BUILD_PARALLEL_LEVEL='1')
    (WORK/'src').mkdir(parents=True);shutil.copyfile(SOURCE,WORK/'src/main.cpp')
    cmake='''cmake_minimum_required(VERSION 3.16)
project(pb_dispatch_fixture LANGUAGES CXX)
find_package(ament_cmake REQUIRED)
find_package(rclcpp 16.0.19 EXACT REQUIRED)
find_package(sensor_msgs 4.9.2 EXACT REQUIRED)
add_executable(dispatch_fixture main.cpp)
target_compile_features(dispatch_fixture PRIVATE cxx_std_17)
ament_target_dependencies(dispatch_fixture rclcpp sensor_msgs)
'''
    (WORK/'src/CMakeLists.txt').write_text(cmake)
    (HERE/'COMMAND.json').write_text(json.dumps(dict(scope='synthetic real DDS fixture; no LIO/SIL/NN/GL',
        source_sha256=sha(SOURCE),runner_sha256=sha(Path(__file__)),environment_manifest_sha256=ENV_SHA,
        environment={k:env[k] for k in ('CMAKE_PREFIX_PATH','LD_LIBRARY_PATH','ROS_DOMAIN_ID','ROS_LOCALHOST_ONLY')},
        workspace=str(WORK)),indent=2)+'\n',encoding='utf8')
    result=dict(scope='synthetic real DDS fixture; no LIO/SIL/NN/GL',passed=False)
    try:
        run(['/usr/bin/cmake','-S',str(WORK/'src'),'-B',str(WORK/'build'),'-DCMAKE_BUILD_TYPE=Release'],env,120,'configure')
        run(['/usr/bin/cmake','--build',str(WORK/'build'),'--parallel','1'],env,180,'compile')
        result['binary_sha256']=sha(WORK/'build/dispatch_fixture')
        for mode in ('some','all'):
            row=run([str(WORK/'build/dispatch_fixture'),mode],env,10,mode)
            data=json.loads(row['stdout']);result[mode]=data
            if not data['passed']:raise RuntimeError('fixture invariant failed')
        result['source_unchanged']=sha(SOURCE)==sha(WORK/'src/main.cpp')
        result['passed']=result['source_unchanged'] and all(result[m]['passed'] for m in ('some','all'))
    finally:
        (HERE/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8');print(json.dumps(result),flush=True)
if __name__=='__main__':main()
