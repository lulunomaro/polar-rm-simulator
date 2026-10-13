"""Post-build source, original-asset, process-group and ingress ELF audit."""
import hashlib
import json
import subprocess
from pathlib import Path

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
WORK=Path('/root/polar-navigation-humble-e05eb08e/lio_tf_build_20261014_04')
OLD=REPO/'artifacts/pb2025-lio-tf-source-20261013-02'
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    if (HERE/'POST_BUILD_AUDIT.json').exists():raise RuntimeError('audit output must be fresh')
    result=json.loads((HERE/'BUILD_RESULT.json').read_text())
    manifest=json.loads((HERE/'OVERLAY_MANIFEST.json').read_text())
    old_manifest=json.loads((OLD/'OVERLAY_MANIFEST.json').read_text())
    old_binary=json.loads((OLD/'BINARY_AUDIT.json').read_text())
    source_rows=[]
    for name,row in manifest['files'].items():
        if name.startswith('point_lio/'):
            actual=sha(WORK/'src'/name)
            source_rows.append(dict(path=str(WORK/'src'/name),expected_sha256=row['sha256'],actual_sha256=actual,unchanged=actual==row['sha256']))
    old_source_rows=[]
    for name,row in old_manifest['files'].items():
        actual=sha(OLD/name)
        old_source_rows.append(dict(path=str(OLD/name),expected_sha256=row['sha256'],actual_sha256=actual,unchanged=actual==row['sha256']))
    old_rows=[dict(path=row['path'],expected_sha256=row['sha256'],actual_sha256=sha(Path(row['path']))) for row in old_binary['rows']]
    for row in old_rows:row['unchanged']=row['expected_sha256']==row['actual_sha256']
    pgid=json.loads((HERE/'BUILD_PID.json').read_text())['pgid']
    ps=subprocess.run(['/usr/bin/ps','-eo','pid=,pgid=,args='],capture_output=True,text=True,check=True)
    members=[]
    for line in ps.stdout.splitlines():
        parts=line.strip().split(maxsplit=2)
        if len(parts)>=2 and int(parts[1])==pgid:members.append(line.strip())
    binary=WORK/'install/point_lio/lib/point_lio/pointlio_mapping'; raw=binary.read_bytes()
    markers={name:name.encode() in raw for name in ('pb_join_original_sim_window_expired','pb_request_join_overflow','pb_raw_join_overflow','pb_source_identity_order_conflict')}
    audit=dict(schema='polar.pb2025.lio-post-build-audit.v1',nodes_started=False,
               build_result_sha256=sha(HERE/'BUILD_RESULT.json'),built_source_rows=source_rows,
               original_02_source_rows=old_source_rows,original_02_binary_rows=old_rows,
               original_build_process_group=pgid,remaining_build_members=members,
               new_binary_path=str(binary),new_binary_sha256=sha(binary),new_ingress_ELF_markers=markers,
               source_unchanged=all(r['unchanged'] for r in source_rows),
               original_02_source_unchanged=all(r['unchanged'] for r in old_source_rows),
               original_02_binaries_unchanged=all(r['unchanged'] for r in old_rows),
               compiler_group_reaped=not members)
    audit['passed']=result['passed'] and all((audit['source_unchanged'],audit['original_02_source_unchanged'],
                       audit['original_02_binaries_unchanged'],audit['compiler_group_reaped'],all(markers.values())))
    (HERE/'POST_BUILD_AUDIT.json').write_text(json.dumps(audit,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in audit.items() if not k.endswith('_rows')}))
    if not audit['passed']:raise SystemExit(1)
if __name__=='__main__':main()
