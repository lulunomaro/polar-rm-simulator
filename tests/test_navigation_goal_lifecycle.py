"""Controlled asynchronous backend regressions; no ROS, sensors or actuation."""
import copy
from concurrent.futures import Future
import threading

import pytest

from rm_match.integrations.navigation_goal_lifecycle import (
    BACKEND_SCHEMA, NavigationGoalLifecycle,
)
from rm_match.platform_v2.contracts import ContractError, IDENTITY


CONTEXT = dict(robot_id="red_sentry", episode=0, binding_epoch=1)


class Clock:
    def __init__(self, now=10.0):
        self.now = now

    def __call__(self):
        return self.now


def intent(seq=1, *, behavior="navigate_to_pose", x=1.0, deadline=10.15):
    command = dict(behavior=behavior, reason="controlled protocol fixture")
    if behavior == "navigate_to_pose":
        command["goal"] = dict(frame="map", position_m=[x, 0.0], yaw_rad=0.0)
    return dict(schema="polar.sim.decision-intent.v1", **CONTEXT,
                observed_seq=seq, sim_time=seq * 0.1, wall_deadline=deadline,
                kind="decision", mode="navigation_intent", command=command)


def original_source(value):
    return {key: copy.deepcopy(value[key]) for key in IDENTITY}


class Operation:
    def __init__(self, operation_id, source, goal):
        self.id = operation_id
        self.source = source
        self.goal = goal
        self.acceptance = Future()
        self.terminal = Future()
        self.cancel_called = threading.Event()
        self.cancel_count = 0
        self.reply = None
        self.planner_uuid = None
        self.navigation_uuid = None


class Backend:
    """Futures belong to the backend; poll never waits for their completion."""
    def __init__(self):
        self.started = []
        self.polled = []
        self.start_error = False
        self.cancel_error = False

    def start(self, goal, source, *, operation_id):
        if self.start_error:
            raise RuntimeError("fixture uncertain start")
        operation = Operation(operation_id, source, goal)
        self.started.append(operation)
        return operation

    def poll(self, operation):
        self.polled.append(operation.id)
        if operation.reply is not None:
            return operation.reply
        if operation.terminal.done():
            return operation.terminal.result()
        return self.status(operation, "active" if operation.acceptance.done() else "sending")

    def cancel(self, operation):
        operation.cancel_count += 1
        operation.cancel_called.set()
        if self.cancel_error:
            raise RuntimeError("fixture cancel failed")

    def status(self, operation, state, *, terminal=False, ack=False, stopped=False):
        return dict(schema=BACKEND_SCHEMA, operation_id=operation.id,
                    source=copy.deepcopy(operation.source), state=state,
                    goal_uuids=dict(planner=operation.planner_uuid,
                                    navigation=operation.navigation_uuid),
                    terminal=terminal, cancel_acknowledged=ack,
                    stop_confirmed=stopped, error_code=None)

    def accept(self, operation):
        index = self.started.index(operation) + 1
        operation.planner_uuid = f"{index:032x}"
        operation.navigation_uuid = f"{index + 100:032x}"
        operation.acceptance.set_result(True)

    def finish(self, operation, state="succeeded", *, ack=False, stopped=True):
        operation.terminal.set_result(self.status(
            operation, state, terminal=True, ack=ack, stopped=stopped))


def engine(*, mode="host", capacity=64, backend=None, clock=None, **kwargs):
    backend = backend or Backend()
    clock = clock or Clock()
    tokens = iter(f"{n:032x}" for n in range(1, 300))
    lifecycle = NavigationGoalLifecycle(
        backend, clock=clock, deadline_mode=mode, history_capacity=capacity,
        token_factory=lambda: next(tokens), **kwargs)
    lifecycle.reset(copy.deepcopy(CONTEXT))
    return lifecycle, backend, clock


def test_late_acceptance_after_cancel_does_not_count_as_stopped():
    lifecycle, backend, _ = engine()
    origin = intent()
    lifecycle.submit(origin)
    operation = backend.started[0]
    cancel_intent = intent(2, behavior="cancel")
    snapshot = lifecycle.submit(cancel_intent)
    assert snapshot["state"] == "canceling" and not snapshot["clean"]
    assert operation.cancel_called.is_set() and operation.cancel_count == 1
    assert not operation.acceptance.done()

    # A backend thread can deliver acceptance after cancellation was requested.
    release = threading.Event()
    completed = threading.Event()
    def accept_late():
        assert release.wait(1.0)
        backend.accept(operation)
        completed.set()
    thread = threading.Thread(target=accept_late)
    thread.start()
    try:
        assert lifecycle.poll()["active"] == operation.id
        release.set()
        assert completed.wait(1.0)
        snapshot = lifecycle.poll()
        assert snapshot["state"] == "canceling" and not snapshot["clean"]
        assert snapshot["goals"][0]["origin_intent"] == origin
        assert snapshot["goals"][0]["stop_intent"] == cancel_intent
        operation.reply = backend.status(operation, "canceling", ack=True)
        assert not lifecycle.poll()["clean"]  # ACK alone is no stop proof.
        operation.reply = None
        backend.finish(operation, "canceled", ack=True)
        snapshot = lifecycle.poll()
        assert snapshot["clean"] and snapshot["state"] == "idle"
        assert operation.cancel_count == 1
    finally:
        release.set()
        thread.join(1.0)
        assert not thread.is_alive()


