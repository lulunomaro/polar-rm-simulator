"""Prepare fresh post-build audit/config tools from immutable 04 tools."""
from pathlib import Path
HERE=Path(__file__).resolve().parent;OLD=HERE.parent/'pb2025-lio-tf-source-20261014-04'
for name in ('audit_build.py','generate_config.py'):
    out=HERE/name
    if out.exists():raise RuntimeError('fresh derived post-audit helper required')
    text=(OLD/name).read_text().replace('lio_tf_build_20261014_04','lio_tf_build_20261014_05_02')
    if name=='audit_build.py':
        text=text.replace("'pb_source_identity_order_conflict')", "'pb_source_identity_order_conflict','polar.pb.dispatch.v1','linux_steady_diagnostic_only','pb.dispatch_diagnostics')")
        anchor="    audit['passed']=result['passed']"
        extra='''    previous=HERE.parent/'pb2025-lio-tf-source-20261014-04'
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
'''
        if text.count(anchor)!=1:raise RuntimeError('04 post-audit anchor changed')
        text=text.replace(anchor,extra+anchor)
        text=text.replace("result['passed'] and all(","result['passed'] and audit['original_04_binary_unchanged'] and audit['only_main_source_changed'] and audit['original_ext4_FINAL_unchanged'] and audit['original_04_source_unchanged'] and all(")
    out.write_text(text,encoding='utf8')
