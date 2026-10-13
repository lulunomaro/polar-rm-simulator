"""Post-build source, original-asset, process-group and ingress ELF audit."""
import hashlib
import json
import subprocess
from pathlib import Path

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
WORK=Path('/root/polar-navigation-humble-e05eb08e/lio_tf_build_20261014_05_02')
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
    markers={name:name.encode() in raw for name in ('pb_join_original_sim_window_expired','pb_request_join_overflow','pb_raw_join_overflow','pb_source_identity_order_conflict','polar.pb.dispatch.v1','linux_steady_diagnostic_only','pb.dispatch_diagnostics')}
    audit=dict(schema='polar.pb2025.lio-post-build-audit.v1',nodes_started=False,
               build_result_sha256=sha(HERE/'BUILD_RESULT.json'),built_source_rows=source_rows,
               original_02_source_rows=old_source_rows,original_02_binary_rows=old_rows,
               original_build_process_group=pgid,remaining_build_members=members,
               new_binary_path=str(binary),new_binary_sha256=sha(binary),new_ingress_ELF_markers=markers,
               source_unchanged=all(r['unchanged'] for r in source_rows),
               original_02_source_unchanged=all(r['unchanged'] for r in old_source_rows),
               original_02_binaries_unchanged=all(r['unchanged'] for r in old_rows),
               compiler_group_reaped=not members)
    previous=HERE.parent/'pb2025-lio-tf-source-20261014-04'
    previous_manifest=json.loads((previous/'OVERLAY_MANIFEST.json').read_text())
    unchanged_rows=[]
    for name,row in manifest['files'].items():
        if name.startswith('point_lio/') and name!='point_lio/src/laserMapping.cpp':
            expected=previous_manifest['files'][name]['sha256']
            unchanged_rows.append(dict(path=name,previous_sha256=expected,current_sha256=row['sha256'],unchanged=expected==row['sha256']))
    old04_audit=json.loads((previous/'BINARY_AUDIT.json').read_text())
    old04_rows=[dict(path=r['path'],expected_sha256=r['sha256'],actual_sha256=sha(Path(r['path']))) for r in old04_audit['rows']]
    for r in old04_rows:r['unchanged']=r['expected_sha256']==r['actual_sha256']
    flags=WORK/'build/point_lio/CMakeFiles/pointlio_mapping.dir/flags.make'
    audit.update(unchanged_04_pointlio_file_rows=unchanged_rows,original_04_binary_rows=old04_rows,
                 original_04_binary_unchanged=all(r['unchanged'] for r in old04_rows),
                 only_main_source_changed=all(r['unchanged'] for r in unchanged_rows),
                 actual_compile_flags_sha256=sha(flags),actual_compile_flags=flags.read_text(),
                 actual_dependencies_sha256=sha(WORK/'build/point_lio/CMakeFiles/pointlio_mapping.dir/compiler_depend.make'),
                 original_ext4_FINAL_sha256=sha(REPO/'artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json'),
                 original_ext4_FINAL_unchanged=sha(REPO/'artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json')=='d60183ebf62d520c72eb20b84207fa4344d8f17183bb0df8eee92f97b7f981ee',
                 original_04_source_unchanged=all(sha(previous/name)==row['sha256'] for name,row in previous_manifest['files'].items()),
                 derived_build_compat_sha256=sha(HERE/'DERIVED_BUILD_COMPAT.json'))
    audit['passed']=result['passed'] and audit['original_04_binary_unchanged'] and audit['only_main_source_changed'] and audit['original_ext4_FINAL_unchanged'] and audit['original_04_source_unchanged'] and all((audit['source_unchanged'],audit['original_02_source_unchanged'],
                       audit['original_02_binaries_unchanged'],audit['compiler_group_reaped'],all(markers.values())))
    (HERE/'POST_BUILD_AUDIT.json').write_text(json.dumps(audit,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in audit.items() if not k.endswith('_rows')}))
    if not audit['passed']:raise SystemExit(1)
if __name__=='__main__':main()
