"""Bind a real sourced controller result to the currently authorized goal.

This foreign JSONL/ROS peer helper owns no executor, clock conversion or motion
algorithm. The injected callback must report its actual computation's goal UUID.
Lifecycle UUIDs are evidence to compare against, never substitute that report.
"""
from __future__ import annotations

import copy
import re

from .navigation_goal_lifecycle import NavigationGoalLifecycle, same_source, source
from ..deployment.navigation_plugin import navigation_status_for, validate_intent, validate_result
from ..platform_v2.contracts import ContractError, exact, identity, IDENTITY
from ..platform_v2.decision_contracts import validate_decision_intent_shape
from ..platform_v2.navigation_contracts import validate_navigation_observation

SELECTION_FIELDS = (
    "operation_id", "origin_intent", "latest_authorization", "goal_uuids",
    "state", "cancel_requested", "terminal", "stop_confirmed",
)


def _same_tree(left, right):
    """Do not let an equal-valued bool/int or int/float mutation disappear."""
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(_same_tree(left[k], right[k]) for k in left)
    if type(left) is list:
        return len(left) == len(right) and all(_same_tree(a, b) for a, b in zip(left, right))
    return left == right


def _selection(snapshot):
    """Select only snapshot.active; a historical terminal is never a fallback."""
    active = snapshot["active"]
    if active is None:
        return None
    selected = [record for record in snapshot["goals"] if record["operation_id"] == active]
    if len(selected) != 1:
        raise ContractError("goal_navigation_active_record_invalid")
    return {key: copy.deepcopy(selected[0][key]) for key in SELECTION_FIELDS}


def _authorized(snapshot, selected, intent, operation_id):
    if (selected is None or operation_id is None or snapshot["fault"] is not None
        or snapshot["stop_requested"] is not False
        or selected["operation_id"] != operation_id
        or selected["state"] != "active" or selected["cancel_requested"] is not False
        or selected["terminal"] is not False or selected["stop_confirmed"] is not False
        or intent["command"]["behavior"] != "navigate_to_pose"):
        return False
    return (selected["origin_intent"]["command"]["behavior"] == "navigate_to_pose"
        and _same_tree(selected["origin_intent"]["command"]["goal"], intent["command"]["goal"])
        and same_source(selected["latest_authorization"], source(intent)))


def _selection_for_receipt(selected, original):
    if selected is None:
        return None
    origin = validate_decision_intent_shape(selected["origin_intent"])
    latest = selected["latest_authorization"]
    exact(latest, IDENTITY, "goal_navigation_latest_source")
    identity(latest)
    for receipt in (origin, latest):
        if any(type(receipt[k]) is not type(original[k]) or receipt[k] != original[k]
               for k in ("robot_id", "episode", "binding_epoch")):
            raise ContractError("goal_navigation_selection_generation")
    if (origin["observed_seq"] > original["observed_seq"] or origin["sim_time"] > original["sim_time"]
        or latest["observed_seq"] > original["observed_seq"] or latest["sim_time"] > original["sim_time"]):
        # No operation is selected for this old input receipt. This does NOT
        # assert that the real lifecycle has no active goal or has stopped.
        return None
    return selected


