"""Fresh Linux Point-LIO build; byte-proven unchanged TF packages are reused."""
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
WORK = Path('/root/polar-navigation-humble-e05eb08e/lio_tf_build_20261014_05')
OLD = REPO / 'artifacts/pb2025-lio-tf-source-20261013-02'
OLD_WORK = Path('/root/polar-navigation-humble-e05eb08e/lio_tf_build_20261013_02')
ENV_FILE = REPO / 'artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json'
ENV_SHA = 'd60183ebf62d520c72eb20b84207fa4344d8f17183bb0df8eee92f97b7f981ee'
REUSED = ('loam_interface', 'sensor_scan_generation')

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def save(name, value): (HERE/name).write_text(json.dumps(value, indent=2)+'\n', encoding='utf8')
def source_check(manifest, directory, prefixes=None):
    return all(sha(directory/name)==row['sha256'] for name,row in manifest['files'].items()
               if prefixes is None or name.startswith(prefixes))

def main():
    if os.name != 'posix': raise RuntimeError('Linux-only actual build')
    if (HERE/'BUILD_COMMAND.json').exists(): raise RuntimeError('fresh execution record required')
    argv=['/usr/bin/colcon','build','--executor','sequential','--packages-select','point_lio',
          '--cmake-args','-DBUILD_TESTING=OFF','-DCMAKE_BUILD_TYPE=Release','-DPython3_EXECUTABLE=/root/polar-humble-ext4-20261014-01/venv/bin/python','-DPYTHON_EXECUTABLE=/root/polar-humble-ext4-20261014-01/venv/bin/python']
    record=dict(schema='polar.pb2025.lio-bounded-join-build.v1',workspace=str(WORK),command=argv,
                build_script_sha256=sha(Path(__file__)),full_ros_build=True,nodes_started=False,
                copied_build_cache=False,source_manifest_sha256=sha(HERE/'OVERLAY_MANIFEST.json'))
    save('BUILD_COMMAND.json',record)
    started=time.perf_counter(); process=None; result=None; old_rows=[]; env=None
    try:
        manifest=json.loads((HERE/'OVERLAY_MANIFEST.json').read_text())
        old_manifest=json.loads((OLD/'OVERLAY_MANIFEST.json').read_text())
        if not source_check(manifest,HERE): raise RuntimeError('owned_source_changed')
        if not source_check(old_manifest,OLD): raise RuntimeError('original_02_source_changed')
        if sha(ENV_FILE)!=ENV_SHA: raise RuntimeError('frozen_build_environment_changed')
        prefixes=tuple(pkg+'/' for pkg in REUSED)
        proof={name:row for name,row in manifest['files'].items() if name.startswith(prefixes)}
        if any(old_manifest['files'].get(name,{}).get('sha256')!=row['sha256'] for name,row in proof.items()):
            raise RuntimeError('TF_package_sources_changed_reuse_rejected')
        if not source_check(old_manifest,OLD_WORK/'src',prefixes): raise RuntimeError('built_02_TF_sources_changed')
        old_audit=json.loads((OLD/'BINARY_AUDIT.json').read_text())
        old_rows=[r for r in old_audit['rows'] if any('/install/'+pkg+'/' in r['path'] for pkg in REUSED)]
        if len(old_rows)!=4 or any(sha(Path(r['path']))!=r['sha256'] for r in old_rows):
            raise RuntimeError('original_02_TF_ELF_changed')
        save('REUSED_TF_SOURCE_PROOF.json',dict(schema='polar.pb2025.unchanged-TF-reuse.v1',
             original_manifest_sha256=sha(OLD/'OVERLAY_MANIFEST.json'),
             original_binary_audit_sha256=sha(OLD/'BINARY_AUDIT.json'),files=proof,
             original_built_source_bytes_verified=True,
             binaries=[dict(path=r['path'],sha256=r['sha256']) for r in old_rows],
             reason='Only Point-LIO ingress/context code changed; TF sources are byte-identical.'))
        if WORK.exists(): raise RuntimeError('owned_workspace_must_be_fresh')
        (WORK/'src').mkdir(parents=True)
        shutil.copytree(HERE/'point_lio',WORK/'src/point_lio')
        if not source_check(manifest,WORK/'src',('point_lio/',)): raise RuntimeError('fresh_copy_changed')
        env=os.environ.copy();env.update(json.loads(ENV_FILE.read_text())['process_environment'])
        # New build-only glog wrapper. Original signed exports, old compatibility
        # wrapper, migrated byte-identical runtime, and FINAL remain unchanged.
        old_prefix=REPO/'artifacts/pb2025-humble-environment-20261013/prefix'
        copied_prefix=Path('/root/polar-humble-ext4-20261014-01/prefix')
        original_wrapper=REPO/'artifacts/pb2025-humble-environment-20261013/compat/lib/cmake/glog/glog-config.cmake'
        version_file=original_wrapper.with_name('glog-config-version.cmake')
        if sha(original_wrapper)!='78564618c9a3167d4eef50c71eb7d5eea1f8b2e727f58e4f430efb457b41603d' or sha(version_file)!='1829cde666f2ce1fa503625366a28a2c094224443f8205f2dc8b47afbc99e333':
            raise RuntimeError('original_glog_compat_changed')
        guarded={
          'usr/lib/x86_64-linux-gnu/cmake/glog/glog-targets.cmake':'a5d8a5a76e89fdbaa32ab2a3221e7890db11a284fe0cc8734206c0df45e975d2',
          'usr/lib/x86_64-linux-gnu/cmake/glog/glog-config.cmake':'27a2331587d0b3fea8d52f74114d37ce940a0b7432d0b4ecaacb408d37e8eb0b',
          'usr/lib/x86_64-linux-gnu/libunwind.so':'5d1f6f104f79698e137c9f17c4b0317dfd96816c0eb6a87c50619a41472ca382'}
        for name,expected in guarded.items():
            if sha(old_prefix/name)!=expected or sha(copied_prefix/name)!=expected:raise RuntimeError('glog_ext4_original_asset_mismatch')
        wrapper=original_wrapper.read_text()
        if wrapper.count(str(old_prefix))!=5:raise RuntimeError('glog_compat_path_anchors_changed')
        derived=wrapper.replace(str(old_prefix),str(copied_prefix))
        compat=WORK/'build_compat';cfg=compat/'lib/cmake/glog';cfg.mkdir(parents=True)
        (cfg/'glog-config.cmake').write_text(derived)
        shutil.copyfile(version_file,cfg/'glog-config-version.cmake')
        env['CMAKE_PREFIX_PATH']=str(compat)+':'+env['CMAKE_PREFIX_PATH']
        save('DERIVED_BUILD_COMPAT.json',dict(schema='polar.pb2025.ext4-build-compat.v1',
             original_wrapper_sha256=sha(original_wrapper),derived_wrapper_path=str(cfg/'glog-config.cmake'),
             derived_wrapper_sha256=sha(cfg/'glog-config.cmake'),version_sha256=sha(version_file),
             original_prefix=str(old_prefix),copied_prefix=str(copied_prefix),
             exact_replacement_count=5,byte_identical_guarded_assets=guarded,
             original_environment_manifest_sha256=ENV_SHA,original_runtime_copy_modified=False))
        env.update(CMAKE_BUILD_PARALLEL_LEVEL='1',MAKEFLAGS='-j1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
        record.update(environment={k:env[k] for k in ('CMAKE_PREFIX_PATH','AMENT_PREFIX_PATH','LD_LIBRARY_PATH',
                      'PYTHONPATH','PKG_CONFIG_PATH','CMAKE_BUILD_PARALLEL_LEVEL','MAKEFLAGS','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS')},
                      environment_manifest_sha256=ENV_SHA,
                      reused_install_prefixes=[str(OLD_WORK/'install'/pkg) for pkg in REUSED])
        save('BUILD_COMMAND.json',record)
        with (HERE/'colcon.log').open('w') as log:
            process=subprocess.Popen(argv,cwd=WORK,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            save('BUILD_PID.json',dict(pid=process.pid,pgid=process.pid,command=argv,compiler_parallelism=1))
            result=process.wait(timeout=2700)
        if result: raise RuntimeError('actual_colcon_failed')
        paths=[WORK/'install/point_lio/lib/point_lio/pointlio_mapping']+[Path(r['path']) for r in old_rows]
        audit_env=env.copy();audit_env['LD_LIBRARY_PATH']=':'.join(
            [str(WORK/'install/point_lio/lib')]+[str(OLD_WORK/'install'/p/'lib') for p in REUSED]+[env['LD_LIBRARY_PATH']])
        rows=[]
        for path in paths:
            raw=path.read_bytes()
            if raw[:4]!=b'\x7fELF': raise RuntimeError('expected_actual_ELF_missing')
            ldd=subprocess.run(['/usr/bin/ldd',str(path)],env=audit_env,capture_output=True,text=True,timeout=15)
            rows.append(dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),ldd_returncode=ldd.returncode,
                             stdout=ldd.stdout,stderr=ldd.stderr,all_resolved=ldd.returncode==0 and 'not found' not in ldd.stdout))
        audit=dict(schema='polar.pb2025.lio-binary-audit.v1',nodes_started=False,rows=rows,
                   ld_library_path=audit_env['LD_LIBRARY_PATH'],passed=all(r['all_resolved'] for r in rows))
        save('BINARY_AUDIT.json',audit)
        if not audit['passed']: raise RuntimeError('actual_ELF_dependencies_unresolved')
    except BaseException as error:
        record['error']=type(error).__name__+':'+str(error)
        raise
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try: process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=2)
        record.update(returncode=result,wall_s=time.perf_counter()-started,
                      source_unchanged=source_check(manifest,HERE) if 'manifest' in locals() else False,
                      original_02_source_unchanged=source_check(old_manifest,OLD) if 'old_manifest' in locals() else False,
                      original_02_TF_ELF_unchanged=all(sha(Path(r['path']))==r['sha256'] for r in old_rows),
                      compiler_driver_reaped=process is None or process.poll() is not None,
                      colcon_log_sha256=sha(HERE/'colcon.log') if (HERE/'colcon.log').exists() else None)
        record['passed']=result==0 and not record.get('error') and record['source_unchanged'] and record['original_02_source_unchanged'] and record['original_02_TF_ELF_unchanged']
        save('BUILD_RESULT.json',record)
        print(json.dumps(record),flush=True)

if __name__=='__main__': main()
