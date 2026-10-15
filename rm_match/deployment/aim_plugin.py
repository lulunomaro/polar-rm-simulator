"""Locally reviewed camera aim plugins; HTTP selects IDs, never executables.

Registration declares interface compatibility, not detector accuracy or live
qualification. The host retains original sensor deadlines, leases and fire.
"""
from __future__ import annotations
import copy
import os
from pathlib import Path
import re
import sys
from .json_adapter import JsonLineAdapter,SCHEMA as JSONL_SCHEMA
from .profile import read_json_snapshot
from ..platform_v2.adapters import descriptor,require_sensors
from ..platform_v2.contracts import ContractError,exact,validate_action

MANIFEST_SCHEMA='polar.sim.aim-plugins.v1'
CAPABILITY_SCHEMA='polar.sim.aim-plugin.capabilities.v1'
CAPABILITY_SCHEMA_V2='polar.sim.aim-plugin.capabilities.v2'
GIMBAL_REFERENCE_INERTIAL='inertial_from_source_base_v1'
STATUS_SCHEMA='polar.sim.aim-status.v1'
CAPABILITIES=dict(schema=CAPABILITY_SCHEMA,
    observation_schema='polar.sim.observation.v2',action_schema='polar.sim.action.v2',
    status_schema=STATUS_SCHEMA,sensor_profile='calibrated_camera_capture_own_v1',
    pipeline_level='direct_gimbal_v1',source_association='exact_capture_context_v1',
    image_encodings=['rgb8','bgr8'],output_modes=['gimbal_target'],
    fire_authority='manual_only',ui_config_contract='empty_v1')
INERTIAL_CAPABILITIES=dict(copy.deepcopy(CAPABILITIES),schema=CAPABILITY_SCHEMA_V2,
    gimbal_reference=GIMBAL_REFERENCE_INERTIAL)
CAPABILITIES_V2=copy.deepcopy(INERTIAL_CAPABILITIES)

def validate_capabilities(value):
    expected=INERTIAL_CAPABILITIES if (type(value) is dict and type(value.get('schema')) is str
        and value['schema']==CAPABILITY_SCHEMA_V2) else CAPABILITIES
    exact(value,expected,'aim_plugin_capabilities')
    for key,wanted in expected.items():
        if type(value[key]) is not type(wanted) or value[key]!=wanted:
            raise ContractError('unsupported_aim_plugin_capability_'+key)
    return copy.deepcopy(value)

def gimbal_reference_for_capabilities(value):
    capabilities=validate_capabilities(value)
    return capabilities.get('gimbal_reference','base_link')

def _same_typed_tree(left,right):
    if type(left) is not type(right):return False
    if type(left) is dict:
        return left.keys()==right.keys() and all(_same_typed_tree(left[k],right[k]) for k in left)
    if type(left) is list:
        return len(left)==len(right) and all(_same_typed_tree(a,b) for a,b in zip(left,right))
    return left==right

