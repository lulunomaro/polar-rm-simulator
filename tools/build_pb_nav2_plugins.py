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
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rm_match.integrations.pb_navigation_workspace import git_snapshot,prepare_controller,write_owned,sha

PLUGIN_COMMIT='d70977132936da4d758bd6e8c0771a8cf4861ad9'


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-root',required=True)
    p.add_argument('--environment',required=True);p.add_argument('--out',required=True)
    a=p.parse_args(argv);out=Path(a.out).absolute();source=Path(a.source_root).absolute()
    if sys.platform!='linux' or out.exists() or any(x.is_symlink() for x in (out,*out.parents)):raise ValueError('requires_new_owned_linux_workspace')
    envraw=Path(a.environment).read_bytes();settings=json.loads(envraw)
    env=dict(os.environ);env.update(settings['process_environment'])
    out.mkdir(parents=True)
    prepare_controller(source/'pb_omni_pid_pursuit_controller',out/'src/pb_omni_pid_pursuit_controller')
    files=git_snapshot(source/'pb_nav2_plugins',PLUGIN_COMMIT)
    write_owned(out/'src/pb_nav2_plugins',files,dict(schema='polar.sim.pb-owned-source.v1',upstream_commit=PLUGIN_COMMIT,
        original_algorithm=True,qualification='original_plugins_not_navigation_acceptance'))
    cmd=['colcon','--log-base',str(out/'logs'),'build','--base-paths',str(out/'src'),
        '--build-base',str(out/'build'),'--install-base',str(out/'install'),'--executor','sequential',
        '--cmake-args','-DBUILD_TESTING=OFF','-DPython3_EXECUTABLE=/usr/bin/python3','-DPYTHON_EXECUTABLE=/usr/bin/python3']
    started=time.perf_counter();proc=None;timed_out=False;clean=False
    # A separate owned process group lets timeout cleanup reach compiler children.
    with (out/'build.log').open('wb') as log:
        try:
            proc=subprocess.Popen(cmd,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            proc.wait(timeout=600)
        except subprocess.TimeoutExpired:
            timed_out=True
            try:os.killpg(proc.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:proc.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                proc.wait(timeout=1.)
        finally:
            if proc is not None and proc.poll() is None:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                proc.wait(timeout=1.)
            clean=proc is not None and proc.poll() is not None
    result=dict(schema='polar.sim.pb-nav2-build.v1',command=cmd,elapsed_seconds=time.perf_counter()-started,
        exit_code=proc.returncode if proc is not None else None,timed_out=timed_out,build_process_reaped=clean,
        navigation_nodes_started=False,algorithm_changed=False,controller_compute_hook=True,
        qualification='build_only_not_lio_nav2_sil_acceptance',environment_sha256=sha(envraw),
        environment=settings['process_environment'],source_identity_sha256={name:sha((out/'src'/name/'SOURCE_IDENTITY.json').read_bytes())
            for name in ('pb_nav2_plugins','pb_omni_pid_pursuit_controller')})
    (out/'BUILD_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
    return 0 if proc.returncode==0 and not timed_out and clean else 2


if __name__=='__main__':raise SystemExit(main())
