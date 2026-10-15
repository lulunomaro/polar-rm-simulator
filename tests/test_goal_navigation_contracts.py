"""Synthetic current-goal authorization; no backend, ROS, physics or clock IO."""
import copy

import pytest

from rm_match.platform_v2.contracts import ContractError, IDENTITY
from rm_match.platform_v2.decision_contracts import (
    build_decision_observation, decision_intent_for,
)
from rm_match.platform_v2.goal_navigation_contracts import (
    GOAL_RESULT_SCHEMA, GoalNavigationResultHistory, goal_navigation_result,
    validate_goal_navigation_result,
)
from rm_match.platform_v2.navigation_contracts import NAV_STATUS_SCHEMA
from test_navigation_plugin import action, observation


OPERATION, PLANNER, NAVIGATION = "1" * 32, "2" * 32, "3" * 32


def six(value):
    return {name: copy.deepcopy(value[name]) for name in IDENTITY}


def status(o, name="no_associated_command"):
    return dict(schema=NAV_STATUS_SCHEMA, **six(o), kind="navigation", status=name)


def fixture(behavior="navigate_to_pose"):
    o = observation()
    o.update(observed_seq=3, wall_deadline=100.15)
    command = dict(behavior=behavior, reason="synthetic protocol fixture")
    if behavior == "navigate_to_pose":
        command["goal"] = dict(frame="map", position_m=[1.0, 2.0], yaw_rad=0.2)
    current = decision_intent_for(build_decision_observation(o), command)
    origin = dict(copy.deepcopy(current), observed_seq=1, sim_time=0.05, wall_deadline=100.10)
    origin["command"] = dict(behavior="navigate_to_pose", reason="original synthetic goal",
                             goal=dict(frame="map", position_m=[1.0, 2.0], yaw_rad=0.2))
    selected = dict(operation_id=OPERATION, origin_intent=origin,
                    latest_authorization=six(current), goal_uuids=dict(planner=PLANNER, navigation=NAVIGATION),
                    state="active", cancel_requested=False, terminal=False, stop_confirmed=False)
    return o, current, selected


def envelope(*, selected=None, no_action=False, behavior="navigate_to_pose"):
    o, intent, default = fixture(behavior)
    selected = default if selected is None else selected
    value = status(o) if no_action else action(o)
    row = goal_navigation_result(o, intent, selected, None if no_action else NAVIGATION, value)
    return o, intent, row


def checked_status(o, intent, selected):
    return goal_navigation_result(o, intent, selected, None, status(o))


def later_status(o, intent, selected, seq):
    o = dict(o, observed_seq=seq)
    intent = dict(intent, observed_seq=seq)
    return checked_status(o, intent, selected)


def test_active_original_goal_and_exact_current_authorization_allow_actual_action():
    o, intent, selected = fixture()
    velocity = action(o)
    row = goal_navigation_result(o, intent, selected, NAVIGATION, velocity)
    assert row["schema"] == GOAL_RESULT_SCHEMA
    assert set(row) == {"schema", "source", "intent", "selection", "controller_goal_uuid", "action"}
    assert row["source"] == six(o) and row["intent"] == intent
    assert row["action"] == velocity and "goal_uuid" not in row["action"]
    assert row["selection"]["origin_intent"]["observed_seq"] == 1
    assert row["selection"]["latest_authorization"]["observed_seq"] == 3
    assert validate_goal_navigation_result(row, o, intent) == row
    selected["origin_intent"]["command"]["goal"]["position_m"][0] = 999
    velocity["command"]["vx_mps"] = 999
    intent["command"]["reason"] = "changed caller"
    assert row["action"]["command"]["vx_mps"] == 0.2
    assert row["intent"]["command"]["reason"] == "synthetic protocol fixture"
    assert row["selection"]["origin_intent"]["command"]["goal"]["position_m"][0] == 1.0


@pytest.mark.parametrize("behavior", ["hold", "cancel"])
@pytest.mark.parametrize("zero", [False, True])
def test_stop_intents_never_authorize_action_including_fabricated_zero(behavior, zero):
    o, intent, selected = fixture(behavior)
    value = action(o)
    if zero:
        value["command"].update(vx_mps=0.0, vy_mps=0.0, wz_rps=0.0)
    with pytest.raises(ContractError):
        goal_navigation_result(o, intent, selected, NAVIGATION, value)
    row = goal_navigation_result(o, intent, selected, None, status(o))
    assert "status" in row and "action" not in row


