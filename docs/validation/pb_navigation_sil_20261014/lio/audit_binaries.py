import hashlib,json,os,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
env=os.environ.copy();env.update(json.loads((HERE.parents[1]/'artifacts/pb2025-humble-environment-20261013/ENVIRONMENT_COMPAT.json').read_text())['process_environment'])
install=Path('/root/polar-navigation-humble-e05eb08e/lio_tf_build_20261013_02/install')
packages=['point_lio','loam_interface','sensor_scan_generation']
env['LD_LIBRARY_PATH']=':'.join(str(install/p/'lib') for p in packages)+':'+env['LD_LIBRARY_PATH']
names=['point_lio/lib/point_lio/pointlio_mapping','loam_interface/lib/loam_interface/loam_interface_node','sensor_scan_generation/lib/sensor_scan_generation/sensor_scan_generation_node','loam_interface/lib/libloam_interface.so','sensor_scan_generation/lib/libsensor_scan_generation.so']
rows=[]
for name in names:
 p=install/name;r=subprocess.run(['ldd',str(p)],env=env,capture_output=True,text=True)
 rows.append(dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),ldd_returncode=r.returncode,stdout=r.stdout,stderr=r.stderr,all_resolved=r.returncode==0 and 'not found' not in r.stdout+r.stderr))
out=dict(schema='polar.pb2025.lio-binary-audit.v1',nodes_started=False,rows=rows,ld_library_path=env['LD_LIBRARY_PATH'],passed=all(r['all_resolved'] for r in rows))
(HERE/'BINARY_AUDIT.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({'passed':out['passed'],'count':len(rows),'binary_sha256':{r['path']:r['sha256'] for r in rows}}))
