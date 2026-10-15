"""Staged PB source/feedback fixtures; no ROS, hardware or real estimates."""
import base64
import copy
import struct

import pytest

from rm_match.integrations.pb_goal_plugin_source import PBGoalPluginSource
from rm_match.integrations.pb_navigation_bridge import NavigationSettings, sourced_goal_result
from rm_match.integrations.ros2_bridge import BridgeError, MAX_RESPONSE, encode_json
from rm_match.platform_v2.contracts import IDENTITY, action_for
from rm_match.platform_v2.navigation_contracts import NAV_SCHEMA, NAV_FRAMES, POINT_ENCODING

CONTEXT = dict(robot_id="red_sentry", episode=0, binding_epoch=1)


def observation(seq=1):
    start, end = (seq - 1) * 100000000, seq * 100000000
    ext = dict(parent_frame="base_link", translation_m=[0., 0., .5], rotation_xyzw=[0., 0., 0., 1.], calibration_id="stage_fixture")
    return dict(schema=NAV_SCHEMA, **CONTEXT, observed_seq=seq, sim_time=end * 1e-9, wall_deadline=.15,
        frames=dict(NAV_FRAMES), own=dict(team="red", role="sentry", hp=100., ammo=10., heat=0., alive=True),
        referee=dict(phase="running", remaining_seconds=299., emergency_stop=False),
        sensors=dict(pointcloud=dict(available=True, reason="available", frame_id=seq,
            acquisition_start_ns=start, acquisition_end_ns=end, capture_sim_time=end * 1e-9,
            frame="livox_frame", encoding=POINT_ENCODING, point_count=1,
            data_base64=base64.b64encode(struct.pack("<fffIBBBx", 1., 0., 0., 0, 24, 0x10, 0)).decode(),
            range_min_m=.1, range_max_m=20., time_quantization_ns=2000000,
            provenance="mujoco_ray_cast_nonrepeating_profile_v1", profile_sha256="1" * 64, extrinsics=ext),
            imu=dict(available=True, reason="available", frame="livox_frame", capture_sim_time=end * 1e-9,
                extrinsics=copy.deepcopy(ext), provenance="mujoco_gyro_accelerometer_v1", samples=[dict(
                    sample_sim_ns=t, angular_velocity_rps=[0., 0., 0.], linear_acceleration_mps2=[0., 0., 9.81]) for t in (start, end)])))


def localization(o):
    c = o["sensors"]["pointcloud"]
    return dict(schema="polar.sim.pb-localization-result.v1", adapter_id="custom_pb_navigation",
        **{k: o[k] for k in IDENTITY}, cloud_frame_id=c["frame_id"], acquisition_start_ns=c["acquisition_start_ns"],
        acquisition_end_ns=c["acquisition_end_ns"], localization_stamp_ns=c["acquisition_end_ns"] - 2000000)


def native(o, uuid="a" * 32):
    c = o["sensors"]["pointcloud"]
    value = action_for(o, "navigation", "velocity_body", dict(frame="base_link", vx_mps=.3, vy_mps=0., wz_rps=0.))
    return sourced_goal_result(o, value, goal_uuid=uuid, cloud_frame_id=c["frame_id"],
        localization_stamp_ns=c["acquisition_end_ns"] - 2000000, controller_stamp_ns=c["acquisition_end_ns"],
        controller_id="nav2_server_pb_pid_goal_v1")


