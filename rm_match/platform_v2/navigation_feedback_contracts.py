"""Estimated navigation feedback with its original scan and algorithm stamp.

The schema checks declared relationships; it cannot tell a fabricated pose from
an estimate merely by inspecting numbers or hash strings. Reviewed owned
producers must prove the exact LIO-context/TFBuffer lookup and pinned binaries.
No simulator state, ideal odometry, enemy state or foreign-clock arithmetic is
an input. Missing evidence is explicit unavailable, never an old retagged pose.
"""
from __future__ import annotations

import copy
import re

from .contracts import ContractError, IDENTITY, exact, finite, identity, integer, vector
from .decision_contracts import validate_decision_intent_shape
from .navigation_contracts import validate_navigation_observation


FEEDBACK_SCHEMA = "polar.sim.navigation-feedback.v1"
NAVIGATION_FEEDBACK_SCHEMA = FEEDBACK_SCHEMA
ESTIMATE_METHOD = "tf_buffer_exact_localization_stamp_v1"
UNAVAILABLE_REASONS = frozenset(("not_provided", "pending_localization", "map_transform_unavailable",
                                 "staged_scan_expired", "pending_navigation"))
_RECEIPT_FIELDS = ("operation_id", "origin_intent", "latest_authorization", "goal_uuids",
                   "state", "cancel_requested", "terminal", "stop_confirmed")
_TERMINAL = frozenset(("succeeded", "canceled", "stopped", "rejected", "aborted"))
_STATES = _TERMINAL | {"sending", "active", "canceling", "fault"}


def _same(a, b):
    if type(a) is not type(b):
        return False
    if type(a) is dict:
        return set(a) == set(b) and all(_same(a[key], b[key]) for key in a)
    if type(a) is list:
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def _six(value):
    return {name: value[name] for name in IDENTITY}


def _source(value):
    exact(value, IDENTITY, "navigation_feedback_source")
    identity(value)
    return value


def _context(a, b):
    return all(type(a[name]) is type(b[name]) and a[name] == b[name]
               for name in ("robot_id", "episode", "binding_epoch"))


def _ordered(a, b):
    return (_context(a, b) and a["observed_seq"] <= b["observed_seq"]
            and a["sim_time"] <= b["sim_time"])


def _hex(value, size, label, *, nullable=False):
    if value is None and nullable:
        return
    if type(value) is not str or not re.fullmatch("[0-9a-f]{" + str(size) + "}", value):
        raise ContractError("invalid_navigation_feedback_" + label)


def _scan(value, source):
    exact(value, ("cloud_frame_id", "acquisition_start_ns", "acquisition_end_ns", "profile_sha256"),
          "navigation_feedback_scan")
    for name in ("cloud_frame_id", "acquisition_start_ns", "acquisition_end_ns"):
        integer(value[name], "feedback_" + name)
    if not 0 < value["acquisition_end_ns"] - value["acquisition_start_ns"] <= 200000000:
        raise ContractError("navigation_feedback_scan_window")
    if value["acquisition_end_ns"] > round(source["sim_time"] * 1000000000):
        raise ContractError("navigation_feedback_scan_future")
    _hex(value["profile_sha256"], 64, "profile_hash")