def test_replacement_waits_for_terminal_stop_then_ignores_old_completion():
    lifecycle, backend, _ = engine()
    first, second = intent(), intent(2, x=2.0)
    lifecycle.submit(first)
    old = backend.started[0]
    backend.accept(old)
    snapshot = lifecycle.submit(second)
    assert snapshot["pending_intent"] == second
    assert len(backend.started) == 1 and old.cancel_count == 1
    old.reply = backend.status(old, "canceling", ack=True)
    lifecycle.poll()
    assert len(backend.started) == 1
    old.reply = backend.status(old, "aborted", terminal=True, ack=True, stopped=False)
    snapshot = lifecycle.poll()
    assert not snapshot["clean"] and len(backend.started) == 1
    old.reply["stop_confirmed"] = True
    snapshot = lifecycle.poll()
    new = backend.started[1]
    assert snapshot["active"] == new.id
    assert new.source == original_source(second)
    old_record = copy.deepcopy(snapshot["goals"][0])
    old_polled = backend.polled.count(old.id)
    # Obsolete backend callback mutates only the old op, which is never polled again.
    old.reply = backend.status(old, "succeeded", terminal=True, stopped=True)
    snapshot = lifecycle.poll()
    assert snapshot["goals"][0] == old_record
    assert backend.polled.count(old.id) == old_polled
    assert snapshot["goals"][1]["origin_intent"] == second
    assert snapshot["current_source"] == original_source(second)
    assert snapshot["state"] == "sending"


def test_same_geometry_renews_authorization_without_retagging_terminal():
    lifecycle, backend, _ = engine()
    first, renewal = intent(), intent(2, deadline=10.14)
    lifecycle.submit(first)
    operation = backend.started[0]
    backend.accept(operation)
    snapshot = lifecycle.submit(renewal)
    assert len(backend.started) == 1
    assert snapshot["goals"][0]["origin_intent"] == first
    assert snapshot["goals"][0]["latest_authorization"] == original_source(renewal)
    backend.finish(operation)
    lifecycle.poll()
    later = intent(3)
    snapshot = lifecycle.submit(later)
    assert len(backend.started) == 1
    assert snapshot["state"] == "idle" and "succeeded" != snapshot["state"]
    assert snapshot["goals"][0]["state"] == "succeeded"
    assert snapshot["goals"][0]["origin_intent"] == first
    assert snapshot["goals"][0]["latest_authorization"] == original_source(later)
    assert snapshot["current_source"] == original_source(later)
    lifecycle.submit(intent(4, behavior="hold"))
    lifecycle.submit(intent(5))
    assert len(backend.started) == 2


@pytest.mark.parametrize("terminal_state", ["rejected", "aborted"])
def test_failed_target_is_not_automatically_retried(terminal_state):
    lifecycle, backend, _ = engine()
    lifecycle.submit(intent())
    backend.finish(backend.started[0], terminal_state)
    lifecycle.poll()
    lifecycle.submit(intent(2))
    assert len(backend.started) == 1
    lifecycle.submit(intent(3, x=2.0))
    assert len(backend.started) == 2


def test_pending_target_expires_while_waiting_for_stop_without_new_timestamp():
    lifecycle, backend, clock = engine()
    lifecycle.submit(intent())
    old = backend.started[0]
    backend.accept(old)
    pending = intent(2, x=2.0, deadline=10.05)
    lifecycle.submit(pending)
    clock.now = pending["wall_deadline"]
    backend.finish(old, "canceled", ack=True)
    snapshot = lifecycle.poll()
    assert len(backend.started) == 1 and snapshot["pending_intent"] is None
    assert snapshot["goals"][0]["stop_intent"] == pending
    assert pending["wall_deadline"] == 10.05


def test_host_expiry_cancels_exactly_at_original_deadline():
    lifecycle, backend, clock = engine()
    original = intent()
    lifecycle.submit(original)
    operation = backend.started[0]
    backend.accept(operation)
    clock.now = 10.149999
    assert lifecycle.poll()["state"] == "active"
    assert operation.cancel_count == 0
    clock.now = original["wall_deadline"]
    snapshot = lifecycle.poll()
    assert operation.cancel_count == 1 and not snapshot["clean"]
    assert snapshot["goals"][0]["stop_reason"] == "authorization_expired"
    assert snapshot["goals"][0]["latest_authorization"] == original_source(original)
    with pytest.raises(ContractError):
        lifecycle.submit(intent(2, deadline=clock.now))


