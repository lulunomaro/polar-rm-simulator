"""Local identity declarations; all native computations are controlled spies."""
import copy
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from rm_match.platform_v2.contracts import ContractError
from rm_match.platform_v2.native_robot_scope import SCHEMA, load_native_robot_scope


def declaration():
    return dict(schema=SCHEMA, robots=[
        dict(robot_id="red_sentry", team="red", role="sentry", referee_id=7),
        # Explicit metadata, deliberately unrelated to the robot_id spelling.
        dict(robot_id="vehicle_b", team="blue", role="infantry", referee_id=103)])


def write_scope(tmp_path, value=None):
    path = tmp_path / "native-scope.json"
    path.write_text(json.dumps(declaration() if value is None else value, allow_nan=False), encoding="utf-8")
    return path


def test_legacy_default_and_explicit_immutable_detached_scope(tmp_path):
    default = load_native_robot_scope()
    assert default.supported_robots == ["red_sentry"]
    assert default.match("red_sentry", "red", "sentry").referee_id == 7
    assert default.path is None and default.sha256 is None
    with pytest.raises(ContractError, match="unsupported"):default.match("vehicle_b", "blue", "infantry")
    path = write_scope(tmp_path);scope = load_native_robot_scope(path)
    assert scope.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    row = scope.match("vehicle_b", "blue", "infantry")
    assert (row.team, row.role, row.referee_id) == ("blue", "infantry", 103)
    with pytest.raises(FrozenInstanceError):row.team = "red"
    with pytest.raises(FrozenInstanceError):scope.path = None
    robots = scope.supported_robots;robots.clear()
    public = scope.declaration();public["robots"][1]["team"] = "red"
    assert scope.supported_robots == ["red_sentry", "vehicle_b"] and row.team == "blue"


@pytest.mark.parametrize("change", [
    lambda x: x.update(schema="unknown"),
    lambda x: x.update(command=["curl", "https://invalid"]),
    lambda x: x.update(robots=[]),
    lambda x: x["robots"].append(copy.deepcopy(x["robots"][0])),
    lambda x: x["robots"][0].update(robot_id=True),
    lambda x: x["robots"][0].update(team="unknown"),
    lambda x: x["robots"][0].update(role=""),
    lambda x: x["robots"][0].update(role=False),
    lambda x: x["robots"][0].update(referee_id=True),
    lambda x: x["robots"][0].update(referee_id=7.0),
    lambda x: x["robots"][0].update(referee_id=0),
    lambda x: x["robots"][0].update(referee_id=256),
    lambda x: x["robots"][0].update(untrusted_extra=True),
])
def test_malformed_scope_rejected_before_native_setup(tmp_path, change):
    value = declaration();change(value)
    with pytest.raises(ContractError):load_native_robot_scope(write_scope(tmp_path, value))


@pytest.mark.parametrize("raw", [
    '{"schema":"polar.sim.native-robot-scope.v1","robots":[],"robots":[]}',
    '{"schema":"polar.sim.native-robot-scope.v1","robots":[{"robot_id":"x","team":"red","team":"blue","role":"sentry","referee_id":7}]}',
    '{"schema":"polar.sim.native-robot-scope.v1","robots":[{"robot_id":"x","team":"red","role":"sentry","referee_id":NaN}]}',
])
def test_ambiguous_or_nonfinite_json_is_rejected(tmp_path, raw):
    path = tmp_path / "bad.json";path.write_text(raw)
    with pytest.raises(ContractError):load_native_robot_scope(path)


@pytest.mark.parametrize("path", ["https://example.invalid/scope.json", "file:///tmp/scope.json", "//server/share/scope.json"])
def test_scope_is_a_plain_local_file_not_a_remote_source(path):
    with pytest.raises(ContractError):load_native_robot_scope(path)


@pytest.mark.parametrize("change", ["bytes", "deleted"])
def test_selected_scope_snapshot_cannot_change_after_registration(tmp_path, change):
    path = write_scope(tmp_path);scope = load_native_robot_scope(path)
    if change == "bytes":path.write_bytes(path.read_bytes() + b" ")
    else:path.unlink()
    with pytest.raises(ContractError, match="changed"):scope.verify_unchanged()
    with pytest.raises(ContractError, match="changed"):load_native_robot_scope(scope)


