"""Current-intent authorization for a source-bound navigation result.

This validates relationships, not the provenance of a UUID. The adapter and
reviewed native computation hook must supply the actual accepted goal handle.
No clock is sampled and no deadline, source, action or status is manufactured.
History is per binding metadata continuity, not a source of actuator authority.
"""
from __future__ import annotations

import copy
import re

from .contracts import ContractError, IDENTITY, exact, identity, validate_action
from .decision_contracts import validate_decision_intent_shape
from .navigation_contracts import (NAV_STATUS_SCHEMA, validate_navigation_observation,
                                   validate_navigation_status)


GOAL_RESULT_SCHEMA = "polar.sim.navigation-goal-result.v1"
_SELECTION_FIELDS = ("operation_id", "origin_intent", "latest_authorization", "goal_uuids",
                     "state", "cancel_requested", "terminal", "stop_confirmed")
_TERMINAL = {"succeeded", "canceled", "stopped", "rejected", "aborted"}
_STATES = _TERMINAL | {"sending", "active", "canceling", "fault"}


def _same(a, b):
    if type(a) is not type(b):
        return False
    if type(a) is dict:
        return set(a) == set(b) and all(_same(a[key], b[key]) for key in a)
    if type(a) is list:
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def _source(value):
    exact(value, IDENTITY, "goal_navigation_source")
    identity(value)
    return value


def _six(value):
    return {name: value[name] for name in IDENTITY}


def _context(a, b):
    return all(type(a[name]) is type(b[name]) and a[name] == b[name]
               for name in ("robot_id", "episode", "binding_epoch"))


def _not_later(earlier, later):
    return (_context(earlier, later) and earlier["observed_seq"] <= later["observed_seq"]
            and earlier["sim_time"] <= later["sim_time"])


def _uuid(value, *, nullable=True):
    if value is None and nullable:
        return
    if type(value) is not str or not re.fullmatch("[0-9a-f]{32}", value):
        raise ContractError("goal_navigation_uuid")


def _selection(value, current):
    if value is None:
        return
    exact(value, _SELECTION_FIELDS, "goal_navigation_selection")
    _uuid(value["operation_id"], nullable=False)
    origin = validate_decision_intent_shape(value["origin_intent"])
    if origin["command"]["behavior"] != "navigate_to_pose" or not _not_later(origin, current):
        raise ContractError("goal_navigation_origin")
    latest = _source(value["latest_authorization"])
    if not _not_later(origin, latest) or not _not_later(latest, current):
        raise ContractError("goal_navigation_authorization_order")
    exact(value["goal_uuids"], ("planner", "navigation"), "goal_navigation_uuids")
    for uuid in value["goal_uuids"].values():
        _uuid(uuid)
    state = value["state"]
    if type(state) is not str or state not in _STATES:
        raise ContractError("goal_navigation_selection_state")
    if state == "succeeded" and value["goal_uuids"]["navigation"] is None:
        raise ContractError("goal_navigation_success_uuid_missing")
    for name in ("cancel_requested", "terminal", "stop_confirmed"):
        if type(value[name]) is not bool:
            raise ContractError("goal_navigation_selection_boolean")
    if state == "fault":
        if value["terminal"] and not value["stop_confirmed"]:
            raise ContractError("goal_navigation_fault_stop")
    elif value["terminal"] != (state in _TERMINAL):
        raise ContractError("goal_navigation_terminal")
    if value["stop_confirmed"] and not value["terminal"]:
        raise ContractError("goal_navigation_stop")
    if state in ("canceling", "canceled", "stopped") and not value["cancel_requested"]:
        raise ContractError("goal_navigation_cancel_unrequested")
    if state in ("canceled", "stopped") and not value["stop_confirmed"]:
        raise ContractError("goal_navigation_terminal_stop_unproved")


def _header(value, current_intent):
    if type(value) is not dict:
        raise ContractError("goal_navigation_result_fields")
    keys = set(value)
    payload = "action" if "action" in keys else "status"
    exact(value, ("schema", "source", "intent", "selection", "controller_goal_uuid", payload),
          "goal_navigation_result")
    if type(value["schema"]) is not str or value["schema"] != GOAL_RESULT_SCHEMA:
        raise ContractError("goal_navigation_result_schema")
    _source(value["source"])
    checked_intent = validate_decision_intent_shape(value["intent"])
    if not _same(checked_intent, current_intent) or not _same(value["source"], _six(current_intent)):
        raise ContractError("goal_navigation_current_intent")
    _uuid(value["controller_goal_uuid"])
    _selection(value["selection"], current_intent)
    return payload


