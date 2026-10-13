"""Trusted local Windows registration; HTTP selects only the registered ID."""
from __future__ import annotations
import threading
import time
from pathlib import Path
from ..deployment.profile import read_json_snapshot,digest
from ..platform_v2.adapters import BaseAdapter,descriptor
from ..platform_v2.contracts import ContractError,IDENTITY,exact,validate_action
from ..platform_v2.navigation_contracts import NAV_PROFILE,validate_navigation_observation,validate_navigation_status
from .pb_wsl_navigation import WslNavigationSession

SCHEMA='polar.sim.pb-wsl-navigation-manifest.v1'
ADAPTER_ID='custom_pb_navigation'


class WslNavigationAdapter(BaseAdapter):
    def __init__(self,session,config,manifest,manifest_sha,*,clock):
        exact(config,(),'pb_wsl_empty_config')
        self.session=session;self.manifest=Path(manifest);self.manifest_sha=manifest_sha;self.clock=clock
        self.failed=False;self.context=None
        self.descriptor=navigation_descriptor()

    def reset(self,context):
        if self.failed or self.context is not None:raise ContractError('pb_wsl_instance_single_use')
        if digest(self.manifest)!=self.manifest_sha:raise ContractError('pb_wsl_manifest_changed')
        super().reset(context)
        try:self.session.reset(context,{})
        except BaseException:self.failed=True;self.session.request_stop();raise

    def act(self,observation):
        if self.failed or self.context is None:raise ContractError('pb_wsl_unavailable')
        o=validate_navigation_observation(observation)
        if any(type(o[k]) is not type(v) or o[k]!=v for k,v in self.context.items()):raise ContractError('pb_wsl_generation_changed')
        remaining=min(.15,o['wall_deadline']-self.clock())
        if remaining<=0:raise ContractError('pb_wsl_original_deadline_expired')
        try:
            reply=self.session.exchange(dict(op='act',observation=o),timeout=remaining)
            field='status' if 'status' in reply else 'action'
            exact(reply,('schema','op','ok',field),'pb_wsl_reply')
            if reply['schema']!='polar.sim.adapter.jsonl.v1' or reply['op']!='act' or reply['ok'] is not True:raise ContractError('pb_wsl_reply_identity')
            result=validate_navigation_status(reply[field],o) if field=='status' else validate_action(reply[field],o,self.descriptor)
            if any(type(result[k]) is not type(o[k]) or result[k]!=o[k] for k in IDENTITY):raise ContractError('pb_wsl_reply_source')
            if self.clock()>=o['wall_deadline']:raise ContractError('pb_wsl_response_after_original_deadline')
            return result
        except BaseException:self.failed=True;self.session.request_stop();raise

    def cancel(self):self.failed=True;self.session.request_stop()
    def close(self):self.cancel();self.session.close()


def navigation_descriptor():
    result=descriptor(ADAPTER_ID,'navigation','PB2025 sourced navigation / Windows + WSL Humble',
        ['pointcloud','imu'],observation_profile=NAV_PROFILE,
        local_registration=True,process_isolation='not_a_security_sandbox',supported_robots=['red_sentry'],
        qualification='opt_in_single_generation_windows_wsl_not_full_match_or_hardware')
    result['ui_config_contract']='empty_v1';return result


def register_pb_wsl_navigation(registry,path,*,repo_root,clock=time.perf_counter,relative_test_goal=False,session_factory=WslNavigationSession):
    path=Path(path).absolute();value,manifest_sha=read_json_snapshot(path)
    exact(value,('schema','config_ref','environment_ref','out','diagnostics'),'pb_wsl_manifest')
    if value['schema']!=SCHEMA or type(value['diagnostics']) is not bool or type(relative_test_goal) is not bool:raise ContractError('pb_wsl_manifest_schema')
    if type(value['out']) is not str or not Path(value['out']).is_absolute():raise ContractError('pb_wsl_absolute_output_required')
    if ADAPTER_ID in {d['adapter_id'] for d in registry.descriptors()}:raise ContractError('pb_wsl_duplicate_registration')
    session=session_factory(repo_root,value['out'],value['config_ref'],value['environment_ref'],clock=clock,
        diagnostics=value['diagnostics'],relative_test_goal=relative_test_goal)
    try:session.prepare()
    except BaseException:
        session.request_stop()
        try:session.close()
        except BaseException:pass
        raise
    lock=threading.Lock();claimed=False
    def factory(config):
        nonlocal claimed
        exact(config,(),'pb_wsl_empty_config')
        with lock:
            if claimed:raise ContractError('pb_wsl_generation_already_claimed')
            if digest(path)!=manifest_sha:session.request_stop();raise ContractError('pb_wsl_manifest_changed')
            adapter=WslNavigationAdapter(session,config,path,manifest_sha,clock=clock);claimed=True;return adapter
    try:registry.register(navigation_descriptor(),factory)
    except BaseException:session.request_stop();session.close();raise
    return session
