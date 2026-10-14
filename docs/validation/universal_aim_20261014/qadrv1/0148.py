"""Local opt-in WSL registry; a prepared model is consumed by exactly one binding."""
from __future__ import annotations
import threading
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from .profile import PROFILE,digest
from .wsl_profile import validate_wsl_spec
from ..platform_v2.adapters import Registry,descriptor
from ..platform_v2.contracts import ContractError
from ..platform_v2.wsl_native_adapter import WslNativeSourceAdapter


class WslRegistry(Registry):
    def __init__(self,checked,out,distribution,trace):
        super().__init__();self.checked=checked;self.out=out
        self.distribution=distribution;self.trace=trace
        self._lock=threading.Lock();self._prepared=None;self.native_instance=None
        self._closed=False;self._preparing=False;self._preparing_instance=None
        capabilities={}
        if checked.metadata['transport']=='wsl_async_bgr_v3':capabilities['aim_plugin_contract']='camera_gimbal_v1'
        self.register(descriptor('aim_native_rmcs_v1','aim',
            'Own RMCS T2, Windows camera / WSL native (stationary red sentry)',
            ('camera','odometry'),supported_robots=['red_sentry'],stationary_only=True,
            confidence_available=False,max_camera_age_sim_s=.08,max_camera_age_wall_s=.08,schedule_on_camera_frame=True,
            source_identity=checked.linux_spec['source_identity'],deployment_profile=PROFILE,
            transport=checked.metadata['transport'],windows_native=False,**capabilities),self._make)

    def _new(self,config):
        return WslNativeSourceAdapter(config,checked=self.checked,out=self.out,
            distribution=self.distribution,trace=self.trace)

    def prepare_native(self,config=None):
        # The local caller performs this before starting its physics clock.
        with self._lock:
            if self._closed:raise ContractError('wsl_registry_closed')
            if self._prepared is not None or self._preparing:raise ContractError('native_already_prepared')
            self._preparing=True
        instance=None
        try:
            instance=self._new({} if config is None else config)
            with self._lock:
                cancelled=self._closed
                if not cancelled:self._preparing_instance=instance
            if cancelled:raise ContractError('wsl_registry_closed')
            instance.prepare()
            with self._lock:
                cancelled=self._closed or instance._cancelled.is_set()
                if not cancelled:self._prepared=instance;self.native_instance=instance
            if cancelled:raise ContractError('wsl_registry_closed')
            return instance
        except BaseException:
            if instance is not None:
                try:instance.cancel()
                finally:instance.close()
            raise
        finally:
            with self._lock:self._preparing=False;self._preparing_instance=None

    def _make(self,config):
        normalized=WslNativeSourceAdapter.normalized_fov(config)
        instance=None
        try:
          with self._lock:
            if self._closed:raise ContractError('wsl_registry_closed')
            if self._preparing:raise ContractError('native_preparation_in_progress')
            instance=self._prepared
            # Inputs loaded into a prepared process have frozen identity already.
            # Recheck the small original spec and controlled host snapshot at
            # handover. Full asset/source checks happen before every new process.
            if instance is not None:
                instance.verify_handover()
                if normalized!=instance.fov:raise ContractError('prepared_native_config_mismatch')
                self._prepared=None
            elif WslNativeSourceAdapter.spec_digest(self.checked._spec_path)!=self.checked.linux_spec_sha256:
                raise ContractError('wsl_spec_changed_after_registration')
          if instance is None:instance=self._new(config)
          with self._lock:
            if self._closed:raise ContractError('wsl_registry_closed')
            self.native_instance=instance
            return instance
        except BaseException:
            if instance is not None:
                with self._lock:
                    if self._prepared is instance:self._prepared=None
                try:instance.cancel()
                finally:instance.close()
            raise

    def close(self):
        with self._lock:
            self._closed=True;instance=self._prepared;self._prepared=None
            preparing=self._preparing_instance
        # Startup owner performs close; don't race its pipe creation/reaping.
        if preparing is not None:preparing.cancel()
        if instance is not None:
            try:instance.cancel()
            finally:instance.close()


def own_wsl_registry(linux_spec_path,native_out,*,repo_root,distribution='Ubuntu',native_trace=None,transport='wsl_stdio_v1'):
    if transport not in ('wsl_stdio_v1','wsl_stdio_bgr_v2','wsl_async_bgr_v3'):raise ContractError('wsl_transport_not_authorized')
    checked=validate_wsl_spec(linux_spec_path,repo_root=repo_root,
        shared_out=native_out,distribution=distribution)
    if transport in ('wsl_stdio_bgr_v2','wsl_async_bgr_v3'):
        # Distinct, explicit bytes transport; bind both added programs at startup.
        from .wsl_profile import _host_path
        sources={};identities=dict(checked._identities);metadata=deepcopy(checked.metadata)
        paths=['rm_match/integrations/wsl_operator_pipe.py','rm_match/integrations/wsl_operator_pipe_worker.py']
        if transport=='wsl_async_bgr_v3':paths+=['rm_match/integrations/wsl_aim_async.py','rm_match/integrations/wsl_aim_async_worker.py']
        for rel in paths:
            selected=_host_path(Path(repo_root)/rel)
            if not selected.is_relative_to(checked._repo_root):raise ContractError('wsl_transport_source_outside_repository')
            sha=digest(selected);identities[str(selected)]=sha;sources[rel]=sha
        metadata.update(transport=transport,image_transport='exact_inline_bgr_to_owned_linux_tmpfs',
            qualification='Explicit Windows host + WSL inline BGR; live/full-match/Windows-native acceptance not qualified')
        metadata['transport_source_sha256'].update(sources)
        if transport=='wsl_async_bgr_v3':
            metadata.update(image_transport='exact_inline_bgr_one_original_async_compute',
                compute_watchdog_s=1.,late_response_policy='discard_original_frame_never_relabel',
                qualification='Explicit async transport; pending is not inference or actuation; live qualification requires actual fresh samples')
        checked=replace(checked,metadata=metadata,_identities=identities)
        checked.verify_unchanged()
    return WslRegistry(checked,native_out,distribution,native_trace)
