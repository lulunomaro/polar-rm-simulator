"""Windows path/byte races with synthetic never-executed ELF/model fixtures."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from rm_match.deployment import profile,wsl_profile as wsl

ROOT=Path(__file__).resolve().parents[1]
def sha(value):return hashlib.sha256(value).hexdigest()
def write_json(path,value):path.write_text(json.dumps(value),encoding='utf-8')


@contextmanager
def fixture():
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);repo=root/'repo';repo.mkdir();out=root/'shared';out.mkdir()
        runtime=repo/'operator_native/runtime';runtime.mkdir(parents=True)
        builddir=repo/'artifacts/build';builddir.mkdir(parents=True)
        for rel in ('build_portable.py','CMakeLists.txt','simulation_profile.json','candidate/tracker.cpp'):
            selected=runtime/rel;selected.parent.mkdir(parents=True,exist_ok=True);selected.write_bytes(('fixture '+rel).encode())
        overlay=runtime/'overlays/corners_contour_v3.cpp';overlay.parent.mkdir()
        overlay.write_bytes((ROOT/'operator_native/runtime/overlays/corners_contour_v3.cpp').read_bytes())
        for rel in ('rm_match/deployment/wsl_profile.py',wsl.SUPERVISOR,wsl.WORKER,
                    'rm_match/integrations/owned_linux_group.py'):
            selected=repo/rel;selected.parent.mkdir(parents=True,exist_ok=True)
            selected.write_bytes((ROOT/rel).read_bytes() if (ROOT/rel).exists() else b'# synthetic transport never launched\n')
        source=dict(base_commit=profile.T2_BASE,tracker_patch_sha256=profile.T2_PATCH,
            patch_identity_format='rmcs-own-source-composition.v1',is_original_upstream=False,is_baseline_40f7=False,
            vision_frontend=dict(id='image_contour_corners_v3',source_path='overlays/corners_contour_v3.cpp',source_sha256=profile.digest(overlay)))
        composition=dict(schema='rmcs-own-source-composition.v1',tracker_patch_sha256=profile.T2_PATCH,
            vision_frontend_sha256=profile.digest(overlay))
        source['patch_sha256']=sha(json.dumps(composition,sort_keys=True,separators=(',',':')).encode())
        base_source=deepcopy(source)
        for key in ('vision_frontend','tracker_patch_sha256','patch_identity_format'):base_source.pop(key,None)
        base_source['patch_sha256']=profile.T2_PATCH
        recovery=dict(algorithm_identity=base_source,files=[dict(path='candidate/tracker.cpp',sha256=profile.digest(runtime/'candidate/tracker.cpp'))])
        write_json(runtime/'RECOVERY_MANIFEST.json',recovery)
        generated=builddir/'generated/corners_contour_v1.cpp';generated.parent.mkdir();generated.write_bytes(overlay.read_bytes())
        main=builddir/'generated/main.cpp';main.write_bytes(b'synthetic never executed operator main')
        hook=builddir/'generated/prepare_fov_hook.py';hook.write_bytes(b'synthetic never executed preparation hook')
        (builddir/'tracking_mode').write_bytes(b'multi_ekf\n')
        binary=builddir/'binary'
        ident=b'\x7fELF\x02\x01\x01'+bytes(9)
        header=struct.pack('<16sHHIQQQIHHHHHH',ident,3,62,1,4096,64,0,0,64,56,1,0,0,0)
        binary.write_bytes(header+bytes(56))
        configs=builddir/'config';configs.write_bytes(b'{}')
        model=repo/'models/shenzhen-0526.onnx';model.parent.mkdir();model.write_bytes(b'synthetic model never executed')
        elf={'class':'ELF64','endianness':'little','machine':'EM_X86_64','elf_type':3,'program_headers':1}
        inputs=dict(algorithm_identity=source,corner_refinement='contour-v3',
            additional_source_files={'overlays/corners_contour_v3.cpp':profile.digest(overlay)},
            generated_sha256={'generated/corners_contour_v1.cpp':profile.digest(generated),'generated/main.cpp':profile.digest(main),'generated/prepare_fov_hook.py':profile.digest(hook)},
            operator_hook_sha256=profile.digest(hook),model_sha256=profile.digest(model),
            recovery_manifest_sha256=profile.digest(runtime/'RECOVERY_MANIFEST.json'),
            source_files={r['path']:r['sha256'] for r in recovery['files']},
            portable_entry_sha256=profile.digest(runtime/'build_portable.py'),
            cmake_project_sha256=profile.digest(runtime/'CMakeLists.txt'),profile_sha256=profile.digest(runtime/'simulation_profile.json'))
        build=dict(status='native_build_succeeded',full_clean_compile=True,binary_sha256=profile.digest(binary),elf=elf,input_identity=inputs)
        write_json(builddir/'BUILD_MANIFEST.json',build)
        def linux(path):return '/mnt/c/'+Path(path).as_posix()[3:]
        mode=sha(b'multi_ekf\n')
        spec=dict(operator_identity='rmcs-sim-operator-fov-v1',binary=linux(binary),executor_yaml=linux(configs),
            autoaim_config=linux(configs),model_share=linux(model.parent),model_sha256=profile.digest(model),
            source_identity=source,runtime_mode_contents='multi_ekf\n',runtime_mode_sha256=mode,
            environment={'OMP_NUM_THREADS':'1'},sha256=dict(binary=profile.digest(binary),executor_yaml=profile.digest(configs),autoaim_config=profile.digest(configs),runtime_mode=mode),
            frozen_build=dict(binary_sha256=profile.digest(binary),manifest_sha256=profile.digest(builddir/'BUILD_MANIFEST.json'),elf=elf))
        selected=builddir/'operator_source.local.json';write_json(selected,spec)
        with patch.object(profile,'RUNTIME_ROOT',runtime),patch.object(profile,'MODEL_SHA256',profile.digest(model)), \
             patch.object(wsl,'OPERATOR_MAIN_SHA256',profile.digest(main)),patch.object(wsl,'OPERATOR_HOOK_SHA256',profile.digest(hook)):
            yield dict(root=root,repo=repo,out=out,runtime=runtime,builddir=builddir,spec_path=selected,spec=spec,build=build,linux=linux)


@unittest.skipUnless(os.name=='nt','Explicit Windows C: host path profile')
class WslProfileTests(unittest.TestCase):
    def check(self,f,**kw):return wsl.validate_wsl_spec(f['spec_path'],repo_root=f['repo'],shared_out=f['out'],**kw)

    def test_diagnostic_metadata_cannot_enter_default_wsl_registry(self):
        with fixture() as f:
            f['spec']['performance_profile']=None
            write_json(f['spec_path'],f['spec'])
            with self.assertRaisesRegex(ValueError,'explicit_offline_entry'):self.check(f)
        with fixture() as f:
            f['build']['input_identity']['performance_profile']=None
            write_json(f['builddir']/'BUILD_MANIFEST.json',f['build'])
            f['spec']['frozen_build']['manifest_sha256']=profile.digest(f['builddir']/'BUILD_MANIFEST.json')
            write_json(f['spec_path'],f['spec'])
            with self.assertRaisesRegex(ValueError,'not_default_deployment'):self.check(f)

    def test_checked_host_spec_keeps_linux_binary_identity_without_launch(self):
        with fixture() as f,patch.object(subprocess,'Popen') as start:
            checked=self.check(f)
            self.assertEqual(checked.linux_spec,f['spec'])
            self.assertEqual(checked.linux_spec_sha256,sha(f['spec_path'].read_bytes()))
            self.assertEqual(Path(checked.host_checked_spec['binary']),f['builddir']/'binary')
            self.assertEqual(checked.host_checked_spec['sha256'],f['spec']['sha256'])
            self.assertEqual(checked.verify_unchanged(),checked.linux_spec_sha256)
            self.assertEqual(checked.metadata['transport'],'wsl_stdio_v1');self.assertFalse(checked.metadata['windows_native'])
            self.assertEqual(set(checked.metadata['transport_source_sha256']),{'rm_match/deployment/wsl_profile.py',wsl.SUPERVISOR,wsl.WORKER,'rm_match/integrations/owned_linux_group.py'})
            start.assert_not_called()

    def test_only_fixed_trusted_ubuntu_and_exact_registered_spec_sha(self):
        with fixture() as f:
            for distribution in ('docker-desktop','Ubuntu; arbitrary','Ubuntu-24.04',None):
                with self.subTest(distribution=distribution),self.assertRaisesRegex(ValueError,'distribution'):self.check(f,distribution=distribution)
            with self.assertRaisesRegex(ValueError,'changed_after_registration'):self.check(f,expected_spec_sha='0'*64)

    def test_paths_reject_traversal_unc_other_drives_and_outside_roots(self):
        with fixture() as f:
            valid=f['linux'](f['builddir']/'binary')
            for value in ('/mnt/d/out','//server/share','C:/binary','/etc/passwd',valid+'/../binary',valid.replace('/binary','//binary'),valid+'/./other',valid+'\\x',valid+'\n'):
                with self.subTest(value=value),self.assertRaises(ValueError):wsl.linux_to_host_path(value,repo_root=f['repo'],shared_out=f['out'])
            outside=f['root']/'outside';outside.write_bytes(b'fixture')
            with self.assertRaisesRegex(ValueError,'outside_explicit_roots'):
                wsl.linux_to_host_path(f['linux'](outside),repo_root=f['repo'],shared_out=f['out'])
            for value in ('\\\\server\\share\\file','D:/file',str(f['repo']/'config:stream')):
                with self.subTest(value=value),self.assertRaises(ValueError):wsl.host_to_linux_path(value,repo_root=f['repo'],shared_out=f['out'])
            self.assertEqual(wsl.host_to_linux_path(f['out']/'future',repo_root=f['repo'],shared_out=f['out']),f['linux'](f['out']/'future'))

    def test_tampered_artifacts_frontend_source_and_transport_fail_after_validation(self):
        with fixture() as f:
            checked=self.check(f)
            paths=[f['builddir']/'binary',f['builddir']/'config',f['repo']/'models/shenzhen-0526.onnx',
                f['builddir']/'tracking_mode',f['builddir']/'generated/corners_contour_v1.cpp',
                f['runtime']/'candidate/tracker.cpp',f['runtime']/'overlays/corners_contour_v3.cpp',
                f['repo']/wsl.SUPERVISOR,f['repo']/wsl.WORKER]
            for path in paths:
                original=path.read_bytes();path.write_bytes(original+b'changed')
                try:
                    with self.subTest(path=path),self.assertRaisesRegex(ValueError,'changed_after_validation'):checked.verify_unchanged()
                finally:path.write_bytes(original)

    def test_spec_swapped_after_snapshot_is_rejected_at_final_guard(self):
        with fixture() as f:
            original=wsl.profile.read_json_snapshot
            def swap(path,*args):
                value,digest=original(path,*args)
                if Path(path)==f['spec_path']:
                    changed=deepcopy(value);changed['source_identity']['base_commit']='FOREIGN'
                    write_json(path,changed)
                return value,digest
            with patch.object(wsl.profile,'read_json_snapshot',side_effect=swap):
                with self.assertRaisesRegex(ValueError,'changed_after_validation'):self.check(f)

    def test_source_changed_after_its_hash_check_is_rejected(self):
        with fixture() as f:
            original=wsl._check_hash;tracker=f['runtime']/'candidate/tracker.cpp'
            def change(path,*args):
                original(path,*args)
                if path==tracker:path.write_bytes(b'changed after identity checked')
            with patch.object(wsl,'_check_hash',side_effect=change):
                with self.assertRaisesRegex(ValueError,'changed_after_validation'):self.check(f)

    def test_mixed_build_frontend_and_untrusted_environment_are_rejected(self):
        with fixture() as f:
            for change in ('front','environment','build','copy','entry','tracker'):
                value=deepcopy(f['spec']);build=deepcopy(f['build'])
                if change=='front':value['source_identity']['vision_frontend']['id']='image_contour_corners_v1'
                if change=='environment':value['environment']['LD_PRELOAD']='/outside/injection.so'
                if change=='build':build['input_identity']['algorithm_identity']['base_commit']='FOREIGN'
                if change=='copy':build['input_identity']['generated_sha256']['generated/corners_contour_v1.cpp']='0'*64
                if change=='entry':build['input_identity']['generated_sha256'].pop('generated/main.cpp')
                if change=='tracker':build['input_identity']['operator_hook_sha256']='0'*64
                write_json(f['builddir']/'BUILD_MANIFEST.json',build)
                value['frozen_build']['manifest_sha256']=profile.digest(f['builddir']/'BUILD_MANIFEST.json');write_json(f['spec_path'],value)
                with self.subTest(change=change),self.assertRaises(ValueError):self.check(f)

    def test_windows_PE_or_incomplete_ELF_rejected_even_when_declared_hash_matches(self):
        with fixture() as f:
            for data in (b'MZ'+bytes(128),b'\x7fELF\x02\x01'+bytes(14)):
                value=deepcopy(f['spec']);build=deepcopy(f['build']);(f['builddir']/'binary').write_bytes(data)
                value['sha256']['binary']=sha(data);value['frozen_build']['binary_sha256']=sha(data);build['binary_sha256']=sha(data)
                write_json(f['builddir']/'BUILD_MANIFEST.json',build);value['frozen_build']['manifest_sha256']=profile.digest(f['builddir']/'BUILD_MANIFEST.json')
                write_json(f['spec_path'],value)
                with self.assertRaisesRegex(ValueError,'complete_linux_ELF64'):self.check(f)

    def test_junction_alias_to_identical_bytes_is_rejected(self):
        with fixture() as f:
            checked=self.check(f);original=f['builddir']/'generated';moved=f['root']/'moved';original.rename(moved)
            completed=subprocess.run(['cmd','/c','mklink','/J',str(original),str(moved)],capture_output=True)
            if completed.returncode:
                moved.rename(original);self.skipTest('Junction creation unavailable')
            try:
                self.assertEqual((original/'corners_contour_v1.cpp').read_bytes(),(moved/'corners_contour_v1.cpp').read_bytes())
                with self.assertRaisesRegex(ValueError,'reparse_point'):checked.verify_unchanged()
                with self.assertRaisesRegex(ValueError,'reparse_point'):self.check(f)
            finally:os.rmdir(original);moved.rename(original)

    def test_junction_introduced_after_shared_ancestor_inspection_is_rejected(self):
        with fixture() as f:
            checked=self.check(f);folder=f['builddir']/'generated';moved=f['builddir']/'moved';trigger=folder/'corners_contour_v1.cpp'
            original_digest=profile.digest;redirected=[]
            def redirect_after_digest(path):
                digest=original_digest(path)
                if Path(path)==trigger and not redirected:
                    folder.rename(moved)
                    result=subprocess.run(['cmd','/c','mklink','/J',str(folder),str(moved)],capture_output=True)
                    if result.returncode:
                        moved.rename(folder);self.skipTest('Junction creation unavailable')
                    redirected.append(True)
                return digest
            try:
                # The first generated file already inspected its parent. Each
                # next leaf must independently resolve, even when parent stat
                # was deduplicated during this one validation pass.
                with patch.object(profile,'digest',side_effect=redirect_after_digest):
                    with self.assertRaisesRegex(ValueError,'reparse_point'):checked.verify_unchanged()
            finally:
                if redirected:os.rmdir(folder);moved.rename(folder)


if __name__=='__main__':unittest.main()