@pytest.mark.parametrize("name", ["pending_localization", "no_associated_command"])
def test_status_with_no_selected_operation_does_not_claim_motion(name):
    o, intent, _ = fixture()
    row = goal_navigation_result(o, intent, None, None, status(o, name))
    assert row["selection"] is None and row["controller_goal_uuid"] is None
    assert row["status"]["status"] == name


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(schema="polar.sim.navigation-goal-result.v0"),
    lambda r: r.update(extra=True),
    lambda r: r.update(selection=None),
    lambda r: r.update(controller_goal_uuid="4" * 32),
    lambda r: r.update(controller_goal_uuid=None),
    lambda r: r["source"].update(episode=True),
    lambda r: r["source"].update(sim_time=0),
    lambda r: r["source"].update(world_xy=[0, 0]),
    lambda r: r["intent"]["command"].update(reason="not the requested intent"),
    lambda r: r["intent"]["command"]["goal"].update(position_m=[2.0, 2.0]),
    lambda r: r["action"].update(observed_seq=2),
    lambda r: r["action"].update(kind="aim"),
    lambda r: r["action"]["command"].update(fire_permission=True),
    lambda r: r["selection"].update(cancel_requested=True),
    lambda r: r["selection"].update(state="sending"),
    lambda r: r["selection"].update(state="fault"),
    lambda r: r["selection"]["goal_uuids"].update(navigation=None),
    lambda r: r["selection"]["origin_intent"]["command"]["goal"].update(position_m=[1, 2.0]),
    lambda r: r["selection"]["latest_authorization"].update(observed_seq=2),
    lambda r: r["selection"]["latest_authorization"].update(wall_deadline=100.14),
])
def test_no_action_from_wrong_intent_uuid_profile_source_or_authorization(mutation):
    o, intent, row = envelope()
    mutation(row)
    with pytest.raises(ContractError):
        validate_goal_navigation_result(row, o, intent)


@pytest.mark.parametrize("state", ["succeeded", "canceled", "stopped", "rejected", "aborted"])
def test_old_terminal_record_cannot_authorize_new_or_zero_motion(state):
    o, intent, selected = fixture()
    selected.update(state=state, terminal=True, stop_confirmed=True,
                     cancel_requested=state in ("canceled", "stopped"))
    for zero in (False, True):
        value = action(o)
        if zero:
            value["command"].update(vx_mps=0.0, vy_mps=0.0, wz_rps=0.0)
        with pytest.raises(ContractError):
            goal_navigation_result(o, intent, selected, NAVIGATION, value)
    assert "status" in checked_status(o, intent, selected)


@pytest.mark.parametrize("where,key,value", [
    ("origin", "robot_id", "red_sentry"), ("origin", "binding_epoch", 4),
    ("origin", "observed_seq", 4), ("origin", "sim_time", 0.11),
    ("latest", "episode", True), ("latest", "observed_seq", 0),
    ("latest", "observed_seq", 4), ("latest", "sim_time", 0.01),
    ("latest", "sim_time", 0.11),
])
def test_even_status_rejects_cross_context_or_future_selection(where, key, value):
    o, intent, selected = fixture()
    selected["origin_intent" if where == "origin" else "latest_authorization"][key] = value
    with pytest.raises(ContractError):
        checked_status(o, intent, selected)


@pytest.mark.parametrize("bad", [None, True, 1, "A" * 32, "a" * 31, "z" * 32])
def test_operation_must_be_a_real_plain_32_hex_identifier(bad):
    o, intent, selected = fixture()
    selected["operation_id"] = bad
    with pytest.raises(ContractError):
        checked_status(o, intent, selected)