class GoalNavigationCompute:
    """Callable ``compute(nav_observation, original_intent)`` for one binding.

    ``sourced_controller`` receives detached observation/intent dictionaries and
    returns exactly ``{value: action_or_status, goal_uuid: actual_uuid_or_none}``.
    It must honor the existing callback/host budget. ``poll_hook`` may advance an
    already-owned executor once and must not block. Neither hook is retried here.
    The owner must continue real cancellation/executor cleanup when close cannot
    yet prove the original lifecycle clean.
    """

    def __init__(self, lifecycle, sourced_controller, *, poll_hook=None):
        if not isinstance(lifecycle, NavigationGoalLifecycle):
            raise ContractError("goal_navigation_lifecycle_required")
        if type(lifecycle.deadline_mode) is not str or lifecycle.deadline_mode != "opaque":
            raise ContractError("goal_navigation_opaque_deadline_required")
        if not callable(sourced_controller) or (poll_hook is not None and not callable(poll_hook)):
            raise ContractError("goal_navigation_callback_required")
        self.lifecycle = lifecycle
        self.sourced_controller = sourced_controller
        self.poll_hook = poll_hook
        self.context = None
        self.closed = False
        self.failed = False
        self.busy = False
        self._last_snapshot = None
        self._history = None

    @property
    def last_snapshot(self):
        """Detached lifecycle diagnostics, never relabeled as this input's proof."""
        return copy.deepcopy(self._last_snapshot)

    def reset(self, context):
        if self.context is not None or self.closed or self.failed or self.busy:
            raise ContractError("goal_navigation_reset_once")
        snapshot = self.lifecycle.reset(copy.deepcopy(context))
        self.context = copy.deepcopy(context)
        self._last_snapshot = copy.deepcopy(snapshot)
        from ..platform_v2.goal_navigation_contracts import GoalNavigationResultHistory
        self._history = GoalNavigationResultHistory()
        return copy.deepcopy(snapshot)

    def _progress(self):
        if self.poll_hook is not None:
            self.poll_hook()
        snapshot = self.lifecycle.poll()
        self._last_snapshot = copy.deepcopy(snapshot)
        return snapshot

    def __call__(self, observation, intent):
        if self.context is None or self.closed or self.failed or self.busy:
            raise ContractError("goal_navigation_compute_unavailable")
        self.busy = True
        try:
            original = validate_navigation_observation(observation)
            checked_intent = validate_intent(intent, original)
            submitted = self.lifecycle.submit(checked_intent, expected_source=source(original))
            self._last_snapshot = copy.deepcopy(submitted)
            operation_id = submitted["active"]
            callback_observation = copy.deepcopy(original)
            callback_intent = copy.deepcopy(checked_intent)
            try:
                response = self.sourced_controller(callback_observation, callback_intent)
            except BaseException as error:
                # Advance real cancellation/result state once even on failure;
                # a progress error must not replace the callback's actual error.
                try:
                    self._progress()
                except BaseException as progress_error:
                    if hasattr(error, "add_note"):
                        error.add_note("goal_navigation_progress_failed:" + type(progress_error).__name__)
                raise
            current = self._progress()
            if (not _same_tree(callback_observation, original)
                or not _same_tree(callback_intent, checked_intent)):
                raise ContractError("goal_navigation_callback_mutated_input")
            response = copy.deepcopy(response)
            exact(response, ("value", "goal_uuid"), "goal_navigation_sourced_result")
            uuid = response["goal_uuid"]
            if uuid is not None and (type(uuid) is not str or not re.fullmatch("[a-f0-9]{32}", uuid)):
                raise ContractError("goal_navigation_controller_uuid_invalid")
            # Validate even a response we will withhold. Invalid source/shape is
            # an error, not a successful no-command fallback.
            kind, value = validate_result(response["value"], original)
            if kind == "status" and uuid is not None:
                raise ContractError("goal_navigation_status_uuid_invalid")
            selected = _selection_for_receipt(_selection(current), original)
            allowed = _authorized(current, selected, checked_intent, operation_id)
            if (kind == "action" and allowed and uuid is not None
                and uuid == selected["goal_uuids"]["navigation"]):
                result_value, result_uuid = value, uuid
            elif kind == "status" and allowed:
                result_value, result_uuid = value, None
            else:
                result_value, result_uuid = navigation_status_for(original), None
            # The protocol helper is strict and detached. It never supplies a
            # UUID, renews the callback action, or silently converts bad input.
            from ..platform_v2.goal_navigation_contracts import goal_navigation_result
            envelope = goal_navigation_result(original, checked_intent, selected, result_uuid, result_value)
            return self._history.check(envelope)
        except BaseException:
            self.failed = True
            raise
        finally:
            self.busy = False

    def close(self):
        self.closed = True
        try:
            self._last_snapshot = self.lifecycle.request_stop()
            snapshot = self._progress()
            if snapshot["clean"] is not True or snapshot["fault"] is not None:
                raise ContractError("goal_navigation_stop_unproved")
        except BaseException as error:
            if isinstance(error, ContractError) and str(error) == "goal_navigation_stop_unproved":
                raise
            raise ContractError("goal_navigation_stop_unproved") from error
        return copy.deepcopy(snapshot)
