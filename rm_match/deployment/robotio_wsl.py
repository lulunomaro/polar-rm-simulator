"""Owned, explicitly prepared WSL peers for navigation/decision components.

Uses the existing birth-bound Windows/Linux supervisor, not bare wsl.exe.
Preparation has no sensor input; binding still needs a real reset ACK under
the original two-second host deadline. One resource belongs to one binding.
This module alone does not qualify actual WSL startup or an algorithm.
"""
from __future__ import annotations
import copy
import math
from pathlib import Path, PurePosixPath
import re
import time
from .decision_plugin import DecisionPluginAdapter, validate_capabilities as decision_capabilities
from .navigation_plugin import NavigationPluginAdapter, validate_capabilities as navigation_capabilities
from .profile import digest
from .wsl_jsonl import OwnedWslJsonProcess, TRANSPORT, validate_linux_settings
from ..platform_v2.contracts import ContractError, exact


class _PreparedWslComponent:
    def __init__(self, *args, repo_root, shared_root, **kwargs):
        super().__init__(*args, **kwargs)
        self.repo_root = Path(repo_root)
        self.shared_root = Path(shared_root)
        self.prepared = False
        self.claimed = False

    def _start_owned_process(self, env):
        return OwnedWslJsonProcess(self.registration, repo_root=self.repo_root,
            shared_root=self.shared_root, stop_event=self._cancelled, env=env)

    def _open_owned_process(self):
        if digest(self.manifest) != self.manifest_sha:
            raise ContractError('custom_manifest_changed_after_registration')
        if self.prepared:
            if self.process is None or self.failed or self._cancelled.is_set() or self.process.poll() is not None:
                raise ContractError('prepared_wsl_component_unavailable')
            self._owned_process.verify_unchanged()
            return
        return super()._open_owned_process()

    def prepare(self, *, startup_timeout=15.):
        if type(startup_timeout) not in (int, float) or not math.isfinite(startup_timeout) or not 0 < startup_timeout <= 15:
            raise ContractError('invalid_wsl_prepare_budget')
        exact(self.config, (), 'wsl_component_binding_config')
        if self.prepared or self.claimed or self.failed or self._cancelled.is_set():
            raise ContractError('wsl_component_prepare_once')
        limit = self.clock() + startup_timeout
        self._open_owned_process()
        self._exchange(dict(op='prepare', config={}), timeout=limit-self.clock())
        self.prepared = True
        # DecisionPluginAdapter has its own prepare guard; actual initialization
        # and the real capabilities-bearing prepare ACK have now both completed.
        if type(self) is WslDecisionPluginAdapter: self._prepared = True
        return self

    def reset(self, context, *, deadline=None):
        if not self.prepared or self.claimed or self.failed or self._cancelled.is_set():
            raise ContractError('wsl_component_requires_fresh_local_preparation')
        kwargs = {} if deadline is None else {'deadline': deadline}
        # The inherited reset performs the real capability handshake. The open
        # hook preserves the same process; it never invents a reset from HELLO.
        super().reset(context, **kwargs)
        self.claimed = True


class WslNavigationPluginAdapter(_PreparedWslComponent, NavigationPluginAdapter):
    pass


class WslDecisionPluginAdapter(_PreparedWslComponent, DecisionPluginAdapter):
    pass


