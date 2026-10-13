"""Fresh interpreter imports and ROS serialization only; no DDS or sensors."""
import hashlib,json,os,pathlib,subprocess,time
root=pathlib.Path(__file__).resolve().parent;repo=root.parents[1]
environment_file=root/'ENVIRONMENT_COMPAT_FINAL.json'
environment=json.loads(environment_file.read_bytes())
env=os.environ.copy();env.update(environment['process_environment']);env.pop('PYTHONPATH',None)
code='''import json,sys,time,importlib,importlib.metadata,os
started=time.perf_counter();stages={};paths={}
for name in ('rclpy','numpy','mujoco','PIL','sensor_msgs.msg','tf2_msgs.msg','nav2_msgs.action','livox_ros_driver2.msg'):
    before=time.perf_counter();module=importlib.import_module(name);stages[name]=time.perf_counter()-before;paths[name]=module.__file__
from rclpy.serialization import serialize_message,deserialize_message
from sensor_msgs.msg import Imu,PointCloud2
from geometry_msgs.msg import TransformStamped
from tf2_msgs.msg import TFMessage
from livox_ros_driver2.msg import CustomMsg,CustomPoint
from nav2_msgs.action import ComputePathToPose,FollowPath
checks={}
for cls in (Imu,PointCloud2,TransformStamped,TFMessage,CustomMsg,CustomPoint,ComputePathToPose.Goal,FollowPath.Goal):
    message=cls();wire=serialize_message(message);result=deserialize_message(wire,cls)
    checks[cls.__name__]=serialize_message(result)==wire
import mujoco
from rm_match.platform_v2.backend import MuJoCoBackend
backend=MuJoCoBackend()
checks['actual_repo_model_created_zero_steps']=backend._sim.data.time==0. and len(backend.robot_ids)==6
checks['no_renderer']=backend._sim.render_enabled is False if hasattr(backend._sim,'render_enabled') else getattr(backend._sim,'renderer',None) is None
backend.close()
versions={name:importlib.metadata.version(name) for name in ('rclpy','numpy','mujoco','Pillow')}
checks['versions_exact']=versions=={'rclpy':'3.3.21','numpy':'2.2.6','mujoco':'3.15.0','Pillow':'12.3.0'}
checks['PYTHONPATH_scrubbed']='PYTHONPATH' not in os.environ
print(json.dumps({'checks':checks,'clean':all(checks.values()),'stages_s':stages,'elapsed_s':time.perf_counter()-started,
    'versions':versions,'paths':paths,'python':sys.executable,'DDS_initialized':False,'navigation_nodes_started':False,
    'sensor_frames':0,'physics_steps':0,'qualification':'fresh imports/real message serialization/actual repository model zero-step; not DDS or navigation qualification'}))
assert all(checks.values())
'''
cases=[]
for index in range(3):
    stdout=root/f'PROBE_{index}.stdout';stderr=root/f'PROBE_{index}.stderr'
    if stdout.exists() or stderr.exists():raise ValueError('fresh import result required')
    start=time.perf_counter();proc=subprocess.run([environment['venv_python'],'-c',code],cwd=repo,env=env,capture_output=True,text=True,timeout=25)
    stdout.write_text(proc.stdout);stderr.write_text(proc.stderr)
    parsed=None
    try:parsed=json.loads(proc.stdout.splitlines()[-1])
    except (IndexError,ValueError):pass
    cases.append({'case':index,'exit_code':proc.returncode,'total_process_s':time.perf_counter()-start,'result':parsed,
        'stdout_sha256':hashlib.sha256(proc.stdout.encode()).hexdigest(),'stderr_sha256':hashlib.sha256(proc.stderr.encode()).hexdigest()})
    (root/'RUNTIME_PROBES_RESULT.json').write_text(json.dumps({'environment_sha256':hashlib.sha256(environment_file.read_bytes()).hexdigest(),
        'script_sha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),'cases':cases,
        'clean':len(cases)==3 and all(c['exit_code']==0 and c['result'] and c['result']['clean'] for c in cases)},indent=2))
    print(json.dumps(cases[-1]),flush=True)
    if proc.returncode:break
assert len(cases)==3 and all(c['exit_code']==0 for c in cases)
