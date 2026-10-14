"""Generate fixed Livox interfaces in a new owned workspace; optional colcon build."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rm_match.integrations.pb_navigation_workspace import prepare_interfaces,prepare_controller,sha


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--livox-source',required=True)
    p.add_argument('--out',required=True);p.add_argument('--controller-source');p.add_argument('--build',action='store_true')
    a=p.parse_args(argv);out=Path(a.out).absolute()
    if out.exists() or any(parent.is_symlink() for parent in (out,*out.parents)):raise ValueError('pb_requires_new_owned_workspace')
    out.mkdir(parents=True)
    prepare_interfaces(a.livox_source,out/'src/livox_ros_driver2')
    if a.controller_source:prepare_controller(a.controller_source,out/'src/pb_omni_pid_pursuit_controller')
    if not a.build:return 0
    if sys.platform!='linux':raise ValueError('pb_interface_build_requires_humble_linux')
    # Scope this one process; no system install, hooks or global environment.
    cmd=['/bin/bash','-c','source /opt/ros/humble/setup.bash && exec colcon --log-base "$1/logs" build --base-paths "$1/src/livox_ros_driver2" --build-base "$1/build" --install-base "$1/install" --executor sequential --cmake-args -DBUILD_TESTING=OFF','pb-owned-build',str(out)]
    started=time.perf_counter()
    with (out/'build.log').open('wb') as log:
        proc=subprocess.run(cmd,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,timeout=180)
    report=dict(schema='polar.sim.pb-interface-build.v1',command=cmd,elapsed_seconds=time.perf_counter()-started,
        returncode=proc.returncode,interfaces_only=True,system_install=False,
        source_identity_sha256=sha((out/'src/livox_ros_driver2/SOURCE_IDENTITY.json').read_bytes()),
        controller_built=False)
    (out/'BUILD_RESULT.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    return proc.returncode


if __name__=='__main__':raise SystemExit(main())
