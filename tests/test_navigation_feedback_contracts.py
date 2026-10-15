"""Declared estimate/scan relationships, not proof of a real TF producer."""
import copy

import pytest

from rm_match.platform_v2.contracts import ContractError, IDENTITY
from rm_match.platform_v2.decision_contracts import (
    build_decision_observation, decision_intent_for,
)
from rm_match.platform_v2.navigation_feedback_contracts import (
    ESTIMATE_METHOD, FEEDBACK_SCHEMA, NavigationFeedbackHistory, goal_status_from_lifecycle,
    navigation_feedback, unavailable_navigation_feedback, validate_navigation_feedback,
)
from test_decision_plugin import nav_observation


def original(seq=3):
    o = nav_observation()
    o.update(observed_seq=seq, wall_deadline=100.15)
    return o


def estimate():
    return dict(available=True, reason="available", frame="map", child_frame="base_link",
                stamp_ns=98000000, localization_stamp_ns=98000000,
                position_m=[0.2, -0.1, 0.01], rotation_xyzw=[0.0, 0.0, 0.0, 1.0],
                provenance=dict(method=ESTIMATE_METHOD, producer_source_sha256="1" * 64,
                    localization_binary_sha256="2" * 64, mapping_binary_sha256="3" * 64))


def receipt(o, index=1, *, state="active"):
    origin_o = dict(o, observed_seq=index)
    origin = decision_intent_for(build_decision_observation(origin_o), dict(
        behavior="navigate_to_pose", reason="synthetic original goal",
        goal=dict(frame="map", position_m=[1.2, -0.1], yaw_rad=0.0)))
    terminal = state in ("succeeded", "canceled", "stopped", "rejected", "aborted")
    return dict(operation_id=f"{index:032x}", origin_intent=origin,
                latest_authorization={name: origin[name] for name in IDENTITY},
                goal_uuids=dict(planner=f"{index + 100:032x}", navigation=f"{index + 200:032x}"),
                state=state, cancel_requested=state in ("canceling", "canceled", "stopped"),
                terminal=terminal, stop_confirmed=terminal)


def goals(o, records=None, *, active=True, count=None):
    records = [receipt(o)] if records is None else records
    return dict(available=True, selection=copy.deepcopy(records[-1]) if active and records else None,
                history=copy.deepcopy(records), operation_count=len(records) if count is None else count,
                stop_requested=False, fault=None)


def feedback(o=None):
    o = original() if o is None else o
    return navigation_feedback(o, estimate(), goal_status=goals(o))


def test_actual_scan_reference_estimate_and_goal_origin_are_detached():
    o = original()
    nav, goal = estimate(), goals(o)
    value = navigation_feedback(o, nav, goal_status=goal)
    assert value["schema"] == FEEDBACK_SCHEMA
    assert value["source"] == {name: o[name] for name in IDENTITY}
    assert value["scan"]["cloud_frame_id"] == o["sensors"]["pointcloud"]["frame_id"]
    assert value["navigation"]["stamp_ns"] == 98000000
    assert value["goal_status"]["history"][0]["origin_intent"]["observed_seq"] == 1
    nav["position_m"][0] = 500.0
    goal["selection"]["origin_intent"]["command"]["reason"] = "mutated"
    o["observed_seq"] = 500
    assert value["navigation"]["position_m"][0] == 0.2
    assert value["goal_status"]["selection"]["origin_intent"]["command"]["reason"] != "mutated"


@pytest.mark.parametrize("reason", ["not_provided", "pending_localization", "map_transform_unavailable",
                                  "staged_scan_expired", "pending_navigation"])
def test_unavailable_still_carries_this_original_source_and_scan_without_pose(reason):
    o = original()
    value = unavailable_navigation_feedback(o, reason)
    assert value["navigation"] == dict(available=False, reason=reason)
    assert value["source"]["observed_seq"] == 3 and value["scan"]["cloud_frame_id"] == 1
    assert value["goal_status"] == dict(available=False, reason="not_provided")
    value["navigation"]["position_m"] = [0.0, 0.0, 0.0]
    with pytest.raises(ContractError):
        validate_navigation_feedback(value, o)


@pytest.mark.parametrize("mutation", [
    lambda f: f.update(schema="wrong"),
    lambda f: f.update(world_robots=[]),
    lambda f: f["source"].update(episode=True),
    lambda f: f["source"].update(observed_seq=2),
    lambda f: f["scan"].update(cloud_frame_id=False),
    lambda f: f["scan"].update(cloud_frame_id=0),
    lambda f: f["scan"].update(profile_sha256="a" * 64),
    lambda f: f["scan"].update(acquisition_start_ns=100000000),
    lambda f: f["scan"].update(acquisition_end_ns=100000001),
    lambda f: f["navigation"].update(stamp_ns=97000000),
    lambda f: f["navigation"].update(stamp_ns=100000001, localization_stamp_ns=100000001),
    lambda f: f["navigation"].update(stamp_ns=True),
    lambda f: f["navigation"].update(frame="world"),
    lambda f: f["navigation"].update(child_frame="enemy"),
    lambda f: f["navigation"].update(position_m=[float("nan"), 0, 0]),
    lambda f: f["navigation"].update(position_m=[100001, 0, 0]),
    lambda f: f["navigation"].update(rotation_xyzw=[0, 0, 0, 0]),
    lambda f: f["navigation"].update(ideal_odom=[1, 2]),
    lambda f: f["navigation"]["provenance"].update(method="world_truth"),
    lambda f: f["navigation"]["provenance"].update(mapping_binary_sha256="Z" * 64),
    lambda f: f["goal_status"]["selection"].update(terminal=1),
    lambda f: f["goal_status"].update(operation_count=0),
])
def test_wrong_source_geometry_stamp_provenance_or_goal_proof_is_rejected(mutation):
    o = original()
    value = feedback(o)
    mutation(value)
    with pytest.raises(ContractError):
        validate_navigation_feedback(value, o)


