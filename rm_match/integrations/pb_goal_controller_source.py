"""Retain the UUID from one strictly validated PB server-computation result.

This optional source adapter starts no resources. One caller owns the bridge and
spins its transport executor on the same thread. Concurrent callers/results fail
closed instead of waiting on a lock or borrowing another scan's UUID.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import threading

from .pb_navigation_bridge import NavigationBridge, NavigationSettings
from .ros2_bridge import BridgeError, MAX_RESPONSE, parse_json


def _same_tree(left, right):
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(_same_tree(left[k], right[k]) for k in left)
    if type(left) is list:
        return len(left) == len(right) and all(_same_tree(a, b) for a, b in zip(left, right))
    return left == right


class PBGoalControllerSource(NavigationBridge):
    """Explicit v2 PB source for ``GoalNavigationCompute`` callback injection.

    The caller owns reset, transport, stack, executor and real goal cleanup.
    ``exchange_sourced(observation, transport)`` returns exactly ``value`` and
    ``goal_uuid``. A status carries None. A UUID is read only from the same raw
    server payload which passed the unchanged parent bridge's source checks.
    """

    def __init__(self, settings, **kwargs):
        if (type(settings) is not NavigationSettings
            or settings.result_profile != "follow_path_uuid_v2"
            or settings.controller_id != "nav2_server_pb_pid_goal_v1"):
            raise BridgeError("pb_goal_source_explicit_v2_settings_required")
        if settings.response_timeout > .05:
            raise BridgeError("pb_goal_source_50ms_budget_required")
        super().__init__(settings, **kwargs)
        self._source_lock = threading.RLock()
        self._source_busy = False
        self._source_owner = None
        self._source_scan_owner = None
        self._source_scan = None
        self._source_capture = None

    @contextmanager
    def _slot(self):
        if not self._source_lock.acquire(blocking=False):
            raise BridgeError("pb_goal_source_concurrent_access")
        try:
            yield
        finally:
            self._source_lock.release()

    def reset(self, context, config):
        with self._slot():
            super().reset(context, config)
            self._source_scan = None
            self._source_capture = None

    def begin(self, observation):
        with self._slot():
            if self._source_busy and self._source_owner != threading.get_ident():
                raise BridgeError("pb_goal_source_concurrent_exchange")
            result = super().begin(observation)
            self._source_scan = object()
            self._source_scan_owner = threading.get_ident()
            self._source_capture = None
            return result

    def receive_result(self, payload):
        with self._slot():
            if self._source_scan_owner is not None and self._source_scan_owner != threading.get_ident():
                raise BridgeError("pb_goal_source_result_requires_owned_spin_thread")
            # Freeze a mutable wire buffer before BOTH reads. Parent validation
            # remains authoritative for route, typed6, scan, LIO, velocity,
            # duplicate result and the original local response deadline.
            raw = bytes(payload) if type(payload) is bytearray else payload
            super().receive_result(raw)
            accepted = parse_json(raw, MAX_RESPONSE)
            self._source_capture = (
                self._source_scan, copy.deepcopy(accepted["action"]), accepted["source"]["goal_uuid"])

    def exchange_sourced(self, observation, transport):
        with self._slot():
            if self._source_busy:
                raise BridgeError("pb_goal_source_concurrent_exchange")
            self._source_busy = True
            self._source_owner = threading.get_ident()
            self._source_capture = None
        try:
            # No source lock spans publish_bundle/spin_once or waits for DDS.
            kind, value = super().exchange(observation, transport)
            with self._slot():
                if kind == "action":
                    captured = self._source_capture
                    if (captured is None or captured[0] is not self._source_scan
                        or not _same_tree(captured[1], value)):
                        raise BridgeError("pb_goal_source_action_capture_mismatch")
                    response = dict(value=copy.deepcopy(value), goal_uuid=captured[2])
                    # UUID extraction/copy/lock acquisition never extends the
                    # parent's original scan-response deadline.
                    if self.clock() >= self._deadline:
                        raise BridgeError("pb_goal_source_local_budget_expired")
                    return response
                if kind != "status":
                    raise BridgeError("pb_goal_source_invalid_exchange_kind")
                return dict(value=copy.deepcopy(value), goal_uuid=None)
        finally:
            with self._slot():
                self._source_capture = None
                self._source_scan = None
                self._source_scan_owner = None
                self._source_owner = None
                self._source_busy = False

    def close(self):
        with self._slot():
            if self._source_busy and self._source_owner != threading.get_ident():
                raise BridgeError("pb_goal_source_concurrent_exchange")
            super().close()
            self._source_capture = None
            self._source_scan = None
            self._source_scan_owner = None
