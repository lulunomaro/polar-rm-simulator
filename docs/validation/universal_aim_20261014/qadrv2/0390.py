"""Production overlay/identity tests only; no compiler, ELF, model or live run."""
import copy
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch
import pytest
from operator_native.runtime import build_portable as portable
from operator_native.runtime.overlays.prepare_inference_threads import render_threads,generate_threads
from rm_match.deployment import profile

ROOT=portable.ROOT
MODEL=ROOT.parents[1]/'models/shenzhen-0526.onnx'
HOOK=ROOT.parent/'prepare_fov_hook.py'


def identity(threads=None,corner='contour-v3'):
    return portable.input_identity(ROOT,MODEL,HOOK,corner_refinement=corner,inference_threads=threads)


def metadata(threads=4):
    inputs=identity(threads);selected=inputs['inference_profile']
    spec=dict(source_identity=inputs['algorithm_identity'],inference_profile=copy.deepcopy(selected),
              frozen_build=dict(inference_profile=copy.deepcopy(selected)))
    build=dict(input_identity=inputs,inference_profile=copy.deepcopy(selected),
               commands=portable.make_commands(ROOT,Path('/fresh'),corner_refinement='contour-v3',inference_threads=threads))
    return spec,build


def test_default_retains_legacy_algorithm_graph_and_compile_command():
    inputs=identity();recovered=portable.verify_sources(ROOT)['algorithm_identity']
    assert inputs['algorithm_identity']['tracker_patch_sha256']==recovered['patch_sha256']
    assert 'runtime_inference_profile' not in inputs['algorithm_identity']
    assert 'inference_profile' not in inputs and 'inference_threads' not in inputs
    assert not any('INFERENCE_THREADS' in x for x in portable.make_commands(ROOT,Path('/fresh'))[0])
    assert profile.validate_source_identity(inputs['algorithm_identity'])[0]=='contour-v3'
    assert profile.base_source_identity(inputs['algorithm_identity'])==recovered


@pytest.mark.parametrize('value',[True,False,0,33,-1,4.,'4'])
def test_unknown_or_scalar_alias_thread_options_rejected_before_prepare(value):
    with pytest.raises(ValueError):identity(value)
    with pytest.raises(ValueError):render_threads(ROOT,value)


def test_production_cannot_mix_with_diagnostic_elf_profile(tmp_path):
    with pytest.raises(ValueError,match='cannot mix'):
        portable.prepare(ROOT,tmp_path/'out',MODEL,HOOK,inference_threads=4,performance_profile='first-frame-trace')
    assert not (tmp_path/'out').exists()


def test_only_compile_boundary_changes_original_algorithm_source():
    raw=(ROOT/'candidate/src/module/detector/armor_detection.cpp').read_bytes().replace(b'\r\n',b'\n')
    files=render_threads(ROOT,4);generated=files['armor_detection_threads.cpp']
    restored=generated.replace(b'#include "production_inference_threads.hpp"\n',b'',1)
    restored=restored.replace(b'        rmcs::production_inference::configure(openvino_core);\n',b'',1)
    restored=restored.replace(b'\n        rmcs::production_inference::verify_and_report(openvino_model);',b'',1)
    assert restored==raw
    header=files['production_inference_threads.hpp'].decode()
    assert 'requested_threads=4' in header and 'core.set_property("CPU",ov::inference_num_threads(requested_threads))' in header
    assert 'getenv(' not in header and 'setNumThreads(' not in header and '.infer(' not in header
    assert 'first_frame_trace' not in header and 'create_infer_request' not in header and 'ov::Tensor' not in header
    assert '[RMCS-PRODUCTION-INFERENCE]' in header and 'std::fflush(stderr)' in header


def test_profiles_have_distinct_hashes_and_strict_legacy_recovery():
    a=identity(4);b=identity(8);original=identity()
    assert len({a['algorithm_identity']['patch_sha256'],b['algorithm_identity']['patch_sha256'],original['algorithm_identity']['patch_sha256']})==3
    assert profile.validate_source_identity(a['algorithm_identity'])==('contour-v3',a['additional_source_files'])
    assert profile.base_source_identity(a['algorithm_identity'])==portable.verify_sources(ROOT)['algorithm_identity']
    # The option also composes with the explicit historical original frontend.
    plain=identity(4,'original')
    assert profile.validate_source_identity(plain['algorithm_identity'])[0]=='original'
    assert profile.base_source_identity(plain['algorithm_identity'])==portable.verify_sources(ROOT)['algorithm_identity']