def _receipt(value, source):
    exact(value, _RECEIPT_FIELDS, "navigation_feedback_goal_receipt")
    _hex(value["operation_id"], 32, "operation_id")
    origin = validate_decision_intent_shape(value["origin_intent"])
    latest = _source(value["latest_authorization"])
    if (origin["command"]["behavior"] != "navigate_to_pose" or
            not _ordered(origin, latest) or not _ordered(latest, source)):
        raise ContractError("navigation_feedback_goal_source_order")
    exact(value["goal_uuids"], ("planner", "navigation"), "navigation_feedback_goal_uuids")
    for uuid in value["goal_uuids"].values():
        _hex(uuid, 32, "goal_uuid", nullable=True)
    state = value["state"]
    if type(state) is not str or state not in _STATES:
        raise ContractError("navigation_feedback_goal_state")
    for name in ("cancel_requested", "terminal", "stop_confirmed"):
        if type(value[name]) is not bool:
            raise ContractError("navigation_feedback_goal_boolean")
    if state == "succeeded" and value["goal_uuids"]["navigation"] is None:
        raise ContractError("navigation_feedback_success_uuid_missing")
    if state == "fault":
        if value["terminal"] and not value["stop_confirmed"]:
            raise ContractError("navigation_feedback_fault_stop")
    elif value["terminal"] != (state in _TERMINAL):
        raise ContractError("navigation_feedback_goal_terminal")
    if value["stop_confirmed"] and not value["terminal"]:
        raise ContractError("navigation_feedback_goal_stop")
    if state in ("canceling", "canceled", "stopped") and not value["cancel_requested"]:
        raise ContractError("navigation_feedback_cancel_unrequested")
    if state in ("canceled", "stopped") and not value["stop_confirmed"]:
        raise ContractError("navigation_feedback_cancel_stop_unproved")


def _goal_status(value, source):
    if type(value) is not dict or type(value.get("available")) is not bool:
        raise ContractError("navigation_feedback_goal_status")
    if value["available"] is False:
        exact(value, ("available", "reason"), "navigation_feedback_goal_unavailable")
        if type(value["reason"]) is not str or value["reason"] not in ("not_provided", "lifecycle_unavailable"):
            raise ContractError("navigation_feedback_goal_reason")
        return
    exact(value, ("available", "selection", "history", "operation_count", "stop_requested", "fault"),
          "navigation_feedback_goal_status")
    integer(value["operation_count"], "feedback_operation_count", 0, 256)
    history = value["history"]
    if (type(history) is not list or len(history) > 8 or value["operation_count"] < len(history)
            or (value["operation_count"] == 0) != (len(history) == 0)):
        raise ContractError("navigation_feedback_goal_history_size")
    if type(value["stop_requested"]) is not bool:
        raise ContractError("navigation_feedback_stop_requested")
    fault = value["fault"]
    if fault is not None and (type(fault) is not str or not re.fullmatch("[a-z][a-z0-9_]{0,63}", fault)):
        raise ContractError("navigation_feedback_fault_code")
    operations, navigation_uuids = {}, set()
    for item in history:
        _receipt(item, source)
        operation = item["operation_id"]
        if operation in operations:
            raise ContractError("navigation_feedback_duplicate_operation")
        operations[operation] = item
        uuid = item["goal_uuids"]["navigation"]
        if uuid is not None:
            if uuid in navigation_uuids:
                raise ContractError("navigation_feedback_duplicate_navigation_uuid")
            navigation_uuids.add(uuid)
    selection = value["selection"]
    if selection is not None:
        _receipt(selection, source)
        if (not _same(operations.get(selection["operation_id"]), selection)
                or (selection["terminal"] and selection["stop_confirmed"])):
            raise ContractError("navigation_feedback_current_selection")


