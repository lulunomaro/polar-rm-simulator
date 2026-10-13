"""Linux-only owned 3-package colcon build; no launch or global install."""
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
WORK=Path('/root/polar-navigation-humble-e05eb08e/lio_tf_build_20261013_02')
MANIFEST=json.loads((HERE/'OVERLAY_MANIFEST.json').read_text())
for name,row in MANIFEST['files'].items():
    if hashlib.sha256((HERE/name).read_bytes()).hexdigest()!=row['sha256']:
        raise RuntimeError('owned_source_changed')
if WORK.exists():raise RuntimeError('owned_build_path_not_fresh')
WORK.mkdir(parents=True)
for pkg in ('point_lio','loam_interface','sensor_scan_generation'):
    shutil.copytree(HERE/pkg,WORK/'src'/pkg)
compat=REPO/'artifacts/pb2025-humble-environment-20261013/ENVIRONMENT_COMPAT.json'
env=os.environ.copy();env.update(json.loads(compat.read_text())['process_environment'])
env.update(CMAKE_BUILD_PARALLEL_LEVEL='1',MAKEFLAGS='-j1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
argv=['/usr/bin/colcon','build','--executor','sequential','--packages-select','loam_interface','sensor_scan_generation','point_lio','--cmake-args','-DBUILD_TESTING=OFF','-DCMAKE_BUILD_TYPE=Release']
start=time.perf_counter()
record=dict(workspace=str(WORK),command=argv,environment={k:env[k] for k in ('CMAKE_PREFIX_PATH','AMENT_PREFIX_PATH','LD_LIBRARY_PATH','PYTHONPATH','PKG_CONFIG_PATH','CMAKE_BUILD_PARALLEL_LEVEL','MAKEFLAGS','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS')},source_manifest_sha256=hashlib.sha256((HERE/'OVERLAY_MANIFEST.json').read_bytes()).hexdigest(),build_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),environment_manifest_sha256=hashlib.sha256(compat.read_bytes()).hexdigest(),full_ros_build=True,nodes_started=False)
(HERE/'BUILD_COMMAND.json').write_text(json.dumps(record,indent=2)+'\n')
result=None
try:
    with (HERE/'colcon.log').open('w') as log:
        result=subprocess.run(argv,cwd=WORK,env=env,stdout=log,stderr=subprocess.STDOUT)
finally:
    record.update(returncode=None if result is None else result.returncode,wall_s=time.perf_counter()-start)
    record['source_unchanged']=all(hashlib.sha256((WORK/'src'/name).read_bytes()).hexdigest()==row['sha256'] for name,row in MANIFEST['files'].items() if name.startswith(('point_lio/','loam_interface/','sensor_scan_generation/')))
    record['colcon_log_sha256']=hashlib.sha256((HERE/'colcon.log').read_bytes()).hexdigest()
    record['passed']=bool(result is not None and result.returncode==0 and record['source_unchanged'])
    (HERE/'BUILD_RESULT.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record))
if result is None or result.returncode:raise SystemExit(1)
