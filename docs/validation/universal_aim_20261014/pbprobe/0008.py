"""Root-executed static registration only: zero physics/images/NN/ROS nodes."""
import argparse,hashlib,json,os,sys,traceback,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
BUILD=Path('/root/polar-pb-aim-build-20261014-01')
VENV='/root/polar-humble-ext4-20261014-01/venv/bin/python'
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):Path(path).write_bytes((json.dumps(value,indent=2,sort_keys=True)+'\n').encode())
def main():
 p=argparse.ArgumentParser();p.add_argument('--label',required=True);p.add_argument('--robot-id',required=True)
 a=p.parse_args();assert __import__('re').fullmatch('[a-z0-9_-]{1,60}',a.label)
 out=Path(__file__).parent/('registered_'+a.label)
 if out.exists():raise ValueError('fresh registration label required')
 out.mkdir();result=dict(success=False,model_nodes_started=False,physics_steps=0,image_captures=0,inference_calls=0)
 backend=provider=None
 try:
  raw=(BUILD/'BUILD_RESULT.json').read_bytes();build=json.loads(raw)
  if not (build['success'] is True and build['source_and_refs_unchanged'] is True and build['build_executed'] is True):raise ValueError('actual successful immutable build required')
  for row in build['commands']:
   if row['exit_code']!=0 or row['cleanup']['clean'] is not True:raise ValueError('actual build command/cleanup not qualified')
  for row in build['installed'].values():
   if sha(row['path'])!=row['sha256']:raise ValueError('installed actual asset changed')
  from tools.build_pb_aim_plugins import opencv_snapshot
  if opencv_snapshot(build['system_opencv']['opencv_dir'])!=build['system_opencv']:raise ValueError('system OpenCV changed')
  from tools.prepare_pb_aim_system_dependencies import checked_extra_prefix
  checked_extra_prefix(build['extra_prefix']['path'],build['extra_prefix']['sha256'])
  from tools.prepare_pb_aim_stack import prepare
  from rm_match.platform_v2.backend import MuJoCoBackend
  from rm_match.platform_v2.camera import CameraProvider
  # Obtain the actual static provider calibration without starting its worker,
  # GL context, exposure, physics or NN. No calibration ID is fabricated.
  backend=MuJoCoBackend(camera=True);provider=CameraProvider(backend._sim)
  calibration=provider.calibrations[a.robot_id]
  if provider.capture_count or provider.thread is not None or backend._sim.time!=0.:raise ValueError('zero-input static setup violated')
  write(out/'CALIBRATION.json',dict(robot_id=a.robot_id,calibration=calibration,physics_steps=0,capture_count=0,GL=False,NN=0))
  env=dict(build['environment']);install=BUILD/'install'
  for key,paths in {'CMAKE_PREFIX_PATH':[str(install)],'AMENT_PREFIX_PATH':[str(install)],
   'LD_LIBRARY_PATH':[str(install/'lib')],'PKG_CONFIG_PATH':[str(install/'lib/pkgconfig')]}.items():
   env[key]=':'.join([x for x in paths if Path(x).is_dir()]+[env[key]])
  env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None);env['ROS_DOMAIN_ID']='85'
  environment=dict(schema='polar.pb-aim-runtime-environment.v1',process_environment=env,venv_python=VENV,
   actual_build_sha256=hashlib.sha256(raw).hexdigest(),base_environment_sha256=build['environment_sha256'],
   extra_prefix=build['extra_prefix'],system_opencv_asset_sha256=build['system_opencv']['asset_sha256'])
  write(out/'ENVIRONMENT.json',environment)
  executables={name:build['installed'][name]['path'] for name in ('armor_detector_opencv','armor_tracker','projectile_motion')}
  spec,prepared=prepare(ROOT/'artifacts/pb2025-aim-source-20261014-03/SOURCE_MANIFEST.json',executables,
   out/'ENVIRONMENT.json',ROOT/'artifacts/aim-mount-calibration-20261014-03/MOUNTS.json',
   build['installed']['mlp.onnx']['path'],build['installed']['label.txt']['path'],out/'stack',
   calibration_id=calibration['extrinsics']['calibration_id'],domain_id=85,adapter_id='custom_pb_aim')
  # Frozen source is not edited: a checked local bootstrap adds installed ROS
  # message modules in-memory, without PYTHONPATH or original venv.pth writes.
  module_paths=[install/'lib/python3.10/site-packages',install/'local/lib/python3.10/dist-packages']
  module_paths=[str(path) for path in module_paths if path.is_dir()]
  if not module_paths:raise ValueError('actual generated ROS Python modules missing')
  modules={str(file):sha(file) for base in module_paths for file in Path(base).rglob('*') if file.is_file() and not file.is_symlink()}
  bootstrap=dict(schema='polar.pb-aim-local-bootstrap.v1',repo_root=str(ROOT),module_paths=module_paths,
   installed_module_sha256=modules,stack_ref=prepared['stack'],actual_build_sha256=hashlib.sha256(raw).hexdigest())
  write(out/'BOOTSTRAP.json',bootstrap)
  peer=Path(__file__).parent/'peer_bootstrap.py'
  command=[VENV,'-u',str(peer),'--bootstrap-ref',str(out/'BOOTSTRAP.json'),'--bootstrap-sha256',sha(out/'BOOTSTRAP.json'),
   '--peer-sha256',sha(peer)]
  from rm_match.deployment.aim_plugin import CAPABILITIES,load_aim_plugins
  manifest=dict(schema='polar.sim.aim-plugins.v1',adapters=[dict(adapter_id='custom_pb_aim',
   label='PB2025 original OpenCV/PnP/EKF/projectile; stationary-first, manual fire',command=command,cwd=str(ROOT),
   supported_robots=[a.robot_id],transport='wsl_jsonl_v1',capabilities=CAPABILITIES,
   wsl=dict(distribution='Ubuntu-22.04',python=VENV,process_env=env))])
  write(out/'AIM_PLUGINS.json',manifest);load_aim_plugins(out/'AIM_PLUGINS.json')
  result.update(success=True,registration_sha256=sha(out/'AIM_PLUGINS.json'),stack=prepared['stack'],
   bootstrap_sha256=sha(out/'BOOTSTRAP.json'),peer_sha256=sha(peer),module_paths=module_paths,
   actual_build_sha256=hashlib.sha256(raw).hexdigest(),calibration_id=calibration['extrinsics']['calibration_id'])
 except BaseException as exc:
  result['error']=type(exc).__name__+':'+str(exc);(out/'FAILED_TRACEBACK.txt').write_text(traceback.format_exc())
 finally:
  if provider is not None:provider.stop()
  if backend is not None:backend.close()
  write(out/'REGISTER_RESULT.json',result);print(json.dumps(result),flush=True)
 return 0 if result['success'] else 2
if __name__=='__main__':raise SystemExit(main())
