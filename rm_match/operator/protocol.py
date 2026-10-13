"""Versioned control lease. Pure Python: no physics, rendering or hardware imports."""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
import math
import threading
import time
import uuid

from .autoaim import AutoAimRequest, parse_aim_request

SCHEMA = 'polar.sim.operator.v1'
DEFAULT_ROBOT = 'red_infantry'


def finite_number(value):
    """Reject JSON numeric extremes without leaking a conversion exception."""
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False

ROBOT_IDS = tuple(f'{team}_{role}' for team in ('red', 'blue')
                  for role in ('hero', 'infantry', 'sentry'))


@dataclass(frozen=True)
class MouseAngle:
    generation: int
    yaw_total_rad: float
    pitch_total_rad: float


def parse_mouse_angle(value):
    if not isinstance(value, dict) or set(value) != {'generation','yaw_total_rad','pitch_total_rad'}:
        raise ValueError('invalid_mouse_angle')
    generation=value['generation']
    if type(generation) is not int or not 0 <= generation <= 2**53-1:
        raise ValueError('invalid_mouse_generation')
    for key in ('yaw_total_rad','pitch_total_rad'):
        if not finite_number(value[key]) or abs(value[key]) > 1e6:
            raise ValueError('invalid_mouse_total')
    return MouseAngle(generation,float(value['yaw_total_rad']),float(value['pitch_total_rad']))


@dataclass(frozen=True)
class DriveAxes:
    forward_mps: float = 0.
    left_mps: float = 0.


def parse_drive_axes(value):
    if not isinstance(value, dict) or set(value) != {'forward_mps','left_mps'}:
        raise ValueError('invalid_drive_axes')
    for key in ('forward_mps','left_mps'):
        if not finite_number(value[key]) or abs(value[key]) > 1.:
            raise ValueError('invalid_drive_axes_'+key)
    forward,left=float(value['forward_mps']),float(value['left_mps'])
    norm=max(1.,math.hypot(forward,left))
    return DriveAxes(forward/norm,left/norm)


@dataclass(frozen=True)
class OperatorInput:
    vx_mps: float = 0.
    vy_mps: float = 0.
    yaw_rate_rps: float = 0.
    pitch_rate_rps: float = 0.
    fire: bool = False
    mouse_angle: MouseAngle | None = None
    aim_request: AutoAimRequest = field(default_factory=AutoAimRequest)
    drive_axes: DriveAxes | None = None

    def movement_requested(self):
        # Exact nonzero check: even a small new-axis request revokes stationary
        # source authority. Legacy vx/vy do not carry these reference-frame axes.
        axes=self.drive_axes
        return (self.vx_mps != 0. or self.vy_mps != 0.
                or (axes is not None and (axes.forward_mps != 0. or axes.left_mps != 0.)))


@dataclass(frozen=True)
class ModeRequest:
    spin_enabled: bool = False
    spin_direction: str = 'auto'
    spin_speed_dps: float = 420.
    chassis_follow: str = 'free'
    spin_origin: str = 'manual'


def parse_mode_request(value):
    if not isinstance(value, dict):
        raise ValueError('invalid_mode_request')
    keys={'spin_enabled','spin_direction','spin_speed_dps','chassis_follow'}
    if set(value) not in (keys, keys | {'spin_origin'}):
        raise ValueError('unsupported_mode_fields')
    if type(value['spin_enabled']) is not bool:
        raise ValueError('invalid_spin_enabled')
    if value['spin_direction'] not in ('auto','cw','ccw'):
        raise ValueError('unsupported_spin_direction')
    speed=value['spin_speed_dps']
    if not finite_number(speed) or not 120 <= speed <= 720:
        raise ValueError('invalid_spin_speed_dps')
    if value['chassis_follow'] not in ('free','gimbal','field'):
        raise ValueError('unsupported_chassis_follow')
    origin=value.get('spin_origin','manual')
    if origin not in ('manual','on_hit'):
        raise ValueError('invalid_spin_origin')
    return ModeRequest(value['spin_enabled'],value['spin_direction'],float(speed),value['chassis_follow'],origin)


