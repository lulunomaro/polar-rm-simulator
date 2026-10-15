"""Controlled asynchronous goal/controller receipts; no ROS or real navigation."""
import base64
import copy
import struct

import pytest

from rm_match.integrations.goal_navigation_compute import GoalNavigationCompute
from rm_match.integrations.navigation_goal_lifecycle import BACKEND_SCHEMA, NavigationGoalLifecycle
from rm_match.deployment.navigation_plugin import navigation_status_for
from rm_match.platform_v2.contracts import ContractError, IDENTITY, action_for
from rm_match.platform_v2.decision_contracts import build_decision_observation, decision_intent_for
from rm_match.platform_v2.navigation_contracts import NAV_SCHEMA, NAV_FRAMES, POINT_ENCODING


CONTEXT = dict(robot_id="blue_sentry", episode=2, binding_epoch=3)


def observation(seq=1):
    start, end = (seq - 1) * 100000000, seq * 100000000
    ext = dict(parent_frame="base_link", translation_m=[0., 0., .5],
        rotation_xyzw=[0., 0., 0., 1.], calibration_id="synthetic_mount")
    return dict(schema=NAV_SCHEMA, **CONTEXT, observed_seq=seq, sim_time=end * 1e-9,
        wall_deadline=.15, frames=dict(NAV_FRAMES),
        own=dict(team="blue", role="sentry", hp=100., ammo=10., heat=0., alive=True),
        referee=dict(phase="running", remaining_seconds=299., emergency_stop=False),
        sensors=dict(pointcloud=dict(available=True, reason="available", frame_id=seq,
            acquisition_start_ns=start, acquisition_end_ns=end, capture_sim_time=end * 1e-9,
            frame="livox_frame", encoding=POINT_ENCODING, point_count=1,
            data_base64=base64.b64encode(struct.pack("<fffIBBBx", 1., 0., 0., 0, 24, 0x10, 0)).decode(),
            range_min_m=.1, range_max_m=20., time_quantization_ns=2000000,
            provenance="mujoco_ray_cast_nonrepeating_profile_v1", profile_sha256="1" * 64, extrinsics=ext),
            imu=dict(available=True, reason="available", frame="livox_frame", capture_sim_time=end * 1e-9,
                extrinsics=copy.deepcopy(ext), provenance="mujoco_gyro_accelerometer_v1",
                samples=[dict(sample_sim_ns=t, angular_velocity_rps=[.1, .2, .3],
                    linear_acceleration_mps2=[0., 0., 9.81]) for t in (start, end)])))


def intent(o, behavior="navigate_to_pose", x=1.):
    command = dict(behavior=behavior, reason="controlled source-bound protocol fixture")
    if behavior == "navigate_to_pose":
        command["goal"] = dict(frame="map", position_m=[x, 0.], yaw_rad=0.)
    return decision_intent_for(build_decision_observation(o), command)


def action(o, vx=.3):
    return action_for(o, "navigation", "velocity_body", dict(frame="base_link", vx_mps=vx, vy_mps=.1, wz_rps=0.))


class Backend:
    """A controlled accepted-handle UUID source, separate from lifecycle records."""
    def __init__(self, *, auto_accept=True, cancel_settles=False):
        self.auto_accept = auto_accept
        self.cancel_settles = cancel_settles
        self.operations = []
        self.polls = 0

    def start(self, goal, source, *, operation_id):
        op = dict(id=operation_id, source=copy.deepcopy(source), goal=copy.deepcopy(goal),
            state="sending", uuid=None, planner=None, terminal=False, ack=False, stopped=False,
            cancel_count=0, canceled=False)
        self.operations.append(op)
        if self.auto_accept:
            self.accept(op)
        return op

    def accept(self, op):
        number = self.operations.index(op) + 1
        op.update(uuid=f"{number + 100:032x}", planner=f"{number:032x}", state="active")
        if op["canceled"] and self.cancel_settles:
            self.finish(op, "canceled", ack=True)

    def cancel(self, op):
        op["cancel_count"] += 1
        op["canceled"] = True
        if self.cancel_settles and op["uuid"] is not None:
            self.finish(op, "canceled", ack=True)

    def finish(self, op, state="succeeded", *, ack=False):
        op.update(state=state, terminal=True, stopped=True, ack=ack)

    def poll(self, op):
        self.polls += 1
        return dict(schema=BACKEND_SCHEMA, operation_id=op["id"], source=copy.deepcopy(op["source"]),
            state=op["state"], goal_uuids=dict(planner=op["planner"], navigation=op["uuid"]),
            terminal=op["terminal"], cancel_acknowledged=op["ack"], stop_confirmed=op["stopped"], error_code=None)


