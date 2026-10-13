import hashlib,json,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
AUDIT=REPO/'artifacts/polarbear-navigation-source-e05eb08e'
SPECS=[('pb2025_sentry_nav','cb97fb07ace54fcc617ddb884227ef85fe4b8f85',('terrain_analysis/','terrain_analysis_ext/')),
 ('pointcloud_to_laserscan_2025','5efaa8ba391bf4450a02cc5bb794b586c9f7d267',('',))]
rows={}
out=HERE/'src'
if out.exists():raise RuntimeError('source_target_not_fresh')
contents={}
for folder,head,prefixes in SPECS:
 repo=AUDIT/folder
 def git(*argv):return subprocess.check_output(['git',*argv],cwd=repo)
 if git('rev-parse','HEAD').decode().strip()!=head or git('status','--porcelain=v1'):raise RuntimeError('source_identity_or_dirty')
 for name in git('ls-tree','-r','--name-only','HEAD').decode().splitlines():
  if not name.startswith(prefixes):continue
  raw=git('show','HEAD:'+name)
  working=repo/name
  if working.is_file():
   actual=working.read_bytes()
   if actual!=raw and actual.replace(b'\r\n',b'\n')!=raw:raise RuntimeError('source_working_changed')
  target=name if folder=='pb2025_sentry_nav' else 'pointcloud_to_laserscan/'+name
  contents[target]=raw;rows[target]=dict(upstream=folder,commit=head,git_path=name,sha256=hashlib.sha256(raw).hexdigest(),modified=False)
out.mkdir(parents=True)
for name,raw in contents.items():
 path=out/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
manifest=dict(schema='polar.pb2025.terrain-scan-source.v1',files=rows,upstream=[dict(repository=f,commit=h) for f,h,_ in SPECS],algorithm_modified=False,build_executed=False,prepare_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
(HERE/'SOURCE_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'source_files':len(rows),'source_dir':str(out.resolve())}))
