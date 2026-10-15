"""Optional, nonblocking Nav2 goal transport; no actuator or truth authority.

The caller owns the node/executor and timeout policy. Imports create no ROS
context, thread or executor, and host wall_deadline is never compared locally.
Stopping requires resolved sends and real terminal results, not a cancel ACK.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
import math
import re

from ..platform_v2.contracts import ContractError, IDENTITY, exact, finite, identity, vector

STATUS_SCHEMA = 'polar.sim.navigation-goal-backend-status.v1'
_TERMINAL_STATUS = (4, 5, 6)  # action_msgs/GoalStatus: succeeded, canceled, aborted.


@dataclass(frozen=True)
class Nav2GoalSettings:
    mode: str
    navigation_action: str | None = None
    planner_action: str | None = None
    controller_action: str | None = None
    planner_id: str = ''
    controller_id: str = ''
    goal_checker_id: str = ''
    behavior_tree: str = ''

    def __post_init__(self):
        if type(self.mode) is not str or self.mode not in ('navigate_to_pose', 'compute_path_then_follow'):
            raise ContractError('nav2_goal_backend_mode')
        selected = ('navigation_action',) if self.mode == 'navigate_to_pose' else ('planner_action', 'controller_action')
        for key in ('navigation_action', 'planner_action', 'controller_action'):
            value = getattr(self, key)
            if key not in selected:
                if value is not None: raise ContractError('nav2_goal_unused_action')
            elif type(value) is not str or len(value) > 256 or not re.fullmatch(r'(?:/[A-Za-z_][A-Za-z0-9_]*)+', value):
                raise ContractError('nav2_goal_absolute_action_required')
        if self.mode == 'compute_path_then_follow' and self.planner_action == self.controller_action:
            raise ContractError('nav2_goal_distinct_actions_required')
        for key in ('planner_id', 'controller_id', 'goal_checker_id', 'behavior_tree'):
            value = getattr(self, key)
            if type(value) is not str or len(value) > 1024 or '\0' in value:
                raise ContractError('nav2_goal_invalid_option')
        if self.mode == 'navigate_to_pose' and any((self.planner_id, self.controller_id, self.goal_checker_id)):
            raise ContractError('nav2_goal_unused_option')
        if self.mode == 'compute_path_then_follow' and self.behavior_tree:
            raise ContractError('nav2_goal_unused_option')


@dataclass
class _Leg:
    role: str
    client: object
    send: object = None
    handle: object = None
    result: object = None
    cancel: object = None
    uuid: str | None = None
    send_resolved: bool = False
    accepted: bool = False
    terminal_status: int | None = None
    rejected: bool = False
    cancel_requested: bool = False
    cancel_acknowledged: bool = False
    uncertain: bool = False
    result_request_attempts: int = 0
    payload: object = None


@dataclass
class _Operation:
    owner: object
    operation_id: str
    source: dict
    goal: dict
    legs: list = field(default_factory=list)
    stop_requested: bool = False
    error_code: str | None = None
    fault: bool = False
    safe_rejected: bool = False
    follow_sent: bool = False


def _uuid(value):
    from array import array
    try: wire = value.uuid
    except AttributeError: raise ContractError('nav2_goal_uuid_invalid') from None
    if type(wire) in (bytes, bytearray):
        raw = bytes(wire)
    elif type(wire) is array and wire.typecode == 'B':
        raw = wire.tobytes()
    elif type(wire) in (list, tuple):
        if len(wire) != 16 or any(type(number) is not int or not 0 <= number <= 255 for number in wire):
            raise ContractError('nav2_goal_uuid_invalid')
        raw = bytes(wire)
    elif type(wire).__module__ == 'numpy':
        import numpy as np
        if type(wire) is not np.ndarray or wire.dtype != np.dtype('uint8') or wire.shape != (16,):
            raise ContractError('nav2_goal_uuid_invalid')
        raw = wire.tobytes(order='C')
    else:
        raise ContractError('nav2_goal_uuid_invalid')
    if len(raw) != 16: raise ContractError('nav2_goal_uuid_invalid')
    return raw.hex()


class Nav2GoalBackend:
    def __init__(self, node, settings, *, client_factory=None, action_types=None, pose_factory=None):
        if type(settings) is not Nav2GoalSettings: raise ContractError('nav2_goal_settings_required')
        if node is None: raise ContractError('nav2_goal_caller_node_required')
        injected = (client_factory, action_types, pose_factory)
        if all(value is None for value in injected):
            try:
                from rclpy.action import ActionClient
                from geometry_msgs.msg import PoseStamped
                from nav2_msgs.action import NavigateToPose, ComputePathToPose, FollowPath
            except (ImportError, OSError):
                raise ContractError('nav2_goal_ros_dependencies_unavailable') from None
            client_factory = ActionClient
            pose_factory = PoseStamped
            action_types = dict(navigate_to_pose=NavigateToPose,
                                compute_path_to_pose=ComputePathToPose, follow_path=FollowPath)
        elif any(value is None for value in injected):
            raise ContractError('nav2_goal_complete_dependency_injection_required')
        if not callable(client_factory) or not callable(pose_factory) or type(action_types) is not dict:
            raise ContractError('nav2_goal_invalid_dependencies')
        required = ('navigate_to_pose',) if settings.mode == 'navigate_to_pose' else ('compute_path_to_pose', 'follow_path')
        if any(name not in action_types or not callable(getattr(action_types[name], 'Goal', None)) for name in required):
            raise ContractError('nav2_goal_invalid_action_types')
        self.settings = settings
        self._types = dict(action_types)
        self._pose_factory = pose_factory
        self._owner = object()
        self._current = None
        self._closed = False
        self._clients = {}
        try:
            if settings.mode == 'navigate_to_pose':
                self._clients['navigation'] = client_factory(node, action_types['navigate_to_pose'], settings.navigation_action)
            else:
                self._clients['planner'] = client_factory(node, action_types['compute_path_to_pose'], settings.planner_action)
                self._clients['navigation'] = client_factory(node, action_types['follow_path'], settings.controller_action)
        except BaseException:
            for client in self._clients.values(): client.destroy()
            raise

    def ready(self):
        return not self._closed and all(client.server_is_ready() is True for client in self._clients.values())

    def _checked(self, operation):
        if type(operation) is not _Operation or operation.owner is not self._owner:
            raise ContractError('nav2_goal_foreign_operation')
        return operation

    def _pose(self, goal, source):
        stamp = round(source['sim_time'] * 1000000000)
        if not 0 <= stamp <= 2147483647 * 1000000000 + 999999999:
            raise ContractError('nav2_goal_simulation_stamp_out_of_range')
        pose = self._pose_factory()
        pose.header.frame_id = 'map'
        pose.header.stamp.sec, pose.header.stamp.nanosec = divmod(stamp, 1000000000)
        pose.pose.position.x, pose.pose.position.y = goal['position_m']
        pose.pose.position.z = 0.
        pose.pose.orientation.x = pose.pose.orientation.y = 0.
        pose.pose.orientation.z = math.sin(goal['yaw_rad'] / 2.)
        pose.pose.orientation.w = math.cos(goal['yaw_rad'] / 2.)
        return pose

    def start(self, goal, source, *, operation_id):
        if self._closed: raise ContractError('nav2_goal_backend_closed')
        exact(source, IDENTITY, 'nav2_goal_source'); identity(source)
        if type(operation_id) is not str or not operation_id or len(operation_id) > 128 or '\0' in operation_id:
            raise ContractError('nav2_goal_operation_id')
        exact(goal, ('frame', 'position_m', 'yaw_rad'), 'nav2_goal')
        if type(goal['frame']) is not str or goal['frame'] != 'map': raise ContractError('nav2_goal_map_frame_required')
        parsed = dict(frame='map', position_m=vector(goal['position_m'], 2, 'nav2_goal_position', -100000, 100000),
                      yaw_rad=finite(goal['yaw_rad'], 'nav2_goal_yaw', -math.pi, math.pi))
        if self._current is not None:
            if operation_id == self._current.operation_id: raise ContractError('nav2_goal_duplicate_operation')
            if not self._stop_confirmed(self._current): raise ContractError('nav2_goal_previous_operation_not_stopped')
        operation = _Operation(self._owner, operation_id, copy.deepcopy(source), parsed)
        pose = self._pose(parsed, source)
        self._current = operation
        if not self.ready():
            operation.safe_rejected = True; operation.error_code = 'action_server_unavailable'
            return operation
        if self.settings.mode == 'navigate_to_pose':
            request = self._types['navigate_to_pose'].Goal()
            request.pose = pose; request.behavior_tree = self.settings.behavior_tree
            self._send(operation, 'navigation', request)
        else:
            request = self._types['compute_path_to_pose'].Goal()
            request.goal = pose; request.use_start = False; request.planner_id = self.settings.planner_id
            self._send(operation, 'planner', request)
        return operation

    def _fault(self, operation, code):
        operation.fault = True
        if operation.error_code is None: operation.error_code = code

    def _send(self, operation, role, request):
        leg = _Leg(role, self._clients[role]); operation.legs.append(leg)
        try: leg.send = leg.client.send_goal_async(request)
        except Exception:
            leg.uncertain = True; self._fault(operation, 'send_request_failed')

    @staticmethod
    def _stop_confirmed(operation):
        return not any(leg.uncertain or not leg.send_resolved
                       or (leg.accepted and leg.terminal_status is None) for leg in operation.legs)

    def _request_cancel(self, operation, leg):
        if not leg.accepted or leg.terminal_status is not None or leg.cancel_requested: return
        leg.cancel_requested = True
        try: leg.cancel = leg.handle.cancel_goal_async()
        except Exception: self._fault(operation, 'cancel_request_failed')

    def cancel(self, operation):
        operation = self._checked(operation)
        operation.stop_requested = True
        for leg in operation.legs: self._request_cancel(operation, leg)

    def _request_result(self, operation, leg):
        if not leg.accepted or leg.result is not None or leg.result_request_attempts >= 2: return
        # One bounded retry of a read-only GetResult request is safe after a
        # synchronous getter failure. Never resend the goal or its cancellation.
        leg.result_request_attempts += 1
        try: leg.result = leg.handle.get_result_async()
        except Exception:
            leg.uncertain = True; self._fault(operation, 'send_or_result_future_failed')

    def _poll_leg(self, operation, leg):
        if not leg.send_resolved:
            if leg.send is None or not leg.send.done(): return
            try:
                handle = leg.send.result()
                if type(handle.accepted) is not bool: raise ValueError('accepted_type')
                leg.send_resolved = True
                if not handle.accepted:
                    leg.rejected = True
                    return
            except Exception:
                leg.uncertain = True; self._fault(operation, 'send_or_result_future_failed')
                return
            # A server-accepted handle is owned even when local metadata parsing
            # fails. Keep it for a real cancel and GetResult; never drop a live
            # goal merely because its generated UUID representation was rejected.
            leg.handle = handle; leg.accepted = True
            try: leg.uuid = _uuid(handle.goal_id)
            except Exception:
                leg.uncertain = True; self._fault(operation, 'send_or_result_future_failed')
        self._request_result(operation, leg)
        if operation.stop_requested or operation.fault: self._request_cancel(operation, leg)
        if leg.cancel is not None and leg.cancel.done():
            try:
                reply = leg.cancel.result()
                if type(reply.return_code) is not int: raise ValueError('cancel_code_type')
                if reply.return_code == 0:
                    if not any(_uuid(info.goal_id) == leg.uuid for info in reply.goals_canceling):
                        raise ValueError('cancel_uuid_mismatch')
                    leg.cancel_acknowledged = True
                elif operation.error_code is None:
                    operation.error_code = 'cancel_not_acknowledged'
            except Exception:
                self._fault(operation, 'cancel_response_invalid')
            leg.cancel = None
        if leg.result is not None and leg.result.done() and leg.terminal_status is None:
            try:
                reply = leg.result.result()
                if type(reply.status) is not int or reply.status not in _TERMINAL_STATUS:
                    raise ValueError('result_status_not_terminal')
                leg.terminal_status = reply.status; leg.payload = reply.result
                # A genuine terminal reply on the preserved accepted handle,
                # with its valid original UUID, resolves resource uncertainty.
                # The operation's business fault remains sticky and visible.
                if leg.send_resolved and leg.accepted and leg.uuid is not None:
                    leg.uncertain = False
            except Exception:
                leg.uncertain = True; self._fault(operation, 'result_future_invalid')

    def _follow(self, operation, planner):
        if operation.follow_sent or operation.stop_requested or operation.fault or operation.safe_rejected: return
        if planner.rejected or planner.terminal_status != 4: return
        if self._clients['navigation'].server_is_ready() is not True:
            operation.safe_rejected = True; operation.error_code = 'action_server_unavailable'
            return
        try:
            path = planner.payload.path
            if (type(path.header.frame_id) is not str or path.header.frame_id != 'map'
                or not 1 <= len(path.poses) <= 10000): raise ValueError('invalid_path')
            request = self._types['follow_path'].Goal()
            request.path = copy.deepcopy(path)
            request.controller_id = self.settings.controller_id
            request.goal_checker_id = self.settings.goal_checker_id
        except Exception:
            self._fault(operation, 'planner_path_invalid')
            return
        operation.follow_sent = True
        self._send(operation, 'navigation', request)

    def poll(self, operation):
        operation = self._checked(operation)
        for leg in tuple(operation.legs): self._poll_leg(operation, leg)
        if self.settings.mode == 'compute_path_then_follow' and operation.legs:
            self._follow(operation, operation.legs[0])
        stopped = self._stop_confirmed(operation)
        if operation.fault:
            state = 'fault'
        elif operation.safe_rejected or any(leg.rejected for leg in operation.legs):
            state = 'rejected'
        elif operation.stop_requested:
            state = ('canceled' if any(leg.terminal_status == 5 for leg in operation.legs)
                     else 'stopped') if stopped else 'canceling'
        elif any(leg.terminal_status == 6 for leg in operation.legs):
            state = 'aborted'
        elif any(leg.terminal_status == 5 for leg in operation.legs):
            state = 'canceled'
        elif operation.legs and operation.legs[-1].role == 'navigation' and operation.legs[-1].terminal_status == 4:
            state = 'succeeded'
        elif any(not leg.send_resolved for leg in operation.legs):
            state = 'sending'
        else:
            state = 'active'
        terminal = stopped and state in ('succeeded', 'canceled', 'stopped', 'rejected', 'aborted', 'fault')
        return dict(schema=STATUS_SCHEMA, operation_id=operation.operation_id,
                    source=copy.deepcopy(operation.source), state=state,
                    goal_uuids={role: next((leg.uuid for leg in operation.legs if leg.role == role), None)
                                for role in ('planner', 'navigation')},
                    terminal=terminal,
                    cancel_acknowledged=any(leg.cancel_acknowledged for leg in operation.legs),
                    stop_confirmed=stopped, error_code=operation.error_code)

    def destroy(self):
        """No implicit cancel-and-forget; caller must drive outstanding results."""
        if self._current is not None and not self._stop_confirmed(self._current):
            raise ContractError('nav2_goal_operations_not_stopped')
        if self._closed: return
        for client in self._clients.values(): client.destroy()
        self._closed = True