def validate_goal_navigation_result(value, observation, intent):
    """Return a detached envelope; wrong authorization is rejected, not zeroed."""
    original = validate_navigation_observation(observation)
    current = validate_decision_intent_shape(intent)
    if not _same(_six(current), _six(original)):
        raise ContractError("goal_navigation_intent_observation")
    value = copy.deepcopy(value)
    payload = _header(value, current)
    if payload == "status":
        if value["controller_goal_uuid"] is not None:
            raise ContractError("goal_navigation_status_uuid")
        validate_navigation_status(value["status"], original)
    else:
        validate_action(value["action"], original, dict(kind="navigation", output_modes=["velocity_body"]))
        selected = value["selection"]
        if (current["command"]["behavior"] != "navigate_to_pose" or selected is None
                or selected["state"] != "active" or selected["cancel_requested"]
                or selected["terminal"] or selected["stop_confirmed"]
                or not _same(selected["origin_intent"]["command"]["goal"], current["command"]["goal"])
                or not _same(selected["latest_authorization"], _six(current))
                or selected["goal_uuids"]["navigation"] is None
                or value["controller_goal_uuid"] != selected["goal_uuids"]["navigation"]):
            raise ContractError("goal_navigation_action_unauthorized")
    return value


def goal_navigation_result(observation, intent, selection, controller_goal_uuid, value):
    """Wrap actual caller output and strictly validate; never substitute status."""
    if type(observation) is not dict or any(name not in observation for name in IDENTITY):
        raise ContractError("goal_navigation_observation_identity")
    payload = "status" if type(value) is dict and value.get("schema") == NAV_STATUS_SCHEMA else "action"
    return validate_goal_navigation_result(dict(
        schema=GOAL_RESULT_SCHEMA, source=_six(observation), intent=intent,
        selection=selection, controller_goal_uuid=controller_goal_uuid,
        **{payload: value}), observation, intent)


class GoalNavigationResultHistory:
    """Continuity after stateless validation; create a new instance per binding.

    None selection does not declare any prior operation finished. All checks are
    transactional and repeated checks of one validated envelope are idempotent.
    The bounded store never evicts proofs to accept a reused goal UUID.
    """
    def __init__(self, capacity=256):
        if type(capacity) is not int or not 1 <= capacity <= 256:
            raise ContractError("goal_navigation_history_capacity")
        self.capacity = capacity
        self._records = {}
        self._navigation_owners = {}
        self._context = None
        self._last_source = None
        self._last_envelope = None

    def checked_copy(self, envelope):
        """Preview one receipt without committing it to this wire history.

        Existing records are only replaced by check(), never mutated in place.
        Copy the bounded indexes, then let check detach the new receipt. A
        producer can therefore withhold an expired action before committing
        exactly one final response for this capture.
        """
        staged = copy.copy(self)
        staged._records = dict(self._records)
        staged._navigation_owners = dict(self._navigation_owners)
        staged.check(envelope)
        return staged

    def check(self, envelope):
        value = copy.deepcopy(envelope)
        if type(value) is not dict:
            raise ContractError("goal_navigation_result_fields")
        current = validate_decision_intent_shape(value.get("intent"))
        _header(value, current)
        source = value["source"]
        if self._context is not None and not _context(self._context, source):
            raise ContractError("goal_navigation_history_generation")
        if self._last_source is not None:
            if not _not_later(self._last_source, source):
                raise ContractError("goal_navigation_history_source_reversed")
            if source["observed_seq"] == self._last_source["observed_seq"]:
                if not _same(source, self._last_source) or not _same(value, self._last_envelope):
                    raise ContractError("goal_navigation_history_response_rewritten")
                return value
        selected = value["selection"]
        if selected is not None:
            operation = selected["operation_id"]
            previous = self._records.get(operation)
            if previous is None and len(self._records) >= self.capacity:
                raise ContractError("goal_navigation_history_full")
            if previous is not None:
                if not _same(previous["origin_intent"], selected["origin_intent"]):
                    raise ContractError("goal_navigation_origin_changed")
                prior_authorization = previous["latest_authorization"]
                authorization = selected["latest_authorization"]
                if (not _not_later(prior_authorization, authorization) or
                        (prior_authorization["observed_seq"] == authorization["observed_seq"]
                         and not _same(prior_authorization, authorization))):
                    raise ContractError("goal_navigation_authorization_reversed")
                for name in ("planner", "navigation"):
                    old_uuid = previous["goal_uuids"][name]
                    if old_uuid is not None and selected["goal_uuids"][name] != old_uuid:
                        raise ContractError("goal_navigation_uuid_changed")
                for name in ("cancel_requested", "terminal", "stop_confirmed"):
                    if previous[name] and not selected[name]:
                        raise ContractError("goal_navigation_history_reversed")
                if previous["terminal"] and selected["state"] != previous["state"]:
                    raise ContractError("goal_navigation_terminal_changed")
            uuid = selected["goal_uuids"]["navigation"]
            if uuid is not None:
                owner = self._navigation_owners.get(uuid)
                if owner is not None and owner != operation:
                    raise ContractError("goal_navigation_uuid_reused")
            detached_selected = copy.deepcopy(selected)
            detached_envelope = copy.deepcopy(value)
            if uuid is not None:
                self._navigation_owners[uuid] = operation
            self._records[operation] = detached_selected
        else:
            detached_envelope = copy.deepcopy(value)
        if self._context is None:
            self._context = _six(source)
        self._last_source = _six(source)
        self._last_envelope = detached_envelope
        return value