@pytest.mark.parametrize('key,value',[('inference_threads',True),('inference_threads',4.),('diagnostic_only',0),
    ('inference_during_setup',0),('header_sha256','0'*64),('device','GPU')])
def test_source_profile_cannot_alias_typed_identity_or_replace_checked_overlay(key,value):
    source=identity(4)['algorithm_identity'];source['runtime_inference_profile'][key]=value
    with pytest.raises(ValueError):profile.validate_source_identity(source)


@pytest.mark.parametrize('container',['spec','frozen','build','inputs'])
def test_cross_manifest_metadata_cannot_be_inconsistent(container):
    spec,build=metadata();targets=dict(spec=spec,frozen=spec['frozen_build'],build=build,inputs=build['input_identity'])
    targets[container]['inference_profile']['inference_threads']=8
    with pytest.raises(ValueError):profile.validate_inference_build_metadata(spec,build)


def test_metadata_and_explicit_compiler_option_are_required():
    spec,build=metadata();profile.validate_inference_build_metadata(spec,build)
    build['commands'][0].remove('-DRMCS_INFERENCE_THREADS=4')
    with pytest.raises(ValueError,match='compile command'):profile.validate_inference_build_metadata(spec,build)
    spec,build=metadata();build['input_identity']['inference_threads']=True
    with pytest.raises(ValueError,match='thread count'):profile.validate_inference_build_metadata(spec,build)
    legacy=identity();spec=dict(source_identity=legacy['algorithm_identity'],inference_profile={})
    with pytest.raises(ValueError,match='cannot hide'):profile.validate_inference_build_metadata(spec,dict(input_identity=legacy))


def test_generated_production_bytes_are_trusted_not_self_declared_hash(tmp_path):
    spec,build=metadata();generated=tmp_path/'generated';generated.mkdir()
    generate_threads(ROOT,generated,4)
    (generated/'prepare_inference_threads.py').write_bytes((ROOT/portable.INFERENCE_SOURCES[0]).read_bytes())
    build['input_identity']['generated_sha256']={'generated/'+p.name:portable.sha(p) for p in generated.iterdir()}
    profile.validate_inference_build_metadata(spec,build,build_root=tmp_path)
    altered=generated/'armor_detection_threads.cpp';altered.write_bytes(altered.read_bytes()+b'\n// unexpected source\n')
    build['input_identity']['generated_sha256']['generated/'+altered.name]=portable.sha(altered)
    with pytest.raises(ValueError,match='trusted transformation'):
        profile.validate_inference_build_metadata(spec,build,build_root=tmp_path)


def test_real_prepare_is_source_only_no_main_protocol_or_yaml_change(tmp_path):
    original=portable.prepare(ROOT,tmp_path/'original',MODEL,HOOK,corner_refinement='contour-v3')
    production=portable.prepare(ROOT,tmp_path/'production',MODEL,HOOK,corner_refinement='contour-v3',inference_threads=4)
    assert original['generated_sha256']['generated/main.cpp']==production['generated_sha256']['generated/main.cpp']==portable.OPERATOR_MAIN_HASH
    for config in ('simulation_autoaim.yaml','simulation_executor.yaml'):
        assert (tmp_path/'original/configs'/config).read_bytes()==(tmp_path/'production/configs'/config).read_bytes()
    assert 'generated/first_frame_trace.hpp' not in production['generated_sha256']
    assert 'generated/armor_detection_threads.cpp' in production['generated_sha256']
    assert portable.verify_sources(ROOT)['algorithm_identity']['patch_sha256']==profile.T2_PATCH


def test_incomplete_production_identity_cannot_hide_in_original():
    source=identity()['algorithm_identity'];source['inference_base_patch_sha256']=source['patch_sha256']
    with pytest.raises(ValueError,match='Incomplete'):profile.validate_source_identity(source)


