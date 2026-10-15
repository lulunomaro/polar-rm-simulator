"""PB wire/source adapter fixtures only; no ROS, DDS or controller algorithm."""
import base64
import copy
import struct
import threading
from unittest.mock import patch

import pytest

from rm_match.integrations.pb_goal_controller_source import PBGoalControllerSource
from rm_match.integrations.pb_navigation_bridge import (
    NavigationBridge, NavigationSettings, sourced_goal_result,
)
from rm_match.integrations.ros2_bridge import BridgeError, MAX_RESPONSE, encode_json
from rm_match.platform_v2.contracts import action_for
from rm_match.platform_v2.navigation_contracts import NAV_SCHEMA, NAV_FRAMES, POINT_ENCODING


CONTEXT = dict(robot_id="blue_sentry", episode=2, binding_epoch=3)
UUID = "a" * 32


def observation(seq=1):
    start, end = (seq - 1) * 100000000, seq * 100000000
    ext = dict(parent_frame="base_link", translation_m=[0., 0., .5],
        rotation_xyzw=[0., 0., 0., 1.], calibration_id="source_adapter_fixture")
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


def action(o):
    return action_for(o, "navigation", "velocity_body", dict(frame="base_link", vx_mps=.3, vy_mps=0., wz_rps=0.))


def settings(**changes):
    return NavigationSettings(result_profile="follow_path_uuid_v2",
        controller_id="nav2_server_pb_pid_goal_v1", expected_robot_id=CONTEXT["robot_id"],
        expected_episode=CONTEXT["episode"], expected_binding_epoch=CONTEXT["binding_epoch"], **changes)


def result(o, uuid=UUID):
    cloud = o["sensors"]["pointcloud"]
    return sourced_goal_result(o, action(o), goal_uuid=uuid, cloud_frame_id=cloud["frame_id"],
        localization_stamp_ns=cloud["acquisition_end_ns"] - 2000000,
        controller_stamp_ns=cloud["acquisition_end_ns"], controller_id="nav2_server_pb_pid_goal_v1")


class Clock:
    def __init__(self):
        self.now = 0.

    def __call__(self):
        return self.now


class Transport:
    def __init__(self, core, clock, rows=(), *, publish_hook=None):
        self.core, self.clock = core, clock
        self.rows = list(rows)
        self.publish_hook = publish_hook
        self.requests = []
        self.spins = []
        self.rejected = []

    def publish_bundle(self, bundle, request):
        self.requests.append((bundle, request))
        if self.publish_hook is not None:
            self.publish_hook()

    def spin_once(self, timeout):
        self.spins.append(timeout)
        if self.rows:
            raw = self.rows.pop(0)
            try:
                self.core.receive_result(raw if type(raw) in (str, bytes, bytearray) else encode_json(raw, MAX_RESPONSE))
            except ValueError as error:
                self.rejected.append(str(error))
        self.clock.now += min(.002, max(.0001, timeout))


def source():
    clock = Clock()
    core = PBGoalControllerSource(settings(), clock=clock)
    core.reset(copy.deepcopy(CONTEXT), {})
    return core, clock


@pytest.mark.parametrize("bad", [NavigationSettings(),
    NavigationSettings(result_profile="follow_path_uuid_v2"), settings(response_timeout=.051)])
def test_requires_explicit_actual_goal_server_profile_and_at_most_original_50ms(bad):
    with pytest.raises(BridgeError):
        PBGoalControllerSource(bad)


def test_retains_exact_validated_wire_uuid_and_action_detached_from_payload():
    core, clock = source();o = observation();payload = result(o)
    transport = Transport(core, clock, [payload])
    response = core.exchange_sourced(o, transport)
    assert response == dict(value=action(o), goal_uuid=UUID)
    assert transport.requests and not transport.rejected
    assert all(0 <= duration <= .002 for duration in transport.spins)
    response["value"]["command"]["vx_mps"] = 100.
    assert payload["action"]["command"]["vx_mps"] == .3
    assert core._source_capture is None and core._pending is None and core._result is None