def compute(*, backend=None, callback=None, hook=None):
    backend = backend or Backend()
    tokens = iter(f"{n + 1000:032x}" for n in range(256))
    lifecycle = NavigationGoalLifecycle(backend, clock=lambda: 100000., deadline_mode="opaque",
        token_factory=lambda: next(tokens))
    def original(o, i):
        return dict(value=action(o), goal_uuid=backend.operations[-1]["uuid"])
    wrapper = GoalNavigationCompute(lifecycle, callback or original, poll_hook=hook)
    wrapper.reset(copy.deepcopy(CONTEXT))
    return wrapper, lifecycle, backend


def test_same_call_sending_to_real_accepted_active_uses_callback_uuid_and_opaque_clock():
    observed = []
    backend = Backend(auto_accept=False)
    wrapper = None
    def callback(o, i):
        observed.append(wrapper.last_snapshot["goals"][0]["state"])
        backend.accept(backend.operations[0])
        return dict(value=action(o), goal_uuid=backend.operations[0]["uuid"])
    wrapper, lifecycle, _ = compute(backend=backend, callback=callback)
    o = observation()
    result = wrapper(o, intent(o))
    assert observed == ["sending"]
    assert result["action"] == action(o)
    assert result["controller_goal_uuid"] == backend.operations[0]["uuid"]
    assert result["selection"]["state"] == "active"
    assert result["source"]["wall_deadline"] == .15  # local clock 100000 is deliberately unrelated
    assert lifecycle.deadline_mode == "opaque"


def test_same_goal_renewal_keeps_origin_and_never_relabels_old_action():
    wrapper, _, backend = compute()
    one, two = observation(), observation(2)
    first = wrapper(one, intent(one))
    second = wrapper(two, intent(two))
    assert len(backend.operations) == 1
    assert second["selection"]["origin_intent"] == first["intent"]
    assert second["selection"]["latest_authorization"] == second["source"]
    assert second["action"]["observed_seq"] == 2
    assert first["action"]["observed_seq"] == 1
    wrapper.sourced_controller = lambda o, i: dict(value=first["action"], goal_uuid=first["controller_goal_uuid"])
    three = observation(3)
    with pytest.raises(ContractError):
        wrapper(three, intent(three))
    assert first["action"]["observed_seq"] == 1


@pytest.mark.parametrize("reported_uuid", [None, "f" * 32])
def test_missing_or_wrong_real_uuid_withholds_even_valid_action_without_mutation(reported_uuid):
    original = {}
    def callback(o, i):
        original.update(value=action(o), goal_uuid=reported_uuid)
        return original
    wrapper, _, _ = compute(callback=callback)
    o = observation()
    result = wrapper(o, intent(o))
    assert result["status"] == navigation_status_for(o)
    assert result["controller_goal_uuid"] is None
    assert result["selection"]["goal_uuids"]["navigation"] is not None
    assert original == dict(value=action(o), goal_uuid=reported_uuid)


@pytest.mark.parametrize("behavior", ["hold", "cancel"])
def test_stop_intent_reaches_backend_and_retained_motion_becomes_status(behavior):
    wrapper, lifecycle, backend = compute()
    o = observation()
    wrapper(o, intent(o))
    two = observation(2)
    result = wrapper(two, intent(two, behavior))
    assert backend.operations[0]["cancel_count"] == 1
    assert result["status"] == navigation_status_for(two)
    assert result["selection"]["cancel_requested"] is True
    assert result["selection"]["terminal"] is False
    assert lifecycle.snapshot()["clean"] is False


def test_late_acceptance_after_hold_is_not_motion_or_stop_confirmation():
    backend = Backend(auto_accept=False)
    wrapper, _, _ = compute(backend=backend)
    o = observation()
    assert "status" in wrapper(o, intent(o))
    def accept_late(o, i):
        backend.accept(backend.operations[0])
        return dict(value=action(o), goal_uuid=backend.operations[0]["uuid"])
    wrapper.sourced_controller = accept_late
    two = observation(2)
    result = wrapper(two, intent(two, "hold"))
    assert "status" in result and result["selection"]["cancel_requested"]
    assert not result["selection"]["stop_confirmed"]


