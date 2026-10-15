"""Per-robot 40ms boolean level, immediate safety on every 0.5ms step."""
from dataclasses import replace
import math
from .fire_level_delay import FireLevelDelay

class MatchFireTransport:
    def __init__(self,rid):
        self.rid=rid;self.delay=FireLevelDelay(80,step_ns=500000);self.events=[];self.episode=None;self.last_reasons=None
    def apply(self,sim,step,command,source,desired_velocity,*,decision=None):
        if self.episode is not None and sim.episode!=self.episode:self.delay.reset(reason='episode_changed')
        self.episode=sim.episode;reasons=[];robot=sim.judge.robots[self.rid]
        o=sim.observe(self.rid,False,False)
        own_values=(*o.own_qpos,*o.odom_vxyw,*o.odom_xyyaw,*desired_velocity)
        if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in own_values):reasons.append('invalid_own_state')
        if not source.client or source.error:reasons.append('source_disconnected')
        if not source.gate.active:reasons.append('not_stationary_segment')
        if not source.latest_response or source.latest_response.get('tracking') is not True:reasons.append('no_tracking')
        if not robot.alive or robot.weak:reasons.append('own_dead_or_weak')
        if sim.paused or sim.judge.terminal or sim.phase!='running' or sim.emergency_stop:reasons.append('match_safety')
        if math.hypot(*desired_velocity)>1e-6:reasons.append('navigation_motion_requested')
        if math.hypot(*o.odom_vxyw[:2])>.03 or abs(o.odom_vxyw[2])>.03:reasons.append('chassis_motion')
        if source.gate.anchor and math.dist(source.gate.anchor,o.odom_xyyaw[:2])>.025:reasons.append('origin_drift')
        if source.last_accepted_s is None or not 0<=sim.time-source.last_accepted_s<=.08:reasons.append('visual_lease')
        if not source.latest_response or source.latest_response.get('observation_shoot_allowed') is not True:reasons.append('unobserved_target')
        response=source.latest_response or {};age=response.get('target_age_s');stamp=response.get('control_time_ns')
        if not isinstance(age,(int,float)) or not math.isfinite(age) or not isinstance(stamp,int) or not 0<=age+(step*500000-stamp)/1e9<=.08:reasons.append('source_target_age')
        if not all(math.isfinite(v) for v in (command.gimbal_yaw,command.gimbal_pitch,command.force_x,command.force_y,command.yaw_torque)):reasons.append('invalid_command')
        if getattr(source,'last_actuator_saturated',False):reasons.append('actuator_saturation')
        # Alignment uses the raw angular target, not gravity-compensated actuator input.
        yaw,pitch=source.raw_ref
        if not all(math.isfinite(v) for v in (yaw,pitch)):reasons.append('invalid_reference')
        direction=response.get('direction')
        if response.get('tracking') is True and (not isinstance(direction,list) or len(direction)!=3 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in direction) or sum(v*v for v in direction)<1e-18):reasons.append('invalid_source_direction')
        if abs(math.atan2(math.sin(yaw-o.own_qpos[3]),math.cos(yaw-o.own_qpos[3])))>.05 or abs(pitch-o.own_qpos[4])>.05:reasons.append('gimbal_not_aligned')
        payload=dict(control_ns=step*500000,source_segment=source.segment) if decision is not None else None
        audit=self.delay.advance(step,decision,safe=not reasons,reasons=reasons,payload=payload)
        if decision is not None or audit['released_events'] or reasons!=self.last_reasons:self.events.append(audit)
        self.last_reasons=reasons;sim.fire_context[self.rid]=audit
        return replace(command,fire=audit['applied_level'])