def validate_navigation_feedback(value, observation=None):
    """Validate detached declared feedback; optional NAV input binds the scan."""
    value = copy.deepcopy(value)
    exact(value, ("schema", "source", "scan", "navigation", "goal_status"), "navigation_feedback")
    if type(value["schema"]) is not str or value["schema"] != FEEDBACK_SCHEMA:
        raise ContractError("unsupported_navigation_feedback")
    source = _source(value["source"])
    _scan(value["scan"], source)
    if observation is not None:
        original = validate_navigation_observation(observation)
        if not _same(source, _six(original)) or not _same(value["scan"], _reference(original)):
            raise ContractError("navigation_feedback_original_scan_mismatch")
    nav = value["navigation"]
    if type(nav) is not dict or type(nav.get("available")) is not bool:
        raise ContractError("navigation_feedback_estimate")
    if nav["available"] is False:
        exact(nav, ("available", "reason"), "navigation_feedback_unavailable")
        if type(nav["reason"]) is not str or nav["reason"] not in UNAVAILABLE_REASONS:
            raise ContractError("navigation_feedback_unavailable_reason")
    else:
        exact(nav, ("available", "reason", "frame", "child_frame", "stamp_ns", "localization_stamp_ns",
                    "position_m", "rotation_xyzw", "provenance"), "navigation_feedback_estimate")
        if (type(nav["reason"]) is not str or nav["reason"] != "available" or type(nav["frame"]) is not str
                or nav["frame"] != "map" or type(nav["child_frame"]) is not str or nav["child_frame"] != "base_link"):
            raise ContractError("navigation_feedback_frames")
        integer(nav["stamp_ns"], "navigation_feedback_stamp")
        integer(nav["localization_stamp_ns"], "navigation_feedback_localization_stamp")
        if (nav["stamp_ns"] != nav["localization_stamp_ns"] or
                not value["scan"]["acquisition_start_ns"] <= nav["stamp_ns"] <= value["scan"]["acquisition_end_ns"] or
                nav["stamp_ns"] > round(source["sim_time"] * 1000000000)):
            raise ContractError("navigation_feedback_original_stamp")
        vector(nav["position_m"], 3, "navigation_feedback_position", -100000, 100000)
        q = vector(nav["rotation_xyzw"], 4, "navigation_feedback_rotation", -1, 1)
        if abs(sum(number * number for number in q) - 1) > 1e-6:
            raise ContractError("navigation_feedback_rotation_not_unit")
        provenance = nav["provenance"]
        exact(provenance, ("method", "producer_source_sha256", "localization_binary_sha256", "mapping_binary_sha256"),
              "navigation_feedback_provenance")
        if type(provenance["method"]) is not str or provenance["method"] != ESTIMATE_METHOD:
            raise ContractError("navigation_feedback_estimator_method")
        for name in ("producer_source_sha256", "localization_binary_sha256", "mapping_binary_sha256"):
            _hex(provenance[name], 64, name)
    _goal_status(value["goal_status"], source)
    return value


def _reference(observation):
    try:
        cloud = observation["sensors"]["pointcloud"]
        return dict(cloud_frame_id=cloud["frame_id"], acquisition_start_ns=cloud["acquisition_start_ns"],
                    acquisition_end_ns=cloud["acquisition_end_ns"], profile_sha256=cloud["profile_sha256"])
    except (KeyError, TypeError):
        raise ContractError("navigation_feedback_observation_reference") from None


def navigation_feedback(observation, navigation, *, goal_status=None):
    if type(observation) is not dict or any(name not in observation for name in IDENTITY):
        raise ContractError("navigation_feedback_observation_identity")
    if goal_status is None:
        goal_status = dict(available=False, reason="not_provided")
    return validate_navigation_feedback(dict(schema=FEEDBACK_SCHEMA, source=_six(observation),
        scan=_reference(observation), navigation=navigation, goal_status=goal_status), observation)


def unavailable_navigation_feedback(observation, reason="not_provided", *, goal_status=None):
    return navigation_feedback(observation, dict(available=False, reason=reason), goal_status=goal_status)


def goal_status_from_lifecycle(snapshot, observation):
    """Project actual last eight records; None active does not choose history."""
    original = validate_navigation_observation(observation)
    if (type(snapshot) is not dict or type(snapshot.get("schema")) is not str
            or snapshot["schema"] != "polar.sim.navigation-goal-lifecycle.v1"):
        raise ContractError("navigation_feedback_lifecycle_schema")
    records = snapshot.get("goals")
    if type(records) is not list or len(records) > 256:
        raise ContractError("navigation_feedback_lifecycle_history")
    try:
        projected = [{key: copy.deepcopy(item[key]) for key in _RECEIPT_FIELDS} for item in records[-8:]]
        active = snapshot["active"]
        selection = None
        if active is not None:
            _hex(active, 32, "active_operation")
            matches = [item for item in projected if item["operation_id"] == active]
            if len(matches) != 1:
                raise ContractError("navigation_feedback_active_record_missing")
            selection = copy.deepcopy(matches[0])
        value = dict(available=True, selection=selection, history=projected, operation_count=len(records),
                     stop_requested=copy.deepcopy(snapshot["stop_requested"]), fault=copy.deepcopy(snapshot["fault"]))
    except (KeyError, TypeError):
        raise ContractError("navigation_feedback_lifecycle_fields") from None
    _goal_status(value, _six(original))
    return value


