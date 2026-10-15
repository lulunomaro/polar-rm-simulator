"""Private typed native envelope, distinct from observation.v2 camera JSON."""
from dataclasses import dataclass, replace
import math
import numpy as np
from .contracts import validate_observation, ContractError, exact,integer,string,finite
from .native_camera_snapshot import is_native_snapshot

NATIVE_SCHEMA='polar.sim.private_native_pixels.v1'


@dataclass(frozen=True)
class NativePixelObservation:
    schema:str
    base:dict
    pixels:object


def validate_native_observation(base,pixels,*,consumer,budget,now):
    base=validate_observation(base)
    if base['sensors']['camera']['available']:raise ContractError('private_native_base_camera_must_be_unavailable')
    if not is_native_snapshot(pixels):raise ContractError('unsealed_native_camera')
    if (type(consumer) is not tuple or len(consumer)!=5
        or any(type(c) is not str for c in consumer[:4]) or type(consumer[4]) is not int):
        raise ContractError('invalid_native_camera_consumer')
    if (pixels.robot_id!=base['robot_id'] or pixels.episode!=base['episode']
        or consumer not in pixels.consumers
        or type(consumer) is not tuple or consumer[:3]!=('adapter',base['robot_id'],'aim')
        or consumer[4]!=base['binding_epoch']):raise ContractError('native_camera_context_mismatch')
    exact(budget,('robot_id','episode','frame_id','capture_wall','capture_sim_time','wall_deadline','sim_deadline'),'native_budget')
    string(budget['robot_id'],'native_budget_robot')
    for k in ('episode','frame_id'):integer(budget[k],'native_budget_'+k)
    for k in ('capture_wall','capture_sim_time','wall_deadline','sim_deadline'):finite(budget[k],'native_budget_'+k,0,1e12)
    for k in ('robot_id','episode','frame_id','capture_wall','capture_sim_time'):
        if budget[k]!=getattr(pixels,k):raise ContractError('native_camera_budget_pair_mismatch')
    # Original clock domains and both 80ms gates, including the operator cap.
    finite(now,'native_now',0,1e12)
    if (not pixels.capture_wall<=now<min(pixels.capture_wall+.08,budget['wall_deadline'],base['wall_deadline'])
        or not pixels.capture_sim_time<=base['sim_time']<=min(pixels.capture_sim_time+.08,budget['sim_deadline'])):
        raise ContractError('native_camera_expired')
    return NativePixelObservation(NATIVE_SCHEMA,base,pixels)


def raw_native_observation(envelope):
    """Rebuild OWN-only sensor object from validated, detached metadata/bytes."""
    from .adapters import raw_observation
    raw=raw_observation(envelope.base)
    p=envelope.pixels
    rgb=np.frombuffer(p.raw_bytes,dtype=np.uint8).reshape(p.height,p.width,3)
    return replace(raw,rgb=rgb,fovy_degrees=math.degrees(2*math.atan(p.height/(2*p.intrinsics[1]))),
        camera_sim_time=p.capture_sim_time,camera_own_qpos=p.own[0],camera_odom_xyyaw=p.own[2])


def reviewed_native_instance(instance):
    from .native_adapter import NativeSourceAdapter
    from .wsl_native_adapter import WslNativeSourceAdapter
    return (type(instance) in (NativeSourceAdapter,WslNativeSourceAdapter)
        and getattr(instance.act,'__func__',None) is NativeSourceAdapter.act)