def _wsl_production(f):
    """Upgrade the existing never-executed ELF fixture, never fabricate runtime."""
    from rm_match.deployment import wsl_profile as wsl
    runtime=f['runtime'];root=f['builddir'];inputs=f['build']['input_identity'];source=f['spec']['source_identity']
    original=runtime/'candidate/src/module/detector/armor_detection.cpp';original.parent.mkdir(parents=True)
    original.write_bytes((ROOT/'candidate/src/module/detector/armor_detection.cpp').read_bytes())
    for rel in portable.INFERENCE_SOURCES:(runtime/rel).write_bytes((ROOT/rel).read_bytes())
    selected=portable.inference_identity(runtime,4);prior=source['patch_sha256']
    source.update(runtime_inference_profile=selected,inference_base_patch_sha256=prior,
        patch_identity_format='rmcs-own-source-inference-composition.v1',
        patch_sha256=portable.inference_combined_patch_hash(prior,selected['patch_sha256']))
    inputs.update(inference_profile=copy.deepcopy(selected),inference_threads=4)
    inputs['additional_source_files'].update({rel:portable.sha(runtime/rel) for rel in portable.INFERENCE_SOURCES})
    generate_threads(runtime,root/'generated',4)
    (root/'generated/prepare_inference_threads.py').write_bytes((runtime/portable.INFERENCE_SOURCES[0]).read_bytes())
    for name in ('armor_detection_threads.cpp','production_inference_threads.hpp','prepare_inference_threads.py'):
        inputs['generated_sha256']['generated/'+name]=portable.sha(root/'generated'/name)
    recovery=json.loads((runtime/'RECOVERY_MANIFEST.json').read_text())
    recovery['files'].append(dict(path=original.relative_to(runtime).as_posix(),sha256=portable.sha(original)))
    portable.write_json(runtime/'RECOVERY_MANIFEST.json',recovery)
    inputs['source_files']={r['path']:r['sha256'] for r in recovery['files']}
    inputs['recovery_manifest_sha256']=portable.sha(runtime/'RECOVERY_MANIFEST.json')
    f['build'].update(inference_profile=copy.deepcopy(selected),commands=portable.make_commands(runtime,root,corner_refinement='contour-v3',inference_threads=4))
    f['spec'].update(inference_profile=copy.deepcopy(selected));f['spec']['frozen_build']['inference_profile']=copy.deepcopy(selected)
    portable.write_json(root/'BUILD_MANIFEST.json',f['build'])
    f['spec']['frozen_build']['manifest_sha256']=portable.sha(root/'BUILD_MANIFEST.json')
    portable.write_json(f['spec_path'],f['spec'])
    return wsl.validate_wsl_spec(f['spec_path'],repo_root=f['repo'],shared_out=f['out'])


@pytest.mark.skipif(os.name!='nt',reason='Explicit Windows C: host path fixture only')
def test_wsl_production_fixture_accepts_exact_profile_without_spawning_and_rechecks_sources():
    import importlib.util
    spec=importlib.util.spec_from_file_location('_production_wsl_fixture',Path(__file__).with_name('test_wsl_profile.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with module.fixture() as f,patch('subprocess.Popen') as spawn:
        checked=_wsl_production(f)
        assert checked.metadata['source_identity']['runtime_inference_profile']['inference_threads']==4
        assert checked.linux_spec['inference_profile']['diagnostic_only'] is False
        spawn.assert_not_called()
        changed=f['runtime']/portable.INFERENCE_SOURCES[1];changed.write_bytes(changed.read_bytes()+b'\n// changed\n')
        with pytest.raises(ValueError,match='changed_after_validation'):checked.verify_unchanged()


@pytest.mark.skipif(os.name!='nt',reason='Explicit Windows C: host path fixture only')
def test_wsl_production_self_rehashed_wrong_generated_threads_are_rejected():
    import importlib.util
    from rm_match.deployment import wsl_profile as wsl
    spec=importlib.util.spec_from_file_location('_production_wsl_fixture',Path(__file__).with_name('test_wsl_profile.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with module.fixture() as f:
        _wsl_production(f)
        header=f['builddir']/'generated/production_inference_threads.hpp'
        header.write_bytes(header.read_bytes().replace(b'requested_threads=4',b'requested_threads=8'))
        f['build']['input_identity']['generated_sha256']['generated/production_inference_threads.hpp']=portable.sha(header)
        portable.write_json(f['builddir']/'BUILD_MANIFEST.json',f['build'])
        f['spec']['frozen_build']['manifest_sha256']=portable.sha(f['builddir']/'BUILD_MANIFEST.json')
        portable.write_json(f['spec_path'],f['spec'])
        with pytest.raises(ValueError,match='trusted transformation'):
            wsl.validate_wsl_spec(f['spec_path'],repo_root=f['repo'],shared_out=f['out'])
