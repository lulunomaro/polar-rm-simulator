"""Linux PB algorithm children in the generic peer's already-owned session.

No wsl.exe, extra JSONL process layer, hardware launch, package setup script or
model warmup. Only locally pinned executable/parameter references are accepted.
"""
from __future__ import annotations
import hashlib
import copy
import json
import os
from pathlib import Path
import signal
import re
import subprocess
import time
from .owned_linux_group import _stat
from .pb_aim_configure import NODES
from ..deployment.profile import read_json_snapshot
from ..platform_v2.contracts import ContractError,exact

STACK_SCHEMA='polar.sim.pb-aim-stack.v1'

def checked_ref(ref):
    exact(ref,('path','sha256'),'pb_aim_stack_ref')
    if type(ref['path']) is not str or type(ref['sha256']) is not str:raise ContractError('pb_aim_ref_type')
    path=Path(ref['path'])
    if (not path.is_absolute() or any(p.is_symlink() for p in (path,*path.parents))
        or not path.is_file()):raise ContractError('pb_aim_ref_path')
    before=path.stat()
    raw=path.read_bytes()
    after=path.stat()
    if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
        raise ContractError('pb_aim_ref_changed_during_read')
    if hashlib.sha256(raw).hexdigest()!=ref['sha256']:raise ContractError('pb_aim_ref_hash_changed')
    return path,raw

def scoped_parameters(original_raw,namespace):
    """Complete original YAML values under exact node names, with frame/time overrides.

    JSON is a YAML subset understood by ROS' parameter parser. No threshold,
    model, EKF, prediction, solver or firing parameter is supplied by a caller.
    """
    if type(namespace) is not str or not re.fullmatch(r'/[A-Za-z][A-Za-z0-9_/]*',namespace) or namespace.endswith('/') or '//' in namespace:
        raise ContractError('pb_aim_scoped_namespace')
    import yaml
    original=yaml.safe_load(original_raw)
    if type(original) is not dict:raise ContractError('pb_aim_original_parameters')
    values={}
    for name in NODES:
        entry=original.get(name)
        exact(entry,('ros__parameters',),'pb_aim_original_node_parameters')
        params=copy.deepcopy(entry['ros__parameters'])
        if type(params) is not dict:raise ContractError('pb_aim_original_parameters')
        params['use_sim_time']=True
        if name=='armor_tracker':params['target_frame']='gimbal_aim_origin'
        if name=='projectile_motion':params['projectile']['target_frame']='shooter_link'
        values[namespace+'/'+name]={'ros__parameters':params}
    return (json.dumps(values,ensure_ascii=True,allow_nan=False,sort_keys=True,indent=2)+'\n').encode()

def load_stack(ref,sha):
    path,raw=checked_ref(dict(path=str(Path(ref).absolute()),sha256=sha))
    spec,current=read_json_snapshot(path)
    exact(spec,('schema','run_uuid','namespace','domain_id','calibration_id','adapter_id','executables',
        'params','params_original','mount','model','labels','environment','source_manifest'),'pb_aim_stack')
    if spec['schema']!=STACK_SCHEMA or current!=sha:raise ContractError('pb_aim_stack_schema_or_race')
    if type(spec['run_uuid']) is not str or not re.fullmatch(r'[0-9a-f]{32}',spec['run_uuid']):raise ContractError('pb_aim_stack_run_uuid')
    if type(spec['domain_id']) is not int or not 0<=spec['domain_id']<=232:raise ContractError('pb_aim_stack_domain')
    if type(spec['calibration_id']) is not str or not spec['calibration_id']:raise ContractError('pb_aim_stack_calibration')
    if type(spec['adapter_id']) is not str or not spec['adapter_id'].startswith('custom_'):raise ContractError('pb_aim_stack_adapter')
    exact(spec['executables'],NODES,'pb_aim_algorithm_nodes')
    for name,reference in spec['executables'].items():
        binary,data=checked_ref(reference)
        if data[:5]!=b'\x7fELF\x02' or not os.access(binary,os.X_OK):raise ContractError('pb_aim_actual_elf_required')
    for name in ('params','params_original','mount','model','labels','environment','source_manifest'):checked_ref(spec[name])
    _,original=checked_ref(spec['params_original']);_,params=checked_ref(spec['params'])
    if params!=scoped_parameters(original,spec['namespace']):raise ContractError('pb_aim_scoped_parameters_changed')
    source_manifest,source_sha=read_json_snapshot(Path(spec['source_manifest']['path']))
    if (source_sha!=spec['source_manifest']['sha256'] or source_manifest.get('schema')!='polar.pb-aim-source-overlay.v1'
        or source_manifest.get('commit')!='df1892c48f90093f86a2f7b02af6441a80aa2d97'
        or 'startup_protocol' not in source_manifest or 'source_safety_hook' not in source_manifest):
        raise ContractError('pb_aim_reviewed_source_manifest_required')
    source_root=Path(spec['source_manifest']['path']).parent
    repo=Path(__file__).resolve().parents[2]
    checked_ref(dict(path=str(repo/'tools/prepare_pb_aim_plugin.py'),sha256=source_manifest['generator_sha256']))
    required_bindings={'rm_match/integrations/pb_aim_engine.py','rm_match/integrations/pb_aim_stack.py',
        'rm_match/integrations/pb_aim_configure.py','rm_match/integrations/pb_aim_ros_peer.py',
        'rm_match/integrations/pb_aim_contract.py','rm_match/integrations/aim_camera_codec.py',
        'rm_match/integrations/aim_jsonl_peer.py','tools/prepare_pb_aim_stack.py',
        'rm_match/integrations/ros2_bridge.py','rm_match/platform_v2/aim_contracts.py','rm_match/platform_v2/contracts.py'}
    bindings=source_manifest.get('adapter_sources_sha256',{})
    if set(bindings)!=required_bindings:raise ContractError('pb_aim_adapter_source_bindings')
    for relative,wanted in bindings.items():checked_ref(dict(path=str(repo/relative),sha256=wanted))
    generated=source_manifest.get('generated_sha256',{})
    if type(generated) is not dict or not generated:raise ContractError('pb_aim_generated_source_required')
    for relative,wanted in source_manifest.get('generated_sha256',{}).items():
        if type(relative) is not str or Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise ContractError('pb_aim_source_relative_path')
        checked_ref(dict(path=str(source_root/relative),sha256=wanted))
    if hashlib.sha256(original).hexdigest()!=source_manifest['generated_sha256']['PB_AIM_PARAMS.yaml']:
        raise ContractError('pb_aim_original_params_source_required')
    cpp='src/projectile_motion/src/projectile_motion_node.cpp'
    if source_manifest['source_safety_hook']['generated_cpp_sha256']!=generated[cpp]:
        raise ContractError('pb_aim_safety_hook_source_binding')
    if spec['model']['sha256']!='b3250176ea8fdbe6d1585be954363757ff6a8245a81e8797f16cea601976d47a':
        raise ContractError('pb_aim_original_model_required')
    if spec['labels']['sha256']!='8cc04e2a54c7ee1c39925c9ca8e6eebe2d1015ee9dab77ab3befd8095be74411':
        raise ContractError('pb_aim_original_labels_required')
    return spec

