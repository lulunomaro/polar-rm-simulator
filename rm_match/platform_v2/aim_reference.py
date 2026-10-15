"""Private host reference for an explicitly declared source-base aim direction.

This preserves a direction, not target position or translation compensation.
It grants no authority or time: runtime must pass every original guard first.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from .contracts import ContractError, IDENTITY, exact, finite, vector

BASE_LINK = 'base_link'
INERTIAL_FROM_SOURCE_BASE = 'inertial_from_source_base_v1'
AIM_REFERENCES = (BASE_LINK, INERTIAL_FROM_SOURCE_BASE)


def reference_value(value):
    if type(value) is not str or value not in AIM_REFERENCES:
        raise ContractError('unsupported_aim_reference')
    return value


def validate_source_camera_budget(observation, budget):
    """Production admission needs the original bounded camera identity."""
    exact(budget, ('robot_id','episode','frame_id','capture_wall','capture_sim_time',
        'wall_deadline','sim_deadline'), 'aim_reference_camera_budget')
    camera = observation['sensors']['camera']
    if camera.get('available') is not True:
        raise ContractError('aim_reference_camera_unavailable')
    for key in ('robot_id','episode'):
        if type(budget[key]) is not type(observation[key]) or budget[key] != observation[key]:
            raise ContractError('aim_reference_camera_identity')
    for key, camera_key in (('frame_id','frame_id'), ('capture_sim_time','capture_sim_time')):
        if type(budget[key]) is not type(camera[camera_key]) or budget[key] != camera[camera_key]:
            raise ContractError('aim_reference_camera_identity')
    capture_wall = finite(budget['capture_wall'], 'aim_reference_capture_wall', 0, 1e12)
    capture_sim = finite(budget['capture_sim_time'], 'aim_reference_capture_sim', 0, 1e12)
    wall_deadline = finite(budget['wall_deadline'], 'aim_reference_wall_deadline', 0, 1e12)
    sim_deadline = finite(budget['sim_deadline'], 'aim_reference_sim_deadline', 0, 1e12)
    if (not capture_wall <= wall_deadline <= capture_wall + .08
        or not capture_sim <= sim_deadline <= capture_sim + .08
        or observation['wall_deadline'] > wall_deadline):
        raise ContractError('aim_reference_original_camera_budget')


def _items(value):
    if type(value) is not dict or any(type(k) is not str for k in value):
        raise ContractError('invalid_aim_reference_receipt')
    for v in value.values():
        if type(v) not in (str, int, float, bool, type(None)):
            raise ContractError('invalid_aim_reference_receipt')
        if type(v) in (int, float):
            try:valid = math.isfinite(v)
            except OverflowError:valid = False
            if not valid:raise ContractError('invalid_aim_reference_receipt')
    return tuple(sorted(value.items()))


def _same(left, right):
    return len(left) == len(right) and all(type(a) is type(b) and a == b for a, b in zip(left, right))


def _same_items(left, right):
    return len(left) == len(right) and all(ka == kb and _same((va,), (vb,))
        for (ka, va), (kb, vb) in zip(left, right))


@dataclass(frozen=True)
class SourceBaseAim:
    source: tuple
    source_base_yaw_rad: float
    command: tuple
    camera_budget: tuple | None

    @classmethod
    def accepted(cls, action, observation, budget):
        source = tuple(observation[k] for k in IDENTITY)
        if not _same(source, tuple(action[k] for k in IDENTITY)):
            raise ContractError('aim_reference_source_mismatch')
        yaw = vector(observation['own']['odom_xyyaw'], 3, 'aim_reference_source_odometry')[2]
        return cls(source, yaw, _items(action['command']), None if budget is None else _items(budget))

    def matches(self, action, budget):
        return (_same(self.source, tuple(action[k] for k in IDENTITY))
            and _same_items(self.command, _items(action['command']))
            and ((budget is None and self.camera_budget is None)
                or (budget is not None and self.camera_budget is not None
                    and _same_items(self.camera_budget, _items(budget)))))

    def target(self, current_base_yaw):
        current = finite(current_base_yaw, 'aim_reference_current_yaw')
        command = dict(self.command)
        delta = self.source_base_yaw_rad + command['yaw_rad'] - current
        command['yaw_rad'] = math.atan2(math.sin(delta), math.cos(delta))
        receipt = dict(reference=INERTIAL_FROM_SOURCE_BASE,
            source=dict(zip(IDENTITY, self.source)), original_command=dict(self.command),
            sensor_budget=None if self.camera_budget is None else dict(self.camera_budget),
            source_base_yaw_rad=self.source_base_yaw_rad,
            current_base_yaw_rad=current, mechanical_yaw_rad=command['yaw_rad'])
        return command, receipt
