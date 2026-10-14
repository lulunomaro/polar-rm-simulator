"""Explicit, locally prepared WSL JSONL aim transport; not a sandbox.

Preparation owns a real peer and acknowledges its actual factory loading. A
binding still sends a fresh reset and waits under the unchanged two-second gate.
One prepared instance can be handed over once; rebind requires new preparation.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import queue
import re
import sys
import threading
import time
import uuid
from .aim_plugin import AimPluginAdapter
from .json_adapter import MAX_RESPONSE
from .json_owned_process import OwnedJsonProcess, OwnedJsonLaunchFailure
from .profile import digest
from ..platform_v2.adapters import BaseAdapter
from ..platform_v2.contracts import ContractError, exact

TRANSPORT='wsl_jsonl_v1'
PREFIX=b'@polar-wsl-jsonl:'
SOURCE_FILES=('rm_match/deployment/wsl_jsonl.py','rm_match/deployment/wsl_jsonl_worker.py',
    'rm_match/deployment/wsl_jsonl_owned_tree.py',
    'rm_match/deployment/json_owned_process.py','rm_match/deployment/windows_owned_job.py',
    'rm_match/deployment/json_adapter.py','rm_match/deployment/aim_plugin.py',
    'rm_match/integrations/aim_jsonl_peer.py','rm_match/integrations/owned_linux_group.py')

def linux_path(value):
    if type(value) is not str or not value.startswith('/') or '\\' in value or '\0' in value:
        raise ContractError('absolute_local_linux_path_required')
    path=PurePosixPath(value)
    if '..' in path.parts or str(path)!=value or value.startswith('//'):
        raise ContractError('normalized_local_linux_path_required')
    return value

def validate_linux_settings(value):
    exact(value,('distribution','python','command','cwd','process_env'),'local_wsl_settings')
    if type(value['distribution']) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}',value['distribution']):
        raise ContractError('explicit_local_wsl_distribution_required')
    linux_path(value['python']);linux_path(value['cwd'])
    command=value['command']
    if type(command) is not list or not 1<=len(command)<=32 or any(type(v) is not str or not v or len(v)>4096 or '\0' in v for v in command):
        raise ContractError('invalid_local_wsl_argv')
    linux_path(command[0])
    env=value['process_env']
    if type(env) is not dict or len(env)>32:raise ContractError('invalid_local_wsl_environment')
    for key,item in env.items():
        if type(key) is not str or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}',key) or key in ('PYTHONPATH','PYTHONHOME','WSLENV') or re.search(r'CREDENTIAL|SECRET|TOKEN|PASSWORD',key):
            raise ContractError('unsupported_local_wsl_environment_key')
        if type(item) is not str or len(item)>8192 or '\0' in item:raise ContractError('invalid_local_wsl_environment_value')
    return copy.deepcopy(value)

def checked_shared_path(path,root):
    path=Path(path).absolute();root=Path(root).absolute()
    if not path.is_relative_to(root):raise ContractError('wsl_output_outside_explicit_root')
    cursor=path
    while True:
        if cursor.exists():
            stat=cursor.lstat()
            if cursor.is_symlink() or getattr(stat,'st_file_attributes',0)&0x400:
                raise ContractError('wsl_shared_links_rejected')
        if cursor==root:break
        cursor=cursor.parent
    if path.resolve()!=path:raise ContractError('wsl_shared_path_not_canonical')
    return path

def mounted_path(path):
    path=Path(path)
    if not re.fullmatch(r'[A-Za-z]:',path.drive) or not path.is_absolute():
        raise ContractError('wsl_shared_path_requires_local_drive')
    return '/mnt/'+path.drive[0].lower()+'/'+ '/'.join(path.parts[1:])

def validate_hello(value,run_id,sha):
    exact(value,('event','run_id','spec_sha256','worker_pid','worker_start_ticks','boot_id','peer_identity','algorithm_ready'),'wsl_hello')
    if value['event']!='hello' or value['run_id']!=run_id or value['spec_sha256']!=sha or value['algorithm_ready'] is not False:
        raise ContractError('wsl_jsonl_ownership_hello_mismatch')
    if any(type(value[k]) is not int or value[k]<=1 for k in ('worker_pid','worker_start_ticks')) or type(value['boot_id']) is not str:
        raise ContractError('wsl_hello_birth_identity_invalid')
    peer=value['peer_identity']
    exact(peer,('run_id','supervisor_pid','boot_id','pid','pgid','leader_start_ticks'),'wsl_peer_identity')
    if any(type(peer[k]) is not int or peer[k]<=1 for k in ('supervisor_pid','pid','pgid','leader_start_ticks')) or type(peer['run_id']) is not str:
        raise ContractError('wsl_peer_birth_identity_invalid')
    if peer['supervisor_pid']!=value['worker_pid'] or peer['boot_id']!=value['boot_id'] or peer['pgid']!=peer['pid']:
        raise ContractError('wsl_peer_owner_identity_mismatch')
    return copy.deepcopy(value)

def validate_cleanup(record,run_id,sha,hello):
    exact(record,('event','run_id','spec_sha256','hello','ownership','io_thread_stopped','clean','error_type'),'wsl_cleanup')
    if type(record) is not dict or record.get('event')!='cleanup' or record.get('run_id')!=run_id or record.get('spec_sha256')!=sha:
        raise ContractError('wsl_cleanup_run_identity_mismatch')
    if hello is not None and record.get('hello')!=hello:raise ContractError('wsl_cleanup_birth_identity_mismatch')
    proof=record.get('ownership')
    if type(proof) is not dict or proof.get('clean') is not True or proof.get('group_empty') is not True or not (proof.get('reaped') is True or proof.get('not_spawned') is True) or record.get('clean') is not True or record.get('io_thread_stopped') is not True:
        raise ContractError('wsl_linux_cleanup_unproved')
    recorded_hello=record.get('hello')
    if recorded_hello is not None:
        validate_hello(recorded_hello,run_id,sha)
        peer=recorded_hello.get('peer_identity')
        if type(peer) is not dict or any(type(proof.get(k)) is not type(v) or proof.get(k)!=v for k,v in peer.items()):
            raise ContractError('wsl_cleanup_peer_identity_mismatch')
    elif proof.get('not_spawned') is not True:raise ContractError('wsl_spawned_peer_birth_identity_missing')
    return copy.deepcopy(record)

class _Lines:
    def __init__(self,owner):self.owner=owner
    def readline(self,limit):
        row=self.owner._rows.get()
        if isinstance(row,BaseException):raise row
        if len(row)>limit:raise ContractError('wsl_jsonl_response_oversized')
        return row
    def close(self):pass

class OwnedWslJsonProcess:
    def __init__(self,registration,*,repo_root,shared_root,stop_event,env):
        if sys.platform!='win32':raise ContractError('wsl_jsonl_host_requires_windows')
        self.run_id=uuid.uuid4().hex;self.hello=None;self.status=None;self._rows=queue.Queue(1)
        self._stop=stop_event;self._reader=None;self._owned=None;self._launch_status=None;self.child=self
        self.repo_root=checked_shared_path(repo_root,repo_root)
        shared_root=checked_shared_path(shared_root,self.repo_root);shared_root.mkdir(parents=True,exist_ok=True)
        self.out=checked_shared_path(shared_root/('wsl_jsonl_'+self.run_id),self.repo_root);self.out.mkdir()
        settings=validate_linux_settings(registration['linux'])
        self.source_sha={rel:digest(self.repo_root/rel) for rel in SOURCE_FILES}
        spec=dict(run_id=self.run_id,linux=settings,source_sha256=self.source_sha)
        raw=json.dumps(spec,allow_nan=False,separators=(',',':')).encode()
        self.sha=hashlib.sha256(raw).hexdigest();spec_path=self.out/'SPEC.json';spec_path.write_bytes(raw)
        self._spec_bytes=raw;self._spec_path=spec_path
        command=[str(Path(os.environ['SystemRoot'])/'System32'/'wsl.exe'),'-d',settings['distribution'],
            '--cd',mounted_path(self.repo_root),'--',settings['python'],'-m','rm_match.deployment.wsl_jsonl_worker',
            '--spec',mounted_path(spec_path),'--sha256',self.sha]
        host_env=dict(env)
        for key in tuple(host_env):
            if re.search(r'CREDENTIAL|SECRET|TOKEN|PASSWORD',key,re.I) or key in ('WSLENV','PYTHONPATH','PYTHONHOME'):
                host_env.pop(key,None)
        try:
            self._owned=OwnedJsonProcess(command,cwd=str(self.repo_root),env=host_env,stop_event=stop_event)
            self.stdin=self._owned.child.stdin;self.stdout=_Lines(self)
            self._reader=threading.Thread(target=self._read,daemon=True,name='wsl-jsonl-host-reader');self._reader.start()
        except BaseException as exc:
            self._launch_status=getattr(exc,'cleanup_status',None)
            try:status=self.cleanup(time.perf_counter()+1.5)
            except Exception:status=dict(clean=False,reaped=False,group_empty=False,errors=['wsl_launch_cleanup_unproved'])
            raise OwnedJsonLaunchFailure(exc,status) from exc
    def _read(self):
        buffer=bytearray()
        try:
            while True:
                part=self._owned.child.stdout.read(65536)
                if not part:raise EOFError('WSL JSONL supervisor stdout closed')
                buffer.extend(part)
                while b'\n' in buffer:
                    line,_,tail=buffer.partition(b'\n');buffer=bytearray(tail)
                    if len(line)>MAX_RESPONSE:raise ContractError('wsl_jsonl_response_oversized')
                    if line.startswith(PREFIX):
                        from .wsl_jsonl_worker import strict_json
                        value=strict_json(line[len(PREFIX):])
                        if self.hello is not None:raise ContractError('duplicate_wsl_hello')
                        self.hello=validate_hello(value,self.run_id,self.sha)
                    else:self._rows.put_nowait(bytes(line)+b'\n')
                if len(buffer)>MAX_RESPONSE:raise ContractError('wsl_jsonl_response_oversized')
        except BaseException as exc:
            try:self._rows.put_nowait(exc)
            except queue.Full:pass
    def poll(self):return self._owned.child.poll()
    def verify_unchanged(self):
        if self._spec_path.read_bytes()!=self._spec_bytes or any(digest(self.repo_root/rel)!=sha for rel,sha in self.source_sha.items()):
            raise ContractError('prepared_wsl_supervisor_identity_changed')
    @property
    def returncode(self):return self._owned.child.returncode
    def request_stop(self):
        self._stop.set()
        checked_shared_path(self.out,self.repo_root)
        target=checked_shared_path(self.out/'STOP',self.repo_root)
        temporary=checked_shared_path(self.out/('STOP_'+uuid.uuid4().hex+'.tmp'),self.repo_root)
        # Cancellation targets the original run even if its config was changed.
        # Changing input identity may reject work; it must not orphan ownership.
        with temporary.open('xb') as stream:
            stream.write(json.dumps(dict(run_id=self.run_id,spec_sha256=self.sha)).encode())
        temporary.replace(target)
    def cleanup(self,deadline):
        if self.status is not None:return copy.deepcopy(self.status)
        if self._owned is None and self._launch_status is not None and self._launch_status.get('not_spawned') is True:
            # Original suspended-Windows launch proof: no wsl.exe ever executed,
            # so no Linux child existed. This is distinct from a reaped child.
            proof=copy.deepcopy(self._launch_status)
            self.status=dict(clean=proof.get('clean') is True,not_spawned=True,reaped=False,
                group_empty=proof.get('group_empty') is True,windows=proof,
                linux=dict(not_spawned=True,source='owned_windows_before_execute_launch_proof'),
                errors=list(proof.get('errors',[])),transport=TRANSPORT,run_id=self.run_id)
            return copy.deepcopy(self.status)
        errors=[];linux=None;windows=None
        try:self.request_stop()
        except Exception as exc:errors.append('stop:'+type(exc).__name__)
        while time.perf_counter()<deadline-.1:
            if (self.out/'CLEANUP.json').is_file():
                try:
                    from .wsl_jsonl_worker import strict_json
                    path=checked_shared_path(self.out/'CLEANUP.json',self.repo_root)
                    raw=path.read_bytes()
                    if len(raw)>MAX_RESPONSE:raise ContractError('wsl_cleanup_oversized')
                    linux=validate_cleanup(strict_json(raw),self.run_id,self.sha,self.hello)
                except Exception as exc:errors.append('linux_proof:'+type(exc).__name__)
                break
            time.sleep(.005)
        if linux is None:errors.append('linux_owned_cleanup_unproved')
        if self._owned is not None:
            try:windows=self._owned.cleanup(deadline)
            except Exception as exc:errors.append('windows_cleanup:'+type(exc).__name__)
            if not windows or windows.get('clean') is not True:errors.append('windows_job_cleanup_unproved')
        elif self._launch_status is not None:
            windows=copy.deepcopy(self._launch_status)
            if windows.get('clean') is not True or windows.get('group_empty') is not True:
                errors.append('windows_launch_cleanup_unproved')
        else:errors.append('windows_launch_identity_unproved')
        if self._reader is not None:
            self._reader.join(max(0,deadline-time.perf_counter()))
            if self._reader.is_alive():errors.append('wsl_host_reader_not_stopped')
        self.status=dict(clean=not errors,reaped=bool(windows and windows.get('reaped')),
            group_empty=not errors,linux=linux,windows=windows,errors=errors,transport=TRANSPORT,
            resource_budget_s=1.5,run_id=self.run_id)
        return copy.deepcopy(self.status)
    def release_handles(self):
        if self._owned is not None:
            try:self._owned.child.stdout.close()
            finally:self._owned.release_handles()

class WslAimPluginAdapter(AimPluginAdapter):
    def __init__(self,*args,repo_root,shared_root,**kwargs):
        super().__init__(*args,**kwargs)
        self.repo_root=Path(repo_root);self.shared_root=Path(shared_root);self.prepared=False;self.claimed=False
    def _start_owned_process(self,env):
        return OwnedWslJsonProcess(self.registration,repo_root=self.repo_root,shared_root=self.shared_root,
            stop_event=self._cancelled,env=env)
    def prepare(self,*,startup_timeout=15.):
        if type(startup_timeout) not in (float,int) or not 0<startup_timeout<=15:raise ContractError('invalid_wsl_prepare_budget')
        exact(self.config,(),'aim_plugin_binding_config')
        self._open_owned_process()
        self._exchange(dict(op='prepare',config={}),timeout=float(startup_timeout))
        self.prepared=True;return self
    def reset(self,context):
        exact(self.config,(),'aim_plugin_binding_config')
        if not self.prepared or self.claimed or self.failed or self._cancelled.is_set():raise ContractError('wsl_plugin_requires_fresh_local_preparation')
        if digest(self.manifest)!=self.manifest_sha:raise ContractError('custom_manifest_changed_after_registration')
        self._owned_process.verify_unchanged()
        BaseAdapter.reset(self,context)
        self._exchange(dict(op='reset',context=context,config={}),timeout=2.)
        self.claimed=True

class PreparedWslAimPlugins:
    """Trusted startup resource owner. Unclaimed resources must be closed."""
    def __init__(self,path,*,repo_root,shared_root,clock=None,startup_timeout=15.):
        from .aim_plugin import load_aim_plugins
        self.path=Path(path).absolute();rows,self.sha=load_aim_plugins(self.path);self.instances={}
        try:
            for row in rows:
                if row['transport']!=TRANSPORT:continue
                kwargs={} if clock is None else dict(clock=clock)
                instance=WslAimPluginAdapter({},registration=row,manifest=self.path,manifest_sha=self.sha,
                    repo_root=repo_root,shared_root=shared_root,**kwargs)
                self.instances[row['adapter_id']]=instance
                instance.prepare(startup_timeout=startup_timeout)
        except BaseException as exc:
            try:self.close_unclaimed()
            except Exception as cleanup_exc:
                cleanup_exc.resources=self
                cleanup_exc.cleanup_status={key:copy.deepcopy(value.shutdown_status) for key,value in self.instances.items()}
                raise cleanup_exc from exc
            raise
    def take(self,adapter_id,manifest_sha):
        if manifest_sha!=self.sha or digest(self.path)!=self.sha:raise ContractError('prepared_wsl_manifest_changed')
        if adapter_id not in self.instances:raise ContractError('prepared_wsl_instance_unavailable_or_claimed')
        instance=self.instances[adapter_id]
        if not instance.prepared or instance.failed or instance._cancelled.is_set():
            raise ContractError('prepared_wsl_instance_cancelled_or_not_ready')
        instance._owned_process.verify_unchanged()
        return self.instances.pop(adapter_id)
    def close_unclaimed(self):
        errors=[]
        for key,instance in tuple(self.instances.items()):
            try:
                instance.close()
                self.instances.pop(key)
            except Exception as exc:errors.append(key+':'+type(exc).__name__)
        if errors:raise RuntimeError('Unclaimed WSL cleanup unproved: '+','.join(errors))
