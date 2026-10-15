"""Read-only scan/action/FollowPath joins, with no actuator or clock authority.

Lifecycle UUIDs are evidence from the recorded backend accepted handles. This
audit cannot create that provenance, infer encoder stop, or select a latest goal.
"""
from __future__ import annotations

import copy
import math
import re

from rm_match.platform_v2.contracts import IDENTITY, exact, identity, integer, validate_action
from rm_match.platform_v2.decision_contracts import validate_decision_intent_shape
from tools.qa_pb_navigation_sil import audit_navigation_consumption


LIFECYCLE_SCHEMA = "polar.sim.navigation-goal-lifecycle.v1"
RESULT_SCHEMA = "polar.sim.pb-navigation-result.v2"
CONTROLLER_ID = "nav2_server_pb_pid_goal_v1"
_RECORD_FIELDS = (
    "operation_id", "origin_intent", "latest_authorization", "goal", "state",
    "goal_uuids", "cancel_requested", "cancel_acknowledged", "terminal",
    "stop_confirmed", "error_code", "stop_intent", "stop_reason",
)
_TERMINAL = {"succeeded", "canceled", "stopped", "rejected", "aborted"}


def _uuid(value):
    if type(value) is not str or not re.fullmatch("[0-9a-f]{32}", value):
        raise ValueError("goal_uuid_type_or_format")
    return value


def _source(value):
    exact(value, IDENTITY, "goal_audit_identity")
    identity(value)
    return {name: copy.deepcopy(value[name]) for name in IDENTITY}


def _key(value):
    identity(value)
    return tuple((type(value[name]).__name__, value[name]) for name in IDENTITY)


def _typed(value):
    """Retain JSON value types; bool/int and int/float cannot alias a receipt."""
    if type(value) is dict:
        return (dict, tuple((name, _typed(item)) for name, item in sorted(value.items())))
    if type(value) is list:
        return (list, tuple(_typed(item) for item in value))
    if type(value) not in (str, int, float, bool, type(None)):
        raise ValueError("goal_audit_non_json_value")
    return type(value), value


def _same_context(a, b):
    return all(type(a[name]) is type(b[name]) and a[name] == b[name]
               for name in ("robot_id", "episode", "binding_epoch"))


def _record(record):
    exact(record, _RECORD_FIELDS, "goal_audit_record")
    operation = _uuid(record["operation_id"])
    origin = validate_decision_intent_shape(record["origin_intent"])
    if origin["command"]["behavior"] != "navigate_to_pose":
        raise ValueError("goal_origin_not_navigation")
    origin_source = {name: origin[name] for name in IDENTITY}
    if _typed(record["goal"]) != _typed(origin["command"]["goal"]):
        raise ValueError("goal_origin_geometry_changed")
    exact(record["goal_uuids"], ("planner", "navigation"), "goal_audit_uuids")
    navigation = _uuid(record["goal_uuids"]["navigation"])
    planner = record["goal_uuids"]["planner"]
    if planner is not None:
        _uuid(planner)
        if planner == navigation:
            raise ValueError("goal_roles_share_uuid")
    for name in ("cancel_requested", "cancel_acknowledged", "terminal", "stop_confirmed"):
        if type(record[name]) is not bool:
            raise ValueError("goal_record_boolean")
    state = record["state"]
    if type(state) is not str or state not in _TERMINAL | {"sending", "active", "canceling", "fault"}:
        raise ValueError("goal_record_state")
    if state != "fault" and record["terminal"] != (state in _TERMINAL):
        raise ValueError("goal_record_terminal")
    if record["stop_confirmed"] and not record["terminal"]:
        raise ValueError("goal_stop_without_terminal")
    if record["cancel_acknowledged"] and not record["cancel_requested"]:
        raise ValueError("goal_cancel_ack_without_request")
    if state == "canceled" and not (record["cancel_requested"] and
            record["cancel_acknowledged"] and record["stop_confirmed"]):
        raise ValueError("goal_cancel_unproved")
    if state == "stopped" and not (record["cancel_requested"] and record["stop_confirmed"]):
        raise ValueError("goal_stop_unrequested")
    if state == "fault" and record["terminal"] and not record["stop_confirmed"]:
        raise ValueError("goal_fault_stop_unproved")
    code = record["error_code"]
    if code is not None and (type(code) is not str or not re.fullmatch("[a-z][a-z0-9_]{0,63}", code)):
        raise ValueError("goal_record_error_code")
    latest = record["latest_authorization"]
    if latest is not None:
        _source(latest)
        if (not _same_context(latest, origin_source) or
                latest["observed_seq"] < origin_source["observed_seq"] or
                latest["sim_time"] < origin_source["sim_time"]):
            raise ValueError("goal_latest_authorization_source")
    stop = record["stop_intent"]
    if stop is not None:
        stop = validate_decision_intent_shape(stop)
        if not _same_context(stop, origin_source) or stop["observed_seq"] < origin_source["observed_seq"]:
            raise ValueError("goal_stop_intent_source")
    reason = record["stop_reason"]
    if reason is not None and (type(reason) is not str or reason not in {
            "hold", "cancel", "authorization_expired", "replaced", "fault", "shutdown"}):
        raise ValueError("goal_stop_reason")
    return operation, planner, navigation, copy.deepcopy(origin_source)


