"""Trusted-local registration for the pointcloud/IMU profile, never HTTP argv."""
from __future__ import annotations
import os
from pathlib import Path
import re
import sys
import time
from ..deployment.json_adapter import JsonLineAdapter, SCHEMA
from ..deployment.profile import read_json_snapshot
from ..platform_v2.adapters import descriptor
from ..platform_v2.contracts import ContractError, IDENTITY, exact, validate_action
from ..platform_v2.navigation_contracts import NAV_PROFILE, validate_navigation_observation, validate_navigation_status


MANIFEST_SCHEMA='polar.sim.pb-navigation-manifest.v1'


class PBNavigationAdapter(JsonLineAdapter):
    def __init__(self,config,**kwargs):
        exact(config,(),'pb_navigation_config');super().__init__(config,**kwargs)
        self.descriptor.update(observation_profile=NAV_PROFILE,ui_config_contract='empty_v1')

    def _validate_response(self,result,packet):
        if packet['op']!='act':return super()._validate_response(result,packet)
        if type(result) is not dict or ('action' in result)==('status' in result):raise ContractError('pb_response_requires_action_xor_status')
        field='action' if 'action' in result else 'status'
        exact(result,('schema','op','ok',field),'pb_jsonl_response')
        if type(result['schema']) is not str or result['schema']!=SCHEMA or type(result['op']) is not str or result['op']!='act' or result['ok'] is not True:raise ContractError('pb_jsonl_response_identity')
        o=packet['observation']
        if field=='status':validate_navigation_status(result[field],o)
        else:
            a=validate_action(result[field],o,self.descriptor)
            if any(type(a[k]) is not type(o[k]) or a[k]!=o[k] for k in IDENTITY):raise ContractError('pb_action_identity_type')

    def act(self,observation):
        o=validate_navigation_observation(observation)
        if any(type(o[k]) is not type(v) or o[k]!=v for k,v in self.context.items()):raise ContractError('pb_adapter_context_mismatch')
        response=self._exchange(dict(op='act',observation=o),timeout=min(.15,o['wall_deadline']-self.clock()))
        return (validate_navigation_status(response['status'],o) if 'status' in response
            else validate_action(response['action'],o,self.descriptor))


def register_pb_navigation(registry,path,*,clock=time.perf_counter):
    path=Path(path).absolute();value,sha=read_json_snapshot(path)
    exact(value,('schema','adapters'),'pb_manifest')
    if value['schema']!=MANIFEST_SCHEMA or type(value['adapters']) is not list or not 1<=len(value['adapters'])<=4:raise ContractError('pb_invalid_manifest')
    seen=set();prepared=[]
    for row in value['adapters']:
        exact(row,('adapter_id','label','command','cwd'),'pb_registration')
        aid=row['adapter_id']
        if type(aid) is not str or not re.fullmatch('custom_[a-z0-9_]{1,100}',aid) or aid in seen:raise ContractError('pb_custom_id_required')
        seen.add(aid)
        if type(row['label']) is not str or not 1<=len(row['label'])<=200:raise ContractError('pb_label')
        c=row['command']
        if type(c) is not list or not 1<=len(c)<=32 or any(type(v) is not str or not v or len(v)>4096 for v in c):raise ContractError('pb_command')
        c=[sys.executable if v=='{python}' else v for v in c]
        binary=Path(c[0])
        if not binary.is_absolute() or not binary.is_file() or not os.access(binary,os.X_OK):raise ContractError('pb_executable_missing')
        if type(row['cwd']) is not str:raise ContractError('pb_cwd')
        cwd=(path.parent/row['cwd']).resolve()
        if not cwd.is_dir():raise ContractError('pb_cwd_missing')
        prepared.append(dict(row,command=c,cwd=str(cwd),kind='navigation',required_sensors=['pointcloud','imu']))
    for row in prepared:
        def factory(config,row=row):return PBNavigationAdapter(config,registration=row,manifest=path,manifest_sha=sha,clock=clock)
        d=descriptor(row['adapter_id'],'navigation',row['label'],['pointcloud','imu'],observation_profile=NAV_PROFILE,
            local_registration=True,process_isolation='not_a_security_sandbox',qualification='optional_humble_bridge_not_navigation_acceptance',supported_robots=['red_sentry'])
        d['ui_config_contract']='empty_v1';registry.register(d,factory)
    return [r['adapter_id'] for r in prepared]
