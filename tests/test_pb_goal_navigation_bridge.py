"""Strict UUID envelope units; not proof of a real FollowPath computation."""
import copy
import json

import pytest

from rm_match.integrations.pb_navigation_bridge import (
    NavigationBridge, NavigationSettings, sourced_goal_result, sourced_result,
)
from rm_match.platform_v2.contracts import ContractError, IDENTITY
from test_pb_navigation_bridge import Clock, FakeTransport, action, observation


UUID = "0123456789abcdef0123456789abcdef"
CONTROLLER = "nav2_server_pb_pid_goal_v1"
V1_SCHEMA = "polar.sim.pb-navigation-result.v1"
V2_SCHEMA = "polar.sim.pb-navigation-result.v2"


def source_kwargs(o, controller=CONTROLLER):
    cloud = o["sensors"]["pointcloud"]
    return dict(cloud_frame_id=cloud["frame_id"],
                localization_stamp_ns=cloud["acquisition_end_ns"],
                controller_stamp_ns=round(o["sim_time"] * 1e9),
                controller_id=controller)


def result(o, *, goal_uuid=UUID):
    return sourced_goal_result(o, action(o), goal_uuid=goal_uuid, **source_kwargs(o))


def bridge(profile="follow_path_uuid_v2"):
    clock = Clock()
    settings = NavigationSettings(result_profile=profile, controller_id=CONTROLLER,
                                  expected_episode=2, expected_binding_epoch=3)
    core = NavigationBridge(settings, clock=clock)
    o = observation()
    core.reset({key: o[key] for key in ("robot_id", "episode", "binding_epoch")}, {})
    return core, clock, o


def wire(row):
    return json.dumps(row, allow_nan=False)


def test_v2_routes_source_uuid_and_returns_unchanged_v2_action():
    core, clock, o = bridge()
    expected_action = action(o)
    row = result(o)
    original_wire = wire(row)
    assert row["schema"] == V2_SCHEMA
    assert set(row["source"]) == {
        "cloud_frame_id", "localization_stamp_ns", "controller_stamp_ns",
        "controller_id", "goal_uuid",
    }
    assert row["source"]["goal_uuid"] == UUID
    transport = FakeTransport(core, row)
    kind, accepted = core.exchange(o, transport)
    assert kind == "action" and accepted == expected_action
    assert set(accepted) == set(expected_action) and "goal_uuid" not in accepted
    for key in IDENTITY:
        assert type(accepted[key]) is type(o[key]) and accepted[key] == o[key]
    assert accepted["wall_deadline"] == 987654321.0  # opaque foreign echo.
    assert clock() < 100.05
    assert wire(row) == original_wire
    assert transport.bundles[0][1]["observed_seq"] == o["observed_seq"]


def test_default_profile_keeps_exact_legacy_shape_and_velocity_semantics():
    settings = NavigationSettings()
    assert settings.result_profile == "scan_v1"
    core, _, o = bridge("scan_v1")
    legacy = sourced_result(o, action(o), **source_kwargs(o))
    assert legacy["schema"] == V1_SCHEMA and "goal_uuid" not in legacy["source"]
    assert core.exchange(o, FakeTransport(core, legacy)) == ("action", action(o))


@pytest.mark.parametrize("selected,received", [
    ("scan_v1", "follow_path_uuid_v2"),
    ("follow_path_uuid_v2", "scan_v1"),
])
def test_profiles_never_accept_each_others_envelope(selected, received):
    core, _, o = bridge(selected)
    core.begin(o)
    row = result(o) if received == "follow_path_uuid_v2" else sourced_result(
        o, action(o), **source_kwargs(o))
    with pytest.raises(ContractError):
        core.receive_result(wire(row))
    assert core._result is None


@pytest.mark.parametrize("bad_uuid", [None, True, 17, 1.0, [], {}, "", "a" * 31,
                                     "a" * 33, "A" * 32, "g" * 32,
                                     "12345678-1234-1234-1234-123456789abc"])
def test_wire_malformed_uuid_is_not_velocity_authority(bad_uuid):
    core, _, o = bridge()
    core.begin(o)
    row = result(o)
    row["source"]["goal_uuid"] = bad_uuid
    with pytest.raises(ContractError):
        core.receive_result(wire(row))
    assert core._result is None