def test_terminal_during_callback_cannot_reuse_historical_uuid():
    wrapper, lifecycle, backend = compute()
    one = observation()
    first = wrapper(one, intent(one))
    def complete(o, i):
        backend.finish(backend.operations[0])
        return dict(value=action(o), goal_uuid=backend.operations[0]["uuid"])
    wrapper.sourced_controller = complete
    two = observation(2)
    result = wrapper(two, intent(two))
    assert result["selection"] is None and "status" in result
    assert lifecycle.snapshot()["goals"][0]["state"] == "succeeded"
    assert lifecycle.snapshot()["active"] is None
    assert first["selection"]["terminal"] is False


def test_replacement_does_not_attach_old_controller_uuid_to_new_operation():
    backend = Backend(cancel_settles=True)
    wrapper, _, _ = compute(backend=backend)
    one = observation()
    first = wrapper(one, intent(one))
    old_uuid = first["controller_goal_uuid"]
    wrapper.sourced_controller = lambda o, i: dict(value=action(o), goal_uuid=old_uuid)
    two = observation(2)
    result = wrapper(two, intent(two, x=2.))
    assert len(backend.operations) == 2
    assert result["selection"]["operation_id"] != first["selection"]["operation_id"]
    assert result["selection"]["goal_uuids"]["navigation"] != old_uuid
    assert "status" in result and result["controller_goal_uuid"] is None


@pytest.mark.parametrize("future_replacement", [False, True])
def test_future_authorization_race_has_no_selection_for_old_input_but_real_snapshot_remains(future_replacement):
    backend = Backend(cancel_settles=True)
    wrapper, lifecycle, _ = compute(backend=backend)
    one = observation()
    first = wrapper(one, intent(one))
    original_id = first["selection"]["operation_id"]
    three = observation(3)
    def race(o, i):
        lifecycle.submit(intent(three, x=2. if future_replacement else 1.))
        return dict(value=action(o), goal_uuid=backend.operations[0]["uuid"])
    wrapper.sourced_controller = race
    two = observation(2)
    result = wrapper(two, intent(two))
    assert result["source"]["observed_seq"] == 2 and result["intent"] == intent(two)
    assert result["selection"] is None and "status" in result
    diagnostic = wrapper.last_snapshot
    assert diagnostic["active"] is not None and diagnostic["current_source"]["observed_seq"] == 3
    assert wrapper._history._records[original_id]["terminal"] is False  # None did not certify old stop.
    diagnostic["goals"].clear()
    assert wrapper.last_snapshot["goals"]
    with pytest.raises(AttributeError):
        wrapper.last_snapshot = {}


def test_hold_during_compute_with_original_source_is_withheld():
    wrapper, lifecycle, backend = compute()
    one = observation()
    wrapper(one, intent(one))
    def race(o, i):
        later = observation(3)
        lifecycle.submit(intent(later, "hold"))
        return dict(value=action(o), goal_uuid=backend.operations[0]["uuid"])
    wrapper.sourced_controller = race
    two = observation(2)
    result = wrapper(two, intent(two))
    assert "status" in result and result["selection"]["cancel_requested"]


@pytest.mark.parametrize("mutate", [
    lambda o, i: o.update(observed_seq=o["observed_seq"] + 1),
    lambda o, i: o["own"].update(hp=10.),
    lambda o, i: i["command"]["goal"].update(yaw_rad=.5),
])
def test_callback_cannot_mutate_input_snapshots_or_hide_that_with_status(mutate):
    def callback(o, i):
        mutate(o, i)
        return dict(value=navigation_status_for(o), goal_uuid=None)
    wrapper, _, _ = compute(callback=callback)
    o = observation(); original = copy.deepcopy(o); original_intent = intent(o)
    with pytest.raises(ContractError, match="callback_mutated_input"):
        wrapper(o, original_intent)
    assert o == original and original_intent == intent(o)


@pytest.mark.parametrize("poll_stage", ["callback", "hook"])
def test_real_terminal_at_either_nonblocking_stage_prevents_action(poll_stage):
    backend = Backend()
    def hook():
        if poll_stage == "hook":
            backend.finish(backend.operations[0])
    def callback(o, i):
        if poll_stage == "callback":
            backend.finish(backend.operations[0])
        return dict(value=action(o), goal_uuid=backend.operations[0]["uuid"])
    wrapper, _, _ = compute(backend=backend, callback=callback, hook=hook)
    o = observation()
    assert wrapper(o, intent(o))["selection"] is None