def transform(stamp):
    return dict(header=dict(frame_id="map", stamp=dict(sec=stamp // 1000000000, nanosec=stamp % 1000000000)),
        child_frame_id="base_link", transform=dict(translation=dict(x=.2, y=-.3, z=.01), rotation=dict(x=0., y=0., z=0., w=1.)))


class Clock:
    def __init__(self):self.now = 100000.
    def __call__(self):return self.now


class Transport:
    def __init__(self, core, clock, callbacks=()):
        self.core, self.clock = core, clock
        self.callbacks = list(callbacks);self.published = [];self.rejected = []
    def publish_bundle(self, bundle, request):self.published.append((copy.deepcopy(bundle), request))
    def spin_once(self, timeout):
        if self.callbacks:
            try:self.callbacks.pop(0)()
            except ValueError as error:self.rejected.append(str(error))
        self.clock.now += max(.0001, min(.002, timeout))


def source(*, lookup=None, ready=lambda: True, goals=None):
    clock = Clock();rows = [];stages = [];queries = []
    def actual_lookup(stamp):
        queries.append(stamp)
        return (lookup or transform)(stamp)
    core = PBGoalPluginSource(NavigationSettings(result_profile="follow_path_uuid_v2", controller_id="nav2_server_pb_pid_goal_v1"),
        lookup_estimate=actual_lookup, navigation_ready=ready, goal_snapshot=goals,
        provenance=dict(producer_source_sha256="1" * 64, localization_binary_sha256="2" * 64, mapping_binary_sha256="3" * 64),
        record=rows.append, record_stage=stages.append, clock=clock)
    core.reset(CONTEXT, {})
    return core, clock, rows, stages, queries


def wire(value):return encode_json(value, MAX_RESPONSE)


def test_observe_then_act_uses_same_one_scan_and_original_local_deadline():
    core, clock, rows, stages, queries = source();o = observation()
    transport = Transport(core, clock, [lambda: core.receive_localization(wire(localization(o))),
        lambda: core.receive_result(wire(native(o)))])
    feedback = core.observe(o, transport)
    deadline = core._deadline
    assert feedback["source"] == {k: o[k] for k in IDENTITY}
    assert feedback["navigation"]["stamp_ns"] == localization(o)["localization_stamp_ns"] == queries[0]
    assert feedback["navigation"]["position_m"] == [.2, -.3, .01]
    assert core._pending == o and len(transport.published) == 1
    result = core.consume_sourced(o, transport)
    assert result == dict(value=native(o)["action"], goal_uuid="a" * 32)
    assert len(transport.published) == 1 and core._deadline == deadline
    assert [r["topic_kind"] for r in rows] == ["request", "localization", "estimated_transform", "controller_result"]
    begin = next(r for r in stages if r["event"] == "stage_begin")
    end = next(r for r in stages if r["event"] == "stage_act_exit")
    assert begin["local_deadline"] - begin["begin_wall"] == pytest.approx(.05)
    assert end["local_wall"] < begin["local_deadline"] and end["value_kind"] == "action"
    with pytest.raises(BridgeError, match="original_observation_required"):
        core.consume_sourced(o, transport)


def test_native_result_generated_during_observe_is_retained_without_new_publish():
    core, clock, _, _, _ = source();o = observation()
    transport = Transport(core, clock, [lambda: core.receive_result(wire(native(o))),
        lambda: core.receive_localization(wire(localization(o)))])
    assert core.observe(o, transport)["navigation"]["available"]
    assert core.consume_sourced(o, transport)["goal_uuid"] == "a" * 32
    assert len(transport.published) == 1


def test_expired_act_cannot_restart_stage_or_return_previously_captured_motion():
    core, clock, _, stages, _ = source();o = observation()
    transport = Transport(core, clock, [lambda: core.receive_result(wire(native(o))),
        lambda: core.receive_localization(wire(localization(o)))])
    core.observe(o, transport);deadline = core._deadline;clock.now = deadline + .01
    response = core.consume_sourced(o, transport)
    assert "status" in response["value"] and response["goal_uuid"] is None
    assert core._deadline == deadline and len(transport.published) == 1
    assert len([r for r in stages if r["event"] == "stage_begin"]) == 1


def test_superseded_unconsumed_scan_drops_native_slot_and_rejects_late_old_scan():
    core, clock, _, stages, _ = source();one, two = observation(), observation(2)
    first = Transport(core, clock, [lambda: core.receive_result(wire(native(one))),
        lambda: core.receive_localization(wire(localization(one)))])
    core.observe(one, first)
    second = Transport(core, clock, [lambda: core.receive_result(wire(native(one))),
        lambda: core.receive_localization(wire(localization(two)))])
    core.observe(two, second)
    assert second.rejected and core._source_capture is None
    with pytest.raises(BridgeError, match="observation_changed"):
        core.consume_sourced(one, second)
    assert any(r["event"] == "stage_discard" and r["reason"] == "superseded" for r in stages)


def test_unchanged_six_with_changed_sensor_bytes_is_not_the_original_stage():
    core, clock, _, _, _ = source();o = observation()
    transport = Transport(core, clock, [lambda: core.receive_localization(wire(localization(o)))])
    core.observe(o, transport)
    changed = copy.deepcopy(o);changed["own"]["hp"] = 50.
    with pytest.raises(BridgeError, match="observation_changed"):
        core.consume_sourced(changed, transport)


@pytest.mark.parametrize("mutate", [
    lambda row: row.update(observed_seq=0), lambda row: row.update(episode=True),
    lambda row: row.update(wall_deadline=0), lambda row: row.update(cloud_frame_id=True),
    lambda row: row.update(acquisition_start_ns=1), lambda row: row.update(localization_stamp_ns=100000001),
    lambda row: row.update(adapter_id="custom_other"), lambda row: row.update(enemy_truth=[1., 2.]),
])
def test_wrong_native_context_cannot_trigger_any_tf_lookup(mutate):
    core, clock, _, _, queries = source();o = observation();bad = localization(o);mutate(bad)
    transport = Transport(core, clock, [lambda: core.receive_localization(wire(bad))])
    feedback = core.observe(o, transport)
    assert not feedback["navigation"]["available"] and not queries and transport.rejected


def test_no_native_context_never_queries_latest_tf_and_reports_expired_stage():
    core, clock, _, _, queries = source()
    feedback = core.observe(observation(), Transport(core, clock))
    assert feedback["navigation"] == dict(available=False, reason="staged_scan_expired")
    assert not queries


def test_exact_tf_unavailable_is_normal_and_no_nearest_fallback_is_attempted():
    core, clock, _, _, queries = source(lookup=lambda stamp: None);o = observation()
    feedback = core.observe(o, Transport(core, clock, [lambda: core.receive_localization(wire(localization(o)))]))
    assert not feedback["navigation"]["available"]
    assert queries and set(queries) == {localization(o)["localization_stamp_ns"]}


def test_original_tf_stamp_mismatch_is_error_instead_of_relabeling_pose():
    core, clock, _, _, _ = source(lookup=lambda stamp: transform(stamp - 1));o = observation()
    with pytest.raises(BridgeError, match="exact_stamp_required"):
        core.observe(o, Transport(core, clock, [lambda: core.receive_localization(wire(localization(o)))]))
    assert core._pending is None and core._stage is None


def test_real_map_estimate_but_inactive_navigation_is_explicit_pending_navigation():
    core, clock, _, _, _ = source(ready=lambda: False);o = observation()
    feedback = core.observe(o, Transport(core, clock, [lambda: core.receive_localization(wire(localization(o)))]))
    assert feedback["navigation"] == dict(available=False, reason="pending_navigation")
    assert clock.now < core._deadline


def test_callback_programming_error_is_not_converted_to_missing_transform():
    def broken(stamp):raise RuntimeError("fixture TF provider failure")
    core, clock, _, _, _ = source(lookup=broken);o = observation()
    with pytest.raises(RuntimeError, match="TF provider"):
        core.observe(o, Transport(core, clock, [lambda: core.receive_localization(wire(localization(o)))]))


def test_close_discards_open_slot_without_sending_another_scan():
    core, clock, _, stages, _ = source();o = observation()
    transport = Transport(core, clock, [lambda: core.receive_localization(wire(localization(o)))])
    core.observe(o, transport);core.close()
    assert core._pending is None and core._closed and len(transport.published) == 1
    assert stages[-1]["event"] == "stage_discard" and stages[-1]["reason"] == "closed"


@pytest.mark.parametrize("overrun", [0., .001])
def test_native_candidate_becomes_same_source_status_when_exit_journal_exhausts_stage(overrun):
    core, clock, rows, stages, _ = source();o = observation()
    transport = Transport(core, clock, [lambda: core.receive_result(wire(native(o))),
        lambda: core.receive_localization(wire(localization(o)))])
    core.observe(o, transport);deadline = core._deadline
    record = core.record_stage
    def delayed_exit(row):
        record(row)
        if row["event"] == "stage_act_exit":clock.now = deadline + overrun
    core.record_stage = delayed_exit
    response = core.consume_sourced(o, transport)
    assert response["goal_uuid"] is None and response["value"]["status"] == "no_associated_command"
    assert {k:response["value"][k] for k in IDENTITY} == {k:o[k] for k in IDENTITY}
    exit = next(row for row in stages if row["event"] == "stage_act_exit")
    withheld = next(row for row in stages if row["event"] == "stage_action_withheld")
    assert exit["value_kind"] == "action" and exit["goal_uuid"] == "a" * 32 and exit["status"] is None
    assert exit["local_wall"] < deadline and withheld["local_wall"] == deadline + overrun
    assert withheld["local_deadline"] == exit["local_deadline"] == deadline == core._deadline
    assert withheld["source"] == exit["source"] == {k:o[k] for k in IDENTITY}
    assert withheld["scan"] == exit["scan"] and withheld["goal_uuid"] == "a" * 32
    assert withheld["value_kind"] == "action" and withheld["reason"] == "stage_exit_budget_expired"
    assert len(transport.published) == 1 and core._closed is False and core._stage is None
    # A new original scan can continue; the expired scan is never restarted.
    core.record_stage = record;two = observation(2)
    next_transport = Transport(core, clock, [lambda: core.receive_localization(wire(localization(two)))])
    assert core.observe(two, next_transport)["source"]["observed_seq"] == 2
    assert len(next_transport.published) == 1


def test_capture_mismatch_is_still_fatal_instead_of_a_successful_withheld_status():
    core, clock, _, _, _ = source();o = observation()
    transport = Transport(core, clock, [lambda: core.receive_result(wire(native(o))),
        lambda: core.receive_localization(wire(localization(o)))])
    core.observe(o, transport)
    _, value, uuid = core._source_capture
    core._source_capture = (object(), value, uuid)
    with pytest.raises(BridgeError, match="action_capture_mismatch"):
        core.consume_sourced(o, transport)