class ControlGate:
    """Explicit session/epoch/robot ownership and a wall-monotonic deadman lease.

    HTTP is stateless; disappearance is detected by the 250 ms lease, not by TCP
    connection closure. A received release or focus loss clears it synchronously.
    Network threads never access MuJoCo. The physics loop samples this gate before
    every physics step, including after rendering or other slow work.
    """
    def __init__(self, robot_id=DEFAULT_ROBOT, *, ttl_ms=250, wall=time.time,
                 monotonic=time.monotonic, session_id=None):
        if robot_id not in ROBOT_IDS:
            raise ValueError('Unknown robot')
        if not 50 <= ttl_ms <= 250:
            raise ValueError('Control TTL must be between 50 and 250 ms')
        self.lock = threading.RLock()
        self.wall, self.monotonic = wall, monotonic
        self.session_id = session_id or str(uuid.uuid4())
        self.epoch = 0
        self.robot_id = robot_id
        self.ttl_ms = ttl_ms
        self.last_seq = -1
        self.accepted_count = self.rejected_count = 0
        self.reason = 'no_control'
        self.input = OperatorInput()
        self.deadline = 0.
        self.enabled = True
        self.mouse_generation = -1
        self.mouse_revoked_generation = -1
        self.mouse_consumed = (0.,0.)
        self.mouse_consumed_seq = -1
        self.mouse_consumed_reason = 'no_input'
        self.safety_revision = 0
        self.source_autoaim_ready = False
        self.source_autoaim_robots = ()
        self.requested_mode = ModeRequest()
        self.active_mode = ModeRequest()
        self.mode_origin_explicit = False
        self.mode_request_explicit = False
        self.mode_request_seq = -1
        # HTTP selection is enabled only after the runtime validates its actual
        # model/judge roster. This is not permission to connect to hardware.
        self.selection_robots = ()
        self.last_selection_id = -1
        self.selection_requires_release = False
        self.drive_frame_requires_release = False

    def configure_selection(self, robot_ids):
        """Called by the physics owner after model/actuator/camera validation."""
        robots = tuple(robot_ids)
        if not robots or len(set(robots)) != len(robots) or any(r not in ROBOT_IDS for r in robots):
            raise ValueError('Invalid simulation selection roster')
        if self.robot_id not in robots:
            raise ValueError('Selected robot is absent from simulation')
        with self.lock:
            self.selection_robots = robots

    def select_robot(self, message):
        """Identity transaction only; no model, renderer, judge or source calls.

        A lost ACK is reconciled with GET /session. Replaying a successful
        request cannot increment epoch twice. Every failed request is neutral.
        """
        with self.lock:
            selection_id = message.get('selection_id') if isinstance(message, dict) else None
            requested = message.get('requested_robot_id') if isinstance(message, dict) else None
            def reject(reason):
                result = self._reject(reason)
                result.update(selection_id=selection_id, last_selection_id=self.last_selection_id,
                              requested_robot_id=requested, requires_rearm=True, match_reset=False)
                return result
            # Revoke the active lease before inspecting any proposed selection.
            self.neutral('selection_requested')
            keys = {'session_id','epoch','robot_id','selection_id','requested_robot_id','sent_at_ms'}
            if not isinstance(message, dict) or set(message) != keys:
                return reject('invalid_selection_fields')
            if not self.enabled:
                return reject('simulation_stopped')
            if not self.selection_robots:
                return reject('selection_unavailable')
            if message['session_id'] != self.session_id:
                return reject('session_mismatch')
            if type(message['epoch']) is not int or message['epoch'] != self.epoch:
                return reject('epoch_mismatch')
            if message['robot_id'] != self.robot_id:
                return reject('robot_mismatch')
            if type(selection_id) is not int or not 0 <= selection_id <= 2**53-1:
                return reject('invalid_selection_id')
            if selection_id <= self.last_selection_id:
                return reject('selection_out_of_order')
            stamp = message['sent_at_ms']
            if not finite_number(stamp):
                return reject('invalid_timestamp')
            age_ms = self.wall()*1000-stamp
            if age_ms < -50 or age_ms >= self.ttl_ms:
                return reject('expired_or_future_timestamp')
            if not isinstance(requested, str) or requested not in self.selection_robots:
                return reject('unknown_selection_robot')
            previous_robot, previous_epoch = self.robot_id, self.epoch
            self.new_epoch(requested)
            self.last_selection_id = selection_id
            self.selection_requires_release = True
            self.reason = 'robot_selected'
            return dict(schema=SCHEMA, accepted=True, reason='robot_selected',
                        session_id=self.session_id, epoch=self.epoch, robot_id=self.robot_id,
                        selection_id=selection_id, last_selection_id=self.last_selection_id,
                        previous_robot_id=previous_robot, previous_epoch=previous_epoch,
                        requested_robot_id=requested, requires_rearm=True, match_reset=False,
                        server_time_ms=self.wall()*1000)

    def neutral(self, reason):
        with self.lock:
            self.mouse_revoked_generation = max(self.mouse_revoked_generation,self.mouse_generation)
            self.mouse_consumed = (0.,0.)
            self.mouse_consumed_seq = -1
            self.mouse_consumed_reason = 'revoked'
            self.safety_revision += 1
            self.input = OperatorInput()
            self.active_mode = ModeRequest()
            self.deadline = 0.
            self.reason = reason

    def new_epoch(self, robot_id=None):
        with self.lock:
            if robot_id is not None:
                if robot_id not in ROBOT_IDS:
                    raise ValueError('Unknown robot')
                self.robot_id = robot_id
            self.epoch += 1
            self.last_seq = -1
            self.requested_mode = ModeRequest()
            self.mode_origin_explicit = False
            self.mode_request_explicit = False
            self.mode_request_seq = -1
            self.drive_frame_requires_release = False
            self.neutral('epoch_changed')
            return self.epoch

    def disable(self, reason='simulation_stopped'):
        with self.lock:
            self.enabled = False
            self.neutral(reason)

    def sample(self):
        with self.lock:
            if self.deadline and self.monotonic() >= self.deadline:
                self.neutral('control_timeout')
            return self.input

    def _reject(self, reason, seq=None):
        self.rejected_count += 1
        self.neutral(reason)
        return dict(schema=SCHEMA, accepted=False, reason=reason,
                    session_id=self.session_id, epoch=self.epoch,
                    robot_id=self.robot_id, seq=seq, last_seq=self.last_seq,
                    server_time_ms=self.wall()*1000)

    def accept(self, message):
        with self.lock:
            # A renewal arriving after an elapsed lease starts a new safety
            # generation, even when its requested values are identical.
            self.sample()
            if not isinstance(message, dict):
                return self._reject('invalid_object')
            seq = message.get('seq')
            if not self.enabled:
                return self._reject('simulation_stopped', seq)
            if message.get('session_id') != self.session_id:
                return self._reject('session_mismatch', seq)
            if type(message.get('epoch')) is not int or message['epoch'] != self.epoch:
                return self._reject('epoch_mismatch', seq)
            if message.get('robot_id') != self.robot_id:
                return self._reject('robot_mismatch', seq)
            if type(seq) is not int or seq < 0 or seq > 2**53-1:
                return self._reject('invalid_seq')
            if seq <= self.last_seq:
                return self._reject('out_of_order', seq)
            stamp = message.get('sent_at_ms')
            if not finite_number(stamp):
                return self._reject('invalid_timestamp', seq)
            age_ms = self.wall()*1000 - stamp
            if age_ms < -50 or age_ms >= self.ttl_ms:
                return self._reject('expired_or_future_timestamp', seq)
            for flag in ('focus', 'deadman', 'fire'):
                if type(message.get(flag)) is not bool:
                    return self._reject('invalid_'+flag, seq)
            if self.selection_requires_release and message['focus'] and message['deadman']:
                return self._reject('selection_release_required', seq)
            values = {}
            for key, bound in [('vx_mps', 1.), ('vy_mps', 1.),
                               ('yaw_rate_rps', 2.), ('pitch_rate_rps', 2.)]:
                value = message.get(key)
                if not finite_number(value) or abs(value) > bound:
                    return self._reject('invalid_'+key, seq)
                values[key] = float(value)
            # Normalize diagonal motion to the advertised resultant speed limit.
            norm = math.hypot(values['vx_mps'], values['vy_mps'])
            if norm > 1:
                values['vx_mps'] /= norm
                values['vy_mps'] /= norm
            try:
                mouse = parse_mouse_angle(message['mouse_angle']) if 'mouse_angle' in message else None
                if mouse is not None and (values['yaw_rate_rps'] != 0 or values['pitch_rate_rps'] != 0):
                    raise ValueError('mixed_mouse_angle_and_rate')
                if message['focus'] and message['deadman']:
                    if mouse is not None:
                        if mouse.generation <= self.mouse_revoked_generation or mouse.generation < self.mouse_generation:
                            raise ValueError('revoked_mouse_generation')
                        if self.reason == 'active' and self.input.mouse_angle is not None and mouse.generation != self.mouse_generation:
                            raise ValueError('mouse_generation_changed_while_active')
                    elif self.reason == 'active' and self.input.mouse_angle is not None:
                        raise ValueError('mouse_angle_missing_while_active')
                mode = parse_mode_request(message['mode_request']) if 'mode_request' in message else ModeRequest()
                drive_axes = parse_drive_axes(message['drive_axes']) if 'drive_axes' in message else None
                if drive_axes is not None and (values['vx_mps'] != 0. or values['vy_mps'] != 0.):
                    raise ValueError('mixed_drive_axes_and_legacy_velocity')
                if mode.chassis_follow != 'free' and drive_axes is None:
                    raise ValueError('drive_axes_required_for_mode')
                if 'aim_request' in message and message['aim_request'] is None:
                    raise ValueError('invalid_aim_request')
                aim_request = parse_aim_request(message.get('aim_request'))
            except ValueError as exc:
                return self._reject(str(exc),seq)
            if message['focus'] and message['deadman']:
                if (self.reason == 'active' and mode.chassis_follow != self.active_mode.chassis_follow):
                    self.drive_frame_requires_release = True
                if self.drive_frame_requires_release:
                    return self._reject('drive_frame_release_required',seq)
            self.requested_mode = mode
            self.mode_request_explicit = 'mode_request' in message
            self.mode_origin_explicit = 'spin_origin' in message.get('mode_request',{})
            self.mode_request_seq = seq
            self.last_seq = seq
            self.accepted_count += 1
            if not message['focus'] or not message['deadman']:
                self.selection_requires_release = False
                self.drive_frame_requires_release = False
                self.neutral('focus_lost' if not message['focus'] else 'deadman_released')
            else:
                if mouse is not None and mouse.generation != self.mouse_generation:
                    self.mouse_generation=mouse.generation
                    self.mouse_consumed=(0.,0.)
                next_input = OperatorInput(**values, fire=message['fire'], aim_request=aim_request, mouse_angle=mouse, drive_axes=drive_axes)
                if (next_input.aim_request != self.input.aim_request
                    or next_input.vx_mps != self.input.vx_mps or next_input.vy_mps != self.input.vy_mps
                    or next_input.drive_axes != self.input.drive_axes
                    or mode != self.active_mode):
                    self.safety_revision += 1
                self.input = next_input
                self.active_mode = mode
                # A command already aged in transit never obtains a fresh full TTL.
                self.deadline = self.monotonic() + (self.ttl_ms-max(age_ms, 0.))/1000
                self.reason = 'active'
            return dict(schema=SCHEMA, accepted=True, reason=self.reason,
                        session_id=self.session_id, epoch=self.epoch,
                        robot_id=self.robot_id, seq=seq, last_seq=self.last_seq,
                        server_time_ms=self.wall()*1000)

    def consume_mouse_angle(self, *, discard=False):
        """Physics-owner consumption, independent of wall or simulation step duration."""
        with self.lock:
            value=self.sample().mouse_angle
            if self.reason != 'active' or value is None:
                return (0.,0.)
            total=(value.yaw_total_rad,value.pitch_total_rad)
            delta=tuple(a-b for a,b in zip(total,self.mouse_consumed))
            self.mouse_consumed=total
            self.mouse_consumed_seq=self.last_seq
            self.mouse_consumed_reason='discarded_by_authority' if discard else 'consumed'
            return (0.,0.) if discard else delta

    def status(self):
        with self.lock:
            self.sample()
            return dict(schema=SCHEMA, session_id=self.session_id, epoch=self.epoch,
                        robot_id=self.robot_id, server_time_ms=self.wall()*1000,
                        ttl_ms=self.ttl_ms, state='active' if self.reason == 'active' else 'idle',
                        reason=self.reason, last_seq=self.last_seq, safety_revision=self.safety_revision,
                        mouse_angle_last_generation=max(self.mouse_generation,self.mouse_revoked_generation),
                        mouse_angle_ack=dict(generation=self.mouse_generation,revoked_generation=self.mouse_revoked_generation,
                            consumed_yaw_total_rad=self.mouse_consumed[0],consumed_pitch_total_rad=self.mouse_consumed[1],
                            consumed_control_seq=self.mouse_consumed_seq,reason=self.mouse_consumed_reason),
                        accepted_count=self.accepted_count, rejected_count=self.rejected_count,
                        last_selection_id=self.last_selection_id,
                        selection_requires_release=self.selection_requires_release,
                        drive_frame_requires_release=self.drive_frame_requires_release,
                        control=asdict(self.input))

    def session(self):
        with self.lock:
            return self._session_locked()

    def _session_locked(self):
        result = self.status()
        result.update(robots=list(ROBOT_IDS), simulation_only=True,
                      hardware_transport=False, coordinate_frame='chassis_body',
                      axes=dict(vx_mps='forward', vy_mps='left',
                                yaw_rate_rps='gimbal_left_positive',
                                pitch_rate_rps='gimbal_up_positive'),
                      limits=dict(speed_mps=1., yaw_rate_rps=2., pitch_rate_rps=2.,
                                  gimbal_yaw_rad=[-3.14,3.14], gimbal_pitch_rad=[-.4,.5]),
                      first_person_camera=self.robot_id+'__aim',
                      endpoints=dict(control='/control', telemetry='/telemetry', frame='/frame.jpg',
                                     select_robot='/select_robot'),
                      capabilities=dict(robot_selection=bool(self.selection_robots),
                                        robot_selection_version=1, reset=False,
                                        automatic_targeting=self.source_autoaim_ready and self.robot_id in self.source_autoaim_robots,
                                        autoaim_robots=list(self.source_autoaim_robots),
                                        autoaim_stationary_only=bool(self.source_autoaim_robots),
                                        autoaim_fire_authority='manual_only',
                                        autoaim_source_identity='rmcs-sim-operator-fov-v1' if self.source_autoaim_robots else None,
                                        aim_request_version=1, operator_modes_version=1, mouse_angle_input_version=1,
                                        spin_mode=True, spin_directions=['auto','cw','ccw'],
                                        spin_speed_dps=[120,720], chassis_follow_modes=['free'], chassis_drive_modes=['free','gimbal','field'],
                                        chassis_drive_frame_version=1,
                                        power_guard=False, buffer_protect=False,
                                        auto_spin_on_hit=True, auto_spin_on_hit_damage_version=1,
                                        auto_spin_on_hit_policy='client_existing_controller',
                                        auto_spin_on_hit_power_guard_supported=False, world_stabilized_gimbal=False))
        result['drive_frame_contract'] = dict(version=1, input_field='drive_axes',
            axes=dict(forward_mps='forward',left_mps='left'), units='m/s',
            yaw_units='rad',yaw_positive='counterclockwise_viewed_from_above',
            free='current_own_chassis_world_yaw',field='world_+X_forward_+Y_left_no_team_mirror',
            gimbal='current_own_chassis_world_yaw_plus_relative_gimbal_yaw',
            legacy_vx_vy_frame='chassis_body',legacy_nonzero_with_drive_axes='rejected',
            automatic_chassis_yaw_follow=False,world_stabilized_gimbal=False)
        result['robot_profiles'] = [dict(robot_id=rid, team=rid.split('_',1)[0],
            role=rid.split('_',1)[1], capabilities=dict(
                automatic_targeting=self.source_autoaim_ready and rid in self.source_autoaim_robots,
                autoaim_stationary_only=rid in self.source_autoaim_robots,
                autoaim_fire_authority='manual_only', spin_mode=True, auto_spin_on_hit=True,
                chassis_follow_modes=['free'], chassis_drive_modes=['free','gimbal','field'], chassis_drive_frame_version=1, power_guard=False, buffer_protect=False,
                world_stabilized_gimbal=False)) for rid in self.selection_robots]
        return result