def test_default_and_own_registries_declare_scope_but_keep_stationary_capability(tmp_path, monkeypatch):
    from rm_match.deployment import profile
    from rm_match.platform_v2 import adapters, native_adapter
    path = write_scope(tmp_path);spec = tmp_path / "spec.json";spec.write_text("{}")
    monkeypatch.setattr(native_adapter, "validate_native_spec", lambda *_: ({}, "spec-pin"))
    monkeypatch.setattr(profile, "validate_t2_spec", lambda *_: ({"source_identity": {"fixture": True}}, profile.digest(spec)))
    for registry in (adapters.default_registry(native_spec=spec, native_out=tmp_path / "out", native_robot_scope=path),
        profile.own_registry(spec, tmp_path / "out", native_robot_scope=path)):
        d = registry.get("aim_native_rmcs_v1").descriptor
        assert d["supported_robots"] == ["red_sentry", "vehicle_b"]
        assert d["stationary_only"] is True and registry.capability("aim_native_rmcs_v1", "stationary_only") is True
        assert d["max_camera_age_sim_s"] == .08 and d["max_camera_age_wall_s"] == .08
        assert d["native_robot_scope"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert d["fire_authority"] == "manual_only"
    registry = adapters.default_registry(native_spec=spec, native_out=tmp_path / "out", native_robot_scope=path)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ContractError, match="scope_changed"):registry.create("aim_native_rmcs_v1", {})


def adapter_fixture(tmp_path, monkeypatch):
    from rm_match.platform_v2 import native_adapter
    from rm_match.platform_v2.test_contracts import sample
    from rm_match.camera_profile import SourceCameraProfile
    from rm_match.contracts import Observation
    path = write_scope(tmp_path);scope = load_native_robot_scope(path)
    monkeypatch.setattr(native_adapter, "validate_native_spec", lambda *_: ({}, "spec-pin"))
    adapter = native_adapter.NativeSourceAdapter({}, spec_path=tmp_path / "spec", out=tmp_path / "out", robot_scope=scope)
    o = sample(True);o.update(robot_id="vehicle_b", sim_time=1.)
    o["own"].update(team="blue", role="infantry", alive=True, odom_xyyaw=[0., 0., 0.], odom_vxyw=[0., 0., 0.])
    o["referee"].update(phase="running", emergency_stop=False)
    cam = o["sensors"]["camera"];p = SourceCameraProfile()
    cam.update(capture_sim_time=1., frame_id=1)
    cam["image"].update(width=p.width, height=p.height)
    cam["intrinsics"].update(fx=p.fx, fy=p.fy, cx=p.cx, cy=p.cy, distortion=list(p.distortion))
    cam["extrinsics"].update(translation_m=[.24, 0., .06], rotation_xyzw=[-.5, .5, -.5, .5])
    raw = Observation(episode=0, sim_time=1., rgb=np.zeros((1, 1, 3), dtype=np.uint8), fovy_degrees=60.,
        own_qpos=(0.,) * 5, own_qvel=(0.,) * 5, own_hp=100., ammo=100., robot_id="vehicle_b",
        odom_xyyaw=(0., 0., 0.), odom_vxyw=(0., 0., 0.))
    monkeypatch.setattr(native_adapter, "raw_observation", lambda *_a, **_kw: raw)
    monkeypatch.setattr(native_adapter, "prepare_native_image", lambda *_a, **_kw: ({"fixture": "unchanged BGR packet"}, None, {}))
    monkeypatch.setattr("rm_match.integrations.rmcs_contract.own_state", lambda _: {"fixture": "capture own state"})
    adapter.directory = tmp_path / "binding"
    adapter.stable_since = 0.;adapter.anchor = [0., 0.];adapter.process = SimpleNamespace(close=lambda: None)
    packets = []
    adapter._native_control = lambda packet, *_a, **_kw: packets.append(copy.deepcopy(packet)) or {"should_control": False}
    return adapter, path, o, packets