def load_aim_plugins(path):
    path=Path(path).absolute();value,sha=read_json_snapshot(path)
    exact(value,('schema','adapters'),'aim_plugin_manifest')
    if type(value['schema']) is not str or value['schema']!=MANIFEST_SCHEMA:
        raise ContractError('unsupported_aim_plugin_manifest')
    if type(value['adapters']) is not list or not 1<=len(value['adapters'])<=16:
        raise ContractError('invalid_aim_plugin_count')
    rows=[];seen=set()
    for row in value['adapters']:
        fields=('adapter_id','label','command','cwd','supported_robots','transport','capabilities')
        if type(row) is dict and row.get('transport')=='wsl_jsonl_v1':fields+=('wsl',)
        exact(row,fields,'aim_plugin_registration')
        aid=row['adapter_id']
        if type(aid) is not str or not re.fullmatch(r'custom_[a-z0-9_]{1,100}',aid) or aid in seen:
            raise ContractError('invalid_or_duplicate_aim_plugin_id')
        seen.add(aid)
        if type(row['label']) is not str or not 1<=len(row['label'])<=200:
            raise ContractError('invalid_aim_plugin_label')
        if type(row['transport']) is not str or row['transport'] not in ('jsonl_v1','ros2_envelope_v1','wsl_jsonl_v1'):
            raise ContractError('unsupported_aim_plugin_transport')
        robots=row['supported_robots']
        if type(robots) is not list or not 1<=len(robots)<=64 or any(type(r) is not str or not re.fullmatch(r'[a-z][a-z0-9_]{0,127}',r) for r in robots) or len(set(robots))!=len(robots):
            raise ContractError('invalid_aim_plugin_robots')
        reference=gimbal_reference_for_capabilities(row['capabilities'])
        sensors=['camera','odometry'] if reference==GIMBAL_REFERENCE_INERTIAL else ['camera']
        if reference==GIMBAL_REFERENCE_INERTIAL and row['transport']=='ros2_envelope_v1':
            raise ContractError('aim_reference_v2_requires_capability_ack_transport')
        command=row['command']
        if type(command) is not list or not 1<=len(command)<=32 or any(type(s) is not str or not s or len(s)>4096 or '\0' in s for s in command):
            raise ContractError('invalid_aim_plugin_argv')
        if row['transport']=='wsl_jsonl_v1':
            from .wsl_jsonl import validate_linux_settings
            exact(row['wsl'],('distribution','python','process_env'),'aim_plugin_wsl')
            linux=validate_linux_settings(dict(row['wsl'],command=command,cwd=row['cwd']))
            rows.append(dict(copy.deepcopy(row),linux=linux,kind='aim',required_sensors=list(sensors)))
            continue
        command=[sys.executable if s=='{python}' else s for s in command]
        binary=Path(command[0])
        if not binary.is_absolute() or not binary.is_file() or not os.access(binary,os.X_OK):
            raise ContractError('aim_plugin_requires_local_absolute_executable')
        if type(row['cwd']) is not str or '\0' in row['cwd']:raise ContractError('invalid_aim_plugin_cwd')
        cwd=(path.parent/row['cwd']).resolve()
        if not cwd.is_dir():raise ContractError('aim_plugin_cwd_missing')
        rows.append(dict(copy.deepcopy(row),command=command,cwd=str(cwd),kind='aim',required_sensors=list(sensors)))
    return rows,sha

class AimPluginAdapter(JsonLineAdapter):
    def __init__(self,*args,**kwargs):
        registration=copy.deepcopy(kwargs['registration'])
        self._aim_capabilities=validate_capabilities(registration['capabilities'])
        reference=gimbal_reference_for_capabilities(self._aim_capabilities)
        expected=['camera','odometry'] if reference==GIMBAL_REFERENCE_INERTIAL else ['camera']
        if registration['required_sensors']!=expected:
            raise ContractError('aim_plugin_sensor_declaration_mismatch')
        if reference==GIMBAL_REFERENCE_INERTIAL and registration['transport']=='ros2_envelope_v1':
            raise ContractError('aim_reference_v2_requires_capability_ack_transport')
        kwargs=dict(kwargs,registration=registration)
        super().__init__(*args,**kwargs)
        if reference==GIMBAL_REFERENCE_INERTIAL:
            self.descriptor.update(version='2.0.0',aim_plugin_contract='camera_gimbal_v2',
                aim_reference=reference,aim_plugin_capabilities=copy.deepcopy(self._aim_capabilities))

    def reset(self,context,*,deadline=None):
        exact(self.config,(),'aim_plugin_binding_config')
        return super().reset(context,**({} if deadline is None else {'deadline':deadline}))

    def _exchange(self,packet,*,timeout):
        # Both ordinary JSONL reset and owned WSL prepare/reset use this one
        # path. V1 requests remain byte-for-byte unchanged. V2 requires the
        # actual peer to agree to this process's pinned local interpretation.
        if not _same_typed_tree(self.registration['capabilities'],self._aim_capabilities):
            raise ContractError('aim_plugin_registered_capabilities_changed')
        if self._aim_capabilities['schema']==CAPABILITY_SCHEMA_V2 and packet.get('op') in ('prepare','reset'):
            if 'capabilities' in packet and not _same_typed_tree(packet['capabilities'],self._aim_capabilities):
                raise ContractError('aim_plugin_capability_request_mismatch')
            packet=dict(packet,capabilities=copy.deepcopy(self._aim_capabilities))
        return super()._exchange(packet,timeout=timeout)

    def _validate_response(self,result,packet):
        if packet['op'] in ('prepare','reset') and self._aim_capabilities['schema']==CAPABILITY_SCHEMA_V2:
            exact(result,('schema','op','ok','capabilities'),'aim_plugin_capability_response')
            if (type(result['schema']) is not str or result['schema']!=JSONL_SCHEMA
                or type(result['op']) is not str or result['op']!=packet['op'] or result['ok'] is not True):
                raise ContractError('aim_plugin_capability_response_identity')
            capabilities=validate_capabilities(result['capabilities'])
            if not _same_typed_tree(capabilities,self._aim_capabilities):
                raise ContractError('aim_plugin_capabilities_mismatch')
            return
        if packet['op']!='act':return super()._validate_response(result,packet)
        if type(result) is not dict:raise ContractError('invalid_aim_plugin_response')
        field='status' if 'status' in result else 'action'
        exact(result,('schema','op','ok',field),'aim_plugin_response')
        if type(result['schema']) is not str or result['schema']!=JSONL_SCHEMA or type(result['op']) is not str or result['op']!='act' or result['ok'] is not True:
            raise ContractError('invalid_aim_plugin_response_identity')
        if field=='status':
            from ..platform_v2.aim_contracts import validate_aim_status
            validate_aim_status(result[field],packet['observation'])
        else:validate_action(result[field],packet['observation'],self.descriptor)

    def act(self,observation):
        o=self.checked(observation);require_sensors(o,self.registration['required_sensors'])
        response=self._exchange(dict(op='act',observation=o),timeout=min(.25,o['wall_deadline']-self.clock()))
        if 'status' in response:
            from ..platform_v2.aim_contracts import validate_aim_status
            return validate_aim_status(response['status'],o)
        return validate_action(response['action'],o,self.descriptor)

