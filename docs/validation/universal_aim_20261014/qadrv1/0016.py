#!/usr/bin/env python3
"""Local C++23 builds. No downloads, Git mutations, ROS or paid services.

Cache identity covers compiler bytes/version, flags, every source/shim file,
and all Eigen/OpenCV/YAML/OpenVINO headers, not just the translation unit.
"""
import argparse,concurrent.futures,hashlib,json,os,pathlib,shutil,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parent
MODULES=['core','imgproc','imgcodecs','calib3d','features2d','flann','dnn','ximgproc']
def first(paths,name):
 for p in paths:
  p=pathlib.Path(p)
  if (p/name).is_file():return p
 return None
def dependencies():
 local=ROOT/'deps/usr/include';include=[local,'/usr/include','/usr/local/include']
 eigen=first(include,'eigen3/Eigen/Core')
 opencv=first([local/'opencv4','/usr/include/opencv4','/usr/local/include/opencv4'],'opencv2/core.hpp')
 yaml=first(include,'yaml-cpp/yaml.h')
 ov=first([ROOT/'deps/openvino_cpp/runtime/include',os.environ.get('OPENVINO_INCLUDE_DIR','/missing')],'openvino/runtime/core.hpp')
 return {'cxx':shutil.which(os.environ.get('CXX','g++')),**{k:str(v) if v else None for k,v in dict(eigen=eigen,opencv=opencv,yaml=yaml,openvino=ov).items()}}
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def tree_identity(root):
 h=hashlib.sha256()
 for p in sorted(pathlib.Path(root).rglob('*')):
  if p.is_file():h.update(str(p.relative_to(root)).encode());h.update(bytes.fromhex(sha(p)))
 return h.hexdigest()
def libraries(dep):
 paths=[ROOT/'deps/usr/lib/x86_64-linux-gnu',pathlib.Path('/usr/lib/x86_64-linux-gnu'),pathlib.Path('/lib/x86_64-linux-gnu')];result=[]
 for name in [*(f'opencv_{m}' for m in MODULES),'yaml-cpp']:
  matches=[p for root in paths for p in sorted(root.glob(f'lib{name}.so*')) if p.is_file()]
  if not matches:raise RuntimeError('Missing runtime library '+name)
  result.append(str(matches[0].resolve()))
 ov=ROOT/'deps/openvino_cpp/runtime/lib/intel64';matches=sorted(ov.glob('libopenvino.so*'))
 if not matches:raise RuntimeError('Missing ABI=1 official OpenVINO C++ archive library under '+str(ov))
 result.append(str(matches[0].resolve()));return result

