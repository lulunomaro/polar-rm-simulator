"""Synthetic immutable receipts, not actual Nav2/physics qualification."""
import copy

import pytest

from rm_match.platform_v2.contracts import IDENTITY
from tools.audit_navigation_goals import audit_goal_navigation_consumption
from test_pb_navigation_sil_audit import evidence


UUID1, UUID2 = "1" * 32, "2" * 32


def fixture(seq, uuid, *, origin_seq=None):
    rows, ros = evidence()
    sim = seq * 0.1
    wall = 100.0 + sim
    end = round(sim * 1e9)
    start = end - 100000000
    frame = seq - 1
    action = rows[0]["action"]
    action.update(observed_seq=seq, sim_time=sim, wall_deadline=wall + 0.14)
    rows[0].update(consume_wall=wall + 0.02, consume_sim_time=sim + 0.02)
    budget = rows[0]["navigation_budget"]
    budget.update(frame_id=frame, capture_wall=wall, wall_deadline=wall + 0.15,
                  capture_sim_time=sim, sim_deadline=sim + 0.15)
    for auth in (rows[0]["authorization"], rows[0]["output_authorization"]):
        auth.update(activation_seq=seq - 1, activation_window_id=seq,
                    activation_expires=wall + 0.14, activation_window_deadline=wall + 0.14)
    rows[1].update(**{name: action[name] for name in IDENTITY if name != "sim_time"},
                   observation_sim_time=sim, sensor_budget=copy.deepcopy(budget))
    rows[1]["cloud_acquisition"].update(frame_id=frame, acquisition_start_ns=start,
                                         acquisition_end_ns=end)
    rows[2]["window"].update(window_id=seq, issued_wall=wall - 0.01,
                              expires_wall=wall + 0.14)
    rows[2]["activation"].update(seq=seq - 1, window_id=seq,
                                  activation_expires=wall + 0.14)
    rows[2]["wall_time"] = wall
    source = {name: action[name] for name in IDENTITY}
    for row in (ros[0]["value"], ros[2]["value"]):
        row.update(**source, cloud_frame_id=frame, acquisition_start_ns=start,
                   acquisition_end_ns=end)
    ros[0]["value"]["localization_stamp_ns"] = end - 2000000
    result = ros[1]["value"]
    result["schema"] = "polar.sim.pb-navigation-result.v2"
    result["source"].update(cloud_frame_id=frame, localization_stamp_ns=end - 2000000,
                            controller_stamp_ns=end, controller_id="nav2_server_pb_pid_goal_v1",
                            goal_uuid=uuid)
    origin = dict(schema="polar.sim.decision-intent.v1", **source, kind="decision",
                  mode="navigation_intent", command=dict(behavior="navigate_to_pose",
                      reason="synthetic goal audit", goal=dict(frame="map", position_m=[float(seq), 0.0], yaw_rad=0.0)))
    if origin_seq is not None:
        origin.update(observed_seq=origin_seq, sim_time=origin_seq * 0.1,
                      wall_deadline=100.0 + origin_seq * 0.1 + 0.14)
    record = dict(operation_id=f"{seq + 100:032x}", origin_intent=origin,
                  latest_authorization={name: source[name] for name in IDENTITY},
                  goal=copy.deepcopy(origin["command"]["goal"]), state="active",
                  goal_uuids=dict(planner=f"{seq + 200:032x}", navigation=uuid),
                  cancel_requested=False, cancel_acknowledged=False, terminal=False,
                  stop_confirmed=False, error_code=None, stop_intent=None, stop_reason=None)
    return rows, ros, record


def two_goals():
    rows1, ros1, first = fixture(1, UUID1)
    rows2, ros2, second = fixture(2, UUID2)
    return rows1 + rows2, ros1 + ros2, dict(schema="polar.sim.navigation-goal-lifecycle.v1",
                                         goals=[first, second])


