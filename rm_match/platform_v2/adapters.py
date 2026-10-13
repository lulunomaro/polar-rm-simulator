"""Explicit local adapter registry. HTTP callers select IDs, never import paths.

Examples are deliberately not equivalent algorithms: repository A* rule baseline,
zero-motion contract fixture, RGB red-blob baseline, and opt-in actual native RMCS.
"""
from __future__ import annotations
import base64
import copy
from dataclasses import dataclass
import math
import numpy as np
from .contracts import ContractError,action_for,validate_observation,exact,finite,vector

@dataclass(frozen=True)
class AdapterSpec:
    descriptor: dict
    factory: object

class Registry:
    def __init__(self):self._specs={}
    def register(self,descriptor,factory):
        d=copy.deepcopy(descriptor);aid=d['adapter_id']
        if aid in self._specs or len(self._specs)>=32:raise ContractError('duplicate_or_full_registry')
        if d['kind'] not in ('navigation','aim') or not callable(factory):raise ContractError('invalid_adapter')
        self._specs[aid]=AdapterSpec(d,factory)
    def get(self,adapter_id):
        if adapter_id not in self._specs:raise ContractError('unknown_adapter')
        s=self._specs[adapter_id];return AdapterSpec(copy.deepcopy(s.descriptor),s.factory)
    def descriptors(self):return [copy.deepcopy(s.descriptor) for s in self._specs.values()]
    def create(self,adapter_id,config):
        s=self.get(adapter_id)
        if not s.descriptor['available']:raise ContractError(s.descriptor['reason'])
        if type(config) is not dict:raise ContractError('invalid_adapter_config')
        return s.factory(copy.deepcopy(config))

def descriptor(aid,kind,label,sensors,*,available=True,reason='available',**extra):
    return dict(adapter_id=aid,version='1.0.0',kind=kind,label=label,
        output_modes=['velocity_body'] if kind=='navigation' else ['gimbal_target'],
        required_sensors=list(sensors),available=available,reason=reason,
        fire_authority='manual_only',ui_config_contract={'nav_rule_v1':'goal_world_2d_v1','aim_native_rmcs_v1':'native_fov_v1','aim_pixel_baseline_v1':'empty_v1','nav_stop_test_v1':'empty_v1','aim_hold_test_v1':'empty_v1'}.get(aid,'unsupported'),**extra)

def require_sensors(o,names):
    for n in names:
        if n=='odometry':
            if o['own']['odom_xyyaw'] is None or o['own']['odom_vxyw'] is None:raise ContractError('odometry_unavailable')
        elif not o['sensors'][n]['available']:raise ContractError(n+'_unavailable')
        elif o['sim_time']-o['sensors'][n]['capture_sim_time']>.2:raise ContractError(n+'_stale')

def raw_observation(o):
    """Rebuild the existing OWN-only DTO; never reconstruct a simulator object."""
    from ..contracts import Observation
    own=o['own'];cam=o['sensors']['camera'];scan=o['sensors']['ranges']
    rgb=np.zeros((0,0,3),dtype=np.uint8);fovy=0.
    if cam['available']:
        im=cam['image'];rgb=np.frombuffer(base64.b64decode(im['data_base64']),dtype=np.uint8).reshape(im['height'],im['width'],3).copy()
        if im['encoding']=='bgr8':rgb=rgb[:,:,::-1].copy()
        fovy=math.degrees(2*math.atan(im['height']/(2*cam['intrinsics']['fy'])))
    return Observation(episode=o['episode'],sim_time=o['sim_time'],rgb=rgb,fovy_degrees=fovy,
        own_qpos=tuple(own['qpos']),own_qvel=tuple(own['qvel']),own_hp=own['hp'],ammo=own['ammo'],robot_id=o['robot_id'],
        odom_xyyaw=tuple(own['odom_xyyaw']) if own['odom_xyyaw'] is not None else None,
        odom_vxyw=tuple(own['odom_vxyw']) if own['odom_vxyw'] is not None else None,
        ranges=tuple(scan['ranges_m']) if scan['available'] else (),range_angles=tuple(scan['angles_rad']) if scan['available'] else (),
        range_max=scan['range_max_m'] if scan['available'] else 8.,own_heat=own['heat'],team=own['team'],role=own['role'],
        remaining_seconds=o['referee']['remaining_seconds'],match_phase=o['referee']['phase'],emergency_stop=o['referee']['emergency_stop'],
        camera_sim_time=cam['capture_sim_time'] if cam['available'] else None,
        camera_own_qpos=tuple(cam['own_qpos_at_capture']) if cam['available'] else None,
        camera_odom_xyyaw=tuple(cam['own_odom_at_capture']) if cam['available'] else None)

class BaseAdapter:
    def reset(self,context):
        exact(context,('episode','robot_id','binding_epoch'),'reset_context');self.context=copy.deepcopy(context)
    def checked(self,o):
        o=validate_observation(o)
        if any(o[k]!=self.context[k] for k in self.context):raise ContractError('adapter_context_mismatch')
        return o
    def close(self):pass