def test_plain_scalar_types_extra_fields_status_xor_and_no_uuid_on_status():
    class NonJsonString(str):
        pass
    o, intent, row = envelope()
    for mutate in (
        lambda r: r.update(controller_goal_uuid=NonJsonString(NAVIGATION)),
        lambda r: r["selection"].update(terminal=0),
        lambda r: r["selection"].update(operation_id=NonJsonString(OPERATION)),
        lambda r: r["selection"].update(world_xy=[0.0, 0.0]),
        lambda r: r.update(status=status(o)),
    ):
        bad = copy.deepcopy(row)
        mutate(bad)
        with pytest.raises(ContractError):
            validate_goal_navigation_result(bad, o, intent)
    stopped = checked_status(o, intent, None)
    stopped["controller_goal_uuid"] = NAVIGATION
    with pytest.raises(ContractError):
        validate_goal_navigation_result(stopped, o, intent)
    stopped["controller_goal_uuid"] = None
    stopped["status"]["observed_seq"] = 0
    with pytest.raises(ContractError):
        validate_goal_navigation_result(stopped, o, intent)


def test_clock_is_opaque_and_result_mutation_does_not_reach_caller():
    o, intent, row = envelope()
    accepted = validate_goal_navigation_result(row, o, intent)
    accepted["selection"]["latest_authorization"]["wall_deadline"] = 0.0
    assert row["selection"]["latest_authorization"]["wall_deadline"] == 100.15
    assert row["source"]["wall_deadline"] == 100.15  # no host/local clock comparison.
    with pytest.raises(ContractError):
        goal_navigation_result({}, intent, None, None, {})


def test_history_is_idempotent_detached_and_does_not_infer_terminal_from_none():
    o, intent, row = envelope()
    history = GoalNavigationResultHistory()
    assert history.check(row) == row and history.check(row) == row
    result = history.check(row)
    result["selection"]["origin_intent"]["command"]["reason"] = "foreign mutation"
    history.check(later_status(o, intent, None, 4))
    later = later_status(o, intent, row["selection"], 5)
    assert history.check(later) == later


def test_history_acceptance_uuid_appears_once_then_cannot_change_or_disappear():
    o, intent, selected = fixture()
    history = GoalNavigationResultHistory()
    pending = copy.deepcopy(selected)
    pending.update(state="sending", goal_uuids=dict(planner=None, navigation=None))
    history.check(checked_status(o, intent, pending))
    history.check(later_status(o, intent, selected, 4))
    for role in ("planner", "navigation"):
        for uuid in (None, "9" * 32):
            bad = copy.deepcopy(selected)
            bad["goal_uuids"][role] = uuid
            with pytest.raises(ContractError):
                history.check(later_status(o, intent, bad, 5))


def test_history_origin_cannot_change_even_when_new_status_is_stateless_legal():
    o, intent, selected = fixture()
    history = GoalNavigationResultHistory()
    history.check(checked_status(o, intent, selected))
    changed = copy.deepcopy(selected)
    changed["origin_intent"]["command"]["reason"] = "substituted origin"
    with pytest.raises(ContractError):
        history.check(later_status(o, intent, changed, 4))
    assert history.check(later_status(o, intent, selected, 4))["selection"] == selected


def test_history_cancel_cannot_reverse_after_unselected_status():
    o, intent, selected = fixture()
    history = GoalNavigationResultHistory()
    canceling = dict(copy.deepcopy(selected), state="canceling", cancel_requested=True)
    history.check(checked_status(o, intent, canceling))
    history.check(later_status(o, intent, None, 4))
    with pytest.raises(ContractError):
        history.check(later_status(o, intent, selected, 5))


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(state="active", terminal=False, stop_confirmed=False),
    lambda r: r.update(stop_confirmed=False),
    lambda r: r.update(state="aborted"),
])
def test_history_terminal_and_stop_proof_never_reverse(mutation):
    o, intent, selected = fixture()
    terminal = dict(copy.deepcopy(selected), state="succeeded", terminal=True, stop_confirmed=True)
    history = GoalNavigationResultHistory()
    history.check(checked_status(o, intent, terminal))
    later = copy.deepcopy(terminal)
    mutation(later)
    with pytest.raises(ContractError):
        history.check(later_status(o, intent, later, 4))


def test_history_navigation_uuid_cannot_be_reused_by_another_operation():
    o, intent, selected = fixture()
    history = GoalNavigationResultHistory()
    history.check(checked_status(o, intent, selected))
    other = dict(copy.deepcopy(selected), operation_id="4" * 32)
    with pytest.raises(ContractError):
        history.check(later_status(o, intent, other, 4))
    other["goal_uuids"]["navigation"] = "5" * 32
    assert history.check(later_status(o, intent, other, 4))["selection"]["operation_id"] == "4" * 32


