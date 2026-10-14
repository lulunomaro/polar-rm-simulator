"""Whitelist the operator display plane; spectator audit data remains unchanged.

This is a response boundary, not team admission, watch authorization, plugin
sandboxing or removal of the separately supplied ideal algorithm sensors.
"""
from __future__ import annotations

import copy
import math

CHANNELS = ('motion', 'gimbal', 'fire')
STATIC = ('robot_id', 'team', 'role')
HUD = ('hp', 'max_hp', 'ammo', 'heat', 'heat_max', 'alive',
       'gimbal_yaw', 'gimbal_pitch', 'pitch')
PUBLIC = ('display_schema', 'episode', 'sim_time', 'sample_sim_time',
          'remaining_seconds', 'duration_seconds', 'phase', 'winner',
          'runtime_state', 'applied_sample_is_historical')
LEASE = ('epoch', 'expires', 'seq', 'input_expires', 'input_window_id',
         'input_window_deadline', 'mode_fault')
BINDING = ('epoch', 'adapter_id', 'activation_required', 'activation_seq',
           'activation_expires', 'activation_window_id',
           'activation_window_deadline')
COMMAND = {
    'motion': ('mode', 'frame', 'vx_mps', 'vy_mps', 'wz_rps', 'direction', 'speed_dps'),
    'gimbal': ('frame', 'yaw_rad', 'pitch_rad', 'active', 'confidence', 'fire_permission'),
    'fire': ('fire',),
}


def _scalars(value, keys):
    """No nested/future objects can cross even under a known field name."""
    if type(value) is not dict:
        return {}
    result = {}
    for key in keys:
        if key not in value:
            continue
        item = value[key]
        if item is None or type(item) in (str, bool, int):
            result[key] = item
        elif type(item) is float and math.isfinite(item):
            result[key] = item
    return result


def _live(lease, session_id, now):
    expires = lease.get('expires')
    return (lease.get('owner') == session_id and type(expires) in (int, float)
            and math.isfinite(expires) and now < expires)