def _audit_goal_navigation_consumption(rows, ros_rows, lifecycle):
    """Attribute original physical receipts; does not qualify the whole scenario.

    The existing scan/LIO/SDK audit runs first. Per-goal counts permit accepted
    targets with zero motion; a caller may separately require multiple moving
    goals. No receive-wall clocks or cancel/terminal times enter the join.
    """
    errors = []
    try:
        navigation = audit_navigation_consumption(rows, ros_rows,
                                                  result_profile="follow_path_uuid_v2")
        errors.extend("navigation:" + str(error) for error in navigation["errors"])
        if navigation.get("passed") is not True and not navigation["errors"]:
            errors.append("navigation:no_qualified_consumption")
    except (KeyError, TypeError, ValueError):
        navigation = dict(passed=False, errors=["navigation_audit_input_invalid"])
        errors.append("navigation_audit_input_invalid")
    per_goal = {}
    try:
        if type(lifecycle) is not dict or type(lifecycle.get("schema")) is not str or lifecycle["schema"] != LIFECYCLE_SCHEMA:
            raise ValueError("goal_lifecycle_schema")
        records = lifecycle["goals"]
        if type(records) is not list or not 1 <= len(records) <= 256:
            raise ValueError("goal_lifecycle_history")
        seen_operations, seen_uuids = set(), set()
        context = None
        for record in records:
            operation, planner, uuid, origin = _record(record)
            if operation in seen_operations:
                raise ValueError("goal_operation_reused")
            seen_operations.add(operation)
            for identifier in (planner, uuid):
                if identifier is not None:
                    if identifier in seen_uuids:
                        raise ValueError("goal_uuid_reused")
                    seen_uuids.add(identifier)
            if context is not None and not _same_context(context, origin):
                raise ValueError("goal_history_generation_changed")
            context = origin
            per_goal[uuid] = dict(origin_source=origin, controller_results=0,
                                  consumed_steps=0, nonzero_consumed_steps=0)
    except (KeyError, TypeError, ValueError) as exc:
        errors.append("lifecycle:" + str(exc))
        per_goal = {}

    candidates = {}
    source_goals = {}
    controller_results = 0
    for index, row in enumerate(ros_rows):
        if type(row) is not dict or row.get("topic_kind") != "controller_result":
            continue
        try:
            value = row["value"]
            exact(value, ("schema", "adapter_id", "action", "source"), "goal_audit_result")
            if type(value["schema"]) is not str or value["schema"] != RESULT_SCHEMA:
                raise ValueError("goal_result_profile")
            if type(value["adapter_id"]) is not str or value["adapter_id"] != "custom_pb_navigation":
                raise ValueError("goal_result_adapter")
            source = value["source"]
            exact(source, ("cloud_frame_id", "localization_stamp_ns", "controller_stamp_ns",
                           "controller_id", "goal_uuid"), "goal_audit_result_source")
            uuid = _uuid(source["goal_uuid"])
            if type(source["controller_id"]) is not str or source["controller_id"] != CONTROLLER_ID:
                raise ValueError("goal_result_controller")
            for name in ("cloud_frame_id", "localization_stamp_ns", "controller_stamp_ns"):
                integer(source[name], name)
            action = validate_action(value["action"], value["action"],
                                     dict(kind="navigation", output_modes=["velocity_body"]))
            if uuid not in per_goal:
                raise ValueError("goal_result_uuid_not_accepted")
            origin = per_goal[uuid]["origin_source"]
            if (not _same_context(action, origin) or action["observed_seq"] < origin["observed_seq"] or
                    action["sim_time"] < origin["sim_time"]):
                raise ValueError("goal_result_precedes_origin")
            if not source["localization_stamp_ns"] <= source["controller_stamp_ns"] <= round(action["sim_time"] * 1e9):
                raise ValueError("goal_result_stamp_order")
            key = (_key(action), _typed(action))
            candidates.setdefault(key, set()).add(uuid)
            source_goals.setdefault(_key(action), set()).add(uuid)
            per_goal[uuid]["controller_results"] += 1
            controller_results += 1
        except (KeyError, TypeError, ValueError) as exc:
            errors.append("result[" + str(index) + "]:" + str(exc))

    consumed, nonzero = set(), set()
    step_owners = {}
    per_consumed = {uuid: set() for uuid in per_goal}
    per_nonzero = {uuid: set() for uuid in per_goal}
    for index, row in enumerate(rows):
        if type(row) is not dict or row.get("event") != "navigation_consumed" or row.get("phase") != "integration_entry":
            continue
        try:
            motion = row["target"].get("motion")
            if motion is None:
                continue
            action = row["action"]
            validate_action(action, action, dict(kind="navigation", output_modes=["velocity_body"]))
            if _typed(motion) != _typed(action["command"]):
                raise ValueError("goal_consumed_action_changed")
            matches = candidates.get((_key(action), _typed(action)), set())
            if len(source_goals.get(_key(action), set())) > 1:
                raise ValueError("goal_consumption_ambiguous")
            if len(matches) != 1:
                raise ValueError("goal_consumption_ambiguous" if matches else "goal_consumption_unmatched")
            uuid = next(iter(matches))
            # Consume sim_time is an existing physical-step key, not a new stamp.
            step = (action["robot_id"], row["consume_sim_time"])
            owner = (uuid, _typed(action))
            if step in step_owners and step_owners[step] != owner:
                raise ValueError("goal_physical_step_conflict")
            step_owners[step] = owner
            consumed.add(step)
            per_consumed[uuid].add(step)
            if any(abs(motion[name]) > 1e-8 for name in ("vx_mps", "vy_mps", "wz_rps")):
                nonzero.add(step)
                per_nonzero[uuid].add(step)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append("receipt[" + str(index) + "]:" + str(exc))
    for uuid, values in per_goal.items():
        values["consumed_steps"] = len(per_consumed[uuid])
        values["nonzero_consumed_steps"] = len(per_nonzero[uuid])
    return dict(passed=navigation.get("passed") is True and not errors, errors=errors,
                per_goal=per_goal, actual_controller_results=controller_results,
                consumed_steps=len(consumed), nonzero_consumed_steps=len(nonzero),
                navigation_audit=navigation,
                qualification="recorded FollowPath UUID/source/action/physical receipt join; no encoder stop or current-goal inference")


