"""Read-only Linux package/loader inventory; starts no ROS node or build."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/pb-match-build-preflight-20261015-01'
OUT.mkdir()
environment=ROOT/'artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json'
env=json.loads(environment.read_bytes());prefix=Path('/root/polar-humble-ext4-20261014-01/prefix/opt/ros/humble')
selected=('behaviortree_cpp','behaviortree_cpp_v3','pb_rm_interfaces','auto_aim_interfaces',
    'rclcpp','geometry_msgs','example_interfaces','nlohmann_json','generate_parameter_library')
packages={}
for name in selected:
    paths=[]
    for base in (prefix,Path('/opt/ros/humble'),Path('/root/polar-navigation-humble-e05eb08e')):
        if base.is_dir():paths.extend(p for p in base.glob('**/'+name+'Config.cmake') if p.is_file())
    packages[name]=[str(p) for p in sorted(set(paths))]
headers={str(p):p.is_file() for p in (Path('/usr/include/nlohmann/json.hpp'),prefix/'include/nlohmann/json.hpp')}
tools={name:shutil.which(name) for name in ('cmake','ninja','c++','g++','ldd')}
versions={}
for name in ('cmake','ninja','c++'):
    if tools[name]:
        child=subprocess.run([tools[name],'--version'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=10)
        versions[name]=dict(returncode=child.returncode,first_line=child.stdout.decode(errors='replace').splitlines()[0])
active=[]
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit():continue
    try:
        cmd=(proc/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
        if any(v in cmd for v in ('colcon build','cmake --build','qa_registered_pb_goal_sil','pointlio_mapping')):
            active.append(dict(pid=int(proc.name),kind=next(v for v in ('colcon build','cmake --build','qa_registered_pb_goal_sil','pointlio_mapping') if v in cmd)))
    except OSError:pass
result=dict(schema='polar.pb-match-build-preflight.v1',packages=packages,headers=headers,tools=tools,versions=versions,
    environment_sha256=hashlib.sha256(environment.read_bytes()).hexdigest(),environment=env,
    active_relevant=active,target_exists=Path('/root/polar-pb-match-bt4-20261015-01').exists(),
    nodes_started=False,build_started=False,python=sys.version)
(OUT/'RESULT.json').write_bytes((json.dumps(result,indent=2)+'\n').encode())
print(json.dumps({k:v for k,v in result.items() if k!='environment'},indent=2))