@pytest.mark.parametrize("localized", [False, True])
def test_original_no_output_status_is_preserved_with_no_uuid(localized):
    core, clock = source();o = observation()
    if localized:
        core.receive_odom_stamp(o["sensors"]["pointcloud"]["acquisition_end_ns"])
    response = core.exchange_sourced(o, Transport(core, clock))
    expected = "no_associated_command" if localized else "pending_localization"
    assert response["value"]["status"] == expected and response["goal_uuid"] is None
    assert core._source_capture is None


@pytest.mark.parametrize("mutate", [
    lambda row: row.update(schema="polar.sim.pb-navigation-result.v1"),
    lambda row: row["source"].update(goal_uuid="A" * 32),
    lambda row: row["source"].update(goal_uuid=None),
    lambda row: row["source"].update(cloud_frame_id=999),
    lambda row: row["source"].update(localization_stamp_ns=100000001),
    lambda row: row["source"].update(controller_id="pb_controller_sourced_v1"),
    lambda row: row["action"].update(episode=True),
    lambda row: row["action"].update(wall_deadline=0),
    lambda row: row["action"]["command"].update(vx_mps=float("nan")),
])
def test_original_bridge_source_rejections_never_leave_uuid_slot(mutate):
    core, clock = source();o = observation();payload = result(o);mutate(payload)
    if payload["action"]["command"]["vx_mps"] != payload["action"]["command"]["vx_mps"]:
        # Deliberately exercise the real JSON parser's NaN rejection, rather than
        # the strict encoder refusing to produce that invalid fixture first.
        import json
        payload = json.dumps(payload).encode()
    transport = Transport(core, clock, [payload])
    response = core.exchange_sourced(o, transport)
    assert transport.rejected
    assert "status" in response["value"] and response["goal_uuid"] is None
    assert core._source_capture is None


def test_duplicate_result_cannot_replace_the_first_accepted_goal_uuid():
    core, clock = source();o = observation();errors = []
    def publish():
        core.receive_result(encode_json(result(o), MAX_RESPONSE))
        try:
            core.receive_result(encode_json(result(o, "b" * 32), MAX_RESPONSE))
        except BridgeError as error:
            errors.append(str(error))
    response = core.exchange_sourced(o, Transport(core, clock, publish_hook=publish))
    assert response["goal_uuid"] == UUID and errors == ["pb_duplicate_result"]


def test_mutable_wire_buffer_is_frozen_before_original_validation_and_uuid_capture():
    core, clock = source();o = observation()
    raw = bytearray(encode_json(result(o), MAX_RESPONSE))
    def publish():
        core.receive_result(raw)
        raw[:] = b"changed caller-owned wire buffer"
    response = core.exchange_sourced(o, Transport(core, clock, publish_hook=publish))
    assert response == dict(value=action(o), goal_uuid=UUID)


def test_cross_scan_stale_action_and_late_wire_cannot_reuse_captured_uuid():
    core, clock = source();one = observation();old = result(one)
    assert core.exchange_sourced(one, Transport(core, clock, [old]))["goal_uuid"] == UUID
    with pytest.raises(BridgeError, match="no_live_pending"):
        core.receive_result(encode_json(old, MAX_RESPONSE))
    two = observation(2)
    stale = Transport(core, clock, [old])
    response = core.exchange_sourced(two, stale)
    assert stale.rejected and response["goal_uuid"] is None
    assert response["value"]["observed_seq"] == 2
    three = observation(3)
    assert core.exchange_sourced(three, Transport(core, clock, [result(three, "c" * 32)]))["goal_uuid"] == "c" * 32


def test_no_raw_capture_is_an_error_not_an_unexplained_status_fallback():
    core, clock = source();o = observation()
    with patch.object(NavigationBridge, "exchange", return_value=("action", action(o))):
        with pytest.raises(BridgeError, match="action_capture_mismatch"):
            core.exchange_sourced(o, Transport(core, clock))
    assert core._source_capture is None and not core._source_busy


def test_added_uuid_copy_cannot_extend_parent_local_deadline():
    core, clock = source();o = observation()
    def sampled_clock():
        return .05 if core._pending is None and core._source_capture is not None else clock.now
    core.clock = sampled_clock
    with pytest.raises(BridgeError, match="local_budget_expired"):
        core.exchange_sourced(o, Transport(core, clock, [result(o)]))
    assert core._source_capture is None