def test_opaque_deadline_is_not_subtracted_from_local_clock():
    clock = Clock(1000.0)
    lifecycle, backend, _ = engine(mode="opaque", clock=clock)
    foreign = intent(deadline=0.15)
    lifecycle.submit(foreign)
    operation = backend.started[0]
    backend.accept(operation)
    clock.now += 0.9
    snapshot = lifecycle.poll()
    assert snapshot["state"] == "active" and operation.cancel_count == 0
    assert snapshot["goals"][0]["origin_intent"]["wall_deadline"] == 0.15


def test_local_send_and_cancel_caps_are_resource_failures_not_fake_completion():
    lifecycle, backend, clock = engine(mode="opaque")
    lifecycle.submit(intent(deadline=0.15))
    operation = backend.started[0]
    clock.now += 1.0
    snapshot = lifecycle.poll()
    assert snapshot["state"] == "fault" and not snapshot["clean"]
    assert operation.cancel_count == 1
    assert not snapshot["goals"][0]["terminal"]
    clock.now += 1.3
    assert lifecycle.poll()["state"] == "fault"
    backend.accept(operation)
    backend.finish(operation, "canceled", ack=True)
    snapshot = lifecycle.poll()
    assert snapshot["active"] is None and not snapshot["clean"]  # sticky fault.
    with pytest.raises(ContractError):
        lifecycle.submit(intent(2))


def test_cancel_cap_does_not_clear_ack_only_operation():
    lifecycle, backend, clock = engine(mode="opaque")
    lifecycle.submit(intent())
    operation = backend.started[0]
    backend.accept(operation)
    lifecycle.submit(intent(2, behavior="cancel"))
    operation.reply = backend.status(operation, "canceling", ack=True)
    clock.now += 1.30001
    snapshot = lifecycle.poll()
    assert snapshot["state"] == "fault" and snapshot["active"] == operation.id
    assert not snapshot["clean"] and not snapshot["goals"][0]["terminal"]


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(extra="unreviewed"),
    lambda value: value.update(operation_id="f" * 32),
    lambda value: value["source"].update(episode=True),
    lambda value: value["source"].update(observed_seq=99),
    lambda value: value.update(terminal=1),
    lambda value: value["goal_uuids"].update(navigation="bad-uuid"),
    lambda value: value.update(state="succeeded", terminal=True, stop_confirmed=True),
    lambda value: value.update(state="canceled", terminal=True, stop_confirmed=True),
    lambda value: value.update(stop_confirmed=True),
    lambda value: value.update(error_code="arbitrary private exception details"),
])
def test_forged_backend_proof_faults_and_requests_owned_cancellation(mutation):
    lifecycle, backend, _ = engine()
    lifecycle.submit(intent())
    operation = backend.started[0]
    value = backend.status(operation, "sending")
    mutation(value)
    operation.reply = value
    snapshot = lifecycle.poll()
    assert snapshot["state"] == "fault" and not snapshot["clean"]
    assert operation.cancel_called.is_set()
    assert snapshot["actuator_authority"] == "none"
    assert snapshot["localization_feedback"] == "unavailable"
    with pytest.raises(ContractError):
        lifecycle.submit(intent(2))


def test_uuid_change_and_ack_reversal_are_not_accepted():
    for reverse_ack in (False, True):
        lifecycle, backend, _ = engine()
        lifecycle.submit(intent())
        operation = backend.started[0]
        backend.accept(operation)
        lifecycle.poll()
        if reverse_ack:
            lifecycle.submit(intent(2, behavior="cancel"))
            operation.reply = backend.status(operation, "canceling", ack=True)
            lifecycle.poll()
            operation.reply["cancel_acknowledged"] = False
        else:
            operation.reply = backend.status(operation, "active")
            operation.reply["goal_uuids"]["navigation"] = "e" * 32
        assert lifecycle.poll()["state"] == "fault"
        assert operation.cancel_count == 1


def test_original_inputs_and_public_snapshots_cannot_mutate_operation():
    lifecycle, backend, _ = engine()
    original = intent()
    expected = copy.deepcopy(original)
    snapshot = lifecycle.submit(original)
    operation = backend.started[0]
    original["command"]["goal"]["position_m"][0] = 500.0
    original["observed_seq"] = 900
    snapshot["goals"][0]["goal"]["position_m"][0] = 800.0
    snapshot["goals"][0]["origin_intent"]["episode"] = 500
    operation.goal["position_m"][0] = 700.0
    assert lifecycle.snapshot()["goals"][0]["origin_intent"] == expected
    assert lifecycle.snapshot()["goals"][0]["goal"]["position_m"][0] == 1.0
    assert operation.source == original_source(expected)