def test_native_frame_uses_explicit_matched_blue_identity_without_changing_native_code(tmp_path, monkeypatch):
    adapter, _, o, packets = adapter_fixture(tmp_path, monkeypatch)
    assert adapter._act_sensor(o, lambda: "held", lambda _: "action") == "held"
    assert len(packets) == 1
    frame = packets[0]["frame"]
    assert frame["own_team"] == "blue" and frame["own_referee_id"] == 103
    assert frame["frame_id"] == o["sensors"]["camera"]["frame_id"]
    assert frame["exposure_timestamp_ns"] == 1_000_000_000 and packets[0]["control_time_ns"] == 1_000_000_000


@pytest.mark.parametrize("change", [dict(team="red"), dict(role="sentry")])
def test_wrong_observed_team_or_role_never_reaches_native(tmp_path, monkeypatch, change):
    adapter, _, o, packets = adapter_fixture(tmp_path, monkeypatch);o["own"].update(change)
    with pytest.raises(ContractError, match="observation_mismatch"):
        adapter._act_sensor(o, lambda: "held", lambda _: "action")
    assert packets == []


@pytest.mark.parametrize("reason", ["motion", "anchor", "warmup", "camera_age", "calibration"])
def test_explicit_scope_does_not_relax_original_stationary_camera_guards(tmp_path, monkeypatch, reason):
    adapter, _, o, packets = adapter_fixture(tmp_path, monkeypatch)
    if reason == "motion":o["own"]["odom_vxyw"][0] = .031
    elif reason == "anchor":o["own"]["odom_xyyaw"][0] = .026
    elif reason == "warmup":adapter.stable_since = .7
    elif reason == "camera_age":o["sensors"]["camera"]["capture_sim_time"] = .919
    else:o["sensors"]["camera"]["extrinsics"]["translation_m"][0] += .001
    if reason == "calibration":
        with pytest.raises(ContractError, match="extrinsics_mismatch"):
            adapter._act_sensor(o, lambda: "held", lambda _: "action")
    else:assert adapter._act_sensor(o, lambda: "held", lambda _: "action") == "held"
    assert packets == []


def test_changed_scope_refuses_adapter_construction_and_native_start(tmp_path, monkeypatch):
    from rm_match.platform_v2.native_adapter import NativeSourceAdapter
    adapter, path, _, _ = adapter_fixture(tmp_path, monkeypatch)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ContractError, match="scope_changed"):
        NativeSourceAdapter({}, spec_path=tmp_path / "spec", out=tmp_path / "out", robot_scope=adapter.robot_scope)
    with pytest.raises(ContractError, match="scope_changed"):adapter._start_process(0)


def test_wsl_prepared_handover_scope_change_closes_instance_without_new_native_process(tmp_path):
    from rm_match.deployment.wsl_registry import WslRegistry
    path = write_scope(tmp_path)
    checked = SimpleNamespace(metadata={"transport": "wsl_async_bgr_v3"}, linux_spec={"source_identity": {}})
    registry = WslRegistry(checked, tmp_path / "out", "Ubuntu", None, native_robot_scope=path)
    events = []
    instance = SimpleNamespace(cancel=lambda: events.append("cancel"), close=lambda: events.append("close"))
    registry._prepared = instance
    d = registry.get("aim_native_rmcs_v1").descriptor
    assert d["supported_robots"] == ["red_sentry", "vehicle_b"] and d["stationary_only"] is True
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ContractError, match="scope_changed"):registry.create("aim_native_rmcs_v1", {})
    assert registry._prepared is None and events == ["cancel", "close"]


def test_wsl_adapter_checks_scope_before_handover_or_owned_start(tmp_path):
    from rm_match.platform_v2.wsl_native_adapter import WslNativeSourceAdapter
    path = write_scope(tmp_path);scope = load_native_robot_scope(path)
    adapter = object.__new__(WslNativeSourceAdapter);adapter.robot_scope = scope
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ContractError, match="scope_changed"):adapter.verify_handover()
    with pytest.raises(ContractError, match="scope_changed"):
        adapter._start_owned_process(0, lambda *_a, **_kw: pytest.fail("must not create a process"))
