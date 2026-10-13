"""Trusted native RMCS wrapper over serialized own-sensor observations only.

Unlike the v1 runtime wrapper, this adapter receives no simulator/renderer/judge.
Local administrator registration supplies verified executable/config locations;
network binding config can only change bounded FOV parameters. No auto fire.
"""
from __future__ import annotations
from dataclasses import replace
import hashlib
import json
import math
import os
import time
import threading
from pathlib import Path
import uuid
import numpy as np
from .native_image import prepare_native_image
from .adapters import BaseAdapter,raw_observation,require_sensors
from .contracts import ContractError,action_for,finite

def validate_native_spec(spec_path,expected_spec_sha=None):
    """Verify the complete locally registered source input set without execution."""
    content=Path(spec_path).read_bytes();spec_sha=hashlib.sha256(content).hexdigest()
    if expected_spec_sha is not None and spec_sha!=expected_spec_sha:raise ContractError('native_spec_changed_after_registration')
    spec=json.loads(content)
    if spec.get('operator_identity')!='rmcs-sim-operator-fov-v1':raise ContractError('native_identity_mismatch')
    environment=spec.get('environment',{})
    reserved={'AUTOAIM_CONFIG','RMCS_HEADLESS_SHARE','ORT_DISABLE_TELEMETRY'}
    if type(environment) is not dict or any(type(k) is not str or type(v) is not str for k,v in environment.items()):raise ContractError('invalid_native_environment')
    if reserved.intersection(environment):raise ContractError('native_reserved_environment_override')
    hashes=spec.get('sha256',{});binary=spec.get('frozen_build',{}).get('binary_sha256')
    paths={k:Path(spec[k]) for k in ('binary','executor_yaml','autoaim_config')}
    paths['model']=Path(spec['model_share'])/'shenzhen-0526.onnx'
    expected=dict(binary=binary,executor_yaml=hashes.get('executor_yaml'),autoaim_config=hashes.get('autoaim_config'),model=spec.get('model_sha256'))
    if hashes.get('binary')!=binary:raise ContractError('native_binary_declarations_mismatch')
    for key,path in paths.items():
        digest=expected[key]
        if type(digest) is not str or len(digest)!=64 or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ContractError('native_'+key+'_hash_mismatch')
    mode=spec.get('runtime_mode_contents')
    if mode!='multi_ekf\n' or hashlib.sha256(mode.encode()).hexdigest()!=spec.get('runtime_mode_sha256') or hashes.get('runtime_mode')!=spec.get('runtime_mode_sha256'):raise ContractError('native_runtime_mode_mismatch')
    return spec,spec_sha