class NavigationFeedbackHistory:
    """One binding's observe stream, after stateless validation (not act stream)."""
    def __init__(self):
        self._source = None
        self._last = None
        self._records = {}
        self._navigation_owners = {}
        self._operation_count = 0
        self._profile_sha256 = None
        self._provenance = None

    def check(self, feedback):
        value = validate_navigation_feedback(feedback)
        source = value["source"]
        if self._profile_sha256 is not None and value["scan"]["profile_sha256"] != self._profile_sha256:
            raise ContractError("navigation_feedback_history_profile_changed")
        provenance = value["navigation"].get("provenance") if value["navigation"]["available"] else None
        if self._provenance is not None and provenance is not None and not _same(provenance, self._provenance):
            raise ContractError("navigation_feedback_history_producer_changed")
        if self._source is not None:
            if not _ordered(self._source, source):
                raise ContractError("navigation_feedback_history_source_reversed")
            if source["observed_seq"] == self._source["observed_seq"]:
                if not _same(source, self._source) or not _same(value, self._last):
                    raise ContractError("navigation_feedback_history_response_changed")
                return value
        goals = value["goal_status"]
        staged = {}
        owners = {}
        if goals["available"]:
            if goals["operation_count"] < self._operation_count:
                raise ContractError("navigation_feedback_history_count_reversed")
            for item in goals["history"]:
                operation = item["operation_id"]
                prior = self._records.get(operation)
                if prior is not None:
                    if not _same(prior["origin_intent"], item["origin_intent"]):
                        raise ContractError("navigation_feedback_history_origin_changed")
                    before, after = prior["latest_authorization"], item["latest_authorization"]
                    if not _ordered(before, after) or (before["observed_seq"] == after["observed_seq"] and not _same(before, after)):
                        raise ContractError("navigation_feedback_history_authorization_reversed")
                    for name in ("planner", "navigation"):
                        uuid = prior["goal_uuids"][name]
                        if uuid is not None and item["goal_uuids"][name] != uuid:
                            raise ContractError("navigation_feedback_history_uuid_changed")
                    for name in ("cancel_requested", "terminal", "stop_confirmed"):
                        if prior[name] and not item[name]:
                            raise ContractError("navigation_feedback_history_goal_reversed")
                    if prior["terminal"] and prior["state"] != item["state"]:
                        raise ContractError("navigation_feedback_history_terminal_changed")
                uuid = item["goal_uuids"]["navigation"]
                if uuid is not None:
                    owner = owners.get(uuid, self._navigation_owners.get(uuid))
                    if owner is not None and owner != operation:
                        raise ContractError("navigation_feedback_history_uuid_reused")
                    owners[uuid] = operation
                staged[operation] = copy.deepcopy(item)
            count = len(set(self._records) | set(staged))
            if count > 256 or count > goals["operation_count"]:
                raise ContractError("navigation_feedback_history_count_invalid")
        # Everything above is checked before publishing any new history/owner.
        detached = copy.deepcopy(value)
        self._records.update(staged)
        self._navigation_owners.update(owners)
        if goals["available"]:
            self._operation_count = goals["operation_count"]
        self._source = copy.deepcopy(source)
        self._last = detached
        self._profile_sha256 = value["scan"]["profile_sha256"]
        if provenance is not None:
            self._provenance = copy.deepcopy(provenance)
        return value