def run(cmd,log):
 with log.open('w') as out:p=subprocess.run(cmd,stdout=out,stderr=subprocess.STDOUT)
 if p.returncode:raise RuntimeError(f'Command failed; see {log}\n'+log.read_text()[-9000:])
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--check',action='store_true');ap.add_argument('--variant',choices=['upstream','candidate','both'],default='both');ap.add_argument('--jobs',type=int,default=4);ap.add_argument('--clean',action='store_true');args=ap.parse_args()
 dep=dependencies();(ROOT/'logs').mkdir(exist_ok=True);(ROOT/'logs/dependencies.json').write_text(json.dumps(dep,indent=2));print(json.dumps(dep,indent=2),flush=True)
 if any(v is None for v in dep.values()):print('Missing development dependencies; no synthetic fallback.',file=sys.stderr);return 2
 if args.check:return 0
 libs=libraries(dep);compiler={'sha256':sha(pathlib.Path(dep['cxx']).resolve()),'version':subprocess.check_output([dep['cxx'],'--version'],text=True)}
 external={str(p):tree_identity(p) for p in [pathlib.Path(dep['eigen'])/'eigen3',pathlib.Path(dep['opencv']),pathlib.Path(dep['yaml'])/'yaml-cpp',pathlib.Path(dep['openvino'])]}
 variants=['upstream','candidate'] if args.variant=='both' else [args.variant]
 for variant in variants:
  src=ROOT/variant/'src';build=ROOT/'build'/variant
  if args.clean and build.exists():shutil.rmtree(build)
  build.mkdir(parents=True,exist_ok=True)
  sources=[ROOT/'main.cpp',*[src/'kernel'/f'{x}.cpp' for x in ['detector','pose_estimator','tracker','fire_control']],src/'utility/logging/printer.cpp',src/'utility/panic.cpp',src/'utility/image/process.cpp']
  for directory in ['utility/math','module/tracker','module/detector','module/fire_control']:sources+=sorted((src/directory).rglob('*.cpp'))
  if variant=='upstream':sources=[ROOT/'upstream_robot_translation.cpp' if p==src/'module/tracker/model/robot.cpp' else p for p in sources]
  flags=['-std=c++23','-O2','-DNDEBUG','-Wall','-Wextra','-Wpedantic','-pthread','-D_GLIBCXX_USE_CXX11_ABI=1','-I'+str(ROOT/'shims'),'-I'+str(src),'-I'+str(src/'kernel')]
  for name in ['eigen','opencv','yaml','openvino']:flags+=['-isystem',dep[name]]
  flags+=['-isystem',str(pathlib.Path(dep['eigen'])/'eigen3')]
  if variant=='candidate':flags+=['-DREBUILD_CANDIDATE=1']
  identity={'cache_policy_version':3,'adapter_headers':{p.name:sha(p) for p in sorted(ROOT.glob('*.hpp'))},'compiler':compiler,'flags':flags,'source_tree':tree_identity(src),'shims':tree_identity(ROOT/'shims'),'external_headers':external}
  commands=[]
  def compile_one(source):
   obj=build/(str(source.relative_to(ROOT)).replace('/','__')+'.o');cmd=[dep['cxx'],*flags,'-c',str(source),'-o',str(obj)]
   commands.append(dict(directory=str(ROOT),file=str(source),output=str(obj),arguments=cmd))
   digest=hashlib.sha256(source.read_bytes()+json.dumps(identity,sort_keys=True).encode()).hexdigest();marker=obj.with_suffix('.sha256')
   if not(obj.exists() and marker.exists() and marker.read_text()==digest):
    # clangd/clang-tidy are not present in this execution environment; perform
    # an explicit compiler syntax stage before compiling each translation unit.
    run([dep['cxx'],*flags,'-fsyntax-only',str(source)],build/(obj.stem+'.syntax.log'))
    run(cmd,build/(obj.stem+'.compile.log'));marker.write_text(digest);print(variant,source.relative_to(ROOT),flush=True)
   return str(obj)
  with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,args.jobs)) as pool:objects=list(pool.map(compile_one,sources))
  (build/'compile_commands.json').write_text(json.dumps(sorted(commands,key=lambda c:c['file']),indent=2))
  binary=ROOT/'build'/f'rmcs_rebuild_{variant}'
  # Use relocatable $ORIGIN search paths; never claim local absolute rpaths portable.
  rpaths=['$ORIGIN/../deps/openvino_cpp/runtime/lib/intel64','$ORIGIN/../deps/openvino_cpp/runtime/3rdparty/tbb/lib']
  cmd=[dep['cxx'],'-pthread',*objects,*libs,*['-Wl,-rpath,'+p for p in rpaths],'-o',str(binary)]
  run(cmd,build/'link.log')
  warnings=[str(p.relative_to(ROOT)) for p in build.glob('*.compile.log') if 'warning:' in p.read_text()]
  manifest={'identity':'rmcs-sync-rebuild-v2','variant':variant,'dependencies':dep,'compile_identity':identity,'link':cmd,'linked_library_sha256':{p:sha(p) for p in libs},'binary_sha256':sha(binary),'warning_logs':warnings,'lsp_available':bool(shutil.which('clangd') or shutil.which('clang-tidy')),'syntax_stage':'g++ -fsyntax-only before every fresh object','clean_requested':args.clean}
  (build/'build_manifest.json').write_text(json.dumps(manifest,indent=2));print('BUILT',binary,flush=True)
 return 0
if __name__=='__main__':
 try:sys.exit(main())
 except Exception as e:print(str(e),file=sys.stderr);sys.exit(1)
