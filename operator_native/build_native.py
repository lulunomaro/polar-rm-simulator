"""Build independent operator adapter using explicitly pinned local source objects.

--full compiles every unchanged source unit too. Neither path writes the source
benchmark. This local build requires its declared source/dependency tree.
"""
import argparse,concurrent.futures,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
parser=argparse.ArgumentParser();parser.add_argument('--base',type=Path,required=True);parser.add_argument('--full',action='store_true');args=parser.parse_args()
base=args.base.resolve();out=ROOT/'build';out.mkdir(exist_ok=True)
manifest=json.loads((base/'build/candidate/build_manifest.json').read_text())
commands=json.loads((base/'build/candidate/compile_commands.json').read_text())
def tree_identity(path):
 h=hashlib.sha256()
 for p in sorted(path.rglob('*')):
  if p.is_file():h.update(str(p.relative_to(path)).encode());h.update(hashlib.sha256(p.read_bytes()).digest())
 return h.hexdigest()
if tree_identity(base/'candidate/src')!=manifest['compile_identity']['source_tree']:
 raise ValueError('External source tree differs from its qualified build manifest')
inputs={};outputs=[]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def run(cmd,name):
 with (out/name).open('w') as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
def compile_one(row):
 src=Path(row['file']);original=Path(row['output']);inputs[str(src)]=sha(src)
 if src.name!='main.cpp' and not args.full:
  inputs[str(original)]=sha(original);return str(original)
 command=row['arguments'];actual=ROOT/'main.cpp' if src.name=='main.cpp' else src
 obj=out/original.name
 cmd=[str(actual) if x==str(src) else str(obj) if x==str(original) else x for x in command]
 run([*cmd[:cmd.index('-c')],'-fsyntax-only',str(actual)],obj.stem+'.syntax.log')
 run(cmd,obj.stem+'.compile.log');return str(obj)
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:outputs=list(pool.map(compile_one,commands))
link=manifest['link'];libs=[x for x in link if '.so' in x]
for lib in libs:inputs[lib]=sha(lib)
# Absolute rpaths are explicitly local build dependencies, not portable claims.
libdirs=sorted({str(Path(x).parent) for x in libs})
libdirs += [str(base/'deps/openvino_cpp/runtime/3rdparty/tbb/lib')]
binary=out/'rmcs_sim_operator_fov'
run([link[0],'-pthread',*outputs,*libs,*['-Wl,-rpath,'+d for d in libdirs],'-o',str(binary)],'link.log')
result=dict(identity='rmcs-sim-operator-fov-v1',full_compile=args.full,binary=str(binary),binary_sha256=sha(binary),
 inputs=inputs,adapter_sha256=sha(ROOT/'main.cpp'),source_benchmark_untouched=True)
(out/'build_manifest.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