class PBAlgorithmStack:
    """Three direct children share the outer birth-bound Linux session owner."""
    def __init__(self,spec,*,clock=time.monotonic):
        self.spec=spec;self.clock=clock;self.children=[];self._prepared=False;self._closed=False
        self.pid=os.getpid();self.births=[];self.cleanup=None

    def start(self,environment):
        if self._prepared or self._closed:raise ContractError('pb_aim_stack_start_once')
        if os.name!='posix' or not Path('/proc/self/stat').is_file():raise ContractError('pb_aim_linux_stack_required')
        self.boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();self._prepared=True
        for name in NODES:
            path,_=checked_ref(self.spec['executables'][name])
            argv=[str(path),'--ros-args','--params-file',self.spec['params']['path'],
                '-r','__node:='+name,'-r','__ns:='+self.spec['namespace'],
                '-r','/tf:=tf','-r','/tf_static:=tf_static','-r','/clock:=clock',
                '-p','pb.run_uuid:='+self.spec['run_uuid'],'-p','pb.calibration_id:='+self.spec['calibration_id']]
            # Remain in the generic peer's owned session/group; outer cleanup
            # can reap this entire tree after EOF/cancel, even if peer fails.
            child=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=None,stderr=None,
                env=environment,start_new_session=False,close_fds=True)
            self.children.append(child)
            birth=_stat(child.pid)
            if birth is None or birth['ppid']!=self.pid or birth['pgid']!=os.getpgrp():
                raise ContractError('pb_aim_node_birth_unverified')
            self.births.append(birth)

    def check_alive(self):
        if any(child.poll() is not None for child in self.children):raise ContractError('pb_aim_original_node_exited')

    def close(self,timeout=1.):
        if self._closed:return self.cleanup
        self._closed=True;deadline=self.clock()+min(1.,timeout);errors=[]
        def send(child,birth,sig):
            if child.poll() is not None:return
            row=_stat(child.pid)
            if (Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=self.boot or row is None
                or row['ppid']!=self.pid or row['start_ticks']!=birth['start_ticks'] or row['pgid']!=birth['pgid']):
                errors.append('pb_aim_node_birth_changed');return
            child.send_signal(sig)
        for child,birth in zip(self.children,self.births):
            try:send(child,birth,signal.SIGTERM)
            except (OSError,ContractError) as exc:errors.append(type(exc).__name__)
        term_deadline=min(deadline,self.clock()+.15)
        while self.clock()<term_deadline and any(child.poll() is None for child in self.children):
            time.sleep(min(.005,max(0.,term_deadline-self.clock())))
        for child,birth in zip(self.children,self.births):
            try:send(child,birth,signal.SIGKILL)
            except (OSError,ContractError) as exc:errors.append(type(exc).__name__)
        for child in self.children:
            try:child.wait(timeout=max(0.,deadline-self.clock()))
            except subprocess.TimeoutExpired:errors.append('pb_aim_node_reap_timeout')
        remaining=[child.pid for child in self.children if child.poll() is None]
        if len(self.births)!=len(self.children):errors.append('pb_aim_partial_start_unverified')
        self.cleanup=dict(clean=not errors and not remaining,remaining_pids=remaining,errors=errors,
            scope='Direct algorithm children only; outer birth-bound session owner must prove all descendants empty')
        if not self.cleanup['clean']:raise ContractError('pb_aim_stack_cleanup_incomplete')
        return self.cleanup