def register_aim_plugins(registry,path,*,clock=None,wsl_prepared=None):
    """Freeze local metadata/manifest SHA; no HTTP-provided command/config."""
    path=Path(path).absolute();rows,sha=load_aim_plugins(path)
    for row in rows:
        reference=gimbal_reference_for_capabilities(row['capabilities'])
        d=descriptor(row['adapter_id'],'aim',row['label'],row['required_sensors'])
        d.update(ui_config_contract='empty_v1',aim_plugin_contract='camera_gimbal_v1',
            schedule_on_camera_frame=True,max_camera_age_wall_s=.08,max_camera_age_sim_s=.08,
            aim_plugin_capabilities=copy.deepcopy(row['capabilities']),
            supported_robots=list(row['supported_robots']),local_registration=True,
            plugin_transport=row['transport'],process_isolation='trusted_local_process_not_a_security_sandbox',
            qualification='interface_declared_not_algorithm_or_live_acceptance')
        if reference==GIMBAL_REFERENCE_INERTIAL:
            d.update(version='2.0.0',aim_plugin_contract='camera_gimbal_v2',aim_reference=reference,
                capability_negotiation='exact_peer_capabilities_on_prepare_and_reset')
        if row['transport']=='wsl_jsonl_v1':
            ready=wsl_prepared is not None and wsl_prepared.sha==sha and row['adapter_id'] in wsl_prepared.instances
            d.update(available=ready,reason='available' if ready else 'explicit_local_wsl_prepare_required',preparation='actual_peer_prepare_ack_required',
                lifecycle='one_prepared_instance_one_binding_restart_for_rebind')
        def factory(config,row=row,d=d):
            exact(config,(),'aim_plugin_binding_config')
            kwargs={} if clock is None else {'clock':clock}
            if row['transport']=='wsl_jsonl_v1':
                if wsl_prepared is None:raise ContractError('wsl_plugin_requires_explicit_local_preparation')
                adapter=wsl_prepared.take(row['adapter_id'],sha)
            else:adapter=AimPluginAdapter(config,registration=row,manifest=path,manifest_sha=sha,**kwargs)
            adapter.descriptor=copy.deepcopy(d)
            return adapter
        registry.register(d,factory)
    return dict(schema=MANIFEST_SCHEMA,manifest_sha256=sha,registered_ids=[r['adapter_id'] for r in rows],
        qualification='interface_declared_not_algorithm_or_live_acceptance')
