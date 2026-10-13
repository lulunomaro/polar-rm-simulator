import hashlib,json,os,shutil,subprocess,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
WORK=Path('/root/polar-navigation-humble-e05eb08e/terrain_scan_build_20261013_01')
manifest=json.loads((HERE/'SOURCE_MANIFEST.json').read_text())
if WORK.exists():raise RuntimeError('build_target_not_fresh')
for name,row in manifest['files'].items():
 if hashlib.sha256((HERE/'src'/name).read_bytes()).hexdigest()!=row['sha256']:raise RuntimeError('source_changed')
WORK.mkdir(parents=True);shutil.copytree(HERE/'src',WORK/'src')
compat=REPO/'artifacts/pb2025-humble-environment-20261013/ENVIRONMENT_COMPAT.json'
snapshot=compat.read_bytes();env=os.environ.copy();env.update(json.loads(snapshot)['process_environment'])
env.update(CMAKE_BUILD_PARALLEL_LEVEL='1',MAKEFLAGS='-j1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
argv=['/usr/bin/colcon','build','--executor','sequential','--packages-select','terrain_analysis','terrain_analysis_ext','pointcloud_to_laserscan','--cmake-args','-DBUILD_TESTING=OFF','-DCMAKE_BUILD_TYPE=Release']
record=dict(schema='polar.pb2025.terrain-scan-build.v1',workspace=str(WORK),command=argv,source_manifest_sha256=hashlib.sha256((HERE/'SOURCE_MANIFEST.json').read_bytes()).hexdigest(),build_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),environment_manifest_sha256=hashlib.sha256(snapshot).hexdigest(),environment={k:env[k] for k in ('CMAKE_PREFIX_PATH','AMENT_PREFIX_PATH','LD_LIBRARY_PATH','PYTHONPATH','PKG_CONFIG_PATH','CMAKE_BUILD_PARALLEL_LEVEL','MAKEFLAGS','OMP_NUM_THREADS')},algorithm_modified=False,nodes_started=False)
(HERE/'BUILD_COMMAND.json').write_text(json.dumps(record,indent=2)+'\n')
start=time.perf_counter();result=None
try:
 with (HERE/'colcon.log').open('w') as log:result=subprocess.run(argv,cwd=WORK,env=env,stdout=log,stderr=subprocess.STDOUT)
finally:
 record.update(returncode=None if result is None else result.returncode,wall_s=time.perf_counter()-start,source_unchanged=all(hashlib.sha256((WORK/'src'/name).read_bytes()).hexdigest()==row['sha256'] for name,row in manifest['files'].items()))
 record['colcon_log_sha256']=hashlib.sha256((HERE/'colcon.log').read_bytes()).hexdigest()
 record['passed']=bool(result is not None and result.returncode==0 and record['source_unchanged'])
 (HERE/'BUILD_RESULT.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
if result is None or result.returncode:raise SystemExit(1)
