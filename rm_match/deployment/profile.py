"""Fail-closed identity and registry for the default simulation deployment."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

PROFILE = 'own-rmcs-t2-v1'
CLIENT_REPOSITORY = 'https://github.com/lulunomaro/polar-rm-client.git'
CLIENT_COMMIT = '0cedf99b70b1beec99865b9980af6789e6c53d99'
T2_BASE = '079a7fe29966fe467630f0c4ab8c3ed075edaad9'
T2_PATCH = 'ea1235cfd11018bde08b40a43f3aba072a0870a8906f40ff35255cfdd16e4c7d'
MODEL_SHA256 = 'b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255'
RUNTIME_ROOT = Path(__file__).resolve().parents[2] / 'operator_native/runtime'
FRONTENDS = {
    'image_contour_corners_v1': ('contour-v1', 'overlays/corners_contour_v1.cpp'),
    'image_contour_corners_v2': ('contour-v2', 'overlays/corners_contour_v2.cpp'),
    'image_contour_corners_v3': ('contour-v3', 'overlays/corners_contour_v3.cpp'),
}
LIMITATIONS = [
    'stationary_red_sentry_only', 'fire_authority_manual_only',
    'live_camera_native_wall_timing_not_qualified', 'full_match_not_qualified',
    'windows_native_not_supported', 'loopback_only_not_cross_machine_LAN',
    'provisional_dynamics_and_referee_subset',
]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read_json_snapshot(path, limit=1024 * 1024):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Expected bounded JSON file: ' + str(path))
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def constant(_):
        raise ValueError('Nonfinite JSON is forbidden')
    with path.open('rb') as stream:content=stream.read(limit+1)
    if len(content)>limit:raise ValueError('Expected bounded JSON file: '+str(path))
    return (json.loads(content,object_pairs_hook=pairs,parse_constant=constant),
            hashlib.sha256(content).hexdigest())


def read_json(path, limit=1024 * 1024):
    return read_json_snapshot(path,limit)[0]


def validate_source_identity(source):
    if source.get('base_commit') != T2_BASE:
        raise ValueError('Own RMCS T2 source identity mismatch; baseline substitution refused')
    frontend = source.get('vision_frontend')
    if frontend is None:
        if source.get('patch_sha256') != T2_PATCH or any(
                key in source for key in ('tracker_patch_sha256','patch_identity_format')):
            raise ValueError('Own RMCS T2 source identity mismatch; baseline substitution refused')
        return 'original', {}
    if type(frontend) is not dict or set(frontend) != {'id','source_path','source_sha256'}:
        raise ValueError('Explicit corner frontend identity required')
    known = FRONTENDS.get(frontend['id'])
    if not known or frontend['source_path'] != known[1]:
        raise ValueError('Unknown corner frontend identity')
    if source.get('tracker_patch_sha256') != T2_PATCH or source.get('patch_identity_format') != 'rmcs-own-source-composition.v1':
        raise ValueError('Contour frontend must retain the own T2 tracker identity')
    frontend_hash = digest(RUNTIME_ROOT / known[1])
    composition = dict(schema='rmcs-own-source-composition.v1',tracker_patch_sha256=T2_PATCH,
                       vision_frontend_sha256=frontend_hash)
    expected = hashlib.sha256(json.dumps(composition,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if frontend['source_sha256'] != frontend_hash or source.get('patch_sha256') != expected:
        raise ValueError('Corner frontend source or composition hash mismatch')
    return known[0], {known[1]:frontend_hash}


def validate_t2_spec(path):
    """Check source + build lineage, then the existing complete native byte guard.

    This verifies declared, local build provenance, not a malicious-build sandbox
    or proof of successful inference. Never accept another RMCS identity because
    it happens to speak the same operator protocol.
    """
    spec, initial_spec_sha = read_json_snapshot(path)
    source = spec.get('source_identity', {})
    corner_revision, additional_sources = validate_source_identity(source)
    if source.get('is_original_upstream') is not False or source.get('is_baseline_40f7') is not False:
        raise ValueError('T2 source identity must explicitly exclude upstream and 40f7 baseline')
    if spec.get('model_sha256') != MODEL_SHA256:
        raise ValueError('Own RMCS model identity mismatch')
    for key in ('binary', 'executor_yaml', 'autoaim_config', 'model_share'):
        if not Path(spec.get(key, '')).is_absolute():
            raise ValueError('Consumer-local absolute native path required: ' + key)
    build_path = Path(path).parent / 'BUILD_MANIFEST.json'
    if digest(build_path) != spec.get('frozen_build', {}).get('manifest_sha256'):
        raise ValueError('Portable build manifest hash mismatch')
    build = read_json(build_path, 4 * 1024 * 1024)
    if (build.get('status') != 'native_build_succeeded'
            or build.get('full_clean_compile') is not True
            or build.get('input_identity', {}).get('algorithm_identity') != source
            or build.get('binary_sha256') != spec.get('sha256', {}).get('binary')):
        raise ValueError('Portable clean build evidence does not match the native spec')
    inputs = build['input_identity']
    if additional_sources:
        if inputs.get('corner_refinement') != corner_revision or inputs.get('additional_source_files') != additional_sources:
            raise ValueError('Contour build inputs do not match the declared frontend')
        generated_hash = digest(Path(path).parent / 'generated/corners_contour_v1.cpp')
        if generated_hash != next(iter(additional_sources.values())) or inputs.get('generated_sha256',{}).get('generated/corners_contour_v1.cpp') != generated_hash:
            raise ValueError('Prepared contour source differs from the frozen build')
    elif inputs.get('additional_source_files') or inputs.get('corner_refinement','original') != 'original':
        raise ValueError('Original T2 build cannot hide an additional frontend')
    from ..platform_v2.native_adapter import validate_native_spec
    checked, spec_sha = validate_native_spec(path,expected_spec_sha=initial_spec_sha)
    with Path(checked['binary']).open('rb') as stream:
        header = stream.read(20)
    if (len(header) < 20 or header[:6] != b'\x7fELF\x02\x01'
            or int.from_bytes(header[18:20], 'little') != 62):
        raise ValueError('Own RMCS deployment requires Linux ELF64 x86-64')
    return checked, spec_sha


def own_registry(spec_path, native_out, *, adapters_json=None, native_trace=None):
    from ..platform_v2.adapters import Registry, descriptor
    from ..platform_v2.native_adapter import NativeSourceAdapter
    checked_spec, registered_sha = validate_t2_spec(spec_path)
    registry = Registry()
    def make_native(config):
        # Spec content is pinned again by NativeSourceAdapter at construction and
        # process start. Recheck T2 lineage here before accepting a new binding.
        if digest(spec_path) != registered_sha:
            raise ValueError('native_spec_changed_after_registration')
        validate_t2_spec(spec_path)
        return NativeSourceAdapter(config, spec_path=spec_path, out=native_out,
                                   registered_spec_sha=registered_sha, trace=native_trace)
    registry.register(descriptor(
        'aim_native_rmcs_v1', 'aim', 'Own RMCS T2 native (stationary red sentry)',
        ('camera', 'odometry'), supported_robots=['red_sentry'],
        stationary_only=True, confidence_available=False,
        max_camera_age_sim_s=.08, source_identity=checked_spec['source_identity'],
        deployment_profile=PROFILE), make_native)
    if adapters_json:
        from .json_adapter import register_json_adapters
        register_json_adapters(registry, adapters_json)
    return registry