def test_helper_rejects_non_json_string_subclass_before_serialization():
    class NonJsonString(str):
        pass
    o = observation()
    with pytest.raises(ContractError):
        result(o, goal_uuid=NonJsonString(UUID))


@pytest.mark.parametrize("mutation", [
    lambda row: row["source"].pop("goal_uuid"),
    lambda row: row["source"].update(world_xy=[1.0, 2.0]),
    lambda row: row.update(goal_uuid=UUID),
    lambda row: row["action"].update(goal_uuid=UUID),
    lambda row: row["source"].update(controller_id="pb_controller_sourced_v1"),
    lambda row: row["source"].update(cloud_frame_id=True),
    lambda row: row["source"].update(cloud_frame_id=0),
    lambda row: row["source"].update(localization_stamp_ns=899999999),
    lambda row: row["source"].update(localization_stamp_ns=1000000001),
    lambda row: row["source"].update(controller_stamp_ns=999999999),
    lambda row: row["source"].update(controller_stamp_ns=1000000001),
    lambda row: row["action"].update(robot_id="blue_sentry"),
    lambda row: row["action"].update(episode=True),
    lambda row: row["action"].update(binding_epoch=4),
    lambda row: row["action"].update(observed_seq=0),
    lambda row: row["action"].update(sim_time=1),
    lambda row: row["action"].update(wall_deadline=987654321),
])
def test_valid_uuid_does_not_bypass_source_identity_or_shape_guards(mutation):
    core, _, o = bridge()
    core.begin(o)
    row = result(o)
    mutation(row)
    with pytest.raises(ContractError):
        core.receive_result(wire(row))
    assert core._result is None


@pytest.mark.parametrize("edge", ["already_expired", "expires_during_validation"])
def test_goal_metadata_never_refreshes_original_local_response_budget(edge):
    core, clock, o = bridge()
    core.begin(o)
    deadline = core._deadline
    if edge == "already_expired":
        clock.now = deadline
    else:
        reads = iter((deadline - 0.000001, deadline))
        core.clock = lambda: next(reads)
    with pytest.raises(ContractError):
        core.receive_result(wire(result(o)))
    assert core._result is None and core._deadline == deadline


def test_pending_source_is_detached_and_duplicate_uuid_result_cannot_replace_it():
    core, _, o = bridge()
    original = copy.deepcopy(o)
    core.begin(o)
    o["observed_seq"] = 999
    o["sensors"]["pointcloud"]["frame_id"] = 99
    core.receive_result(wire(result(original)))
    accepted = copy.deepcopy(core._result)
    second = result(original, goal_uuid="f" * 32)
    with pytest.raises(ContractError):
        core.receive_result(wire(second))
    assert core._result == accepted == action(original)


def test_timed_out_scan_does_not_relabel_late_goal_result_for_next_capture():
    core, _, old = bridge()
    assert core.exchange(old, FakeTransport(core))[0] == "status"
    new = observation(2, 2, 1000000000, 1100000000)
    core.begin(new)
    with pytest.raises(ContractError):
        core.receive_result(wire(result(old)))
    assert core._result is None
    core.receive_result(wire(result(new)))
    assert core._result == action(new)
    assert core._result["observed_seq"] == 2


def test_helper_only_wraps_reviewed_caller_metadata_and_detaches_action():
    o = observation()
    velocity = action(o)
    row = sourced_goal_result(o, velocity, goal_uuid=UUID, **source_kwargs(o))
    expected = copy.deepcopy(row)
    velocity["command"]["vx_mps"] = 100.0
    o["observed_seq"] = 500
    assert row == expected
    assert row["action"]["command"]["vx_mps"] == 0.2
    # No live Nav2 handle exists in this unit: the helper cannot attest origin.
    assert row["source"]["goal_uuid"] == UUID


@pytest.mark.parametrize("profile", ["unknown", "", None, True, 1])
def test_unknown_result_profile_is_rejected(profile):
    with pytest.raises(ContractError):
        NavigationSettings(result_profile=profile)
