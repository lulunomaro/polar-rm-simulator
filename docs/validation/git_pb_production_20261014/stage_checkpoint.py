"""Stage only this authorized checkpoint and verify literal Git index bytes."""
import hashlib,json,subprocess,sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'.git').exists())
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)
def sha(raw):return hashlib.sha256(raw).hexdigest()
assert git('branch','--show-current').decode().strip()=='work/plan-t01-t03'
quality=json.loads((ROOT/'artifacts/quality-20261014-wsl-production-frozen-02/manifest.json').read_bytes())
assert quality['status']=='checks_passed_not_milestone_acceptance' and quality['source_unchanged_during_checks'] is True
assert all(row['exit_code']==0 for row in quality['steps']) and quality['milestone_accepted'] is False
post={'.gitattributes','docs/ROBOT_IO_V1.md','docs/ACCEPTANCE_TRACEABILITY.md'}
changed=[]
for name,expected in quality['source_files_sha256'].items():
 raw=(ROOT/name).read_bytes()
 if sha(raw)!=expected:changed.append(dict(path=name,checked_sha256=expected,current_sha256=sha(raw)))
assert {row['path'] for row in changed}==post,changed
proof=ROOT/'docs/validation/git_pb_production_20261014';proof.mkdir()
(proof/'stage_checkpoint.py').write_bytes(Path(__file__).read_bytes())
(proof/'README.md').write_bytes(('Git index audit of the authorized work/plan-t01-t03 checkpoint.\n\n'
 'The frozen quality checks passed; only two documentation clarifications and Git TSV byte-preservation attributes changed afterward. '
 'All checked executable/config/model files still match the quality SHA map. '
 'The two docs have exact before/after records in the production archive. '
 'The new TSV attribute prevents CRLF normalization of the frozen index; no evidence bytes were rewritten.\n\n'
 'stage_checkpoint.py records the payload index before its own report is added. The final artifact audit verifies every staged file, including this report.\n').encode())
new=['tests/test_pb_external_goal_session.py','tests/test_pb_external_navigation_goal.py','tests/test_pb_sil_duration.py',
 'tests/test_pb_stack_shutdown_deadline.py','tests/test_platform_http_rejection.py','tools/pb_external_goal_session.py',
 'tools/pb_sil_duration.py','tools/qa_pb_external_goal_supervisor.py','tools/qa_pb_external_navigation_goal.py',
 'tools/qa_pb_wsl_production_sil.py']
base=ROOT/'docs/validation/pb_wsl_production_20261014'
inventory=json.loads((base/'FILES.json').read_bytes());evidence=[]
for row in inventory['files']:
 p=base/row['path'];assert p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(base.resolve())
 raw=p.read_bytes();assert len(raw)==row['bytes'] and sha(raw)==row['sha256']
 assert not raw.startswith(b'\x7fELF') and len(raw)<10*1024*1024
 evidence.append(p.relative_to(ROOT).as_posix())
evidence.append((base/'FILES.json').relative_to(ROOT).as_posix())
git('add','-u');git('add','--',*new)
selected=evidence+[p.relative_to(ROOT).as_posix() for p in proof.iterdir()]
for offset in range(0,len(selected),200):git('add','-f','--',*selected[offset:offset+200])
def index_rows():
 names=[n for n in git('diff','--cached','--name-only','-z').decode().split('\0') if n]
 data=subprocess.check_output(['git','cat-file','--batch'],cwd=ROOT,input=''.join(':'+n+'\n' for n in names).encode())
 offset=0;rows=[]
 for name in names:
  end=data.index(b'\n',offset);fields=data[offset:end].split();offset=end+1
  assert len(fields)==3 and fields[1]==b'blob';size=int(fields[2]);raw=data[offset:offset+size];offset+=size+1
  assert raw==(ROOT/name).read_bytes(),'Git changed literal bytes: '+name
  rows.append(dict(path=name,bytes=size,sha256=sha(raw)))
 assert offset==len(data)
 return rows
payload=index_rows()
report=dict(schema='polar.pb.production-git-index-audit.v1',all_index_bytes_exact=True,
 files=payload,postcheck_nonruntime_changes=changed,all_other_checked_files_unchanged=True,
 quality_scope='local checks passed; no M0-M5 acceptance',archive_payload_files=len(evidence))
(proof/'PAYLOAD_INDEX_AUDIT.json').write_bytes((json.dumps(report,indent=2)+'\n').encode())
git('add','-f','--',str((proof/'PAYLOAD_INDEX_AUDIT.json').relative_to(ROOT)))
final=index_rows();git('-c','core.whitespace=trailing-space,space-before-tab,cr-at-eol','diff','--cached','--check')
(ROOT/'artifacts/pb-production-final-index-20261014.json').write_bytes((json.dumps(dict(all_index_bytes_exact=True,
 count=len(final),files=final),indent=2)+'\n').encode())
print(json.dumps(dict(staged_files=len(final),archive_files=len(evidence),all_index_bytes_exact=True,
 total_staged_bytes=sum(row['bytes'] for row in final))))