def _json_plain(value, parents=None):
    if type(value) in (dict, list):
        parents = set() if parents is None else parents
        identifier = id(value)
        if identifier in parents:
            raise ValueError("goal_audit_cycle")
        parents.add(identifier)
        try:
            if type(value) is dict:
                if any(type(key) is not str for key in value):
                    raise ValueError("goal_audit_non_json_key")
                items = value.values()
            else:
                items = value
            for item in items:
                _json_plain(item, parents)
        finally:
            parents.remove(identifier)
    elif type(value) is float:
        if not math.isfinite(value):
            raise ValueError("goal_audit_nonfinite")
    elif type(value) not in (str, int, bool, type(None)):
        raise ValueError("goal_audit_non_json_value")


def audit_goal_navigation_consumption(rows, ros_rows, lifecycle):
    """Fail closed even for partial/failed probe records; never hides cleanup."""
    try:
        if type(rows) is not list or type(ros_rows) is not list or type(lifecycle) is not dict:
            raise ValueError("goal_audit_input_shape")
        _json_plain((dict(rows=rows, ros_rows=ros_rows, lifecycle=lifecycle)))
        result = _audit_goal_navigation_consumption(rows, ros_rows, lifecycle)
    except Exception:
        return dict(passed=False, errors=["goal_audit_input_invalid"], per_goal={},
                    actual_controller_results=0, consumed_steps=0, nonzero_consumed_steps=0)
    if not result["passed"]:
        result["per_goal"] = {}
    return result
