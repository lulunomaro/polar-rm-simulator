"""Derive a fresh build driver from frozen 04; never modify original assets."""
import hashlib
from pathlib import Path
HERE=Path(__file__).resolve().parent;OLD=HERE.parent/'pb2025-lio-tf-source-20261014-04'
raw=(OLD/'build_owned.py').read_bytes()
if hashlib.sha256(raw).hexdigest()!='511eabf87690cbe71b1506771df5db5efcd3599f0dca729665761745fa7e5d23':raise RuntimeError('04 builder changed')
out=HERE/'build_owned.py'
if out.exists():raise RuntimeError('fresh derived driver required')
text=raw.decode().replace('lio_tf_build_20261014_04','lio_tf_build_20261014_05')
text=text.replace("artifacts/pb2025-humble-environment-20261013/ENVIRONMENT_COMPAT.json", "artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json")
text=text.replace('0cd98634002c5456b5b0f77789b700c1c8941d9051fe9ac8a3cebae82da9ec49','d60183ebf62d520c72eb20b84207fa4344d8f17183bb0df8eee92f97b7f981ee')
text=text.replace("'-DCMAKE_BUILD_TYPE=Release']", "'-DCMAKE_BUILD_TYPE=Release','-DPython3_EXECUTABLE=/root/polar-humble-ext4-20261014-01/venv/bin/python','-DPYTHON_EXECUTABLE=/root/polar-humble-ext4-20261014-01/venv/bin/python']")
anchor="        env=os.environ.copy();env.update(json.loads(ENV_FILE.read_text())['process_environment'])"
replacement=anchor+'''
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
             original_environment_manifest_sha256=ENV_SHA,original_runtime_copy_modified=False))'''
if text.count(anchor)!=1:raise RuntimeError('driver environment anchor changed')
text=text.replace(anchor,replacement)
out.write_text(text,encoding='utf8')
print(hashlib.sha256(out.read_bytes()).hexdigest())
