import ctypes,hashlib,json,os,subprocess,sys,time
from pathlib import Path
root=Path('/mnt/c/Users/lulu/Desktop/claude/polarsimulation/polar-rm-simulator')
out=root/'artifacts/pb-nav2-elf-loader-audit-20261014'
env=dict(os.environ);env.update(json.loads((root/'artifacts/pb2025-humble-environment-20261013/ENVIRONMENT_COMPAT.json').read_text())['process_environment'])
plugin=root/'artifacts/pb2025-nav2-plugins-actual-build-20261014-03/install/pb_nav2_plugins'
controller=root/'artifacts/pb2025-nav2-plugins-actual-build-20261013-02/install/pb_omni_pid_pursuit_controller'
env['LD_LIBRARY_PATH']=str(plugin/'lib')+':'+str(controller/'lib')+':'+env['LD_LIBRARY_PATH']
env['AMENT_PREFIX_PATH']=str(plugin)+':'+str(controller)+':'+env['AMENT_PREFIX_PATH']
assert '20261013-02/install/pb_nav2_plugins' not in str(env)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(cmd,name):
 t=time.perf_counter();r=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=30)
 (out/(name+'.stdout')).write_text(r.stdout);(out/(name+'.stderr')).write_text(r.stderr)
 return dict(command=cmd,exit_code=r.returncode,elapsed=time.perf_counter()-t,stdout=r.stdout,stderr=r.stderr)
records=[]
for prefix,lib in [(plugin,'libpb_intensity_layers.so'),(plugin,'libpb_back_up_frees_space_behavior.so'),(controller,'libpb_omni_pid_pursuit_controller.so')]:
 p=prefix/'lib'/lib
 record=dict(path=str(p),sha256=sha(p),size=p.stat().st_size,prefix=str(prefix))
 record['dynamic']=run(['readelf','-d',str(p)],lib+'.dynamic')
 record['ldd']=run(['ldd',str(p)],lib+'.ldd')
 record['load']=run(['/usr/bin/python3','-c','import ctypes,os;ctypes.CDLL('+repr(str(p))+',mode=os.RTLD_NOW);print("RTLD_NOW_LOADED")'],lib+'.load')
 record['defined_symbols']=run(['nm','-D','-C','--defined-only',str(p)],lib+'.symbols')
 record['dependencies_resolved']='not found' not in record['ldd']['stdout']
 records.append(record)
old=root/'artifacts/pb2025-nav2-plugins-actual-build-20261013-02/install/pb_nav2_plugins/lib/liblayers.so'
collision=dict(path=str(old),sha256=sha(old),dynamic=run(['readelf','-d',str(old)],'old_collision.dynamic'),load=run(['/usr/bin/python3','-c','import ctypes,os;ctypes.CDLL('+repr(str(old))+',mode=os.RTLD_NOW)'],'old_collision.load'))
assets=[]
for prefix,paths in [(plugin,['share/pb_nav2_plugins/costmap_plugins.xml','share/pb_nav2_plugins/behavior_plugin.xml']),(controller,['share/pb_omni_pid_pursuit_controller/pb_omni_pid_pursuit_controller.xml'])]:
 for rel in paths:
  p=prefix/rel;assets.append(dict(path=str(p),sha256=sha(p),text=p.read_text()))
result=dict(schema='polar.sim.pb-elf-loader-audit.v1',records=records,collision=collision,assets=assets,
 process_environment={k:env[k] for k in ('LD_LIBRARY_PATH','AMENT_PREFIX_PATH')},
 all_loads_pass=all(r['load']['exit_code']==0 and r['dependencies_resolved'] for r in records),
 qualification='real_original_shared_library_load_only_not_navigation_or_plugin_compute',ros_nodes_started=False)
(out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k in ('all_loads_pass','qualification')}))
