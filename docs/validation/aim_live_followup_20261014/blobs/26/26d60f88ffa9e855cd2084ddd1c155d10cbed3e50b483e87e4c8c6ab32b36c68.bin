"""Owned build of fixed original PB plugins and reviewed controller compute hook."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rm_match.integrations.pb_navigation_workspace import git_snapshot,prepare_controller,write_owned,sha,replace_once

PLUGIN_COMMIT='d70977132936da4d758bd6e8c0771a8cf4861ad9'


def rename_layers(files):
    """Link/registration binding only; preserve every algorithm and class byte."""
    original=dict(files);result=dict(files)
    xml=ET.fromstring(original['costmap_plugins.xml'])
    libraries=xml.findall('library')
    if len(libraries)!=1 or libraries[0].attrib.get('path')!='layers':raise ValueError('pb_layer_registration_anchor')
    classes=[dict(c.attrib) for c in xml.iter('class')]
    if classes!=[dict(type='pb_nav2_costmap_2d::IntensityVoxelLayer',base_class_type='nav2_costmap_2d::Layer')]:raise ValueError('pb_layer_class_identity')
    marker='ament_auto_add_library(layers SHARED\n  src/layers/intensity_voxel_layer.cpp\n)'
    result['CMakeLists.txt']=replace_once(original['CMakeLists.txt'],marker,marker+'\nset_target_properties(layers PROPERTIES OUTPUT_NAME pb_intensity_layers)')
    result['costmap_plugins.xml']=replace_once(original['costmap_plugins.xml'],'path="layers"','path="pb_intensity_layers"')
    if [dict(c.attrib) for c in ET.fromstring(result['costmap_plugins.xml']).iter('class')]!=classes:raise ValueError('pb_layer_class_changed')
    algorithm={name:sha(value) for name,value in original.items() if name.endswith(('.cpp','.hpp','.h'))}
    if not algorithm or any(sha(result[name])!=value for name,value in algorithm.items()):raise ValueError('pb_layer_algorithm_changed')
    patch=dict(kind='library_output_and_xml_binding_only',before='liblayers.so',after='libpb_intensity_layers.so',
        class_identity=classes,algorithm_sha256=algorithm,
        changed_files={k:dict(before_sha256=sha(original[k]),after_sha256=sha(result[k])) for k in ('CMakeLists.txt','costmap_plugins.xml')})
    return result,patch


def build_timeout(value):
    try:seconds=int(value)
    except (TypeError,ValueError):raise argparse.ArgumentTypeError('build timeout must be an integer in 60..3600 seconds')
    if not 60<=seconds<=3600:raise argparse.ArgumentTypeError('build timeout must be in 60..3600 seconds')
    return seconds


def parse_args(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-root',required=True)
    p.add_argument('--environment',required=True);p.add_argument('--out',required=True)
    selected=p.add_mutually_exclusive_group()
    selected.add_argument('--plugins-only',action='store_true',help='reuse separately identified controller build; no duplicate controller compilation')
    selected.add_argument('--controller-only',action='store_true',help='build only fixed controller and reviewed compute header; retain separately identified plugin build')
    p.add_argument('--build-timeout-seconds',type=build_timeout,default=1800,
        help='owned build resource budget, 60..3600 (default 1800); does not change SDK deadlines')
    return p.parse_args(argv)


def stop_build_group(proc):
    """Bounded TERM then KILL of the owned group, including surviving compilers."""
    try:os.killpg(proc.pid,signal.SIGTERM)
    except ProcessLookupError:pass
    try:proc.wait(timeout=.5)
    except subprocess.TimeoutExpired:pass
    # A reaped colcon leader does not imply that its compiler children exited.
    try:os.killpg(proc.pid,signal.SIGKILL)
    except ProcessLookupError:pass
    if proc.poll() is None:proc.wait(timeout=1.)


def build_command(out,settings):
    interpreter=settings.get('venv_python',sys.executable)
    if type(interpreter) is not str or not Path(interpreter).is_absolute() or not Path(interpreter).is_file() or not os.access(interpreter,os.X_OK):raise ValueError('build_python_requires_existing_absolute_executable')
    return ['colcon','--log-base',str(out/'logs'),'build','--base-paths',str(out/'src'),
        '--build-base',str(out/'build'),'--install-base',str(out/'install'),'--executor','sequential',
        '--cmake-args','-DBUILD_TESTING=OFF','-DPython3_EXECUTABLE='+interpreter,'-DPYTHON_EXECUTABLE='+interpreter]


def main(argv=None):
    a=parse_args(argv);out=Path(a.out).absolute();source=Path(a.source_root).absolute()
    if sys.platform!='linux' or out.exists() or any(x.is_symlink() for x in (out,*out.parents)):raise ValueError('requires_new_owned_linux_workspace')
    envraw=Path(a.environment).read_bytes();settings=json.loads(envraw)
    cmd=build_command(out,settings)
    env=dict(os.environ);env.update(settings['process_environment'])
    out.mkdir(parents=True)
    packages=[]
    if not a.plugins_only:
        prepare_controller(source/'pb_omni_pid_pursuit_controller',out/'src/pb_omni_pid_pursuit_controller')
        packages.append('pb_omni_pid_pursuit_controller')
    if not a.controller_only:
        files=git_snapshot(source/'pb_nav2_plugins',PLUGIN_COMMIT)
        files,binding_patch=rename_layers(files)
        write_owned(out/'src/pb_nav2_plugins',files,dict(schema='polar.sim.pb-owned-source.v1',upstream_commit=PLUGIN_COMMIT,
            original_algorithm=True,binding_patch=binding_patch,qualification='original_plugins_with_unique_library_binding_not_navigation_acceptance'))
        packages.append('pb_nav2_plugins')
    started=time.perf_counter();proc=None;timed_out=False;clean=False
    # A separate owned process group lets timeout cleanup reach compiler children.
    with (out/'build.log').open('wb') as log:
        try:
            proc=subprocess.Popen(cmd,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            proc.wait(timeout=a.build_timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out=True
            stop_build_group(proc)
        finally:
            if proc is not None and proc.poll() is None:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                proc.wait(timeout=1.)
            clean=proc is not None and proc.poll() is not None
    result=dict(schema='polar.sim.pb-nav2-build.v1',command=cmd,elapsed_seconds=time.perf_counter()-started,
        exit_code=proc.returncode if proc is not None else None,timed_out=timed_out,build_process_reaped=clean,
        build_timeout_seconds=a.build_timeout_seconds,
        build_budget_reason='600s combined build timed out; independent original package builds succeeded',
        navigation_nodes_started=False,algorithm_changed=False,controller_compute_hook=not a.plugins_only,
        qualification='build_only_not_lio_nav2_sil_acceptance',environment_sha256=sha(envraw),
        environment=settings['process_environment'],source_identity_sha256={name:sha((out/'src'/name/'SOURCE_IDENTITY.json').read_bytes())
            for name in packages})
    (out/'BUILD_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
    return 0 if proc.returncode==0 and not timed_out and clean else 2


if __name__=='__main__':raise SystemExit(main())