@pytest.mark.parametrize("mutation", [
    lambda a: a.update(robot_id="red_sentry"),
    lambda a: a.update(episode=True),
    lambda a: a.update(wall_deadline=0),
    lambda a: a["command"].update(vx_mps=float("nan")),
    lambda a: a["command"].update(fire=True),
    lambda a: a.update(ideal_enemy_position=[1., 2.]),
])
def test_malformed_callback_source_or_action_is_error_even_when_wrong_uuid(mutation):
    def callback(o, i):
        value = action(o);mutation(value)
        return dict(value=value, goal_uuid="f" * 32)
    wrapper, _, _ = compute(callback=callback)
    o = observation()
    with pytest.raises(ContractError):
        wrapper(o, intent(o))


def test_mixed_legal_source_types_remain_exact_and_equal_value_type_change_fails():
    wrapper, _, backend = compute()
    o = observation();o["wall_deadline"] = 17
    result = wrapper(o, intent(o))
    assert type(result["source"]["wall_deadline"]) is int
    assert type(result["action"]["sim_time"]) is float
    def converted(o, i):
        value = action(o);value["wall_deadline"] = float(value["wall_deadline"])
        return dict(value=value, goal_uuid=backend.operations[0]["uuid"])
    wrapper.sourced_controller = converted
    two = observation(2);two["wall_deadline"] = 17
    with pytest.raises(ContractError):
        wrapper(two, intent(two))


def test_callback_pending_status_is_retained_only_under_current_authorization():
    def pending(o, i):
        return dict(value=navigation_status_for(o, "pending_localization"), goal_uuid=None)
    wrapper, _, _ = compute(callback=pending)
    one = observation()
    assert wrapper(one, intent(one))["status"]["status"] == "pending_localization"
    two = observation(2)
    assert wrapper(two, intent(two, "hold"))["status"]["status"] == "no_associated_command"


def test_callback_exception_is_not_masked_by_progress_exception_or_fake_success():
    original = RuntimeError("actual fixture controller failure")
    def callback(o, i):
        raise original
    def hook():
        raise LookupError("actual fixture executor failure")
    wrapper, _, _ = compute(callback=callback, hook=hook)
    o = observation()
    with pytest.raises(RuntimeError) as raised:
        wrapper(o, intent(o))
    assert raised.value is original
    assert wrapper.failed is True
    with pytest.raises(ContractError, match="compute_unavailable"):
        wrapper(observation(2), intent(observation(2)))


def test_reset_once_opaque_only_and_unreset_computation_rejected():
    backend = Backend()
    host = NavigationGoalLifecycle(backend, deadline_mode="host")
    with pytest.raises(ContractError, match="opaque_deadline"):
        GoalNavigationCompute(host, lambda *_: None)
    lifecycle = NavigationGoalLifecycle(backend, deadline_mode="opaque")
    wrapper = GoalNavigationCompute(lifecycle, lambda *_: None)
    o = observation()
    with pytest.raises(ContractError, match="compute_unavailable"):
        wrapper(o, intent(o))
    with pytest.raises(ContractError):
        wrapper.reset(dict(CONTEXT, episode=True))
    context = copy.deepcopy(CONTEXT)
    snapshot = wrapper.reset(context);context["robot_id"] = "red_sentry";snapshot["state"] = "mutated"
    assert wrapper.context == CONTEXT and wrapper.last_snapshot["state"] == "idle"
    with pytest.raises(ContractError, match="reset_once"):
        wrapper.reset(CONTEXT)


def test_close_ack_alone_not_clean_and_owner_can_progress_real_terminal_then_close():
    calls = []
    wrapper, lifecycle, backend = compute(hook=lambda: calls.append("poll"))
    o = observation();wrapper(o, intent(o));op = backend.operations[0]
    op.update(state="canceling", ack=True)
    prior = len(calls)
    with pytest.raises(ContractError, match="goal_navigation_stop_unproved"):
        wrapper.close()
    assert len(calls) == prior + 1 and op["cancel_count"] == 1
    assert lifecycle.snapshot()["stop_requested"] and not lifecycle.snapshot()["clean"]
    backend.finish(op, "canceled", ack=True)
    closed = wrapper.close()
    assert closed["clean"] and op["cancel_count"] == 1
    with pytest.raises(ContractError, match="compute_unavailable"):
        wrapper(observation(2), intent(observation(2)))


def test_equal_value_different_goal_types_do_not_bypass_strict_goal_geometry():
    wrapper, _, _ = compute()
    one = observation();wrapper(one, intent(one, x=1.))
    two = observation(2)
    result = wrapper(two, intent(two, x=1))
    assert "status" in result and "action" not in result
