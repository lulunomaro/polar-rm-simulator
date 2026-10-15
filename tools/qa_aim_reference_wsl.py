#!/usr/bin/env python3
"""Actual harmless WSL v2 prepare/reset/cleanup; no image, inference or physics."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--linux-python',required=True)
    p.add_argument('--distribution',default='Ubuntu')
    a=p.parse_args(argv);out=a.out.absolute()
    if out.exists():p.error('Fresh evidence directory required')
    out.mkdir(parents=True)
    # Check the explicitly selected distribution/interpreter before creating
    # an owned peer. Failure here is preflight, never a fabricated cleanup ACK.
    probe=subprocess.run([str(Path(os.environ['SystemRoot'])/'System32'/'wsl.exe'),'-d',a.distribution,
        '--',a.linux_python,'-c','import sys,numpy; print(sys.version.split()[0])'],
        capture_output=True,timeout=15.,creationflags=subprocess.CREATE_NO_WINDOW)
    (out/'PREFLIGHT_STDOUT.bin').write_bytes(probe.stdout)
    (out/'PREFLIGHT_STDERR.bin').write_bytes(probe.stderr)
    if probe.returncode:
        (out/'RESULT.json').write_text(json.dumps(dict(passed=False,state='interpreter_preflight_failed',
            returncode=probe.returncode,owned_peer_started=False,frames=0,inferences=0,physics_steps=0))+'\n',encoding='utf8',newline='\n')
        return 2
    from rm_match.deployment.aim_plugin import CAPABILITIES_V2,AimPluginAdapter,register_aim_plugins
    from rm_match.deployment.wsl_jsonl import PreparedWslAimPlugins,mounted_path
    from rm_match.platform_v2.adapters import Registry
    wrapper=out/'harmless_peer.py'
    wrapper.write_text('import sys\nsys.path.insert(0,'+repr(mounted_path(ROOT))+')\n'
        'from rm_match.deployment.aim_plugin import CAPABILITIES_V2\n'
        'from rm_match.integrations.aim_jsonl_peer import run_aim_plugin\n'
        'def factory():\n'
        ' def compute(*args):raise RuntimeError("no image computation authorized by this lifecycle QA")\n'
        ' return compute\n'
        'raise SystemExit(run_aim_plugin(factory,capabilities=CAPABILITIES_V2))\n', encoding='utf8',newline='\n')
    manifest=out/'manifest.json'
    manifest.write_text(json.dumps(dict(schema='polar.sim.aim-plugins.v1',adapters=[dict(
        adapter_id='custom_inertial_wsl_qa',label='Harmless lifecycle fixture, no algorithm',
        command=[a.linux_python,'-u',mounted_path(wrapper)],cwd=mounted_path(ROOT),
        supported_robots=['red_infantry'],transport='wsl_jsonl_v1',
        wsl=dict(distribution=a.distribution,python=a.linux_python,process_env={}),
        capabilities=copy.deepcopy(CAPABILITIES_V2))]),indent=2)+'\n',encoding='utf8',newline='\n')
    sources={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT/'rm_match').rglob('*.py')}
    sources[Path(__file__).relative_to(ROOT).as_posix()]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    original=AimPluginAdapter._validate_response;acks=[];errors=[];pool=instance=None;cleanup=None;descriptor=None
    def record(self,result,packet):
        # Capture actual parsed wire objects, then invoke the exact original
        # validator. No ACK, result or capability is manufactured here.
        acks.append(dict(request=copy.deepcopy(packet),response=copy.deepcopy(result)))
        return original(self,result,packet)
    start=time.perf_counter()
    AimPluginAdapter._validate_response=record
    try:
        pool=PreparedWslAimPlugins(manifest,repo_root=ROOT,shared_root=out/'owned')
        registry=Registry();register_aim_plugins(registry,manifest,wsl_prepared=pool)
        descriptor=registry.get('custom_inertial_wsl_qa').descriptor
        instance=registry.create('custom_inertial_wsl_qa',{})
        instance.reset(dict(robot_id='red_infantry',episode=17,binding_epoch=3))
    except Exception as exc:
        errors.append(type(exc).__name__+':'+str(exc))
        # Failed constructors retain their original owner diagnostics too.
        if pool is None:pool=getattr(exc,'resources',None)
        cleanup=getattr(exc,'cleanup_status',cleanup)
    finally:
        if instance is not None:
            try:instance.close()
            except Exception as exc:errors.append('close:'+type(exc).__name__+':'+str(exc))
            cleanup=instance.shutdown_status
        if pool is not None:
            try:pool.close_unclaimed()
            except Exception as exc:errors.append('pool:'+type(exc).__name__+':'+str(exc))
        AimPluginAdapter._validate_response=original
    source_unchanged=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in sources.items())
    checks=dict(actual_prepare_reset=[x['request']['op'] for x in acks]==['prepare','reset'],
        exact_capabilities=bool(acks) and all(x['request'].get('capabilities')==CAPABILITIES_V2
            and x['response'].get('capabilities')==CAPABILITIES_V2 for x in acks),
        clean=type(cleanup) is dict and cleanup.get('clean') is True,
        instrumentation_restored=AimPluginAdapter._validate_response is original,source_unchanged=source_unchanged)
    result=dict(schema='polar.aim-reference.wsl-lifecycle.v1',passed=all(checks.values()) and not errors,
        checks=checks,errors=errors,parsed_wire=acks,descriptor=descriptor,cleanup=cleanup,
        elapsed_wall_s=time.perf_counter()-start,source_sha256=sources,
        frames=0,inferences=0,physics_steps=0,moving_aim_qualified=False,
        scope='Actual WSL harmless process prepare/reset capability ACK and owned cleanup only')
    (out/'RESULT.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
    print(json.dumps({k:result[k] for k in ('passed','checks','errors','elapsed_wall_s')}))
    return 0 if result['passed'] else 2


if __name__=='__main__':raise SystemExit(main())