def operator_state(value, control, *, session_id, allowed_robots=None):
    """Project at the current control snapshot, never from cached ownership.

    Caller must keep the control lock while validating the session, snapshotting
    leases and projecting. Watch alone does not authorize dynamic own HUD data.
    """
    now = control['server_monotonic_s']
    allowed = {}
    summaries = {}
    visible=[r for r in control['robot_ids'] if allowed_robots is None or r in allowed_robots]
    for rid in visible:
        allowed[rid] = set()
        summaries[rid] = {}
        for channel in CHANNELS:
            lease = control.get('leases', {}).get(rid, {}).get(channel, {})
            live = _live(lease, session_id, now)
            if live:
                allowed[rid].add(channel)
                summary = _scalars(lease, LEASE)
                summary.update(owner=session_id, occupied=True)
                summary['input'] = (None if lease.get('input') is None else
                                    _scalars(lease['input'], COMMAND[channel]))
            else:
                occupied = lease.get('owner') is not None
                summary = _scalars(lease, ('epoch',))
                summary.update(owner='occupied' if occupied else None, occupied=occupied)
            summaries[rid][channel] = summary

    result = _scalars(value, PUBLIC)
    result.update(source='operator_limited_display', data_plane='operator_limited_display',
                  algorithm_input=False, state_projection_version=1)
    result['robots'] = []
    for raw in value.get('robots', []):
        row = _scalars(raw, STATIC)
        if row.get('robot_id') not in allowed:
            continue
        if allowed[row['robot_id']]:
            row.update(_scalars(raw, HUD))
        result['robots'].append(row)

    # Preserve UI selection/occupied semantics without disclosing another SID,
    # control input, adapter configuration, activation details or receipts.
    projected_control = _scalars(control, ('stopped', 'server_monotonic_s', 'revision'))
    projected_control.update(robot_ids=visible, leases=summaries, bindings={})
    for rid in visible:
        projected_control['bindings'][rid] = {}
        for kind, channel in (('navigation', 'motion'), ('aim', 'gimbal')):
            binding = control.get('bindings', {}).get(rid, {}).get(kind, {})
            if channel in allowed[rid] and binding.get('owner') == session_id:
                own = _scalars(binding, BINDING)
                own['owner'] = session_id
                epochs = binding.get('lease_epochs', {})
                own['lease_epochs'] = _scalars(epochs, (channel,))
                projected_control['bindings'][rid][kind] = own
            else:
                projected_control['bindings'][rid][kind] = {
                    'owner': 'occupied' if binding.get('owner') is not None else None,
                }
    result['control'] = projected_control

    # Display bounded original result status only for this owner's current live
    # gimbal binding. Never expose raw status/error graphs or another owner's
    # context, and never interpret a result as a physical consumption receipt.
    aim_context={}
    contexts=value.get('algorithm_status_context',{})
    if type(contexts) is not dict:contexts={}
    for rid in visible:
        if 'gimbal' not in allowed[rid]:continue
        binding=control.get('bindings',{}).get(rid,{}).get('aim',{})
        lease=control.get('leases',{}).get(rid,{}).get('gimbal',{})
        per_robot=contexts.get(rid,{})
        if type(per_robot) is not dict:continue
        raw=per_robot.get('aim',{})
        if type(raw) is not dict or binding.get('owner')!=session_id:continue
        keys=('episode','binding_epoch','adapter_id','status','observed_seq','wall_deadline','source_frame_id')
        ctx=_scalars(raw,keys)
        if set(ctx)!=set(keys) or raw.get('owner')!=session_id:continue
        if (any(type(ctx[k]) is not int or ctx[k]<0 for k in ('episode','binding_epoch','observed_seq','source_frame_id'))
            or type(ctx['adapter_id']) is not str or type(ctx['status']) is not str
            or ctx['status'] not in ('no_target','pending_result','result_available')
            or type(ctx['wall_deadline']) is not float or not math.isfinite(ctx['wall_deadline'])
            or now>=ctx['wall_deadline'] or ctx['episode']!=value.get('episode')
            or type(raw.get('lease_epoch')) is not int or raw['lease_epoch']!=lease.get('epoch')
            or type(binding.get('epoch')) is not int or ctx['binding_epoch']!=binding['epoch']
            or ctx['adapter_id']!=binding.get('adapter_id')):continue
        aim_context[rid]={'aim':ctx}
    if aim_context:result['algorithm_status_context']=aim_context

    # OfflineRuntime inherits this projection. Publish only scheduler/lifecycle
    # metadata needed by the client's renewal/cleanup loop, never its full
    # truth cache or native exception text (which may contain private paths).
    profile=value.get('clock_profile',{})
    if type(profile) is dict and profile.get('kind') in ('wall_deadline_live','offline_modeled_latency_v1'):
        result['clock_profile']=_scalars(profile,('kind','label','barrier_state',
            'simulation_tick','simulation_ns','episode_origin_mj_time_ns',
            'delays_are_engineering_configuration_not_device_calibration',
            'host_delay_s','wall_elapsed_s','simulation_time_unit','wall_clock','real_time_factor_limit'))
        if profile.get('kind')=='offline_modeled_latency_v1':
            if type(profile.get('delays')) is dict:
                result['clock_profile']['delays']=_scalars(profile['delays'],(
                    'physics_step_ns','capture_period_ns','controller_period_ns',
                    'sensor_delay_ns','compute_delay_ns','actuation_delay_ns','max_age_ns'))
            if value.get('offline_final_state') in ('COMPLETED','HALTED'):
                result['offline_final_state']=value['offline_final_state']
            count=value.get('completed_captures')
            if type(count) is int and count>=0:result['completed_captures']=count
            if value.get('offline_halt_reason'):
                reason=value['offline_halt_reason']
                prefix=reason.split(':',1)[0] if type(reason) is str else ''
                known={'stop_requested','attempt_wall_watchdog','episode_changed','lease_or_binding_changed',
                    'referee_or_alive_gate','stationary_required','physics_tick_clock_mismatch',
                    'initial_binding_wall_watchdog','camera_barrier_wall_watchdog','native_barrier_wall_watchdog',
                    'native_error','camera_error','modeled_age_exceeded','robot_limit_rejected'}
                result['offline_halt_code']=prefix if prefix in known else 'offline_halted'

    result['applied_targets'] = {}
    for rid, channels in allowed.items():
        if not channels:
            continue
        # Applied samples are historical; only disclose those whose owner/epoch
        # can be proved by a receipt from the same current lease. Never infer
        # ownership of a cached command from a newly acquired lease.
        receipt = value.get('manual_consumption_receipts', {}).get(rid) or {}
        authorizations = receipt.get('manual_inputs', {})
        raw_targets = value.get('applied_targets', {}).get(rid, {})
        targets = {}
        for channel in channels:
            recorded = authorizations.get(channel, {})
            current = control['leases'][rid][channel]
            if recorded.get('owner') != session_id or recorded.get('epoch') != current['epoch']:
                continue
            target = raw_targets.get(channel)
            if channel == 'fire':
                if type(target) is bool:
                    targets[channel] = target
            elif target is None:
                targets[channel] = None
            else:
                targets[channel] = _scalars(target, COMMAND[channel])
        if targets:
            result['applied_targets'][rid] = targets
    # Dynamic status, feedback, receipts, score/coin maps, configs and unknown
    # top-level additions are deliberately absent unless separately reviewed.
    return result


def project_state(value, control, *, session_id, role, allowed_robots=None, audit_authorized=True):
    if role == 'spectator':
        if not audit_authorized:raise ValueError('audit_authorization_required')
        return copy.deepcopy(value)
    if role != 'operator':
        raise ValueError('unsupported_state_role')
    return operator_state(value, control, session_id=session_id,allowed_robots=allowed_robots)


def operator_camera_display(value):
    """JPEG and static calibration only, even before the operator claims a car."""
    result=_scalars(value,('available','reason','robot_id','episode','watch_epoch',
        'max_frame_age_wall_s','frame_seq','capture_sim_time','capture_wall_monotonic',
        'encode_completed_wall_monotonic','age_wall_s','full_frame'))
    result.update(source='operator_camera_display_v1',algorithm_input=False,
                  data_plane='operator_limited_display',camera_display_version=1)
    if value.get('available') is True:
        result['image']=_scalars(value.get('image'),('encoding','width','height','data_base64'))
        calibration=value.get('calibration',{})
        intrinsics=calibration.get('intrinsics',{})
        extrinsics=calibration.get('extrinsics',{})
        intr=_scalars(intrinsics,('fx','fy','cx','cy','distortion_model'))
        ext=_scalars(extrinsics,('parent_frame','calibration_id'))
        for source,target,key,n in ((intrinsics,intr,'distortion',5),
                                    (extrinsics,ext,'translation_m',3),
                                    (extrinsics,ext,'rotation_xyzw',4)):
            vector=source.get(key)
            if type(vector) is list and len(vector)==n and all(type(v) in (int,float) and math.isfinite(v) for v in vector):
                target[key]=list(vector)
        result['calibration']=dict(intrinsics=intr,extrinsics=ext)
    return result