def create_wsl_plugin(row, *, manifest, manifest_sha, repo_root, shared_root, clock=None):
    """Accept only a trusted validated local row; no HTTP executable selection."""
    if type(row) is not dict or row.get('transport') != TRANSPORT or row.get('kind') not in ('navigation', 'decision'):
        raise ContractError('unsupported_owned_wsl_component')
    if type(manifest_sha) is not str or not re.fullmatch(r'[0-9a-f]{64}', manifest_sha):
        raise ContractError('invalid_wsl_component_manifest_identity')
    manifest = Path(manifest).absolute()
    if digest(manifest) != manifest_sha:
        raise ContractError('custom_manifest_changed_after_registration')
    registration = copy.deepcopy(row)
    linux = validate_linux_settings(registration['linux'])
    if registration['command'] != linux['command'] or registration['cwd'] != linux['cwd']:
        raise ContractError('wsl_component_local_settings_mismatch')
    if PurePosixPath(linux['command'][0]).name.lower() in ('wsl', 'wsl.exe'):
        raise ContractError('bare_wsl_component_command_rejected')
    registration['linux'] = linux
    cls = WslNavigationPluginAdapter if row['kind'] == 'navigation' else WslDecisionPluginAdapter
    validator = navigation_capabilities if row['kind'] == 'navigation' else decision_capabilities
    validator(registration['capabilities'])
    kwargs = {} if clock is None else {'clock': clock}
    instance = cls({}, registration=registration, manifest=manifest, manifest_sha=manifest_sha,
        repo_root=repo_root, shared_root=shared_root, **kwargs)
    if row['kind'] == 'navigation':
        instance.descriptor.update(observation_profile='pointcloud_imu_v1',
            ui_config_contract='empty_v1', navigation_plugin_contract='pointcloud_imu_v1',
            navigation_plugin_capabilities=copy.deepcopy(registration['capabilities']),
            supported_robots=list(registration['supported_robots']),
            goal_input_modes=list(registration['capabilities']['goal_input_modes']))
    instance.descriptor.update(plugin_transport=TRANSPORT,
        lifecycle='one_prepared_instance_one_binding_restart_for_rebind',
        qualification='interface_declared_not_algorithm_or_live_acceptance')
    return instance


class PreparedWslPlugins:
    """One owner for each unclaimed component; take transfers ownership once."""
    def __init__(self, rows, *, manifest, manifest_sha, repo_root, shared_root,
                 clock=None, startup_timeout=15.):
        self.path = Path(manifest).absolute(); self.sha = manifest_sha
        self.instances = {}; self.cleanup_status = {}
        try:
            for row in rows:
                aid = row['adapter_id']
                if aid in self.instances: raise ContractError('duplicate_prepared_wsl_component')
                self.instances[aid] = create_wsl_plugin(row, manifest=self.path, manifest_sha=self.sha,
                    repo_root=repo_root, shared_root=shared_root, clock=clock)
            for instance in self.instances.values(): instance.prepare(startup_timeout=startup_timeout)
        except BaseException as exc:
            try: self.close_unclaimed()
            except Exception as cleanup_exc:
                cleanup_exc.resources = self
                cleanup_exc.cleanup_status = copy.deepcopy(self.cleanup_status)
                raise cleanup_exc from exc
            raise

    def take(self, adapter_id, manifest_sha):
        if manifest_sha != self.sha or digest(self.path) != self.sha:
            raise ContractError('prepared_wsl_manifest_changed')
        if adapter_id not in self.instances:
            raise ContractError('prepared_wsl_instance_unavailable_or_claimed')
        instance = self.instances[adapter_id]
        if not instance.prepared or instance.claimed or instance.failed or instance._cancelled.is_set():
            raise ContractError('prepared_wsl_instance_cancelled_or_not_ready')
        if instance.process is None or instance.process.poll() is not None:
            raise ContractError('prepared_wsl_peer_exited')
        instance._owned_process.verify_unchanged()
        return self.instances.pop(adapter_id)

    def close_unclaimed(self, *, deadline=None):
        limit = time.perf_counter()+1.5
        if deadline is not None:
            if type(deadline) not in (int, float) or not math.isfinite(deadline):
                raise ContractError('invalid_wsl_pool_close_deadline')
            limit = min(limit, deadline)
        errors = []
        for aid, instance in tuple(self.instances.items()):
            try:
                instance.close(deadline=limit)
                self.cleanup_status[aid] = copy.deepcopy(instance.shutdown_status)
                if not instance.shutdown_status or instance.shutdown_status.get('clean') is not True:
                    raise RuntimeError('component_cleanup_unproved')
                self.instances.pop(aid)
            except Exception as exc:
                self.cleanup_status[aid] = copy.deepcopy(instance.shutdown_status)
                errors.append(aid+':'+type(exc).__name__)
        if errors: raise RuntimeError('Unclaimed WSL cleanup unproved: '+','.join(errors))
