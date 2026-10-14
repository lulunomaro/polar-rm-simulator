"""Explicit preloaded Windows camera / WSL ELF adapter with live host deadlines."""
from __future__ import annotations
import json
import hashlib
from pathlib import Path
import uuid

from .adapters import BaseAdapter
from .contracts import ContractError,finite
from .native_adapter import NativeSourceAdapter,validate_native_spec


class WslNativeSourceAdapter(NativeSourceAdapter):
    @staticmethod
    def spec_digest(path):
        # Small snapshots do not need the asset hasher's 1 MiB buffer. Still
        # hash every raw byte and reject an unexpectedly unbounded replacement.
        digest=hashlib.sha256();size=0
        with Path(path).open('rb') as stream:
            for chunk in iter(lambda:stream.read(64*1024),b''):
                size+=len(chunk)
                if size>1024*1024:raise ContractError('wsl_spec_size_exceeded')
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def normalized_fov(config):
        if type(config) is not dict or set(config)-{'fov_degrees','circle_radius_x_norm','circle_radius_y_norm'}:
            raise ContractError('invalid_native_config')
        return dict(fov_degrees=finite(config.get('fov_degrees',85.),'fov',10,180),
            circle_radius_x_norm=finite(config.get('circle_radius_x_norm',.25),'circle_x',1e-6,2),
            circle_radius_y_norm=finite(config.get('circle_radius_y_norm',.25),'circle_y',1e-6,2))

    def __init__(self,config,*,checked,out,distribution='Ubuntu',trace=None):
        self.normalized_fov(config)
        from ..deployment.wsl_profile import host_to_linux_path
        if distribution!=checked.metadata['distribution']:raise ContractError('wsl_distribution_not_authorized')
        self.checked_wsl=checked
        self.linux_spec_path=checked._spec_path
        self.distribution=distribution
        self.transport=checked.metadata['transport']
        if self.transport not in ('wsl_stdio_v1','wsl_stdio_bgr_v2'):raise ContractError('wsl_transport_not_authorized')
        self._evidence_required=self.transport=='wsl_stdio_bgr_v2'
        host_to_linux_path(out,repo_root=checked._repo_root,shared_out=checked._shared_out)
        root=Path(out).resolve()
        if not root.is_relative_to(checked._shared_out):raise ContractError('wsl_output_outside_registered_shared_directory')
        root.mkdir(parents=True,exist_ok=True)
        snapshot=root/('host_spec_'+uuid.uuid4().hex+'.json')
        with snapshot.open('x',encoding='utf8',newline='\n') as stream:
            json.dump(checked.host_checked_spec,stream,sort_keys=True,indent=2);stream.write('\n')
        super().__init__(config,spec_path=snapshot,out=root,trace=trace)
        self._evidence_required=self.transport=='wsl_stdio_bgr_v2'
        self._prepared=False;self._bound=False;self._starting=False

    def verify_handover(self):
        from ..deployment.wsl_profile import _host_path,_within
        seen=set()
        roots=(_host_path(self.checked_wsl._repo_root,seen),_host_path(self.checked_wsl._shared_out,seen))
        for path in (self.linux_spec_path,self.spec_path):
            _within(_host_path(path,seen),roots)
            if not path.is_file():raise ContractError('wsl_shared_input_missing')
        if self.spec_digest(self.linux_spec_path)!=self.checked_wsl.linux_spec_sha256:raise ContractError('wsl_spec_changed_after_registration')
        if self.spec_digest(self.spec_path)!=self.spec_sha:raise ContractError('native_spec_changed_after_registration')
        if self._cancelled.is_set():raise ContractError('native_adapter_cancelled')

    def prepare(self):
        """Local setup only: load model and prove stdin-ready without a native tick."""
        if self._cancelled.is_set() or self._bound:raise ContractError('native_adapter_not_preparable')
        if self.process is not None:raise ContractError('native_adapter_already_prepared')
        self._start_process(None)
        with self._lifecycle_lock:
            cancelled=self._cancelled.is_set()
            if not cancelled:self._prepared=True
        if cancelled:self.close();raise ContractError('native_adapter_cancelled')
        return self

    def reset(self,context):
        self.verify_handover()
        BaseAdapter.reset(self,context)
        if self._bound or not self._prepared:self.close()
        self._bound=True;self._prepared=False
        self.stable_since=None;self.anchor=None;self.last_capture=-1;self.last_time=None

    def _start_process(self,episode):
        if self.transport=='wsl_stdio_bgr_v2':
            from ..integrations.wsl_operator_pipe import WslPipeOperatorProcess as WslOperatorProcess
        else:
            from ..integrations.wsl_operator import WslOperatorProcess
        with self._lifecycle_lock:
            if self._cancelled.is_set():raise ContractError('native_adapter_cancelled')
            if self.process is not None or self._starting:raise ContractError('native_adapter_process_already_started')
            self._starting=True
        try:self._start_owned_process(episode,WslOperatorProcess)
        finally:
            with self._lifecycle_lock:self._starting=False

    def _start_owned_process(self,episode,process_type):
        self.checked_wsl.verify_unchanged()
        validate_native_spec(self.spec_path,self.spec_sha)
        if self._cancelled.is_set():raise ContractError('native_adapter_cancelled')
        self.directory=self.root/('binding_'+uuid.uuid4().hex)
        self.directory.mkdir(parents=True,exist_ok=False)
        (self.directory/'tracking_mode').write_text(self.spec['runtime_mode_contents'],newline='\n')
        if self.transport=='wsl_stdio_bgr_v2':
            from .native_evidence import ActualFrameEvidenceWriter
            evidence=ActualFrameEvidenceWriter(self.directory/'actual_frames')
            with self._lifecycle_lock:
                cancelled=self._cancelled.is_set()
                if not cancelled:self._evidence_writer=evidence
            if cancelled:
                evidence.request_stop();evidence.close(timeout=.15)
                raise ContractError('native_adapter_cancelled')
        process=process_type(self.linux_spec_path,self.directory,self.fov,
            distribution=self.distribution,timeout=.08,startup_timeout=15.,
            registered_spec_sha=self.checked_wsl.linux_spec_sha256)
        with self._lifecycle_lock:
            cancelled=self._cancelled.is_set()
            if not cancelled:self.process=process
        if cancelled:
            try:process.request_stop()
            finally:process.close()
            raise ContractError('native_adapter_cancelled')
        try:
            process.reset(dict(episode=episode))
            if self._cancelled.is_set():raise ContractError('native_adapter_cancelled')
        except BaseException:
            try:process.request_stop()
            finally:self.close()
            raise

    def _native_control(self,packet,observation,*,image_bytes=None,prepared_image=None):
        # This is the original host deadline, already capped by the camera's
        # capture_wall + 80ms. Never restart the budget at pipe submission.
        if self._cancelled.is_set():raise ContractError('native_adapter_cancelled')
        if self.transport=='wsl_stdio_bgr_v2':
            if type(image_bytes) is not bytes:raise ContractError('inline_native_image_required')
            packet=dict(packet,image_bytes=image_bytes)
            if prepared_image is not None:packet['prepared_image']=prepared_image
        elif prepared_image is not None:raise ContractError('prepared_native_requires_v2')
        return self.process.control(dict(packet,host_deadline=observation['wall_deadline']))
