"""Bind an actually built PB source overlay to the generic prepared aim peer.

This local tool checks real ELF/model/source references and creates scoped ROS
parameters. It never launches ROS, executes an ELF, warms a model or invents a
robot generation. Preparation is not build/readiness or closed-loop evidence.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from rm_match.integrations.pb_aim_stack import checked_ref,scoped_parameters,load_stack,STACK_SCHEMA
from rm_match.integrations.pb_aim_configure import NODES

def reference(path):
    path=Path(path).absolute()
    value=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    checked_ref(value);return value

def prepare(source_manifest,executables,environment,mount,model,labels,out,*,calibration_id,
            run_uuid=None,domain_id=85,adapter_id='custom_pb_aim'):
    out=Path(out).absolute()
    if out.exists():raise ValueError('Fresh PB stack output required')
    run_uuid=uuid.uuid4().hex if run_uuid is None else run_uuid
    namespace='/polar_aim_'+run_uuid
    source_ref=reference(source_manifest);source_root=Path(source_ref['path']).parent
    original=reference(source_root/'PB_AIM_PARAMS.yaml')
    params=scoped_parameters(checked_ref(original)[1],namespace)
    # All supplied paths are trusted local deployment inputs, never HTTP data.
    refs={name:reference(executables[name]) for name in NODES}
    dependencies={name:reference(path) for name,path in dict(environment=environment,mount=mount,model=model,labels=labels).items()}
    out.mkdir(parents=True)
    (out/'SCOPED_PARAMS.yaml').write_bytes(params)
    spec=dict(schema=STACK_SCHEMA,run_uuid=run_uuid,namespace=namespace,domain_id=domain_id,
        calibration_id=calibration_id,adapter_id=adapter_id,executables=refs,
        params=reference(out/'SCOPED_PARAMS.yaml'),params_original=original,source_manifest=source_ref,**dependencies)
    path=out/'STACK.json';path.write_bytes((json.dumps(spec,indent=2,sort_keys=True)+'\n').encode())
    checked=load_stack(path,reference(path)['sha256'])
    report=dict(schema='polar.pb-aim-stack-preparation.v1',stack=reference(path),
        generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        namespace=namespace,run_uuid=run_uuid,validation='static actual-byte/source binding only',
        build_executed=False,ros_started=False,inference_executed=False,
        generic_peer_argv=['-m','rm_match.integrations.pb_aim_engine','--stack-ref',str(path),
            '--stack-sha256',reference(path)['sha256']],
        lifecycle='factory loads three unconfigured actual nodes; prepare ACK after real graph; reset once requires three matching source ACKs')
    (out/'PREPARATION.json').write_bytes((json.dumps(report,indent=2,sort_keys=True)+'\n').encode())
    return checked,report

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source-manifest','executables-json','environment','mount','model','labels','out','calibration-id'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--run-uuid');parser.add_argument('--domain-id',type=int,default=85)
    parser.add_argument('--adapter-id',default='custom_pb_aim')
    args=parser.parse_args(argv)
    executables=json.loads(Path(args.executables_json).read_text(encoding='utf-8'))
    if set(executables)!=set(NODES):raise ValueError('Exactly three original PB algorithm executable paths required')
    _,report=prepare(args.source_manifest,executables,args.environment,args.mount,args.model,args.labels,args.out,
        calibration_id=args.calibration_id,run_uuid=args.run_uuid,domain_id=args.domain_id,adapter_id=args.adapter_id)
    print(json.dumps(report,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
