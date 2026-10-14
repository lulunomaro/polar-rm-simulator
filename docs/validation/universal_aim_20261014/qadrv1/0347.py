"""Synthetic ELF-header binding fixtures; no compiler/native/model invocation."""
import json
from pathlib import Path
import struct
from unittest.mock import patch
import pytest
from tools import validate_native_performance_profile as validator


@pytest.fixture
def diagnostic(tmp_path):
    p=validator.portable;root=validator.RUNTIME;model=validator.ROOT/'models/shenzhen-0526.onnx'
    profile='first-frame-trace';out=tmp_path/'diagnostic'
    inputs=p.prepare(root,out,model,root.parent/'prepare_fov_hook.py',corner_refinement='contour-v3',performance_profile=profile)
    binary=out/'bin/rmcs_sim_operator_fov';binary.parent.mkdir()
    ident=b'\x7fELF'+bytes((2,1,1,0))+bytes(8)
    header=struct.pack('<16sHHIQQQIHHHHHH',ident,3,62,1,4096,64,0,0,64,56,1,0,0,0)+bytes(56)
    binary.write_bytes(header+b'[RMCS-FIRST-FRAME] rmcs.first-frame-trace.v1 first-frame-trace')
    units=[]
    for rel in p.verify_sources(root)['translation_units']:
        selected={'main.cpp':out/'generated/main.cpp',
            'candidate/src/module/detector/armor_detection.cpp':out/'generated/armor_detection_profile.cpp',
            'candidate/src/utility/math/corners_optimizor.cpp':out/'generated/corners_contour_v1.cpp'}.get(rel,root/rel)
        units.append(str(selected.resolve()))
    cmake=out/'cmake';cmake.mkdir();(cmake/'CMakeCache.txt').write_text('synthetic-static-unit-fixture-no-compiler\n')
    p.write_json(cmake/'compile_commands.json',[dict(file=name) for name in units])
    build=dict(status='native_build_succeeded',diagnostic_only=True,full_clean_compile=True,
        performance_profile=inputs['performance_profile'],input_identity=inputs,binary_sha256=p.sha(binary),elf=p.elf_identity(binary),
        syntax_checks=[dict(file=name,compiler_syntax='passed') for name in units],
        compile_commands_sha256=p.sha(cmake/'compile_commands.json'),cmake_cache_sha256=p.sha(cmake/'CMakeCache.txt'),
        commands=p.make_commands(root,out,corner_refinement='contour-v3',performance_profile=profile))
    p.write_json(out/'BUILD_MANIFEST.json',build)
    spec=p.make_spec(binary,out/'configs',model,inputs,p.sha(out/'BUILD_MANIFEST.json'))
    p.write_json(out/'operator_source.local.json',spec)
    return out,build,spec


def test_explicit_diagnostic_binding_accepts_only_matching_profile(diagnostic):
    out,_,_=diagnostic;path=out/'operator_source.local.json'
    spec,digest=validator.validate_performance_spec(path,expected_profile='first-frame-trace')
    assert digest==validator.portable.sha(path) and spec['diagnostic_only'] is True
    with pytest.raises(ValueError):validator.validate_performance_spec(path,expected_profile='request-preallocate-trace')
    with pytest.raises(ValueError):validator.validate_performance_spec(path,expected_profile='original')


def test_source_tamper_and_self_rehashed_generated_overlay_are_not_trusted(diagnostic):
    out,build,spec=diagnostic;p=validator.portable
    main=out/'generated/main.cpp';main.write_bytes(main.read_bytes()+b'\n// unauthorized replacement\n')
    build['input_identity']['generated_sha256']['generated/main.cpp']=p.sha(main)
    p.write_json(out/'BUILD_MANIFEST.json',build);spec['frozen_build']['manifest_sha256']=p.sha(out/'BUILD_MANIFEST.json')
    p.write_json(out/'operator_source.local.json',spec)
    with pytest.raises(ValueError,match='trusted transformation'):
        validator.validate_performance_spec(out/'operator_source.local.json',expected_profile='first-frame-trace')


def test_duplicate_json_and_changed_spec_during_validation_rejected(diagnostic):
    out,_,_=diagnostic;path=out/'operator_source.local.json';original=path.read_bytes()
    path.write_bytes(b'{"diagnostic_only":true,"diagnostic_only":false}')
    with pytest.raises(ValueError,match='Duplicate'):validator.validate_performance_spec(path,expected_profile='first-frame-trace')
    path.write_bytes(original);read=validator.read_json_snapshot
    def snapshot_then_replace(selected,*args,**kwargs):
        decoded,digest=read(selected,*args,**kwargs)
        if Path(selected)==path:path.write_bytes(original+b'\n')
        return decoded,digest
    with patch.object(validator,'read_json_snapshot',side_effect=snapshot_then_replace):
        with pytest.raises(ValueError,match='changed during validation'):
            validator.validate_performance_spec(path,expected_profile='first-frame-trace')


def test_boolean_identity_flag_cannot_be_aliased_by_integer(diagnostic):
    out,_,spec=diagnostic;spec['performance_profile']['diagnostic_only']=1
    validator.portable.write_json(out/'operator_source.local.json',spec)
    with pytest.raises(ValueError,match='identity mismatch'):
        validator.validate_performance_spec(out/'operator_source.local.json',expected_profile='first-frame-trace')


def test_default_registry_validator_refuses_marked_diagnostic_spec(diagnostic):
    from rm_match.deployment.profile import validate_t2_spec
    out,_,_=diagnostic
    with pytest.raises(ValueError,match='[Dd]iagnostic'):
        validate_t2_spec(out/'operator_source.local.json')
