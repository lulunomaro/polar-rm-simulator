"""Explicit new .pth configuration after byte-identical migration; no ROS nodes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.migrate_humble_runtime_ext4 import digest,remap_path


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--migration',type=Path,required=True)
    p.add_argument('--original-environment',type=Path,required=True);args=p.parse_args(argv)
    root=args.migration;result_path=root/'FINALIZATION_RESULT.json'
    if result_path.exists():raise ValueError('fresh_finalization_result_required')
    original_refs=[root/'MIGRATION_RESULT.json',root/'ENVIRONMENT_COMPAT.json',root/'DERIVED_PTH.json',args.original_environment]
    before={str(f):digest(f) for f in original_refs}
    migration=json.loads(original_refs[0].read_bytes());old_env=json.loads(original_refs[1].read_bytes())
    if migration['status']!='copied_and_verified' or not migration['source_environment_unchanged']:
        raise ValueError('complete_verified_migration_required')
    original=json.loads(args.original_environment.read_bytes())
    if before[str(args.original_environment)]!=migration['source_environment_sha256']:raise ValueError('original_environment_changed')
    mappings=[(Path(r['source']),Path(r['destination'])) for r in migration['mappings']]
    initial=json.loads(original_refs[2].read_bytes());pth=Path(initial['destination'])
    if digest(pth)!=initial['destination_sha256']:raise ValueError('unexpected_pth_before_finalization')
    paths=[remap_path(line,mappings) for line in pth.read_text().splitlines()]
    paths += [remap_path(part,mappings) for part in original['process_environment'].get('PYTHONPATH','').split(':') if part]
    paths=list(dict.fromkeys(paths))
    if any(not s.startswith('/') or '\n' in s or ';' in s for s in paths):raise ValueError('trusted_absolute_pth_paths_only')
    raw=('\n'.join(paths)+'\n').encode();pth.write_bytes(raw)
    derived=dict(schema='polar.humble-ext4-pth-final.v1',path=str(pth),before_sha256=initial['destination_sha256'],
        after_sha256=hashlib.sha256(raw).hexdigest(),trusted_paths=paths,
        source_environment_sha256=before[str(args.original_environment)],no_free_callback=True)
    (root/'DERIVED_PTH_FINAL.json').write_text(json.dumps(derived,indent=2))
    final_env=dict(old_env,derived_pth_sha256=derived['after_sha256'],
        finalizer_source_sha256=digest(__file__),original_migration_environment_sha256=before[str(original_refs[1])])
    (root/'ENVIRONMENT_COMPAT_FINAL.json').write_text(json.dumps(final_env,indent=2))
    checks={'original_evidence_unchanged':all(digest(f)==before[str(f)] for f in original_refs),
        'PYTHONPATH_not_required':'PYTHONPATH' not in final_env['process_environment']}
    record=dict(schema='polar.humble-ext4-finalization.v1',clean=all(checks.values()),checks=checks,
        original_evidence_sha256=before,final_environment_sha256=digest(root/'ENVIRONMENT_COMPAT_FINAL.json'),
        venv_python=final_env['venv_python'],asset_path_mappings=migration['mappings'],
        pth=derived,navigation_nodes_started=False,physics_steps=0,source_sha256=digest(__file__))
    result_path.write_text(json.dumps(record,indent=2));print(json.dumps(record),flush=True)


if __name__=='__main__':main()
