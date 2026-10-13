import hashlib,json,os,signal,subprocess,time
from pathlib import Path
root=Path('/mnt/c/Users/lulu/Desktop/claude/polarsimulation/polar-rm-simulator')
out=root/'artifacts/pb-bridge-imports-20261014'
environment=root/'artifacts/pb2025-humble-environment-20261013/ENVIRONMENT_COMPAT.json'
settings=json.loads(environment.read_text());env=dict(os.environ);env.update(settings['process_environment'])
for key in ('PYTHONPATH','PYTHONHOME','POLAR_PB_BRIDGE_PHASE_FILE'):env.pop(key,None)
base=[('rclpy','import rclpy\nfrom rclpy.context import Context\nfrom rclpy.executors import SingleThreadedExecutor\nfrom rclpy.qos import QoSProfile, HistoryPolicy, ReliabilityPolicy, DurabilityPolicy'),
 ('messages','from sensor_msgs.msg import PointCloud2, PointField, Imu\nfrom livox_ros_driver2.msg import CustomMsg, CustomPoint\nfrom rosgraph_msgs.msg import Clock\nfrom geometry_msgs.msg import TransformStamped\nfrom nav_msgs.msg import Odometry\nfrom std_msgs.msg import String')]
records=[]
for iteration,mode in enumerate(('broadcaster','tfmessage','tfmessage','broadcaster')):
 stages=base+[(mode,'from tf2_ros import StaticTransformBroadcaster' if mode=='broadcaster' else 'from tf2_msgs.msg import TFMessage')]
 code="import time,json,sys,os\nstarted=time.perf_counter();rows=[]\n"
 for name,statement in stages:
  code+='t=time.perf_counter()\n'+statement+'\nrows.append(dict(stage='+repr(name)+',seconds=time.perf_counter()-t))\n'
 code+="print(json.dumps(dict(pid=os.getpid(),python=sys.version,stages=rows,total_seconds=time.perf_counter()-started,initialized=False,nodes_started=False)))\n"
 started=time.perf_counter();proc=subprocess.Popen([settings['venv_python'],'-c',code],env=env,cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
 try:stdout,stderr=proc.communicate(timeout=15)
 except subprocess.TimeoutExpired:
  os.killpg(proc.pid,signal.SIGKILL);stdout,stderr=proc.communicate(timeout=1);raise
 (out/f'{iteration}_{mode}.stdout').write_text(stdout);(out/f'{iteration}_{mode}.stderr').write_text(stderr)
 records.append(dict(order=iteration,mode=mode,elapsed_seconds=time.perf_counter()-started,exit_code=proc.returncode,child=json.loads(stdout) if proc.returncode==0 else None))
result=dict(schema='polar.sim.pb-import-diagnostic.v1',records=records,environment_sha256=hashlib.sha256(environment.read_bytes()).hexdigest(),interpreter=settings['venv_python'],pythonpath_scrubbed=True,
 qualification='fresh_child_imports_only_no_init_dds_sensor_or_nn; OS cache/order not controlled',all_children_reaped=True)
(out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(records))
