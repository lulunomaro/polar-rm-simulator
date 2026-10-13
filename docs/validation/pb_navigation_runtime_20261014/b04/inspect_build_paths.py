"""Read-only capture of actual compile paths; no benchmark or build change."""
import hashlib
import json
import shlex
import subprocess
from pathlib import Path

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
WORK=Path('/root/polar-navigation-humble-e05eb08e/lio_tf_build_20261014_04')
FLAGS=WORK/'build/point_lio/CMakeFiles/pointlio_mapping.dir/flags.make'
CACHE=WORK/'build/point_lio/CMakeCache.txt'
WRAPPER=REPO/'artifacts/pb2025-humble-environment-20261013/compat/lib/cmake/glog/glog-config.cmake'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
pgid=json.loads((HERE/'BUILD_PID.json').read_text())['pgid']
ps=subprocess.run(['/usr/bin/ps','-eo','pid=,pgid=,etime=,pcpu=,rss=,args='],capture_output=True,text=True,check=True)
owned=[line.strip() for line in ps.stdout.splitlines() if len(line.split())>=2 and int(line.split()[1])==pgid]
tokens=shlex.split(next(line.split('=',1)[1] for line in FLAGS.read_text().splitlines() if line.startswith('CXX_INCLUDES =')))
paths=[tokens[i+1] for i,t in enumerate(tokens[:-1]) if t=='-isystem' and tokens[i+1].startswith('/mnt/c/')]
selected=[line for line in CACHE.read_text().splitlines() if line.startswith(tuple(k+'_DIR:' for k in ('pcl_ros','livox_ros_driver2','nlohmann_json','glog','PCL','Eigen3')))]
wrapper_lines=[dict(line=i,text=line) for i,line in enumerate(WRAPPER.read_text().splitlines(),1) if '/mnt/c/' in line]
record=dict(schema='polar.pb2025.build-path-inspection.v1',read_only=True,benchmark=False,
            flags_path=str(FLAGS),flags_sha256=sha(FLAGS),flags_text=FLAGS.read_text(),
            cmake_cache_path=str(CACHE),cmake_cache_sha256=sha(CACHE),selected_package_directories=selected,
            actual_owned_process_rows=owned,drvfs_system_include_paths=paths,
            glog_wrapper_path=str(WRAPPER),glog_wrapper_sha256=sha(WRAPPER),hardcoded_glog_wrapper_lines=wrapper_lines,
            conclusion='Old build ENV explicitly selects old relocatable package configs. The glog compatibility wrapper separately hardcodes original DrvFs config/SHA/library paths.',
            recommendation='For a later fresh ext4 build, create a separate hash-guarded derived glog wrapper mapping its original targets/config/unwind check, included config and linked unwind paths to byte-proven ext4 copies. Do not mutate running ENV, old artifacts, copied original wrappers or CMakeCache.',
            per_path_latency_measured=False)
out=HERE/'BUILD_PATH_INSPECTION.json'
if out.exists():raise RuntimeError('inspection record must be fresh')
out.write_text(json.dumps(record,indent=2)+'\n',encoding='utf8')
print(json.dumps(dict(artifact=str(out),drvfs_system_include_paths=paths,per_path_latency_measured=False)))
