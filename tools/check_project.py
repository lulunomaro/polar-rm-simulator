#!/usr/bin/env python3
"""T17 local quality entry; preserves fresh logs and labels evidence levels."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def source_hashes(*, exclude_output=None):
    excluded=Path(exclude_output).resolve() if exclude_output is not None else None
    names=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=ROOT).decode('utf-8').split('\0')
    return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
            for name in sorted(set(names)) if name and (ROOT/name).is_file()
            and (excluded is None or not (ROOT/name).resolve().is_relative_to(excluded))}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True,help='Fresh evidence directory')
    parser.add_argument('--camera',action='store_true',help='Also run real bounded loopback camera QA')
    args=parser.parse_args();out=args.out.absolute()
    if out.exists():parser.error('Choose a fresh --out directory; existing evidence is preserved')
    out.mkdir(parents=True)
    steps=[('acceptance_preset','configuration_only',
            [sys.executable,'tools/validate_acceptance.py','--out',str(out/'preset.json')]),
           ('source_provenance','static_source_identity',
            [sys.executable,'tools/verify_standalone.py']),
           ('interface_static','static_contracts',
            [sys.executable,'tools/check_standalone_contracts.py']),
           ('pytest','unit_synthetic_and_physics_tests_not_native_match',
            [sys.executable,'-m','pytest','-q','--junitxml='+str(out/'pytest.xml')])]
    if args.camera:
        steps.append(('camera','real_loopback_camera_not_native_aim_or_LAN',
                      [sys.executable,'-m','rm_match.platform_v2.qa_camera','--out',str(out/'camera')]))
    report=dict(schema='polar.quality.run.v1',status='running',steps=[],
                source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                working_tree_patch_sha256=hashlib.sha256(subprocess.check_output(['git','diff','HEAD'],cwd=ROOT)).hexdigest(),
                source_files_sha256=source_hashes(exclude_output=out),
                milestone_accepted=False,scope='Local quality checks; no full native match, Windows native, new-machine LAN or HIL acceptance.')
    manifest=out/'manifest.json'
    def save():manifest.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    save()
    for name,level,command in steps:
        started=time.monotonic();error=None
        with (out/(name+'.log')).open('wb') as log:
            try:
                result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=1200)
                exit_code=result.returncode
            except subprocess.TimeoutExpired:
                exit_code=124;error='quality_step_timeout'
        report['steps'].append(dict(name=name,evidence_level=level,command=command,
                                    exit_code=exit_code,wall_seconds=time.monotonic()-started,error=error))
        save();print(name+': '+('passed' if exit_code==0 else 'failed'),flush=True)
        if exit_code:
            report['status']='failed';save();return 1
    report['source_unchanged_during_checks']=source_hashes(exclude_output=out)==report['source_files_sha256']
    report['status']='checks_passed_not_milestone_acceptance' if report['source_unchanged_during_checks'] else 'source_changed_during_checks'
    save()
    if not report['source_unchanged_during_checks']:return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