def test_reentrant_exchange_rejected_without_mutating_current_receipt():
    core, clock = source();o = observation();errors = []
    def reenter():
        try:
            core.exchange_sourced(observation(2), Transport(core, clock))
        except BridgeError as error:
            errors.append(str(error))
    response = core.exchange_sourced(o, Transport(core, clock, [result(o)], publish_hook=reenter))
    assert errors == ["pb_goal_source_concurrent_exchange"]
    assert response == dict(value=action(o), goal_uuid=UUID)


def test_foreign_executor_callback_fails_closed_without_waiting_on_owner_spin():
    core, clock = source();o = observation();errors = [];completed = threading.Event()
    def foreign_result():
        try:
            core.receive_result(encode_json(result(o), MAX_RESPONSE))
        except BridgeError as error:
            errors.append(str(error))
        finally:
            completed.set()
    def publish():
        thread = threading.Thread(target=foreign_result)
        thread.start()
        try:
            assert completed.wait(1.)
        finally:
            thread.join(1.)
        assert not thread.is_alive()
    transport = Transport(core, clock, [result(o)], publish_hook=publish)
    response = core.exchange_sourced(o, transport)
    assert errors == ["pb_goal_source_result_requires_owned_spin_thread"]
    assert response["goal_uuid"] == UUID  # Accepted only by the actual owner spin.


def test_slot_lock_contention_rejects_instead_of_waiting_for_callback_thread():
    core, _ = source();entered = threading.Event();release = threading.Event()
    def hold():
        with core._source_lock:
            entered.set()
            assert release.wait(1.)
    thread = threading.Thread(target=hold);thread.start()
    try:
        assert entered.wait(1.)
        with pytest.raises(BridgeError, match="concurrent_access"):
            core.begin(observation())
    finally:
        release.set();thread.join(1.)
    assert not thread.is_alive()


def test_close_and_original_generation_reset_rules_remain_fail_closed():
    core, clock = source()
    with pytest.raises(BridgeError, match="reset_once"):
        core.reset(CONTEXT, {})
    core.close();core.close()
    with pytest.raises(BridgeError):
        core.exchange_sourced(observation(), Transport(core, clock))
    assert core._source_capture is None


@pytest.mark.parametrize("raw_uuid, authorized", [(UUID, True), ("f" * 32, False)])
def test_generic_compute_consumes_only_raw_pb_uuid_never_its_lifecycle_uuid(raw_uuid, authorized):
    from rm_match.integrations.goal_navigation_compute import GoalNavigationCompute
    from rm_match.integrations.navigation_goal_lifecycle import BACKEND_SCHEMA, NavigationGoalLifecycle
    from rm_match.platform_v2.decision_contracts import build_decision_observation, decision_intent_for
    class Backend:
        def start(self, goal, source, *, operation_id):
            return dict(operation_id=operation_id, source=source)
        def poll(self, operation):
            return dict(schema=BACKEND_SCHEMA, **operation, state="active",
                goal_uuids=dict(planner="1" * 32, navigation=UUID), terminal=False,
                cancel_acknowledged=False, stop_confirmed=False, error_code=None)
        def cancel(self, operation):
            pass
    core, clock = source();o = observation()
    lifecycle = NavigationGoalLifecycle(Backend(), deadline_mode="opaque", clock=lambda: 99.)
    wrapper = GoalNavigationCompute(lifecycle,
        lambda current, intent: core.exchange_sourced(current, Transport(core, clock, [result(current, raw_uuid)])))
    wrapper.reset(CONTEXT)
    current = decision_intent_for(build_decision_observation(o), dict(behavior="navigate_to_pose",
        reason="controlled raw UUID composition fixture", goal=dict(frame="map", position_m=[1., 0.], yaw_rad=0.)))
    envelope = wrapper(o, current)
    if authorized:
        assert envelope["action"] == action(o) and envelope["controller_goal_uuid"] == UUID
    else:
        assert envelope["status"]["status"] == "no_associated_command"
        assert envelope["controller_goal_uuid"] is None
        assert envelope["selection"]["goal_uuids"]["navigation"] == UUID