def test_without_raw_nav_only_declared_scan_can_be_checked_not_actual_provenance():
    o = original()
    value = feedback(o)
    value["scan"]["cloud_frame_id"] = 9
    assert validate_navigation_feedback(value)["scan"]["cloud_frame_id"] == 9
    with pytest.raises(ContractError):
        validate_navigation_feedback(value, o)
    # Numbers alone cannot prove an algorithm produced this pose. Owned producer
    # and native source/TF evidence remain necessary beyond this shape contract.


def test_goal_status_projects_actual_last_eight_without_relabeling_terminal():
    o = original(20)
    records = [receipt(o, index, state="succeeded") for index in range(1, 11)]
    snapshot = dict(schema="polar.sim.navigation-goal-lifecycle.v1", active=None, goals=records,
                    stop_requested=False, fault=None)
    value = goal_status_from_lifecycle(snapshot, o)
    assert value["selection"] is None and value["operation_count"] == 10
    assert [r["origin_intent"]["observed_seq"] for r in value["history"]] == list(range(3, 11))
    assert value["history"][-1]["state"] == "succeeded"
    snapshot["active"] = records[-1]["operation_id"]
    with pytest.raises(ContractError):
        goal_status_from_lifecycle(snapshot, o)


def test_current_selection_must_be_actual_matching_unstopped_history_record():
    o = original()
    records = [receipt(o, state="succeeded"), receipt(o, 2)]
    snapshot = dict(schema="polar.sim.navigation-goal-lifecycle.v1", active=records[1]["operation_id"],
                    goals=records, stop_requested=False, fault=None)
    value = goal_status_from_lifecycle(snapshot, o)
    assert value["selection"] == value["history"][1]
    value["selection"]["origin_intent"]["command"]["reason"] = "changed"
    with pytest.raises(ContractError):
        navigation_feedback(o, estimate(), goal_status=value)


def test_success_without_uuid_and_future_goal_authorization_are_rejected():
    o = original()
    for mutate in (lambda r: r["goal_uuids"].update(navigation=None),
                   lambda r: r["latest_authorization"].update(observed_seq=10)):
        record = receipt(o, state="succeeded")
        mutate(record)
        with pytest.raises(ContractError):
            navigation_feedback(o, estimate(), goal_status=goals(o, [record], active=False))


def test_foreign_wall_deadline_is_an_opaque_original_echo():
    o = original()
    o["wall_deadline"] = 0.001
    value = unavailable_navigation_feedback(o)
    assert value["source"]["wall_deadline"] == 0.001
    assert validate_navigation_feedback(value, o) == value


def test_history_same_source_idempotence_and_changed_pose_response_rejected():
    value = feedback()
    history = NavigationFeedbackHistory()
    assert history.check(value) == history.check(value) == value
    mutated = copy.deepcopy(value)
    mutated["navigation"]["position_m"][0] += 0.01
    with pytest.raises(ContractError):
        history.check(mutated)
    assert history.check(value) == value


@pytest.mark.parametrize("mutation", [
    lambda f: f["goal_status"]["history"][0]["origin_intent"]["command"].update(reason="retagged"),
    lambda f: f["goal_status"]["history"][0]["latest_authorization"].update(wall_deadline=99.0),
    lambda f: f["goal_status"]["history"][0]["goal_uuids"].update(navigation="f" * 32),
])
def test_truncated_history_cannot_rewrite_seen_operation_and_failure_is_transactional(mutation):
    first_o = original()
    first = feedback(first_o)
    history = NavigationFeedbackHistory()
    history.check(first)
    next_o = original(4)
    good = navigation_feedback(next_o, estimate(), goal_status=first["goal_status"])
    bad = copy.deepcopy(good)
    mutation(bad)
    bad["goal_status"]["selection"] = copy.deepcopy(bad["goal_status"]["history"][0])
    validate_navigation_feedback(bad, next_o)
    with pytest.raises(ContractError):
        history.check(bad)
    assert history.check(good) == good


def test_unavailable_goal_metadata_does_not_erase_cancel_or_count_proofs():
    o = original()
    record = receipt(o, state="canceling")
    first = navigation_feedback(o, estimate(), goal_status=goals(o, [record]))
    history = NavigationFeedbackHistory()
    history.check(first)
    history.check(unavailable_navigation_feedback(original(4)))
    reverted = navigation_feedback(original(5), estimate(), goal_status=goals(o))
    with pytest.raises(ContractError):
        history.check(reverted)


def test_history_rejects_source_generation_profile_and_algorithm_changes():
    first = feedback()
    for mutate in (
        lambda f: f["source"].update(observed_seq=2),
        lambda f: f["source"].update(binding_epoch=4),
        lambda f: f["scan"].update(profile_sha256="f" * 64),
        lambda f: f["navigation"]["provenance"].update(producer_source_sha256="f" * 64),
    ):
        history = NavigationFeedbackHistory()
        history.check(first)
        bad = navigation_feedback(original(4), estimate(), goal_status=first["goal_status"])
        mutate(bad)
        with pytest.raises(ContractError):
            history.check(bad)