def test_two_goal_uuid_source_action_and_physical_receipt_join():
    rows, ros, lifecycle = two_goals()
    before = copy.deepcopy((rows, ros, lifecycle))
    result = audit_goal_navigation_consumption(rows, ros, lifecycle)
    assert result["passed"] and result["errors"] == []
    assert result["consumed_steps"] == result["nonzero_consumed_steps"] == 2
    assert result["actual_controller_results"] == 2
    for uuid, seq in ((UUID1, 1), (UUID2, 2)):
        goal = result["per_goal"][uuid]
        assert goal["controller_results"] == goal["consumed_steps"] == goal["nonzero_consumed_steps"] == 1
        assert goal["origin_source"]["observed_seq"] == seq
    assert (rows, ros, lifecycle) == before


def test_goal_with_no_motion_is_allowed_without_inventing_consumption():
    rows, ros, lifecycle = two_goals()
    rows = rows[:3]
    ros = ros[:3]
    result = audit_goal_navigation_consumption(rows, ros, lifecycle)
    assert result["passed"]
    assert result["per_goal"][UUID2]["consumed_steps"] == 0
    assert result["per_goal"][UUID2]["controller_results"] == 0


def test_latest_authorization_does_not_retag_origin_or_existing_result():
    rows, ros, record = fixture(3, UUID1, origin_seq=1)
    record["latest_authorization"].update(observed_seq=50, sim_time=5.0, wall_deadline=9000.0)
    result = audit_goal_navigation_consumption(rows, ros, dict(
        schema="polar.sim.navigation-goal-lifecycle.v1", goals=[record]))
    assert result["passed"]
    assert result["per_goal"][UUID1]["origin_source"]["observed_seq"] == 1
    assert ros[1]["value"]["action"]["observed_seq"] == 3


def test_canceled_terminal_does_not_imply_encoder_stop_or_forbid_old_source_receipt():
    rows, ros, lifecycle = two_goals()
    first = lifecycle["goals"][0]
    first.update(state="canceled", cancel_requested=True, cancel_acknowledged=True,
                 terminal=True, stop_confirmed=True, stop_reason="hold")
    first["stop_intent"] = dict(copy.deepcopy(first["origin_intent"]), observed_seq=3,
                               command=dict(behavior="hold", reason="synthetic cancel"))
    result = audit_goal_navigation_consumption(rows, ros, lifecycle)
    assert result["passed"] and result["per_goal"][UUID1]["nonzero_consumed_steps"] == 1


@pytest.mark.parametrize("bad_uuid", ["3" * 32, "A" * 32, True, None, "bad"])
def test_unknown_even_well_formed_uuid_never_selects_latest_goal(bad_uuid):
    rows, ros, lifecycle = two_goals()
    ros[1]["value"]["source"]["goal_uuid"] = bad_uuid
    result = audit_goal_navigation_consumption(rows, ros, lifecycle)
    assert not result["passed"] and result["errors"]


def test_cross_goal_uuid_swap_rejected_when_action_predates_other_origin():
    rows, ros, lifecycle = two_goals()
    ros[1]["value"]["source"]["goal_uuid"] = UUID2
    result = audit_goal_navigation_consumption(rows, ros, lifecycle)
    assert not result["passed"]
    assert any("precedes_origin" in error for error in result["errors"])


@pytest.mark.parametrize("mutation", [
    lambda r: r["origin_intent"].update(episode=True),
    lambda r: r["origin_intent"].update(robot_id="blue_sentry"),
    lambda r: r["origin_intent"].update(observed_seq=9),
    lambda r: r["origin_intent"].update(sim_time=0.5),
    lambda r: r["origin_intent"]["command"].update(behavior="hold"),
    lambda r: r["origin_intent"].update(world_xy=[1, 2]),
    lambda r: r.update(operation_id="BAD"),
    lambda r: r["goal_uuids"].update(navigation=None),
    lambda r: r["goal"].update(position_m=[500.0, 0.0]),
    lambda r: r["latest_authorization"].update(binding_epoch=2),
    lambda r: r.update(terminal=1),
])
def test_forged_lifecycle_origin_and_proof_cannot_authorize_receipts(mutation):
    rows, ros, lifecycle = two_goals()
    mutation(lifecycle["goals"][0])
    assert not audit_goal_navigation_consumption(rows, ros, lifecycle)["passed"]


