"""One published scan shared by exact-stamp feedback and later goal actuation.

The stage keeps the original PB bridge's local 50 ms deadline. Observing a scan
does not submit/renew a goal. Consuming it never publishes or timestamps it again.
ROS resources and the actual TFBuffer belong to the caller.
"""
from __future__ import annotations

import copy
import re
import threading
import time

from .pb_goal_controller_source import PBGoalControllerSource, _same_tree
from .pb_navigation_bridge import navigation_status
from .ros2_bridge import BridgeError, MAX_RESPONSE, parse_json
from ..platform_v2.contracts import IDENTITY, exact, integer
from ..platform_v2.navigation_feedback_contracts import (
    ESTIMATE_METHOD, goal_status_from_lifecycle, navigation_feedback,
    unavailable_navigation_feedback,
)


class PBGoalPluginSource(PBGoalControllerSource):
    def __init__(self, settings, *, lookup_estimate, provenance, navigation_ready,
                 goal_snapshot=None, record=None, record_stage=None, clock=time.perf_counter):
        if not callable(lookup_estimate) or not callable(navigation_ready):
            raise BridgeError("pb_staged_estimate_callbacks_required")
        if any(item is not None and not callable(item) for item in (goal_snapshot, record, record_stage)):
            raise BridgeError("pb_staged_diagnostic_callback")
        exact(provenance, ("producer_source_sha256", "localization_binary_sha256", "mapping_binary_sha256"),
              "pb_staged_provenance")
        if any(type(value) is not str or not re.fullmatch("[a-f0-9]{64}", value) for value in provenance.values()):
            raise BridgeError("pb_staged_provenance_hash")
        super().__init__(settings, clock=clock)
        self.lookup_estimate, self.navigation_ready = lookup_estimate, navigation_ready
        self.provenance = dict(method=ESTIMATE_METHOD, **copy.deepcopy(provenance))
        self.goal_snapshot = goal_snapshot
        self.record, self.record_stage = record, record_stage
        self._stage = None
        self._stage_used = False
        self._stage_busy = False
        self._localization_stamps = []

    def _event(self, event, *, _wall=None, **fields):
        if self.record_stage is None or self._stage is None:
            return
        o = self._stage;cloud = o["sensors"]["pointcloud"]
        self.record_stage(dict(event=event, source={k: copy.deepcopy(o[k]) for k in IDENTITY},
            scan=dict(cloud_frame_id=cloud["frame_id"], acquisition_start_ns=cloud["acquisition_start_ns"],
                acquisition_end_ns=cloud["acquisition_end_ns"], profile_sha256=cloud["profile_sha256"]),
            local_wall=self.clock() if _wall is None else _wall,
            local_deadline=self._deadline, clock="linux_local_perf_counter", **fields))

    def _native(self, kind, row):
        if self.record is not None:
            self.record(dict(topic_kind=kind, value=copy.deepcopy(row), receive_wall=self.clock(),
                receive_clock="linux_local_perf_counter"))

    def discard_stage(self, reason="superseded"):
        with self._slot():
            if self._stage_busy:
                raise BridgeError("pb_staged_concurrent_operation")
            if self._source_scan_owner is not None and self._source_scan_owner != threading.get_ident():
                raise BridgeError("pb_staged_owned_thread_required")
            self._event("stage_discard", reason=reason)
            self._pending = None;self._result = None
            self._source_capture = None;self._source_scan = None;self._source_scan_owner = None
            self._stage = None;self._stage_used = False;self._localization_stamps = []

    def receive_localization(self, payload):
        with self._slot():
            if self._source_scan_owner is not None and self._source_scan_owner != threading.get_ident():
                raise BridgeError("pb_staged_owned_thread_required")
            if self._pending is None or self._closed or self.clock() >= self._deadline:
                raise BridgeError("pb_staged_no_live_localization")
            row = parse_json(bytes(payload) if type(payload) is bytearray else payload, MAX_RESPONSE)
            fields = ("schema", "adapter_id", *IDENTITY, "cloud_frame_id", "acquisition_start_ns",
                      "acquisition_end_ns", "localization_stamp_ns")
            exact(row, fields, "pb_staged_localization")
            if (type(row["schema"]) is not str or row["schema"] != "polar.sim.pb-localization-result.v1"
                or type(row["adapter_id"]) is not str or row["adapter_id"] != self.settings.adapter_id):
                raise BridgeError("pb_staged_localization_route")
            if any(type(row[k]) is not type(self._pending[k]) or row[k] != self._pending[k] for k in IDENTITY):
                raise BridgeError("pb_staged_localization_identity")
            cloud = self._pending["sensors"]["pointcloud"]
            for key, original in (("cloud_frame_id", cloud["frame_id"]),
                ("acquisition_start_ns", cloud["acquisition_start_ns"]),
                ("acquisition_end_ns", cloud["acquisition_end_ns"])):
                integer(row[key], key)
                if row[key] != original:
                    raise BridgeError("pb_staged_localization_scan")
            stamp = integer(row["localization_stamp_ns"], "localization_stamp_ns")
            if not cloud["acquisition_start_ns"] <= stamp <= cloud["acquisition_end_ns"]:
                raise BridgeError("pb_staged_localization_window")
            self._localization_stamps.append(stamp)
            self._localization_stamps = self._localization_stamps[-64:]
            self._native("localization", row)

    def receive_result(self, payload):
        raw = bytes(payload) if type(payload) is bytearray else payload
        super().receive_result(raw)
        self._native("controller_result", parse_json(raw, MAX_RESPONSE))

    def _goals(self, o):
        if self.goal_snapshot is None:
            return None
        return goal_status_from_lifecycle(self.goal_snapshot(), o)

    def _estimate(self):
        if not self._localization_stamps:
            return None, "pending_localization"
        # Each candidate is an actual native source event of THIS scan. This is
        # not nearest/latest TF selection, and no stamp is rewritten on return.
        for stamp in reversed(self._localization_stamps):
            transform = self.lookup_estimate(stamp)
            if transform is None:
                continue
            exact(transform, ("header", "child_frame_id", "transform"), "pb_staged_transform")
            exact(transform["header"], ("stamp", "frame_id"), "pb_staged_transform_header")
            time_value = transform["header"]["stamp"]
            exact(time_value, ("sec", "nanosec"), "pb_staged_transform_stamp")
            actual = integer(time_value["sec"], "tf_sec") * 1000000000 + integer(time_value["nanosec"], "tf_nanosec", 0, 999999999)
            if (actual != stamp or type(transform["header"]["frame_id"]) is not str
                or transform["header"]["frame_id"] != "map" or type(transform["child_frame_id"]) is not str
                or transform["child_frame_id"] != "base_link"):
                raise BridgeError("pb_staged_transform_exact_stamp_required")
            cloud = self._stage["sensors"]["pointcloud"]
            self._native("estimated_transform", dict(source={k: copy.deepcopy(self._stage[k]) for k in IDENTITY},
                scan=dict(cloud_frame_id=cloud["frame_id"], acquisition_start_ns=cloud["acquisition_start_ns"],
                    acquisition_end_ns=cloud["acquisition_end_ns"], profile_sha256=cloud["profile_sha256"]),
                requested_stamp_ns=stamp, transform=copy.deepcopy(transform)))
            exact(transform["transform"], ("translation", "rotation"), "pb_staged_transform_value")
            p, q = transform["transform"]["translation"], transform["transform"]["rotation"]
            exact(p, ("x", "y", "z"), "pb_staged_transform_position")
            exact(q, ("x", "y", "z", "w"), "pb_staged_transform_rotation")
            navigation = dict(available=True, reason="available", frame="map", child_frame="base_link",
                stamp_ns=actual, localization_stamp_ns=stamp,
                position_m=[p[k] for k in "xyz"], rotation_xyzw=[q[k] for k in "xyzw"],
                provenance=copy.deepcopy(self.provenance))
            # A malformed native transform is an error even while Nav2 is
            # configuring; readiness cannot conceal NaNs or invalid rotation.
            navigation_feedback(self._stage, navigation)
            ready = self.navigation_ready()
            if type(ready) is not bool:
                raise BridgeError("pb_staged_navigation_ready_type")
            if not ready:
                return None, "pending_navigation"
            return navigation, "available"
        return None, "map_transform_unavailable"

    def observe(self, observation, transport):
        with self._slot():
            self.discard_stage("superseded")
            self._stage_busy = True
        try:
            bundle, request = super().begin(observation)
            self._stage = copy.deepcopy(self._pending)
            self._event("stage_begin", begin_wall=self._deadline - self.settings.response_timeout,
                response_timeout_s=self.settings.response_timeout, published_count=0)
            transport.publish_bundle(bundle, request)
            self._native("request", parse_json(request.encode(), MAX_RESPONSE))
            self._event("stage_published", published_count=1)
            navigation, reason = None, "pending_localization"
            while self.clock() < self._deadline:
                navigation, reason = self._estimate()
                if navigation is not None or reason == "pending_navigation":
                    break
                transport.spin_once(min(.002, max(0., self._deadline - self.clock())))
            goals = self._goals(self._stage)
            if self.clock() >= self._deadline:
                feedback = unavailable_navigation_feedback(self._stage, "staged_scan_expired", goal_status=goals)
            elif navigation is None:
                feedback = unavailable_navigation_feedback(self._stage, reason, goal_status=goals)
            else:
                feedback = navigation_feedback(self._stage, navigation, goal_status=goals)
                if self.clock() >= self._deadline:
                    feedback = unavailable_navigation_feedback(self._stage, "staged_scan_expired", goal_status=goals)
            self._event("stage_feedback", available=feedback["navigation"]["available"],
                reason=feedback["navigation"]["reason"])
            return feedback
        except BaseException:
            self._pending = None;self._result = None;self._source_capture = None
            self._source_scan = None;self._source_scan_owner = None
            self._stage = None;self._localization_stamps = []
            raise
        finally:
            self._stage_busy = False

    def consume_sourced(self, observation, transport):
        with self._slot():
            if self._stage_busy or self._stage is None or self._stage_used:
                raise BridgeError("pb_staged_original_observation_required")
            if self._source_scan_owner != threading.get_ident():
                raise BridgeError("pb_staged_owned_thread_required")
            if not _same_tree(observation, self._stage):
                raise BridgeError("pb_staged_observation_changed")
            self._stage_used = True;self._stage_busy = True
        self._event("stage_act_enter")
        try:
            while self._result is None and self.clock() < self._deadline:
                transport.spin_once(min(.002, max(0., self._deadline - self.clock())))
            if self._result is not None and self.clock() < self._deadline:
                captured = self._source_capture
                if (captured is None or captured[0] is not self._source_scan
                    or not _same_tree(captured[1], self._result)):
                    raise BridgeError("pb_staged_action_capture_mismatch")
                response = dict(value=copy.deepcopy(self._result), goal_uuid=captured[2])
                if self.clock() >= self._deadline:
                    response = dict(value=navigation_status(self._stage, "no_associated_command"), goal_uuid=None)
            else:
                cloud = self._stage["sensors"]["pointcloud"]
                localized = bool(self._localization_stamps) or cloud["acquisition_start_ns"] <= self._odom_stamp <= cloud["acquisition_end_ns"]
                status = "no_associated_command" if localized else "pending_localization"
                response = dict(value=navigation_status(self._stage, status), goal_uuid=None)
            finish = self.clock()
            if "command" in response["value"] and finish >= self._deadline:
                response = dict(value=navigation_status(self._stage, "no_associated_command"), goal_uuid=None)
            kind = "action" if "command" in response["value"] else "status"
            self._event("stage_act_exit", _wall=finish, value_kind=kind, goal_uuid=response["goal_uuid"],
                status=response["value"].get("status"))
            if kind == "action" and self.clock() >= self._deadline:
                raise BridgeError("pb_staged_local_budget_expired")
            return response
        finally:
            self._stage_busy = False
            self.discard_stage("consumed")

    def close(self):
        self.discard_stage("closed")
        super().close()
