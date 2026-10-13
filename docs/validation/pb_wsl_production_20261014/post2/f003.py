"""Record documentation clarification after checks; executable source stays frozen."""
import argparse,hashlib,json,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
quality=json.loads((root/'artifacts/quality-20261014-wsl-production-frozen-02/manifest.json').read_bytes())
p=argparse.ArgumentParser();p.add_argument('--revision',type=int,default=1);args=p.parse_args()
out=root/('artifacts/pb-postcheck-documentation-20261014' if args.revision==1 else
 f'artifacts/pb-postcheck-documentation-20261014-{args.revision:02}');out.mkdir();rows=[]
for name in ('docs/ROBOT_IO_V1.md','docs/ACCEPTANCE_TRACEABILITY.md'):
 before=subprocess.check_output(['git','show','HEAD:'+name],cwd=root)
 assert hashlib.sha256(before).hexdigest()==quality['source_files_sha256'][name]
 after=(root/name).read_bytes()
 for label,data in (('before',before),('after',after)):(out/(Path(name).stem+'.'+label+'.md')).write_bytes(data)
 rows.append(dict(path=name,checked_before_sha256=hashlib.sha256(before).hexdigest(),
  current_sha256=hashlib.sha256(after).hexdigest()))
changed=[]
for name,expected in quality['source_files_sha256'].items():
 if (root/name).is_file() and hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:changed.append(name)
assert sorted(changed)==sorted(row['path'] for row in rows),changed
report=dict(scope='Two documentation clarifications after quality; default/opt-in sensors and offline/live evidence separated',
 source_changed_during_checks=False,postcheck_changed_files=rows,all_other_checked_files_unchanged=True)
(out/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8');print(json.dumps(report))
