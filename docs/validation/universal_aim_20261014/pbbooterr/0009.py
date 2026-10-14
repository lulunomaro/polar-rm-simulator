"""Reproducible owned PB seven-package Humble build; never starts model nodes.

Run on Ubuntu 22.04 only, under a new ext4 directory. Sources are copied from
the already-reviewed PB03/dependency03 manifests, byte checked before/after.
No setup.sh, hardware driver, global install, source patch or model warmup.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
PACKAGES=('armor_detector_opencv','armor_tracker','projectile_motion','polar_pb_aim_interfaces',
    'auto_aim_interfaces','pb_rm_interfaces','rmoss_projectile_motion')
PINS={'source':'3871fc79ad57946a8dfcdbde50a198f1faf8915bf18b5718f33a966f5ba466ed',
 'dependencies':'7af632d034786f18e0e5b5703e840845c8911dfef110200f92bd6e9cde23c365',
 'environment':'d60183ebf62d520c72eb20b84207fa4344d8f17183bb0df8eee92f97b7f981ee',
 'mount':'296aaa073da96fa0dcc0ecf473284e76eb94859dd53006457c9507cdda86bf62'}
MODEL='b3250176ea8fdbe6d1585be954363757ff6a8245a81e8797f16cea601976d47a'
LABEL='8cc04e2a54c7ee1c39925c9ca8e6eebe2d1015ee9dab77ab3befd8095be74411'

def digest(raw):return hashlib.sha256(raw).hexdigest()

def read_checked(path,wanted):
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_file():raise ValueError('input_symlink_or_missing:'+str(path))
    before=path.stat();raw=path.read_bytes();after=path.stat()
    if (before.st_dev,before.st_ino,before.st_mtime_ns,before.st_size)!=(after.st_dev,after.st_ino,after.st_mtime_ns,after.st_size):
        raise ValueError('input_changed_during_read:'+str(path))
    if digest(raw)!=wanted:raise ValueError('input_sha_changed:'+str(path))
    return raw

def literal_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate_json_key:'+key)
            result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda value:(_ for _ in ()).throw(ValueError('nonfinite_json')))

def manifest_files(root,kind):
    root=Path(root);raw=read_checked(root/'SOURCE_MANIFEST.json',PINS[kind]);manifest=literal_json(raw)
    if kind=='source' and (manifest['commit']!='df1892c48f90093f86a2f7b02af6441a80aa2d97' or 'source_safety_hook' not in manifest):
        raise ValueError('reviewed_pb03_required')
    if kind=='dependencies' and (manifest['message_and_solver_bytes_unchanged'] is not True or len(manifest['changed'])!=4):
        raise ValueError('reviewed_dependency03_required')
    snapshots={}
    for rel,wanted in manifest['generated_sha256'].items():
        if type(rel) is not str or Path(rel).is_absolute() or '..' in Path(rel).parts or '\\' in rel:raise ValueError('manifest_relative_path')
        snapshots[rel]=read_checked(root/rel,wanted)
    return manifest,snapshots

def copy_sources(source,dependencies,out):
    """Pure byte-copy boundary; may be tested on Windows without any ROS import."""
    source=Path(source).absolute();dependencies=Path(dependencies).absolute();out=Path(out).absolute()
    if out.exists() or any(p.is_symlink() for p in (out,*out.parents)):raise ValueError('fresh_owned_workspace_required')
    if any(out.is_relative_to(origin) or origin.is_relative_to(out) for origin in (source,dependencies)):
        raise ValueError('independent_owned_workspace_required')
    manifests={};snapshots={};originals={}
    for kind,origin in (('source',Path(source)),('dependencies',Path(dependencies))):
        manifest,files=manifest_files(origin,kind);manifests[kind]=manifest;snapshots[kind]=files
        originals[str(origin/'SOURCE_MANIFEST.json')]=PINS[kind]
        for rel,raw in files.items():originals[str(origin/rel)]=digest(raw)
    staged={}
    for kind,files in snapshots.items():
        for rel,raw in files.items():
            target=rel if rel.startswith('src/') else 'inputs/'+kind+'/'+rel
            if target in staged:raise ValueError('package_or_path_collision:'+target)
            staged[target]=raw
    found={}
    for rel,raw in staged.items():
        if rel.startswith('src/') and rel.endswith('/package.xml'):
            name=ET.fromstring(raw).findtext('name');found[name]=rel
    if set(found)!=set(PACKAGES):raise ValueError('exact_seven_packages_required')
    if digest(staged['src/armor_detector_opencv/model/mlp.onnx'])!=MODEL or digest(staged['src/armor_detector_opencv/model/label.txt'])!=LABEL:
        raise ValueError('original_classifier_required')
    out.mkdir(parents=True)
    copied={}
    for rel,raw in staged.items():
        target=out/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        read_checked(target,digest(raw));copied[rel]=dict(bytes=len(raw),sha256=digest(raw))
    for kind,origin in (('source',Path(source)),('dependencies',Path(dependencies))):
        (out/'inputs'/kind/'SOURCE_MANIFEST.json').write_bytes(read_checked(origin/'SOURCE_MANIFEST.json',PINS[kind]))
    for path,wanted in originals.items():read_checked(path,wanted)
    return dict(schema='polar.pb-aim-build-source-copy.v1',packages=list(PACKAGES),
        original_files_sha256=originals,copied_files=copied,originals_unchanged=True,
        source_manifest_sha256=PINS['source'],dependency_manifest_sha256=PINS['dependencies'],
        source_patch_executed=False,model_loaded=False,nodes_started=False)

def build_environment(settings):
    values=settings.get('process_environment')
    if type(values) is not dict or any(type(k) is not str or type(v) is not str for k,v in values.items()):raise ValueError('owned_environment_required')
    if any(key in values for key in ('PYTHONHOME','PYTHONPATH')):raise ValueError('final_owned_pth_required')
    env=dict(os.environ);env.pop('PYTHONHOME',None);env.pop('PYTHONPATH',None);env.update(values)
    for key in ('CC','CXX','CFLAGS','CXXFLAGS','LDFLAGS'):env.pop(key,None)
    env.update(ROS_DISTRO='humble',ROS_VERSION='2',ROS_PYTHON_VERSION='3',PYTHONDONTWRITEBYTECODE='1',MAKEFLAGS='-j1',CMAKE_BUILD_PARALLEL_LEVEL='1')
    interpreter=settings.get('venv_python')
    if type(interpreter) is not str or not interpreter.startswith('/root/') or not interpreter.endswith('/venv/bin/python'):
        raise ValueError('owned_humble_venv_required')
    env['VIRTUAL_ENV']=str(Path(interpreter).parents[1]);env['PATH']=str(Path(interpreter).parent)+':'+env.get('PATH','/usr/bin:/bin')
    return env,interpreter

def build_command(out,interpreter):
    out=Path(out)
    return [interpreter,'/usr/bin/colcon','--log-base',str(out/'logs'),'build','--base-paths',str(out/'src'),
        '--build-base',str(out/'build'),'--install-base',str(out/'install'),'--merge-install','--executor','sequential',
        '--packages-up-to','armor_detector_opencv','armor_tracker','projectile_motion','--cmake-args',
        '-DBUILD_TESTING=OFF','-DCMAKE_BUILD_TYPE=Release','-DPython3_EXECUTABLE='+interpreter,
        '-DPYTHON_EXECUTABLE='+interpreter,'-DPython_EXECUTABLE='+interpreter,
        '-DCMAKE_C_COMPILER=/usr/bin/gcc','-DCMAKE_CXX_COMPILER=/usr/bin/g++',
        '-DPython3_FIND_VIRTUALENV=ONLY','-DPython_FIND_VIRTUALENV=ONLY']

def add_extra_prefix(env,manifest,sha):
    """Explicit reviewed addition; original environment reference stays unchanged."""
    from tools.prepare_pb_aim_system_dependencies import checked_extra_prefix
    prefix,value=checked_extra_prefix(manifest,sha)
    result=dict(env)
    additions={'CMAKE_PREFIX_PATH':[prefix/'opt/ros/humble',prefix/'usr'],
        'AMENT_PREFIX_PATH':[prefix/'opt/ros/humble'],
        'LD_LIBRARY_PATH':[prefix/'opt/ros/humble/lib',prefix/'usr/lib/x86_64-linux-gnu',prefix/'usr/lib',prefix/'lib/x86_64-linux-gnu'],
        'PKG_CONFIG_PATH':[prefix/'usr/lib/x86_64-linux-gnu/pkgconfig',prefix/'usr/share/pkgconfig']}
    for key,paths in additions.items():
        found=[str(path) for path in paths if path.is_dir()]
        result[key]=':'.join(found+[result[key]])
    return result,dict(path=str(Path(manifest).absolute()),sha256=sha,prefix=str(prefix),
        packages=[row['package'] for row in value['packages']],verification='Exact complete prefix regular-file bytes and symlink targets')

def filesystem_type(path,mountinfo):
    selected=[]
    for line in mountinfo.splitlines():
        lhs,rhs=line.split(' - ',1);point=lhs.split()[4].replace('\\040',' ')
        if path==point or path.startswith(point.rstrip('/')+'/'):selected.append((len(point),rhs.split()[0]))
    if not selected:raise ValueError('owned_mount_not_found')
    return max(selected)[1]

def preflight_files(out,source_record):
    out=Path(out);probe=out/'preflight';probe.mkdir()
    external=set()
    for file in (out/'src').glob('*/package.xml'):
        external.update(e.text for e in ET.parse(file).getroot() if e.tag in ('depend','build_depend','buildtool_depend','build_export_depend'))
    external-=set(PACKAGES);external.discard('eigen');external.update(('ament_cmake_auto','OpenCV','Eigen3','nlohmann_json'))
    packages=sorted(external-{'Eigen3'})+['Eigen3']
    cmake='cmake_minimum_required(VERSION 3.16)\nproject(pb_aim_environment_probe LANGUAGES C CXX)\n'
    cmake+=''.join('find_package('+name+' REQUIRED)\n' for name in packages)
    cmake+='file(WRITE "${CMAKE_BINARY_DIR}/COMPILER.txt" "${CMAKE_CXX_COMPILER}\n${CMAKE_CXX_COMPILER_ID}\n${CMAKE_CXX_COMPILER_VERSION}\n${Python3_EXECUTABLE}\n")\n'
    (probe/'CMakeLists.txt').write_bytes(cmake.encode())
    code='''import json,sys,sysconfig,importlib
names=('colcon_core','ament_package','catkin_pkg','rosidl_adapter','rosidl_parser','em','lark','setuptools','yaml','rclpy','cv_bridge')
modules={name:str(importlib.import_module(name).__file__) for name in names}
assert sys.version_info[:2]==(3,10), 'Humble Python3.10 required'
assert sys.prefix!=sys.base_prefix, 'owned venv required'
print(json.dumps(dict(interpreter=sys.executable,prefix=sys.prefix,version=sys.version,paths=sys.path,modules=modules,model_loaded=False,ros_context_started=False)))
'''
    (probe/'python_probe.py').write_bytes(code.encode())
    return probe,packages

def run_owned(argv,env,log,timeout):
    # Existing birth-bound stdlib-only helper, with actual process-group reap
    # proof; no claim that reaping only the colcon leader cleaned compilers.
    if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
    from rm_match.integrations.owned_linux_group import LinuxOwnedProcessGroup
    owner=LinuxOwnedProcessGroup();started=time.perf_counter();child=None;failure=None;timed_out=False
    with Path(log).open('wb') as output:
        try:
            child=subprocess.Popen(argv,env=env,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
            owner.attach(child);child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:timed_out=True;failure='timeout'
        except BaseException as exc:failure=type(exc).__name__+':'+str(exc)
        finally:cleanup=owner.cleanup()
    return dict(argv=argv,pid=child.pid if child else None,exit_code=child.returncode if child else None,
        elapsed_seconds=time.perf_counter()-started,timed_out=timed_out,error=failure,cleanup=cleanup,
        raw_log=str(log),log_sha256=digest(Path(log).read_bytes()))

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT/'artifacts/pb2025-aim-source-20261014-03')
    parser.add_argument('--dependencies',type=Path,default=ROOT/'artifacts/pb2025-aim-dependency-compat-20261014-03')
    parser.add_argument('--environment',type=Path,default=ROOT/'artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json')
    parser.add_argument('--mount',type=Path,default=ROOT/'artifacts/aim-mount-calibration-20261014-03/MOUNTS.json')
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--timeout',type=int,default=1800)
    parser.add_argument('--extra-prefix-manifest',type=Path);parser.add_argument('--extra-prefix-sha256')
    mode=parser.add_mutually_exclusive_group(required=True);mode.add_argument('--preflight-only',action='store_true');mode.add_argument('--run',action='store_true')
    args=parser.parse_args(argv);out=args.out.absolute()
    if sys.platform!='linux' or 'VERSION_ID="22.04"' not in Path('/etc/os-release').read_text() or 'ID=ubuntu' not in Path('/etc/os-release').read_text():
        raise ValueError('Ubuntu22.04 build execution required')
    if not 60<=args.timeout<=3600:raise ValueError('build_budget_60_to_3600')
    if not str(out).startswith('/root/polar-pb-aim-') or filesystem_type(str(out),Path('/proc/self/mountinfo').read_text())!='ext4':
        raise ValueError('fresh_owned_ext4_root_required')
    envraw=read_checked(args.environment,PINS['environment']);settings=literal_json(envraw);env,interpreter=build_environment(settings)
    if bool(args.extra_prefix_manifest)!=bool(args.extra_prefix_sha256):raise ValueError('extra_prefix_ref_and_sha_required_together')
    extra=None
    if args.extra_prefix_manifest:
        if not re.fullmatch('[0-9a-f]{64}',args.extra_prefix_sha256):raise ValueError('extra_prefix_SHA_type')
        env,extra=add_extra_prefix(env,args.extra_prefix_manifest,args.extra_prefix_sha256)
        if filesystem_type(extra['prefix'],Path('/proc/self/mountinfo').read_text())!='ext4':raise ValueError('extra_prefix_ext4_required')
    mount=read_checked(args.mount,PINS['mount'])
    record=copy_sources(args.source,args.dependencies,out)
    (out/'SOURCE_COPY.json').write_bytes((json.dumps(record,indent=2)+'\n').encode())
    (out/'inputs/ENVIRONMENT_COMPAT_FINAL.json').write_bytes(envraw);(out/'inputs/MOUNTS.json').write_bytes(mount)
    report=dict(schema='polar.pb-aim-owned-build.v1',environment_sha256=PINS['environment'],mount_sha256=PINS['mount'],
        source_copy_sha256=digest((out/'SOURCE_COPY.json').read_bytes()),build_tool_sha256=digest(Path(__file__).read_bytes()),
        cleanup_helper_sha256=digest((ROOT/'rm_match/integrations/owned_linux_group.py').read_bytes()),
        environment={key:env[key] for key in sorted(set(settings['process_environment'])|
            {'ROS_DISTRO','ROS_VERSION','ROS_PYTHON_VERSION','VIRTUAL_ENV','MAKEFLAGS','CMAKE_BUILD_PARALLEL_LEVEL','PATH'})},
        interpreter=interpreter,commands=[],success=False,build_executed=False,
        model_loaded=False,nodes_started=False,hardware_started=False,physics_steps=0,inference_calls=0)
    report['extra_prefix']=extra
    try:
        if not Path(interpreter).is_file() or not os.access(interpreter,os.X_OK):raise ValueError('actual_owned_python_missing')
        pth=Path(interpreter).parents[1]/'lib/python3.10/site-packages/owned_humble.pth'
        read_checked(pth,settings['derived_pth_sha256'])
        report['owned_python_pth']=dict(path=str(pth),sha256=settings['derived_pth_sha256'])
        for key in ('CMAKE_PREFIX_PATH','AMENT_PREFIX_PATH','LD_LIBRARY_PATH','PKG_CONFIG_PATH'):
            for value in env[key].split(':'):
                if not value.startswith('/') or value.startswith('/mnt/') or not Path(value).is_dir():raise ValueError('missing_or_DrvFs_dependency:'+key+':'+value)
        probe,packages=preflight_files(out,record);report['cmake_preflight_packages']=packages
        commands=[([interpreter,str(probe/'python_probe.py')],out/'python_preflight.log',30),
            (['/usr/bin/cmake','-S',str(probe),'-B',str(probe/'build'),'-DPython3_EXECUTABLE='+interpreter,
              '-DPYTHON_EXECUTABLE='+interpreter,'-DCMAKE_C_COMPILER=/usr/bin/gcc','-DCMAKE_CXX_COMPILER=/usr/bin/g++'],out/'cmake_preflight.log',60)]
        if args.run:commands.append((build_command(out,interpreter),out/'build.log',args.timeout))
        for command,log,budget in commands:
            row=run_owned(command,env,log,budget);report['commands'].append(row)
            if log.name=='build.log':report['build_executed']=True
            if row['exit_code']!=0 or not row['cleanup']['clean'] or row['error']:raise ValueError('owned_command_failed:'+log.name)
        for path,wanted in record['original_files_sha256'].items():read_checked(path,wanted)
        for rel,value in record['copied_files'].items():read_checked(out/rel,value['sha256'])
        read_checked(args.environment,PINS['environment']);read_checked(args.mount,PINS['mount'])
        report['source_and_refs_unchanged']=True
        if args.run:
            installed={};commands=[]
            for name in ('armor_detector_opencv','armor_tracker','projectile_motion'):
                file=out/'install/lib'/name/(name+'_node');raw=file.read_bytes()
                if not raw.startswith(b'\x7fELF\x02') or not os.access(file,os.X_OK):raise ValueError('actual_node_elf_missing:'+name)
                installed[name]=dict(path=str(file),sha256=digest(raw),bytes=len(raw))
            for name,wanted in (('mlp.onnx',MODEL),('label.txt',LABEL)):
                file=out/'install/share/armor_detector_opencv/model'/name;read_checked(file,wanted)
                installed[name]=dict(path=str(file),sha256=wanted)
            report['installed']=installed
            for file in sorted((out/'install').rglob('*')):
                if file.is_file() and not file.is_symlink() and file.read_bytes()[:4]==b'\x7fELF':
                    log=out/('ldd-'+file.relative_to(out/'install').as_posix().replace('/','_')+'.log')
                    row=run_owned(['/usr/bin/ldd',str(file)],dict(env,LD_LIBRARY_PATH=str(out/'install/lib')+':'+env['LD_LIBRARY_PATH']),log,10)
                    row['elf_sha256']=digest(file.read_bytes());row['elf_path']=str(file);report['commands'].append(row)
                    if row['exit_code']!=0 or b'not found' in log.read_bytes() or not row['cleanup']['clean']:raise ValueError('installed_ELF_unresolved:'+str(file))
        report['success']=True
    except BaseException as exc:report['error']=type(exc).__name__+':'+str(exc)
    finally:
        try:
            for path,wanted in record['original_files_sha256'].items():read_checked(path,wanted)
            for rel,value in record['copied_files'].items():read_checked(out/rel,value['sha256'])
            read_checked(args.environment,PINS['environment']);read_checked(args.mount,PINS['mount'])
            if extra:add_extra_prefix(env,args.extra_prefix_manifest,args.extra_prefix_sha256)
            report['source_and_refs_unchanged']=True
        except BaseException as exc:
            report['source_and_refs_unchanged']=False;report['source_audit_error']=type(exc).__name__+':'+str(exc);report['success']=False
        report['compiler_identity']={}
        for path in ('/usr/bin/gcc','/usr/bin/g++','/usr/bin/cmake','/usr/bin/colcon',interpreter):
            actual=Path(path).resolve()
            if actual.is_file():report['compiler_identity'][path]=dict(resolved_path=str(actual),sha256=digest(actual.read_bytes()))
        report['build_metadata_sha256']={}
        for directory in (out/'preflight/build',out/'build'):
            if directory.is_dir():
                for file in directory.rglob('*'):
                    if file.is_file() and not file.is_symlink() and file.name in ('flags.make','link.txt','CMakeCache.txt','compile_commands.json','CMakeCXXCompiler.cmake','COMPILER.txt'):
                        report['build_metadata_sha256'][str(file.relative_to(out))]=digest(file.read_bytes())
        (out/'BUILD_RESULT.json').write_bytes((json.dumps(report,indent=2)+'\n').encode())
        print(json.dumps(dict(success=report['success'],build_executed=report['build_executed'],out=str(out),error=report.get('error')),sort_keys=True),flush=True)
    return 0 if report['success'] else 2

if __name__=='__main__':raise SystemExit(main())
