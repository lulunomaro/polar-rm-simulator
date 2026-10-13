import hashlib,json,os,shlex,subprocess,time
from pathlib import Path
root=Path('/mnt/c/Users/lulu/Desktop/claude/polarsimulation/polar-rm-simulator')
out=root/'artifacts/pb-nav2-elf-loader-audit-20261014'
env=dict(os.environ);env.update(json.loads((root/'artifacts/pb2025-humble-environment-20261013/ENVIRONMENT_COMPAT.json').read_text())['process_environment'])
env.update(json.loads((out/'RESULT.json').read_text())['process_environment'])
build=root/'artifacts/pb2025-nav2-plugins-actual-build-20261014-03/build/pb_nav2_plugins'
tokens=shlex.split(json.loads((build/'compile_commands.json').read_text())[0]['command'])
includes=[];i=0
while i<len(tokens):
 t=tokens[i]
 if t in ('-I','-isystem'):includes.extend([t,tokens[i+1]]);i+=2;continue
 if t.startswith('-I'):includes.append(t)
 i+=1
links=[t for t in shlex.split((build/'CMakeFiles/layers.dir/link.txt').read_text()) if t.endswith('.so') and t.startswith('/')]
cmd=['/usr/bin/g++','-std=c++17',str(out/'plugin_probe.cpp'),'-o',str(out/'plugin_probe'),*includes,*links]
start=time.perf_counter();r=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=180)
(out/'plugin_compile.stdout').write_text(r.stdout);(out/'plugin_compile.stderr').write_text(r.stderr)
result=dict(command=cmd,exit_code=r.returncode,elapsed=time.perf_counter()-start,source_sha256=hashlib.sha256((out/'plugin_probe.cpp').read_bytes()).hexdigest(),nodes_started=False,compute_called=False)
if r.returncode==0:
 p=subprocess.run([str(out/'plugin_probe')],env=env,capture_output=True,text=True,timeout=15)
 (out/'plugin_class.stdout').write_text(p.stdout);(out/'plugin_class.stderr').write_text(p.stderr)
 result['run']=dict(exit_code=p.returncode,stdout=p.stdout,stderr=p.stderr)
 result['binary_sha256']=hashlib.sha256((out/'plugin_probe').read_bytes()).hexdigest()
(out/'PLUGIN_CLASS_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k in ('exit_code','elapsed','run')}))
