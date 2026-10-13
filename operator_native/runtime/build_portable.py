#!/usr/bin/env python3
"""Explicit local clean build for the simulation-only RMCS operator adapter.

plan/prepare never compile or launch native code. build invokes local CMake only.
No downloads, package installation, network calls, hardware IO, or inference.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import shlex
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
IDENTITY = 'rmcs-sim-operator-fov-v1'
MODEL_HASH = 'b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255'
HOOK_HASH = '26a33ad0e6a1bb4dfb3e00abce8ba4f5cc4a75002a62f094349069e5a0d49aee'
OPERATOR_MAIN_HASH = '4357b6e6b3495730229b0b08e9eeb94d0de7db57a5dc435b916a4ae26772e5ca'
MODE = 'multi_ekf\n'
CORNER_FRONTENDS = {
    'contour-v1': ('overlays/corners_contour_v1.cpp', 'image_contour_corners_v1'),
    'contour-v2': ('overlays/corners_contour_v2.cpp', 'image_contour_corners_v2'),
    'contour-v3': ('overlays/corners_contour_v3.cpp', 'image_contour_corners_v3'),
}


def combined_patch_hash(tracker_patch_sha256, frontend_sha256):
    value=dict(schema='rmcs-own-source-composition.v1',tracker_patch_sha256=tracker_patch_sha256,
               vision_frontend_sha256=frontend_sha256)
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def verify_sources(base=ROOT):
    manifest = json.loads((base / 'RECOVERY_MANIFEST.json').read_text())
    for row in manifest['files']:
        path = base / row['path']
        if not path.resolve().is_relative_to(base.resolve()):
            raise ValueError('Source manifest path escapes runtime directory')
        if not path.is_file() or sha(path) != row['sha256']:
            raise ValueError('Recovered source changed: ' + row['path'])
    return manifest


def make_commands(base, out, *, cmake='cmake', jobs=2, prefix=None, corner_refinement='original'):
    configure = [cmake, '-S', str(base), '-B', str(out / 'cmake'),
                 '-DCMAKE_BUILD_TYPE=Release',
                 '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
                 '-DRMCS_GENERATED_DIR=' + str(out / 'generated'),
                 '-DCMAKE_RUNTIME_OUTPUT_DIRECTORY=' + str(out / 'bin')]
    if prefix:
        configure.append('-DCMAKE_PREFIX_PATH=' + str(prefix))
    if corner_refinement != 'original' and corner_refinement not in CORNER_FRONTENDS:
        raise ValueError('Unsupported corner frontend revision')
    if corner_refinement!='original':configure.append('-DRMCS_USE_CONTOUR_CORNERS=ON')
    return [configure, [cmake, '--build', str(out / 'cmake'), '--target',
                        'rmcs_sim_operator_fov', '--parallel', str(jobs)]]


def input_identity(base, model, hook, *, corner_refinement='original'):
    recovered = verify_sources(base)
    if model.name != 'shenzhen-0526.onnx' or not model.is_file() or sha(model) != MODEL_HASH:
        raise ValueError('Expected exact shenzhen-0526.onnx model is missing or changed')
    if not hook.is_file() or sha(hook) != HOOK_HASH:
        raise ValueError('Operator FOV transformation script changed')
    algorithm=dict(recovered['algorithm_identity'])
    extra={}
    if corner_refinement in CORNER_FRONTENDS:
        overlay_source, overlay_id = CORNER_FRONTENDS[corner_refinement]
        overlay=base/overlay_source
        if not overlay.is_file():raise ValueError('Explicit contour frontend source is missing')
        overlay_hash=sha(overlay);tracker_hash=algorithm['patch_sha256']
        algorithm.update(tracker_patch_sha256=tracker_hash,
                         vision_frontend=dict(id=overlay_id,source_path=overlay_source,source_sha256=overlay_hash),
                         patch_identity_format='rmcs-own-source-composition.v1',
                         patch_sha256=combined_patch_hash(tracker_hash,overlay_hash))
        extra[overlay_source]=overlay_hash
    elif corner_refinement!='original':raise ValueError('Unsupported corner frontend revision')
    return {'recovery_manifest_sha256': sha(base / 'RECOVERY_MANIFEST.json'),
            'source_files': {r['path']: r['sha256'] for r in recovered['files']},
            'algorithm_identity': algorithm,
            'additional_source_files':extra,'corner_refinement':corner_refinement,
            'model_sha256': MODEL_HASH, 'operator_hook_sha256': HOOK_HASH,
            'portable_entry_sha256': sha(base / 'build_portable.py'),
            'cmake_project_sha256': sha(base / 'CMakeLists.txt'),
            'profile_sha256': sha(base / 'simulation_profile.json')}


def prepare(base, out, model, hook, *, corner_refinement='original'):
    identity = input_identity(base, model, hook,corner_refinement=corner_refinement)
    # Each attempt gets a fresh directory. Preserve prior failures and results.
    if out.exists():
        raise ValueError('Output already exists; choose a fresh --out directory')
    if out == base or base.is_relative_to(out):
        raise ValueError('Output must not contain the recovered source tree')
    out.mkdir(parents=True)
    generated = out / 'generated'
    generated.mkdir()
    if corner_refinement in CORNER_FRONTENDS:
        shutil.copyfile(base/CORNER_FRONTENDS[corner_refinement][0],generated/'corners_contour_v1.cpp')
    isolated_hook = generated / 'prepare_fov_hook.py'
    shutil.copyfile(hook, isolated_hook)
    subprocess.run([sys.executable, str(isolated_hook), '--base', str(base)], check=True)
    main = generated / 'main.cpp'
    # The exact hook writes native platform newlines. Its generated C++ is
    # canonically LF on every host; recovered inputs remain byte-for-byte sealed.
    main.write_bytes(main.read_bytes().replace(b'\r\n',b'\n'))
    text = main.read_text()
    if sha(main) != OPERATOR_MAIN_HASH or IDENTITY not in text or 'fov_admitted2d' not in text or 'std::erase_if' not in text:
        raise ValueError('Expected operator FOV transformation is incomplete')
    profile = json.loads((base / 'simulation_profile.json').read_text())
    profile['autoaim']['detector']['model_location'] = str(model)
    configs = out / 'configs'
    configs.mkdir()
    # JSON is also valid YAML. This avoids a Python YAML dependency in setup.
    write_json(configs / 'simulation_autoaim.yaml', profile['autoaim'])
    write_json(configs / 'simulation_executor.yaml', profile['executor'])
    (out / 'tracking_mode').write_text(MODE)
    identity['generated_sha256'] = {
        p.relative_to(out).as_posix(): sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
    write_json(out / 'PREPARED_INPUTS.json', identity)
    return identity


def elf_identity(binary):
    with binary.open('rb') as stream:
        header = stream.read(64)
    if len(header) != 64:
        raise ValueError('Native output has a truncated ELF header')
    fields = struct.unpack('<16sHHIQQQIHHHHHH', header)
    ident, kind, machine, version = fields[:4]
    entry, phoff, _, _, ehsize, phentsize, phnum = fields[4:11]
    if (ident[:7] != b'\x7fELF\x02\x01\x01' or ident[7] not in (0, 3)
            or kind not in (2, 3) or machine != 62 or version != 1
            or ehsize != 64 or entry == 0 or phentsize != 56 or phnum < 1
            or phoff < 64 or phoff + phnum * phentsize > binary.stat().st_size):
        raise ValueError('Native output must be a complete ELF64 little-endian x86-64 executable')
    return {'class': 'ELF64', 'endianness': 'little', 'machine': 'EM_X86_64',
            'elf_type': kind, 'program_headers': phnum}


def make_spec(binary, configs, model, identity, build_manifest_hash):
    # This function records bytes; it never starts a process or validates control.
    elf = elf_identity(binary)
    if sha(model) != MODEL_HASH:
        raise ValueError('Detector model changed during build')
    digest = sha(binary)
    mode_hash = hashlib.sha256(MODE.encode()).hexdigest()
    return {
        'id': 't2_sim_operator_portable_local', 'operator_identity': IDENTITY,
        'runner_identity': IDENTITY, 'binary': str(binary),
        'executor_yaml': str(configs / 'simulation_executor.yaml'),
        'autoaim_config': str(configs / 'simulation_autoaim.yaml'),
        'model_share': str(model.parent), 'model_sha256': MODEL_HASH,
        'sha256': {'binary': digest,
                   'executor_yaml': sha(configs / 'simulation_executor.yaml'),
                   'autoaim_config': sha(configs / 'simulation_autoaim.yaml'),
                   'runtime_mode': mode_hash},
        'frozen_build': {'binary_sha256': digest, 'manifest_sha256': build_manifest_hash,
                         'elf': elf,
                         'scope': 'New local clean build; no historical binary equivalence'},
        'runtime_mode_contents': MODE, 'runtime_mode_sha256': mode_hash,
        'environment': {'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1',
                        'MKL_NUM_THREADS': '1'},
        'source_identity': identity['algorithm_identity'],
        'qualification': 'Built only; no inference, MuJoCo closed-loop, live, or hardware qualification',
        'algorithm_description': 'Recovered 079a7fe plus T2 tracker changes; explicit frontend ' + identity.get('corner_refinement','original') + '; operator FOV adapter; simulation-only stationary red sentry; no automatic fire authority',
    }


def syntax_command(row):
    args = list(row.get('arguments') or shlex.split(row['command']))
    result = []
    skip = False
    for item in args:
        if skip:
            skip = False
        elif item == '-o':
            skip = True
        elif item == '-c':
            result.append('-fsyntax-only')
        else:
            result.append(item)
    if '-fsyntax-only' not in result:
        raise ValueError('Compile database lacks explicit compile-only option')
    return result


def syntax_checks(out):
    rows = json.loads((out / 'cmake/compile_commands.json').read_text())
    tidy = shutil.which('clang-tidy')
    reports = []
    for index, row in enumerate(rows):
        if tidy:
            command = [tidy, str(row['file']), '-p', str(out / 'cmake'), '--quiet']
            with (out / ('tidy_%03d.log' % index)).open('w') as log:
                subprocess.run(command, cwd=row['directory'], stdout=log, stderr=subprocess.STDOUT, check=True)
        command = syntax_command(row)
        with (out / ('syntax_%03d.log' % index)).open('w') as log:
            subprocess.run(command, cwd=row['directory'], stdout=log, stderr=subprocess.STDOUT, check=True)
        reports.append({'file': row['file'], 'compiler_syntax': 'passed',
                        'clang_tidy': 'passed' if tidy else 'unavailable'})
    return reports


def build(base, out, model, hook, *, jobs=2, prefix=None,corner_refinement='original'):
    if platform.system() != 'Linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
        raise RuntimeError('This native build supports Linux x86-64 only')
    cmake = shutil.which('cmake')
    if cmake is None:
        raise RuntimeError('CMake is missing; install documented local prerequisites yourself')
    identity = prepare(base, out, model, hook,corner_refinement=corner_refinement)
    commands = make_commands(base, out, cmake=cmake, jobs=jobs, prefix=prefix,corner_refinement=corner_refinement)
    write_json(out / 'BUILD_ATTEMPT.json', {'status': 'running', 'commands': commands})
    try:
        for name, command in zip(('configure.log', 'build.log'), commands):
            with (out / name).open('w') as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
            if name == 'configure.log':
                syntax = syntax_checks(out)
        if input_identity(base, model, hook,corner_refinement=corner_refinement) != {k:v for k,v in identity.items() if k != 'generated_sha256'}:
            raise ValueError('Build inputs changed during compilation')
        for rel, digest in identity['generated_sha256'].items():
            if sha(out / rel) != digest:
                raise ValueError('Prepared input changed during compilation: ' + rel)
        binary = out / 'bin/rmcs_sim_operator_fov'
        elf = elf_identity(binary)
        manifest = {'status': 'native_build_succeeded', 'operator_identity': IDENTITY,
                    'full_clean_compile': True, 'historical_binary_equivalence': False,
                    'binary_sha256': sha(binary), 'elf': elf, 'input_identity': identity,
                    'commands': commands, 'verification': 'build only; native executable never launched',
                    'syntax_checks': syntax,
                    'cmake_cache_sha256': sha(out / 'cmake/CMakeCache.txt'),
                    'compile_commands_sha256': sha(out / 'cmake/compile_commands.json')}
        write_json(out / 'BUILD_MANIFEST.json', manifest)
        spec = make_spec(binary, out / 'configs', model, identity, sha(out / 'BUILD_MANIFEST.json'))
        write_json(out / 'operator_source.local.json', spec)
        write_json(out / 'BUILD_ATTEMPT.json', {'status': 'native_build_succeeded', 'commands': commands})
        return {'status': 'native_build_succeeded_not_runtime_qualified',
                'spec': str(out / 'operator_source.local.json'),
                'spec_sha256': sha(out / 'operator_source.local.json'),
                'binary_sha256': sha(binary)}
    except Exception as exc:
        write_json(out / 'BUILD_ATTEMPT.json', {'status': 'failed', 'error': str(exc), 'commands': commands})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'prepare', 'build'))
    parser.add_argument('--out', type=Path, default=ROOT / 'local_build')
    parser.add_argument('--model', type=Path, default=ROOT.parents[1] / 'models/shenzhen-0526.onnx')
    parser.add_argument('--operator-hook', type=Path, default=ROOT.parent / 'prepare_fov_hook.py')
    parser.add_argument('--prefix', help='CMake package prefixes, separated by semicolons, e.g. OpenVINO runtime/cmake')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--corner-refinement',choices=('original',*CORNER_FRONTENDS),default='contour-v3',
                        help='Explicit source revision; each contour frontend is separately identified from original T2')
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    out, model, hook = args.out.resolve(), args.model.resolve(), args.operator_hook.resolve()
    if args.action == 'plan':
        identity = input_identity(ROOT, model, hook,corner_refinement=args.corner_refinement)
        result = {'status': 'unbuilt_plan', 'inputs': identity,
                  'commands_not_executed': make_commands(ROOT, out, jobs=args.jobs, prefix=args.prefix,corner_refinement=args.corner_refinement),
                  'cmake_available': shutil.which('cmake') is not None,
                  'dependencies': json.loads((ROOT / 'RECOVERY_MANIFEST.json').read_text())['dependencies']}
    elif args.action == 'prepare':
        result = {'status': 'prepared_unbuilt_no_spec', 'inputs': prepare(ROOT, out, model, hook,corner_refinement=args.corner_refinement)}
    else:
        result = build(ROOT, out, model, hook, jobs=args.jobs, prefix=args.prefix,corner_refinement=args.corner_refinement)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
