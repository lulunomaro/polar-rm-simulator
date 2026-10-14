"""Strict setup validator for diagnostic ELF profiles, never ordinary registry IO."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import tempfile
from rm_match.deployment.profile import read_json_snapshot

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'operator_native/runtime'
_spec=importlib.util.spec_from_file_location('rmcs_performance_portable',RUNTIME/'build_portable.py')
portable=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(portable)


def _exact(actual,expected):
    return json.dumps(actual,sort_keys=True,separators=(',',':'),allow_nan=False)==json.dumps(expected,sort_keys=True,separators=(',',':'),allow_nan=False)


def validate_performance_spec(spec_path,*,expected_profile):
    """Reproduce static overlays and attest every input; never compile or run code."""
    if expected_profile not in portable.PERFORMANCE_PROFILES[1:]:raise ValueError('Explicit diagnostic performance profile required')
    spec_path=Path(spec_path).resolve();out=spec_path.parent
    spec,spec_sha=read_json_snapshot(spec_path);build_path=out/'BUILD_MANIFEST.json'
    build,build_sha=read_json_snapshot(build_path)
    if type(spec) is not dict or type(build) is not dict:raise ValueError('Diagnostic spec/build must be objects')
    inputs=build.get('input_identity',{})
    if type(inputs) is not dict:raise ValueError('Diagnostic input identity must be an object')
    selected=portable.performance_identity(RUNTIME,expected_profile)
    if (spec.get('diagnostic_only') is not True or build.get('diagnostic_only') is not True
        or build.get('status')!='native_build_succeeded' or build.get('full_clean_compile') is not True
        or not _exact(spec.get('performance_profile'),selected) or not _exact(build.get('performance_profile'),selected)):
        raise ValueError('Diagnostic profile manifest/spec identity mismatch')
    model=ROOT/'models/shenzhen-0526.onnx';hook=RUNTIME.parent/'prepare_fov_hook.py'
    corner=inputs.get('corner_refinement')
    expected_input=portable.input_identity(RUNTIME,model,hook,corner_refinement=corner,performance_profile=expected_profile)
    if not _exact({k:v for k,v in inputs.items() if k!='generated_sha256'},expected_input):
        raise ValueError('Diagnostic build source inputs differ from trusted profile')
    binary=out/'bin/rmcs_sim_operator_fov';configs=out/'configs'
    expected_spec=portable.make_spec(binary,configs,model,inputs,build_sha)
    if not _exact(spec,expected_spec) or build.get('binary_sha256')!=portable.sha(binary) or not _exact(build.get('elf'),portable.elf_identity(binary)):
        raise ValueError('Diagnostic ELF/spec/build binding mismatch')
    binary_bytes=binary.read_bytes()
    for marker in (b'[RMCS-FIRST-FRAME]',b'rmcs.first-frame-trace.v1',expected_profile.encode()):
        if marker not in binary_bytes:raise ValueError('Diagnostic ELF lacks its actual profile marker')
    generated=inputs.get('generated_sha256')
    if type(generated) is not dict:raise ValueError('Missing diagnostic generated input manifest')
    # Re-run only pure Python source preparation, not CMake/compiler/model code.
    with tempfile.TemporaryDirectory(prefix='rmcs-profile-validation-') as temporary:
        prepared=portable.prepare(RUNTIME,Path(temporary)/'expected',model,hook,
            corner_refinement=corner,performance_profile=expected_profile)
        if not _exact(generated,prepared['generated_sha256']):raise ValueError('Diagnostic generated overlay is not the trusted transformation')
    for rel,digest in generated.items():
        path=out/rel
        if not path.resolve().is_relative_to(out) or not path.is_file() or portable.sha(path)!=digest:
            raise ValueError('Diagnostic prepared artifact changed: '+rel)
    recovered=portable.verify_sources(RUNTIME)
    expected_units={str((RUNTIME/rel).resolve()) for rel in recovered['translation_units']}
    replacements={'main.cpp':'generated/main.cpp',
        'candidate/src/module/detector/armor_detection.cpp':'generated/armor_detection_profile.cpp'}
    if corner!='original':replacements['candidate/src/utility/math/corners_optimizor.cpp']='generated/corners_contour_v1.cpp'
    for old,new in replacements.items():expected_units.remove(str((RUNTIME/old).resolve()));expected_units.add(str((out/new).resolve()))
    rows=build.get('syntax_checks',[])
    if len(rows)!=len(expected_units) or {str(Path(row['file']).resolve()) for row in rows}!=expected_units or any(row.get('compiler_syntax')!='passed' for row in rows):
        raise ValueError('Diagnostic clean syntax source closure mismatch')
    compile_path=out/'cmake/compile_commands.json';cache_path=out/'cmake/CMakeCache.txt'
    if (build.get('compile_commands_sha256')!=portable.sha(compile_path)
        or build.get('cmake_cache_sha256')!=portable.sha(cache_path)):
        raise ValueError('Diagnostic compiler manifest changed')
    commands,commands_sha=read_json_snapshot(compile_path,16*1024*1024)
    if commands_sha!=build.get('compile_commands_sha256'):raise ValueError('Diagnostic compiler snapshot changed')
    if len(commands)!=len(expected_units) or {str(Path(row['file']).resolve()) for row in commands}!=expected_units:
        raise ValueError('Diagnostic compile database source closure mismatch')
    if not any('-DRMCS_PERFORMANCE_PROFILE='+expected_profile in command for command in build.get('commands',[])):
        raise ValueError('Diagnostic profile configure flag missing')
    # Original decoded objects and their original hashes travel together. A
    # later rewrite never acquires the earlier object's validation result.
    if portable.sha(spec_path)!=spec_sha or portable.sha(build_path)!=build_sha:
        raise ValueError('Diagnostic spec/build changed during validation')
    return spec,spec_sha