class StopTestAdapter(BaseAdapter):
    def __init__(self,config):exact(config,(),'stop_config')
    def act(self,o):
        o=self.checked(o)
        return action_for(o,'navigation','velocity_body',dict(frame='base_link',vx_mps=0.,vy_mps=0.,wz_rps=0.))

class RuleNavigationAdapter(BaseAdapter):
    def __init__(self,config):
        if set(config)-{'goal_world_m'}:raise ContractError('unknown_navigation_config')
        self.goal=vector(config.get('goal_world_m',[0.,0.]),2,'goal_world_m',-100,100)
        from ..navigation import NavigationBaseline
        self.policy=NavigationBaseline(bounds=(-6.,6.,-4.,4.),max_speed=1.)
    def reset(self,context):
        super().reset(context);self.policy.reset(context['episode'])
        self.policy.set_intent(dict(behavior='move',target_point={'x':self.goal[0],'y':self.goal[1]},reason='explicit_local_adapter_goal'))
    def act(self,o):
        from ..navigation import NavObservation
        o=self.checked(o);require_sensors(o,('odometry','ranges'))
        raw=raw_observation(o);vx,vy=self.policy.velocity(NavObservation.from_observation(raw));yaw=o['own']['odom_xyyaw'][2]
        bx=math.cos(yaw)*vx+math.sin(yaw)*vy;by=-math.sin(yaw)*vx+math.cos(yaw)*vy
        norm=max(1.,math.hypot(bx,by))
        return action_for(o,'navigation','velocity_body',dict(frame='base_link',vx_mps=bx/norm,vy_mps=by/norm,wz_rps=0.))

class PixelAimAdapter(BaseAdapter):
    def __init__(self,config):
        exact(config,(),'pixel_config')
        from ..controllers import PixelBaseline
        self.policy=PixelBaseline(enable_fire=False)
    def reset(self,context):super().reset(context);self.policy.reset(context['episode'])
    def act(self,o):
        o=self.checked(o);require_sensors(o,('camera','odometry'));raw=raw_observation(o)
        c=self.policy.act(raw);rgb=raw.rgb.astype(float)
        active=bool(np.count_nonzero((rgb[:,:,0]>80)&(rgb[:,:,0]>rgb[:,:,1]*2)&(rgb[:,:,0]>rgb[:,:,2]*2))>=3)
        yaw=math.atan2(math.sin(c.gimbal_yaw),math.cos(c.gimbal_yaw))
        return action_for(o,'aim','gimbal_target',dict(frame='base_link',yaw_rad=yaw,pitch_rad=max(-math.pi/2,min(math.pi/2,c.gimbal_pitch)),active=active,confidence=None,fire_permission=False))

class HoldAimTestAdapter(BaseAdapter):
    def __init__(self,config):exact(config,(),"hold_config");self.hold=None
    def reset(self,context):super().reset(context);self.hold=None
    def act(self,o):
        o=self.checked(o)
        if self.hold is None:self.hold=list(o["own"]["qpos"])
        q=self.hold
        return action_for(o,"aim","gimbal_target",dict(frame="base_link",yaw_rad=math.atan2(math.sin(q[3]),math.cos(q[3])),pitch_rad=max(-math.pi/2,min(math.pi/2,q[4])),active=True,confidence=None,fire_permission=False))

def default_registry(*,native_spec=None,native_out=None,native_trace=None):
    r=Registry()
    r.register(descriptor('nav_rule_v1','navigation','Existing sensor A* rule baseline',('odometry','ranges'),goal_input_modes=['point_world_config'],trajectory_input=False),RuleNavigationAdapter)
    r.register(descriptor('nav_stop_test_v1','navigation','Zero-motion contract test adapter',(),goal_input_modes=[],trajectory_input=False,test_only=True),StopTestAdapter)
    r.register(descriptor('aim_pixel_baseline_v1','aim','Existing red-blob pixel baseline; not native RMCS',('camera','odometry'),confidence_available=False),PixelAimAdapter)
    r.register(descriptor('aim_hold_test_v1','aim','Own-angle hold contract fixture; no detection',(),test_only=True,confidence_available=False),HoldAimTestAdapter)
    ready=native_spec is not None and native_out is not None
    registered_sha=None
    if ready:
        from .native_adapter import validate_native_spec
        _,registered_sha=validate_native_spec(native_spec)
    def make_native(config):
        from .native_adapter import NativeSourceAdapter
        return NativeSourceAdapter(config,spec_path=native_spec,out=native_out,registered_spec_sha=registered_sha,trace=native_trace)
    r.register(descriptor('aim_native_rmcs_v1','aim','Actual opt-in native RMCS sensor wrapper',('camera','odometry'),available=ready,reason='available' if ready else 'explicit_trusted_native_spec_required',supported_robots=['red_sentry'],stationary_only=True,confidence_available=False,max_camera_age_sim_s=.08),make_native)
    return r
