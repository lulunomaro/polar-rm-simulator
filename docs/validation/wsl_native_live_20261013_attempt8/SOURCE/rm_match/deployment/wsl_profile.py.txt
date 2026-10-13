"""Explicit Windows-host/Ubuntu-native byte identity; never chooses executable argv.

Paths are trusted local configuration, not HTTP input. This guards a reviewed
local build, not a malicious-build sandbox or Windows-native qualification.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass,field
import hashlib
from pathlib import Path,PurePosixPath
import struct

from . import profile

TRANSPORT='wsl_stdio_v1'
DISTRIBUTION='Ubuntu'
SUPERVISOR='rm_match/integrations/wsl_operator.py'
WORKER='rm_match/integrations/wsl_operator_worker.py'
OPERATOR_MAIN_SHA256='4357b6e6b3495730229b0b08e9eeb94d0de7db57a5dc435b916a4ae26772e5ca'
OPERATOR_HOOK_SHA256='26a33ad0e6a1bb4dfb3e00abce8ba4f5cc4a75002a62f094349069e5a0d49aee'


def _no_reparse(path,checked_components=None):
    """Reject even an in-root alias: WSL and Windows must name identical files."""
    for component in (path,*path.parents):
        if checked_components is not None and component in checked_components:continue
        try:stat=component.lstat()
        except FileNotFoundError:continue
        if component.is_symlink() or getattr(stat,'st_file_attributes',0)&0x400:
            raise ValueError('wsl_path_reparse_point_rejected')
        if checked_components is not None:checked_components.add(component)


def _host_path(path,checked_components=None):
    value=Path(path)
    if not value.is_absolute() or value.drive.upper()!='C:':
        raise ValueError('wsl_host_requires_explicit_C_drive_path')
    if any(part in ('.','..') or ':' in part or any(c in part for c in '<>"|?*')
           or part.rstrip(' .')!=part for part in value.parts[1:]):
        raise ValueError('wsl_noncanonical_host_path')
    _no_reparse(value,checked_components)
    resolved=value.resolve(strict=False)
    if resolved!=value.absolute():raise ValueError('wsl_path_reparse_point_rejected')
    return resolved


def _roots(repo_root,shared_out):
    return _host_path(repo_root),_host_path(shared_out)


def _within(path,roots):
    if not any(path.is_relative_to(root) for root in roots):
        raise ValueError('wsl_path_outside_explicit_roots')
    return path


def linux_to_host_path(value,*,repo_root,shared_out,must_exist=True):
    if type(value) is not str or '\\' in value or any(ord(c)<32 for c in value):
        raise ValueError('wsl_expected_canonical_mnt_c_path')
    path=PurePosixPath(value)
    if (not value.startswith('/mnt/c/') or path.as_posix()!=value
            or any(part in ('.','..') for part in value.split('/'))):
        raise ValueError('wsl_expected_canonical_mnt_c_path')
    host=_within(_host_path('C:/'+str(path.relative_to('/mnt/c'))),_roots(repo_root,shared_out))
    if must_exist and not host.exists():raise ValueError('wsl_shared_input_missing')
    return host


def host_to_linux_path(value,*,repo_root,shared_out,must_exist=False):
    host=_within(_host_path(value),_roots(repo_root,shared_out))
    if must_exist and not host.exists():raise ValueError('wsl_shared_input_missing')
    return '/mnt/c/'+host.as_posix()[3:]


def _relative_file(root,value):
    if type(value) is not str or '\\' in value or ':' in value:
        raise ValueError('wsl_invalid_build_relative_path')
    rel=PurePosixPath(value)
    if rel.is_absolute() or rel.as_posix()!=value or any(p in ('.','..') for p in value.split('/')):
        raise ValueError('wsl_invalid_build_relative_path')
    selected=_host_path(root.joinpath(*rel.parts))
    if not selected.is_relative_to(root):raise ValueError('wsl_build_path_escape')
    return selected


def _check_hash(path,expected,label,identities):
    if type(expected) is not str or len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected):
        raise ValueError('wsl_invalid_'+label+'_sha256')
    if not path.is_file() or profile.digest(path)!=expected:raise ValueError('wsl_'+label+'_hash_mismatch')
    identities[str(path)]=expected


def _elf(path):
    with path.open('rb') as stream:header=stream.read(64)
    if len(header)!=64:raise ValueError('wsl_requires_complete_linux_ELF64')
    fields=struct.unpack('<16sHHIQQQIHHHHHH',header)
    ident,kind,machine,version=fields[:4];entry,phoff,_,_,ehsize,phentsize,phnum=fields[4:11]
    if (ident[:7]!=b'\x7fELF\x02\x01\x01' or ident[7] not in (0,3)
            or kind not in (2,3) or machine!=62 or version!=1 or ehsize!=64 or entry==0
            or phentsize!=56 or phnum<1 or phoff<64 or phoff+phnum*phentsize>path.stat().st_size):
        raise ValueError('wsl_requires_complete_linux_ELF64')
    return dict(class_='ELF64',endianness='little',machine='EM_X86_64',elf_type=kind,program_headers=phnum)


@dataclass(frozen=True)
class CheckedWslSpec:
    linux_spec:dict
    linux_spec_sha256:str
    host_checked_spec:dict
    metadata:dict
    _spec_path:Path=field(repr=False)
    _repo_root:Path=field(repr=False)
    _shared_out:Path=field(repr=False)
    _identities:dict=field(repr=False)

    def verify_unchanged(self):
        # Recheck aliases as well as bytes; moving an identical file behind a
        # junction is still a change in the Windows/WSL path trust boundary.
        # Share ancestor inspections only WITHIN this check, never between
        # requests. Each leaf is still resolved independently to catch an alias
        # introduced after its parent was inspected earlier in this same pass.
        seen=set();roots=(_host_path(self._repo_root,seen),_host_path(self._shared_out,seen))
        for name,expected in self._identities.items():
            path=_within(_host_path(name,seen),roots)
            if not path.is_file() or profile.digest(path)!=expected:
                raise ValueError('wsl_input_changed_after_validation')
        return self.linux_spec_sha256


def validate_wsl_spec(spec_path,*,repo_root,shared_out,distribution=DISTRIBUTION,expected_spec_sha=None):
    if distribution!=DISTRIBUTION:raise ValueError('wsl_distribution_not_authorized')
    roots=_roots(repo_root,shared_out);repo,out=roots
    spec_path=(linux_to_host_path(str(spec_path),repo_root=repo,shared_out=out)
               if str(spec_path).startswith('/') else _within(_host_path(spec_path),roots))
    spec,spec_sha=profile.read_json_snapshot(spec_path)
    if expected_spec_sha is not None and spec_sha!=expected_spec_sha:
        raise ValueError('wsl_spec_changed_after_registration')
    if type(spec) is not dict or spec.get('operator_identity')!='rmcs-sim-operator-fov-v1':
        raise ValueError('wsl_native_operator_identity_mismatch')
    source=spec.get('source_identity',{})
    revision,extra=profile.validate_source_identity(source)
    if revision!='contour-v3' or source.get('is_original_upstream') is not False or source.get('is_baseline_40f7') is not False:
        raise ValueError('wsl_requires_own_T2_contour_v3')
    runtime=_host_path(repo/'operator_native/runtime')
    if runtime!=profile.RUNTIME_ROOT.resolve():raise ValueError('wsl_repo_source_root_mismatch')
    identities={str(spec_path):spec_sha};host=deepcopy(spec)
    for key in ('binary','executor_yaml','autoaim_config','model_share'):
        host[key]=str(linux_to_host_path(spec.get(key),repo_root=repo,shared_out=out))
    hashes=spec.get('sha256',{});frozen=spec.get('frozen_build',{})
    if hashes.get('binary')!=frozen.get('binary_sha256') or spec.get('model_sha256')!=profile.MODEL_SHA256:
        raise ValueError('wsl_native_artifact_declarations_mismatch')
    for key in ('binary','executor_yaml','autoaim_config'):
        _check_hash(Path(host[key]),hashes.get(key),key,identities)
    _check_hash(_host_path(Path(host['model_share'])/'shenzhen-0526.onnx'),profile.MODEL_SHA256,'model',identities)
    mode=hashlib.sha256(b'multi_ekf\n').hexdigest()
    if spec.get('runtime_mode_contents')!='multi_ekf\n' or spec.get('runtime_mode_sha256')!=mode or hashes.get('runtime_mode')!=mode:
        raise ValueError('wsl_runtime_mode_mismatch')
    environment=spec.get('environment',{})
    if type(environment) is not dict or any(k not in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')
            or type(v) is not str or v!='1' for k,v in environment.items()):
        raise ValueError('wsl_native_environment_not_authorized')
    build_path=_host_path(spec_path.parent/'BUILD_MANIFEST.json')
    build,build_sha=profile.read_json_snapshot(build_path,4*1024*1024)
    if build_sha!=frozen.get('manifest_sha256'):raise ValueError('wsl_build_manifest_hash_mismatch')
    identities[str(build_path)]=build_sha
    inputs=build.get('input_identity',{})
    if (build.get('status')!='native_build_succeeded' or build.get('full_clean_compile') is not True
            or build.get('binary_sha256')!=hashes['binary'] or inputs.get('algorithm_identity')!=source
            or inputs.get('corner_refinement')!=revision or inputs.get('additional_source_files')!=extra):
        raise ValueError('wsl_build_source_lineage_mismatch')
    for rel,expected in extra.items():_check_hash(_relative_file(runtime,rel),expected,'frontend',identities)
    generated=inputs.get('generated_sha256',{})
    if generated.get('generated/corners_contour_v1.cpp')!=next(iter(extra.values())):
        raise ValueError('wsl_copied_frontend_identity_mismatch')
    if type(generated) is not dict or not generated:raise ValueError('wsl_generated_inputs_missing')
    for rel,expected in generated.items():_check_hash(_relative_file(spec_path.parent,rel),expected,'generated',identities)
    _check_hash(spec_path.parent/'tracking_mode',mode,'tracking_mode',identities)
    if generated.get('generated/main.cpp')!=OPERATOR_MAIN_SHA256 or generated.get('generated/prepare_fov_hook.py')!=OPERATOR_HOOK_SHA256:
        raise ValueError('wsl_operator_entry_identity_mismatch')
    if inputs.get('operator_hook_sha256')!=OPERATOR_HOOK_SHA256 or inputs.get('model_sha256')!=profile.MODEL_SHA256:
        raise ValueError('wsl_operator_build_inputs_mismatch')
    recovery_path=_relative_file(runtime,'RECOVERY_MANIFEST.json')
    recovery,recovery_sha=profile.read_json_snapshot(recovery_path,4*1024*1024)
    if recovery_sha!=inputs.get('recovery_manifest_sha256'):raise ValueError('wsl_recovery_manifest_identity_mismatch')
    identities[str(recovery_path)]=recovery_sha
    base_source=deepcopy(source)
    for key in ('vision_frontend','tracker_patch_sha256','patch_identity_format'):base_source.pop(key,None)
    base_source['patch_sha256']=source['tracker_patch_sha256']
    if recovery.get('algorithm_identity')!=base_source:raise ValueError('wsl_recovered_tracker_identity_mismatch')
    declared={row['path']:row['sha256'] for row in recovery['files']}
    if inputs.get('source_files')!=declared:raise ValueError('wsl_recovered_source_identity_mismatch')
    for rel,expected in declared.items():_check_hash(_relative_file(runtime,rel),expected,'source',identities)
    for rel,key in (('build_portable.py','portable_entry_sha256'),('CMakeLists.txt','cmake_project_sha256'),('simulation_profile.json','profile_sha256')):
        _check_hash(_relative_file(runtime,rel),inputs.get(key),'build_input',identities)
    elf=_elf(Path(host['binary']));elf['class']=elf.pop('class_')
    if frozen.get('elf')!=elf or build.get('elf')!=elf:raise ValueError('wsl_declared_ELF_identity_mismatch')
    transport_sources={}
    for rel in ('rm_match/deployment/wsl_profile.py',SUPERVISOR,WORKER):
        selected=_relative_file(repo,rel);expected=profile.digest(selected)
        _check_hash(selected,expected,'transport_source',identities);transport_sources[rel]=expected
    metadata=dict(transport=TRANSPORT,distribution=DISTRIBUTION,windows_native=False,
        qualification='Windows host + WSL native; live timing and full-match acceptance not qualified',
        linux_spec_sha256=spec_sha,build_manifest_sha256=build_sha,source_identity=deepcopy(source),
        transport_source_sha256=transport_sources)
    checked=CheckedWslSpec(deepcopy(spec),spec_sha,host,metadata,spec_path,repo,out,identities)
    checked.verify_unchanged()
    return checked


def own_wsl_registry(linux_spec_path,native_out,*,repo_root,distribution=DISTRIBUTION,native_trace=None,transport=TRANSPORT):
    """Explicit opt-in entry point; never selects Windows-native implicitly."""
    from .wsl_registry import own_wsl_registry as make_registry
    return make_registry(linux_spec_path,native_out,repo_root=repo_root,
        distribution=distribution,native_trace=native_trace,transport=transport)