def test_history_is_bounded_without_eviction_and_failed_add_does_not_corrupt_existing():
    o, intent, selected = fixture()
    history = GoalNavigationResultHistory(capacity=1)
    first = checked_status(o, intent, selected)
    history.check(first)
    other = copy.deepcopy(selected)
    other.update(operation_id="4" * 32, goal_uuids=dict(planner=None, navigation="5" * 32))
    with pytest.raises(ContractError):
        history.check(later_status(o, intent, other, 4))
    assert history.check(first) == first


def test_history_needs_new_instance_for_new_binding():
    o, intent, selected = fixture()
    history = GoalNavigationResultHistory()
    history.check(checked_status(o, intent, None))
    changed = copy.deepcopy(o)
    changed["binding_epoch"] += 1
    current = dict(copy.deepcopy(intent), binding_epoch=changed["binding_epoch"])
    row = checked_status(changed, current, None)
    with pytest.raises(ContractError):
        history.check(row)
    assert GoalNavigationResultHistory().check(row) == row


@pytest.mark.parametrize("field,value", [("observed_seq", 2), ("sim_time", 0.09),
                                        ("wall_deadline", 100.16)])
def test_history_global_source_cannot_roll_back_or_rewrite_same_sequence(field, value):
    o, intent, selected = fixture()
    history = GoalNavigationResultHistory()
    history.check(checked_status(o, intent, selected))
    # All envelopes in this test remain stateless-valid; only the response stream is invalid.
    modified_o, modified_i = dict(o), dict(intent)
    modified_o[field] = modified_i[field] = value
    if field == "sim_time":
        modified_o["observed_seq"] = modified_i["observed_seq"] = 4
        # Current navigation sensor time must still be <= the observation sim time.
        modified_o["sim_time"] = modified_i["sim_time"] = 0.1
        previous_o, previous_i = dict(o, sim_time=0.11), dict(intent, sim_time=0.11)
        history.check(later_status(previous_o, previous_i, selected, 4))
        modified_o["observed_seq"] = modified_i["observed_seq"] = 5
    selected_for_bad = copy.deepcopy(selected)
    selected_for_bad["latest_authorization"] = six(modified_i)
    if field == "observed_seq":
        selected_for_bad["latest_authorization"]["observed_seq"] = 2
    bad = checked_status(modified_o, modified_i, selected_for_bad)
    with pytest.raises(ContractError):
        history.check(bad)
    assert history.check(later_status(o if field != "sim_time" else previous_o,
                                      intent if field != "sim_time" else previous_i,
                                      selected, 6))["source"]["observed_seq"] == 6


def test_same_original_source_cannot_have_two_different_responses():
    o, intent, selected = fixture()
    first = checked_status(o, intent, selected)
    history = GoalNavigationResultHistory()
    history.check(first)
    different = copy.deepcopy(first)
    different["status"]["status"] = "pending_localization"
    validate_goal_navigation_result(different, o, intent)
    with pytest.raises(ContractError):
        history.check(different)
    assert history.check(first) == first
    assert history.check(later_status(o, intent, selected, 4))["source"]["observed_seq"] == 4


@pytest.mark.parametrize("mutation", [
    lambda auth: auth.update(observed_seq=2),
    lambda auth: auth.update(sim_time=0.09),
    lambda auth: auth.update(wall_deadline=100.14),
])
def test_same_operation_latest_authorization_cannot_regress_or_rewrite(mutation):
    o, intent, selected = fixture()
    history = GoalNavigationResultHistory()
    history.check(checked_status(o, intent, selected))
    regressed = copy.deepcopy(selected)
    mutation(regressed["latest_authorization"])
    with pytest.raises(ContractError):
        history.check(later_status(o, intent, regressed, 4))
    assert history.check(later_status(o, intent, selected, 4))["selection"] == selected


def test_status_cannot_claim_success_without_a_navigation_uuid():
    o, intent, selected = fixture()
    selected.update(state="succeeded", terminal=True, stop_confirmed=True)
    selected["goal_uuids"]["navigation"] = None
    with pytest.raises(ContractError, match="success_uuid_missing"):
        checked_status(o, intent, selected)
