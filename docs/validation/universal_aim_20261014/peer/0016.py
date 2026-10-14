"""Explicit harmless Windows→WSL lifecycle proof; no detector/ROS/NN/physics.

Run only in the root agent's agreed WSL window, using a verified Linux Python:
POLAR_RUN_WSL_JSONL_ACTUAL=1, POLAR_WSL_JSONL_TEST_PYTHON=<absolute Linux venv>.
The pure tests cannot substitute for these real process fixtures.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import pytest
from rm_match.deployment.aim_plugin import CAPABILITIES,MANIFEST_SCHEMA,register_aim_plugins
from rm_match.deployment.wsl_jsonl import PreparedWslAimPlugins,mounted_path
from rm_match.platform_v2.adapters import Registry

pytestmark=pytest.mark.skipif(sys.platform!='win32' or os.environ.get('POLAR_RUN_WSL_JSONL_ACTUAL')!='1',
    reason='explicit coordinated Windows/WSL harmless process fixture required')
ROOT=Path(__file__).resolve().parents[1]

def fixture(tmp_path,*,leader_exit=False):
    import uuid
    out=ROOT/'artifacts'/('wsl-jsonl-harmless-'+uuid.uuid4().hex);out.mkdir()
    python=os.environ['POLAR_WSL_JSONL_TEST_PYTHON']
    # The peer deliberately starts a new SID, which original-PGID cleanup misses.
    wrapper=out/'peer.py'
    wrapper.write_text('import os,sys,subprocess,json,signal\n'
        'sys.path.insert(0,'+repr(mounted_path(ROOT))+')\n'
        'from rm_match.integrations.aim_jsonl_peer import run_aim_plugin\n'
        'def factory():\n'
        ' child=subprocess.Popen([sys.executable,"-c","import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(120)"],start_new_session=True)\n'
        ' open('+repr(mounted_path(out/'grandchild.json'))+',"w").write(json.dumps({"pid":child.pid}))\n'
        ' class Engine:\n'
        '  def __call__(self,*args):raise RuntimeError("fixture never receives images")\n'
        '  def reset(self,context):\n'
        +('   os._exit(0)\n' if leader_exit else '   pass\n')+
        ' return Engine()\n'
        'raise SystemExit(run_aim_plugin(factory))\n')
    row=dict(adapter_id='custom_harmless_owned_peer',label='Synthetic ownership fixture; no algorithm',
        command=[python,str(mounted_path(wrapper))],cwd=mounted_path(ROOT),supported_robots=['red_sentry'],
        transport='wsl_jsonl_v1',capabilities=CAPABILITIES,
        wsl=dict(distribution=os.environ.get('POLAR_WSL_JSONL_TEST_DISTRO','Ubuntu-22.04'),
            python='/usr/bin/python3',process_env={}))
    manifest=out/'plugins.json';manifest.write_text(json.dumps(dict(schema=MANIFEST_SCHEMA,adapters=[row])))
    return out,manifest

@pytest.mark.parametrize('leader_exit',[False,True])
def test_real_nested_sid_and_leader_exit_are_owned_and_reaped(tmp_path,leader_exit):
    out,path=fixture(tmp_path,leader_exit=leader_exit);pool=None;adapter=None;failure=None
    try:
        pool=PreparedWslAimPlugins(path,repo_root=ROOT,shared_root=out)
        registry=Registry();register_aim_plugins(registry,path,wsl_prepared=pool)
        adapter=registry.create('custom_harmless_owned_peer',{})
        if leader_exit:
            with pytest.raises(Exception):adapter.reset(dict(episode=14,robot_id='red_sentry',binding_epoch=71))
        else:adapter.reset(dict(episode=14,robot_id='red_sentry',binding_epoch=71))
    except BaseException as exc:failure=exc
    finally:
        if adapter is not None:adapter.close()
        if pool is not None:pool.close_unclaimed()
    if failure:raise failure
    status=adapter.shutdown_status;proof=status['ownership']
    assert status['clean'] and proof['clean'] and proof['linux']['clean']
    pid=json.loads((out/'grandchild.json').read_text())['pid']
    linux=proof['linux']['ownership']
    assert str(pid) in {str(p) for p in linux['observed_births']}
    assert linux['group_empty'] and linux['reaped'] and linux['remaining_members']==[]
    assert any(r['pid']==pid for r in linux['reaped_descendants'])
    assert proof['windows']['group_empty']
    (out/'RESULT.json').write_text(json.dumps(dict(scope='harmless nested-session process ownership only',
        leader_exit=leader_exit,source_sha256={rel:hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()
        for rel in ('rm_match/deployment/wsl_jsonl.py','rm_match/deployment/wsl_jsonl_worker.py',
        'rm_match/deployment/wsl_jsonl_owned_tree.py')},status=status),indent=2))