class NativeSourceAdapter(BaseAdapter):
    def __init__(self,config,*,spec_path,out,registered_spec_sha=None,trace=None):
        from ..operator.source_aim import IDENTITY
        # Definition-only Python imports belong to local setup, before the
        # physics/camera clock starts. No exposure, native tick or inference.
        from . import native_observation
        from ..integrations import rmcs_contract
        if set(config)-{'fov_degrees','circle_radius_x_norm','circle_radius_y_norm'}:raise ContractError('invalid_native_config')
        self.fov=dict(fov_degrees=finite(config.get('fov_degrees',85.),'fov',10,180),circle_radius_x_norm=finite(config.get('circle_radius_x_norm',.25),'circle_x',1e-6,2),circle_radius_y_norm=finite(config.get('circle_radius_y_norm',.25),'circle_y',1e-6,2))
        self.trace=trace
        self.spec_path=Path(spec_path);self.spec,self.spec_sha=validate_native_spec(self.spec_path,registered_spec_sha)
        self.root=Path(out);self.process=None
        self._evidence_writer=None;self._evidence_required=False;self._last_evidence_status=None
        self._cancelled=threading.Event();self._lifecycle_lock=threading.Lock()
        self.stable_since=None;self.anchor=None;self.last_capture=-1;self.last_time=None
    def reset(self,context):
        if self._cancelled.is_set():raise ContractError('native_adapter_cancelled')
        super().reset(context);self.close();self.stable_since=None;self.anchor=None;self.last_capture=-1;self.last_time=None
    def cancel(self):
        """Trusted lifecycle hook, no waiting or pipe closure on the authority."""
        self._cancelled.set()
        with self._lifecycle_lock:process=self.process;evidence=getattr(self,'_evidence_writer',None)
        if evidence is not None:evidence.request_stop()
        if process is not None:
            stop=getattr(process,'request_stop',None)
            if callable(stop):stop()
    def close(self):
        with self._lifecycle_lock:
            process=self.process;self.process=None
            evidence=getattr(self,'_evidence_writer',None);self._evidence_writer=None
        errors=[]
        if evidence is not None:
            try:evidence.close(timeout=.15)
            except BaseException as exc:errors.append(exc)
            self._last_evidence_status=evidence.shutdown_status
            if self.trace:
                try:self.trace(dict(event='native_evidence_closed',wall_time=time.perf_counter(),wall_clock='host_perf_counter',status=evidence.shutdown_status))
                except BaseException as exc:errors.append(exc)
        if process is not None:
            try:process.close()
            except BaseException as exc:errors.append(exc)
        if errors:raise errors[0]
    def _hold(self,o):
        q=o['own']['qpos']
        return action_for(o,'aim','gimbal_target',dict(frame='base_link',yaw_rad=math.atan2(math.sin(q[3]),math.cos(q[3])),pitch_rad=max(-math.pi/2,min(math.pi/2,q[4])),active=False,confidence=None,fire_permission=False))
    def act(self,o):
        from .contracts import validate_observation
        decoded={};o=validate_observation(o,image_bytes=decoded)
        return self._act_validated(o,decoded['raw'])

    def _act_validated(self,o,decoded_image):
        # Only the reviewed native slot calls this after strict validation. Direct
        # act() remains fully validated; no private pixel cache enters the DTO.
        if any(o[k]!=self.context[k] for k in self.context):raise ContractError('adapter_context_mismatch')
        return self._act_sensor(o,lambda:self._hold(o),lambda c:action_for(o,'aim','gimbal_target',c),decoded_image=decoded_image)

    def _act_native_pixels(self,base,pixels,*,consumer,budget,now):
        """Explicit private schema. Never create an incomplete observation.v2."""
        from .native_observation import validate_native_observation,reviewed_native_instance
        if not reviewed_native_instance(self):raise ContractError('private_native_type_not_reviewed')
        envelope=validate_native_observation(base,pixels,consumer=consumer,budget=budget,now=now)
        o=envelope.base
        if any(o[k]!=self.context[k] for k in self.context):raise ContractError('adapter_context_mismatch')
        return self._act_sensor(o,lambda:self._hold(o),lambda c:action_for(o,'aim','gimbal_target',c),native_envelope=envelope)

    def _start_process(self,episode):
        from ..operator.source_aim import OperatorFovProcess
        validate_native_spec(self.spec_path,self.spec_sha)
        self.directory=self.root/('binding_'+uuid.uuid4().hex);self.directory.mkdir(parents=True,exist_ok=False)
        (self.directory/'tracking_mode').write_text(self.spec['runtime_mode_contents'])
        env=os.environ.copy();env.update(self.spec.get('environment',{}))
        env.update(AUTOAIM_CONFIG=str(Path(self.spec['autoaim_config']).absolute()),RMCS_HEADLESS_SHARE=str(Path(self.spec['model_share']).absolute()),ORT_DISABLE_TELEMETRY='1')
        process=OperatorFovProcess(self.spec['binary'],self.spec['executor_yaml'],self.directory,env,fov=self.fov,timeout=2.)
        with self._lifecycle_lock:
            if self._cancelled.is_set():raise ContractError('native_adapter_cancelled')
            self.process=process
        process.reset(dict(episode=episode))
        if self._cancelled.is_set():
            stop=getattr(process,'request_stop',None)
            if callable(stop):stop()
            self.close();raise ContractError('native_adapter_cancelled')

    def _native_control(self,packet,observation,*,image_bytes=None):
        return self.process.control(packet)

    def _act_sensor(self,o,hold,emit,*,decoded_image=None,native_envelope=None):
        # Shared sensor computation only. Callers validate a distinct live or
        # offline envelope before entry; runtime acceptance policies stay separate.
        from ..integrations.rmcs_contract import own_state,command_from_direction
        from ..camera_profile import SourceCameraProfile
        if self._cancelled.is_set():raise ContractError('native_adapter_cancelled')
        require_sensors(o,('camera','odometry') if native_envelope is None else ('odometry',))
        cam=o['sensors']['camera'] if native_envelope is None else native_envelope.pixels.metadata()
        p=SourceCameraProfile()
        if o['robot_id']!='red_sentry':raise ContractError('native_robot_unsupported')
        intr=cam['intrinsics'];im=cam['image'];ext=cam['extrinsics']
        if (im['width'],im['height'])!=(p.width,p.height):raise ContractError('native_camera_resolution_mismatch')
        if any(abs(intr[k]-getattr(p,k))>1e-8 for k in ('fx','fy','cx','cy')) or not np.allclose(intr['distortion'],p.distortion,atol=1e-10,rtol=0):raise ContractError('native_camera_calibration_mismatch')
        # optical-to-pitch transform encoded as xyzw. q and -q are equivalent.
        expected=np.array([-.5,.5,-.5,.5]);quat=np.array(ext['rotation_xyzw'])
        if not np.allclose(ext['translation_m'],[.24,0,.06],atol=1e-9,rtol=0) or min(np.linalg.norm(quat-expected),np.linalg.norm(quat+expected))>1e-8:raise ContractError('native_camera_extrinsics_mismatch')
        t=o['sim_time'];v=o['own']['odom_vxyw'];xy=o['own']['odom_xyyaw'][:2]
        eligible=(o['own']['alive'] and o['referee']['phase']=='running' and not o['referee']['emergency_stop'] and math.hypot(*v[:2])<=.03 and abs(v[2])<=.03)
        if self.last_time is not None and t<self.last_time:eligible=False
        self.last_time=t
        if self.anchor is not None and math.dist(xy,self.anchor)>.025:eligible=False
        if not eligible:
            self.close();self.stable_since=None;self.anchor=None;return hold()
        if self.stable_since is None:self.stable_since=t;self.anchor=list(xy)
        if t-self.stable_since<.4 or t-cam['capture_sim_time']>.08:return hold()
        if cam['frame_id']<=self.last_capture:return hold()
        if native_envelope is None:raw=raw_observation(o,decoded_image=decoded_image)
        else:
            from .native_observation import raw_native_observation
            raw=raw_native_observation(native_envelope)
        if self.process is None:
            self._start_process(o['episode'])
        inline=getattr(self,'transport',None)=='wsl_stdio_bgr_v2'
        # Only this private v2 route preserves every immutable BGR frame. The
        # post-close auditor must verify/reconstruct RGB; a missing digest here
        # is an explicit deferred obligation, never fabricated audit success.
        deferred_rgb=native_envelope is not None and inline
        prepared=prepare_native_image(raw.rgb,self.directory/'sensor_input.bgr',
            trace_rgb=self.trace is not None and not deferred_rgb,return_bytes=inline,write_artifact=not inline)
        image,rgb_sha,image_stages=prepared[:3];image_bytes=prepared[3] if inline else None
        if inline:
            writer=self._evidence_writer
            if writer is None:raise ContractError('native_evidence_not_prepared')
            receipt=writer.submit(cam['frame_id'],image_bytes,image['sha256'])
            if self.trace:self.trace(dict(event='native_evidence_accepted',wall_time=time.perf_counter(),wall_clock='host_perf_counter',receipt=receipt,sha256=image['sha256']))
        captured=replace(raw,sim_time=cam['capture_sim_time'],own_qpos=tuple(cam['own_qpos_at_capture']),own_qvel=tuple(cam['own_qvel_at_capture']),odom_xyyaw=tuple(cam['own_odom_at_capture']),odom_vxyw=tuple(cam['own_odom_velocity_at_capture']))
        frame=dict(schema='rmcs-mujoco-actor-frame-v1',episode=o['episode'],frame_id=cam['frame_id'],exposure_timestamp_ns=round(cam['capture_sim_time']*1e9),capture_time_s=cam['capture_sim_time'],own_referee_id=7,own_team='red',image=image,camera={k:intr[k] for k in ('fx','fy','cx','cy','distortion')},own=own_state(captured))
        self.last_capture=cam['frame_id']
        if self.trace:
            trace_identity=dict(robot_id=o['robot_id'],episode=o['episode'],binding_epoch=o['binding_epoch'],observed_seq=o['observed_seq'],frame_id=cam['frame_id'],capture_sim_time=cam['capture_sim_time'],observation_sim_time=t,clock_profile=o.get('clock_profile','wall_deadline_live'),wall_deadline=o.get('wall_deadline'),schedule=o.get('schedule'),raw_bgr_sha256=frame['image']['sha256'],raw_rgb_sha256=rgb_sha,
                rgb_trace_strategy='archived_bgr_postclose_exact_channel_swap' if deferred_rgb else 'synchronous_rgb_sha256',
                own_at_capture={k:cam[k] for k in ('own_qpos_at_capture','own_qvel_at_capture','own_odom_at_capture','own_odom_velocity_at_capture')})
            self.trace(dict(event='native_frame_prepare',wall_time=time.perf_counter(),image_stages=image_stages,**trace_identity))
            self.trace(dict(event='native_request',wall_time=time.perf_counter(),wall_clock='host_perf_counter',**trace_identity))
        response=self._native_control(dict(episode=o['episode'],control_time_ns=round(t*1e9),frame=frame),o,image_bytes=image_bytes)
        if self.trace:self.trace(dict(event='native_result',wall_time=time.perf_counter(),wall_clock='host_perf_counter',response=response,**trace_identity))
        age=response.get('target_age_s')
        active=(response.get('should_control') is True and response.get('observation_shoot_allowed') is True and type(age) in (int,float) and math.isfinite(age) and 0<=age<=.08)
        if not active:return hold()
        c=command_from_direction(response,raw)
        return emit(dict(frame='base_link',yaw_rad=math.atan2(math.sin(c.gimbal_yaw),math.cos(c.gimbal_yaw)),pitch_rad=c.gimbal_pitch,active=True,confidence=None,fire_permission=False))