@pytest.mark.parametrize("reuse", ["operation", "navigation_uuid", "planner_uuid"])
def test_operation_and_uuid_reuse_across_goals_rejected(reuse):
    rows, ros, lifecycle = two_goals()
    first, second = lifecycle["goals"]
    if reuse == "operation":
        second["operation_id"] = first["operation_id"]
    else:
        role = "navigation" if reuse == "navigation_uuid" else "planner"
        second["goal_uuids"][role] = first["goal_uuids"][role]
    assert not audit_goal_navigation_consumption(rows, ros, lifecycle)["passed"]


@pytest.mark.parametrize("different_velocity", [False, True])
def test_same_original_source_with_multiple_goal_uuids_is_ambiguous(different_velocity):
    rows, ros, lifecycle = two_goals()
    duplicate = copy.deepcopy(ros[1])
    duplicate["value"]["source"]["goal_uuid"] = UUID2
    if different_velocity:
        duplicate["value"]["action"]["command"]["vx_mps"] = 0.3
    # Both goals could have been accepted on earlier scans; neither is "latest" evidence.
    second_origin = lifecycle["goals"][1]["origin_intent"]
    second_origin.update(observed_seq=0, sim_time=0.0)
    ros.append(duplicate)
    result = audit_goal_navigation_consumption(rows, ros, lifecycle)
    assert not result["passed"]
    assert any("ambiguous" in error for error in result["errors"])


def test_duplicate_physical_receipt_counts_once_and_changed_command_fails():
    rows, ros, lifecycle = two_goals()
    rows.append(copy.deepcopy(rows[0]))
    result = audit_goal_navigation_consumption(rows, ros, lifecycle)
    assert result["passed"] and result["consumed_steps"] == 2
    rows[-1]["target"]["motion"]["vx_mps"] = 0.3
    assert not audit_goal_navigation_consumption(rows, ros, lifecycle)["passed"]


def test_preceding_original_sensor_sdk_audit_is_required_not_mocked_out():
    rows, ros, lifecycle = two_goals()
    rows[0]["consume_wall"] = rows[0]["navigation_budget"]["wall_deadline"]
    result = audit_goal_navigation_consumption(rows, ros, lifecycle)
    assert not result["passed"] and not result["navigation_audit"]["passed"]
    assert any(error.startswith("navigation:") for error in result["errors"])


@pytest.mark.parametrize("bad", [None, {}, {"goals": []}, {"schema": "wrong", "goals": []},
                                  {"schema": "polar.sim.navigation-goal-lifecycle.v1", "goals": [object()]}])
def test_incomplete_or_non_json_lifecycle_returns_failure_without_partial_mapping(bad):
    rows, ros, _ = two_goals()
    result = audit_goal_navigation_consumption(rows, ros, bad)
    assert result["passed"] is False and result["errors"] and result["per_goal"] == {}


@pytest.mark.parametrize("bad_rows,bad_ros", [(None, []), ({}, []), ([None], []),
                                            ([{"unknown": float("nan")}], []),
                                            ([], [object()])])
def test_partial_probe_inputs_cannot_raise_over_cleanup(bad_rows, bad_ros):
    _, _, lifecycle = two_goals()
    result = audit_goal_navigation_consumption(bad_rows, bad_ros, lifecycle)
    assert result["passed"] is False and result["per_goal"] == {} and result["errors"]


def test_cyclic_non_json_input_is_rejected_without_following_foreign_methods():
    rows, ros, lifecycle = two_goals()
    lifecycle["cycle"] = lifecycle
    result = audit_goal_navigation_consumption(rows, ros, lifecycle)
    assert result["passed"] is False and result["per_goal"] == {}


def test_early_failure_before_any_controller_action_has_explicit_failure_reason():
    _, _, lifecycle = two_goals()
    result = audit_goal_navigation_consumption([], [], lifecycle)
    assert result["passed"] is False and result["per_goal"] == {}
    assert "navigation:no_qualified_consumption" in result["errors"]