@pytest.mark.parametrize("field,value", [
    ("episode", True), ("binding_epoch", True), ("observed_seq", True),
    ("sim_time", float("nan")), ("wall_deadline", float("inf")),
    ("robot_id", "blue_sentry"), ("episode", 1), ("binding_epoch", 2),
])
def test_bad_or_cross_generation_intent_never_starts_backend(field, value):
    lifecycle, backend, _ = engine()
    bad = intent()
    bad[field] = value
    with pytest.raises(ContractError):
        lifecycle.submit(bad)
    assert backend.started == []


def test_replay_expected_source_and_reset_once_enforced():
    lifecycle, backend, _ = engine()
    first = intent()
    wrong = original_source(first)
    wrong["observed_seq"] = 2
    with pytest.raises(ContractError):
        lifecycle.submit(first, expected_source=wrong)
    assert backend.started == []
    lifecycle.submit(first, expected_source=original_source(first))
    with pytest.raises(ContractError):
        lifecycle.submit(first)
    with pytest.raises(ContractError):
        lifecycle.reset(CONTEXT)
    assert len(backend.started) == 1


def test_request_stop_preserves_origin_blocks_new_submit_until_true_stop():
    lifecycle, backend, _ = engine()
    first = intent()
    lifecycle.submit(first)
    operation = backend.started[0]
    snapshot = lifecycle.request_stop()
    assert snapshot["stop_requested"] and not snapshot["clean"]
    with pytest.raises(ContractError):
        lifecycle.submit(intent(2))
    backend.accept(operation)
    lifecycle.poll()
    assert not lifecycle.snapshot()["clean"]
    backend.finish(operation, "stopped")
    snapshot = lifecycle.poll()
    assert snapshot["clean"] and snapshot["state"] == "stopped"
    assert snapshot["goals"][0]["origin_intent"] == first
    assert operation.cancel_count == 1


def test_unknown_start_or_cancel_failure_cannot_report_clean():
    backend = Backend()
    backend.start_error = True
    lifecycle, _, _ = engine(backend=backend)
    snapshot = lifecycle.submit(intent())
    assert snapshot["state"] == "fault" and not snapshot["clean"]
    assert not lifecycle.request_stop()["clean"]
    backend = Backend()
    backend.cancel_error = True
    lifecycle, _, _ = engine(backend=backend)
    lifecycle.submit(intent())
    snapshot = lifecycle.request_stop()
    assert snapshot["state"] == "fault" and not snapshot["clean"]


def test_history_capacity_faults_without_overwriting_old_origin():
    lifecycle, backend, _ = engine(capacity=1)
    first = intent()
    lifecycle.submit(first)
    backend.finish(backend.started[0], "rejected")
    lifecycle.poll()
    snapshot = lifecycle.submit(intent(2, x=2.0))
    assert snapshot["state"] == "fault" and not snapshot["clean"]
    assert len(backend.started) == 1 and len(snapshot["goals"]) == 1
    assert snapshot["goals"][0]["origin_intent"] == first


@pytest.mark.parametrize("later_state", ["active", "aborted"])
def test_terminal_result_cannot_be_erased_while_waiting_for_stop(later_state):
    lifecycle, backend, _ = engine()
    lifecycle.submit(intent())
    operation = backend.started[0]
    backend.accept(operation)
    operation.reply = backend.status(operation, "succeeded", terminal=True, stopped=False)
    snapshot = lifecycle.poll()
    assert snapshot["goals"][0]["state"] == "succeeded"
    assert snapshot["active"] == operation.id and not snapshot["clean"]
    operation.reply = backend.status(operation, later_state,
                                     terminal=later_state == "aborted", stopped=False)
    snapshot = lifecycle.poll()
    assert snapshot["state"] == "fault" and not snapshot["clean"]
    assert snapshot["goals"][0]["state"] == "succeeded"
    assert snapshot["goals"][0]["terminal"]
    assert operation.cancel_called.is_set()


@pytest.mark.parametrize("field", ["schema", "operation_id"])
def test_backend_identity_strings_require_plain_json_scalar_types(field):
    class NonJsonString(str):
        pass
    lifecycle, backend, _ = engine()
    lifecycle.submit(intent())
    operation = backend.started[0]
    operation.reply = backend.status(operation, "sending")
    operation.reply[field] = NonJsonString(operation.reply[field])
    snapshot = lifecycle.poll()
    assert snapshot["state"] == "fault" and not snapshot["clean"]
    assert operation.cancel_called.is_set()
