#!/usr/bin/env python3
"""Validate T01 preset; --require-frozen fails while decisions remain open."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rm_match.acceptance import validate_preset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preset', type=Path, default=ROOT/'config/acceptance/m1-v1.json')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--require-frozen', action='store_true')
    args = parser.parse_args()
    if args.out and args.out.exists():
        parser.error('Choose a fresh --out file; preserve existing evidence')
    value = json.loads(args.preset.read_text(encoding='utf-8'))
    pending = validate_preset(value)
    packages = {}
    for name in ('mujoco', 'numpy', 'Pillow', 'opencv-python-headless', 'pytest'):
        try: packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: packages[name] = None
    report = dict(schema='polar.acceptance.preset-report.v1', configuration_valid=True,
                  freeze_complete=value['status']=='frozen' and not pending,
                  milestone_accepted=False, unresolved=pending,
                  preset_sha256=hashlib.sha256(args.preset.read_bytes()).hexdigest(),
                  source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                  working_tree_dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True)),
                  development_host=dict(system=platform.system(),release=platform.release(),
                                        machine=platform.machine(),python=platform.python_version(),packages=packages),
                  scope='Preset validation only. No inference, physics, rendering, match or hardware acceptance.')
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
    return 2 if args.require_frozen and not report['freeze_complete'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
