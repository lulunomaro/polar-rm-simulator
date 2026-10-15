"""Explicit reference negotiation; fixtures do not qualify moving algorithms."""
import copy
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

from rm_match.deployment.aim_plugin import (
    AimPluginAdapter, CAPABILITIES, CAPABILITIES_V2, CAPABILITY_SCHEMA_V2,
    GIMBAL_REFERENCE_INERTIAL, INERTIAL_CAPABILITIES, MANIFEST_SCHEMA,
    load_aim_plugins, register_aim_plugins, validate_capabilities)
from rm_match.deployment.json_adapter import SCHEMA as JSONL_SCHEMA
from rm_match.deployment.robotio_plugin import SCHEMA as GRAPH_SCHEMA, register_robotio_plugins
from rm_match.deployment.wsl_jsonl import WslAimPluginAdapter
from rm_match.platform_v2.adapters import BaseAdapter, Registry, default_registry, descriptor
from rm_match.platform_v2.contracts import ContractError, IDENTITY, action_for
from rm_match.platform_v2.test_contracts import sample


def manifest(tmp_path, *, capabilities=CAPABILITIES_V2, transport="jsonl_v1", command=None):
    row = dict(adapter_id="custom_explicit_reference", label="Reference protocol fixture, not moving qualification",
        command=command or [sys.executable, "-c", "raise RuntimeError('must not run during registration')"],
        cwd=str(tmp_path), supported_robots=["red_infantry", "blue_infantry"],
        transport=transport, capabilities=copy.deepcopy(capabilities))
    if transport == "wsl_jsonl_v1":
        row.update(command=["/usr/bin/python3", "-m", "explicit_fixture"], cwd="/tmp/owned_fixture",
            wsl=dict(distribution="Ubuntu-22.04", python="/usr/bin/python3", process_env={"ROS_DOMAIN_ID": "84"}))
    path = tmp_path / "aim.json"
    path.write_text(json.dumps(dict(schema=MANIFEST_SCHEMA, adapters=[row])), encoding="utf-8")
    return path, row


def host_adapter(tmp_path, *, capabilities=CAPABILITIES_V2, transport="jsonl_v1"):
    path, row = manifest(tmp_path, capabilities=capabilities, transport=transport)
    rows, digest = load_aim_plugins(path)
    cls = WslAimPluginAdapter if transport == "wsl_jsonl_v1" else AimPluginAdapter
    extra = dict(repo_root=tmp_path, shared_root=tmp_path) if transport == "wsl_jsonl_v1" else {}
    a = cls({}, registration=rows[0], manifest=path, manifest_sha=digest, clock=lambda: 1., **extra)
    # Real wire admission/response validation, with no child process or pipe.
    a.process = object()
    a.close = lambda **_: None
    return a, path, row


def ack(op, *, capabilities=CAPABILITIES_V2):
    value = dict(schema=JSONL_SCHEMA, op=op, ok=True)
    if capabilities is not None:value["capabilities"] = copy.deepcopy(capabilities)
    return value


def reset_packet(o):
    return dict(op="reset", context={k: o[k] for k in ("episode", "robot_id", "binding_epoch")}, config={})


def test_capability_versions_are_exact_detached_and_v1_does_not_gain_a_reference():
    assert CAPABILITIES_V2 == INERTIAL_CAPABILITIES
    assert "gimbal_reference" not in CAPABILITIES
    assert CAPABILITIES_V2 == dict(CAPABILITIES, schema=CAPABILITY_SCHEMA_V2,
        gimbal_reference=GIMBAL_REFERENCE_INERTIAL)
    parsed = validate_capabilities(CAPABILITIES_V2)
    parsed["image_encodings"].clear()
    assert CAPABILITIES_V2["image_encodings"] == ["rgb8", "bgr8"]
    assert validate_capabilities(CAPABILITIES) == CAPABILITIES
    with pytest.raises(ContractError):validate_capabilities(dict(CAPABILITIES, gimbal_reference=GIMBAL_REFERENCE_INERTIAL))


@pytest.mark.parametrize("change", [
    lambda c: c.pop("gimbal_reference"),
    lambda c: c.update(gimbal_reference="base_link"),
    lambda c: c.update(gimbal_reference=True),
    lambda c: c.update(schema="polar.sim.aim-plugin.capabilities.v3"),
    lambda c: c.update(fire_authority="algorithm_fire"),
    lambda c: c.update(image_encodings=[True, "bgr8"]),
    lambda c: c.update(output_modes=["velocity_body"]),
    lambda c: c.update(unknown=True),
])
def test_malformed_new_capability_never_registers(tmp_path, change):
    caps = copy.deepcopy(CAPABILITIES_V2);change(caps)
    path, _ = manifest(tmp_path, capabilities=caps);registry = Registry()
    with pytest.raises(ContractError):register_aim_plugins(registry, path)
    assert registry.descriptors() == []


def test_v2_registration_requires_camera_and_odometry_and_exposes_new_contract(tmp_path):
    path, _ = manifest(tmp_path);registry = Registry();register_aim_plugins(registry, path)
    d = registry.descriptors()[0]
    assert d["version"] == "2.0.0" and d["aim_plugin_contract"] == "camera_gimbal_v2"
    assert d["required_sensors"] == ["camera", "odometry"]
    assert d["aim_reference"] == GIMBAL_REFERENCE_INERTIAL
    assert d["fire_authority"] == "manual_only"
    assert d["max_camera_age_wall_s"] == .08 and d["max_camera_age_sim_s"] == .08
    assert d["qualification"] == "interface_declared_not_algorithm_or_live_acceptance"
    assert registry.capability(d["adapter_id"], "aim_reference") == GIMBAL_REFERENCE_INERTIAL
    d["aim_reference"] = "base_link";d["required_sensors"].clear()
    d["aim_plugin_capabilities"]["gimbal_reference"] = "base_link"
    assert registry.capability("custom_explicit_reference", "aim_reference") == GIMBAL_REFERENCE_INERTIAL
    assert registry.descriptors()[0]["aim_plugin_capabilities"] == CAPABILITIES_V2


def test_legacy_capability_default_and_native_stationary_policy_stay_unchanged(tmp_path):
    path, _ = manifest(tmp_path, capabilities=CAPABILITIES);registry = Registry();register_aim_plugins(registry, path)
    d = registry.descriptors()[0]
    assert d["version"] == "1.0.0" and d["aim_plugin_contract"] == "camera_gimbal_v1"
    assert d["required_sensors"] == ["camera"] and "aim_reference" not in d
    assert registry.capability(d["adapter_id"], "aim_reference") == "base_link"
    native = default_registry()
    assert native.capability("aim_native_rmcs_v1", "aim_reference") == "base_link"
    assert native.capability("aim_native_rmcs_v1", "stationary_only") is True


@pytest.mark.parametrize("change", [
    lambda d: d.update(aim_reference="unknown"),
    lambda d: d.update(aim_reference=True),
    lambda d: d.update(aim_reference="base_link"),
    lambda d: d.update(version="1.0.0"),
    lambda d: d.update(aim_plugin_contract="camera_gimbal_v1"),
    lambda d: d.update(required_sensors=["camera"]),
    lambda d: d.update(required_sensors=["camera", "odometry", "odometry"]),
    lambda d: d.update(kind="navigation"),
    lambda d: d.update(output_modes=["velocity_body"]),
    lambda d: d.update(fire_authority="algorithm_fire"),
    lambda d: d.update(ui_config_contract="arbitrary_config"),
])
def test_conflicting_reference_metadata_never_mutates_registry_maps(change):
    d = descriptor("custom_bad_reference", "aim", "Fixture", ["camera", "odometry"],
        aim_plugin_capabilities=copy.deepcopy(CAPABILITIES_V2), aim_reference=GIMBAL_REFERENCE_INERTIAL,
        aim_plugin_contract="camera_gimbal_v2")
    d.update(version="2.0.0",ui_config_contract="empty_v1");change(d)
    registry = Registry();old_specs = registry._specs;old_caps = registry._capabilities
    with pytest.raises(ContractError):registry.register(d, lambda _: None)
    assert registry._specs is old_specs and registry._capabilities is old_caps
    assert not registry._specs and not registry._capabilities
    with pytest.raises(ContractError):registry.register(descriptor("missing_caps", "aim", "Fixture", [],
        aim_reference=GIMBAL_REFERENCE_INERTIAL), lambda _: None)


@pytest.mark.parametrize("op", ["prepare", "reset"])
@pytest.mark.parametrize("transport", ["jsonl_v1", "wsl_jsonl_v1"])
def test_both_transport_paths_send_and_validate_actual_full_v2_capabilities(tmp_path, op, transport):
    a, _, _ = host_adapter(tmp_path, transport=transport)
    packet = dict(op="prepare", config={}) if op == "prepare" else reset_packet(sample(True))
    original = copy.deepcopy(packet);a.responses.put_nowait(ack(op))
    result = a._exchange(packet, timeout=.5)
    wire = json.loads(a.requests.get_nowait())
    assert wire == dict(schema=JSONL_SCHEMA, **original, capabilities=CAPABILITIES_V2)
    assert packet == original and result == ack(op)
    wire["capabilities"]["gimbal_reference"] = "base_link"
    assert a._aim_capabilities == CAPABILITIES_V2


@pytest.mark.parametrize("bad_ack", [
    lambda: ack("reset", capabilities=None),
    lambda: ack("reset", capabilities=CAPABILITIES),
    lambda: dict(ack("reset"), ok=1),
    lambda: dict(ack("prepare")),
    lambda: dict(ack("reset"), capabilities=dict(CAPABILITIES_V2, gimbal_reference=True)),
    lambda: dict(ack("reset"), extra=True),
])
def test_wrong_peer_cannot_negotiate_the_locally_declared_v2_reference(tmp_path, bad_ack):
    a, _, _ = host_adapter(tmp_path);closed=[];a.close=lambda **_:closed.append(True)
    a.responses.put_nowait(bad_ack())
    with pytest.raises(ContractError):a._exchange(reset_packet(sample(True)), timeout=.5)
    assert a.failed and closed == [True]


def test_registration_copy_cannot_be_mutated_to_switch_reference_after_construction(tmp_path):
    a, _, _ = host_adapter(tmp_path)
    a.registration["capabilities"]["gimbal_reference"] = "base_link"
    with pytest.raises(ContractError, match="registered_capabilities_changed"):
        a._exchange(reset_packet(sample(True)), timeout=.5)
    assert a.requests.empty()


def test_v1_request_and_ack_remain_exactly_legacy_wire(tmp_path):
    a, _, _ = host_adapter(tmp_path, capabilities=CAPABILITIES)
    packet=reset_packet(sample(True));a.responses.put_nowait(ack("reset", capabilities=None))
    a._exchange(packet, timeout=.5)
    raw=a.requests.get_nowait()
    expected=(json.dumps(dict(schema=JSONL_SCHEMA, **packet), allow_nan=False, separators=(",", ":"))+"\n").encode()
    assert raw == expected and b"capabilities" not in raw
    with pytest.raises(ContractError):a._validate_response(ack("reset"), packet)


def test_v2_missing_odometry_cannot_reach_algorithm_or_return_a_fake_reference(tmp_path):
    a, _, _ = host_adapter(tmp_path);o=sample(True)
    BaseAdapter.reset(a, {k:o[k] for k in ("episode", "robot_id", "binding_epoch")})
    o["own"]["odom_xyyaw"] = None;o["own"]["odom_vxyw"] = None
    a._exchange=lambda *_a, **_kw:pytest.fail("Missing source odometry must not reach the peer")
    with pytest.raises(ContractError, match="odometry_unavailable"):a.act(o)


def test_legacy_ros_envelope_cannot_claim_unimplemented_v2_capability_ack(tmp_path):
    path, _ = manifest(tmp_path, transport="ros2_envelope_v1");registry=Registry()
    with pytest.raises(ContractError, match="capability_ack_transport"):register_aim_plugins(registry, path)
    assert registry.descriptors() == []


@pytest.mark.parametrize("caps,version,negotiation", [
    (CAPABILITIES,"1.0.0","declared_aim_contract"),
    (CAPABILITIES_V2,"2.0.0","exact_peer_capabilities_on_reset"),
])
def test_robotio_catalog_retains_explicit_version_and_negotiation(tmp_path,caps,version,negotiation):
    path,_=manifest(tmp_path,capabilities=caps)
    graph=tmp_path/"robotio.json"
    graph.write_text(json.dumps(dict(schema=GRAPH_SCHEMA,
        manifests=dict(navigation=None,decision=None,aim=path.name),pipelines=[])),encoding="utf-8")
    registry=Registry();register_robotio_plugins(registry,graph)
    catalog=registry.plugin_catalog();row=catalog[0]
    assert row["version"]==version and row["negotiation"]==negotiation and row["capabilities"]==caps
    row["capabilities"]["image_encodings"].clear()
    assert registry.plugin_catalog()[0]["capabilities"]["image_encodings"]==["rgb8","bgr8"]


def test_actual_harmless_v2_peer_reset_and_action_preserve_original_six(tmp_path):
    root=Path(__file__).resolve().parents[1];script=tmp_path/"reference_peer.py"
    script.write_text("import sys\nsys.path.insert(0,"+repr(str(root))+")\n"
        "from rm_match.integrations.aim_jsonl_peer import run_aim_plugin\n"
        "from rm_match.deployment.aim_plugin import CAPABILITIES_V2\n"
        "from rm_match.platform_v2.contracts import action_for\n"
        "def factory():\n"
        " def compute(bundle,o):\n"
        "  return action_for(o,'aim','gimbal_target',dict(frame='base_link',yaw_rad=.2,pitch_rad=.1,active=True,confidence=None,fire_permission=False))\n"
        " return compute\n"
        "raise SystemExit(run_aim_plugin(factory,capabilities=CAPABILITIES_V2))\n",encoding="utf-8")
    path,row=manifest(tmp_path,command=[sys.executable,"-u",str(script)])
    registry=Registry();register_aim_plugins(registry,path);a=registry.create(row["adapter_id"],{})
    o=sample(True)
    try:
        a.reset({k:o[k] for k in ("episode","robot_id","binding_epoch")})
        o["wall_deadline"]=time.perf_counter()+.15
        result=a.act(o)
        assert all(type(result[k]) is type(o[k]) and result[k]==o[k] for k in IDENTITY)
        assert result["command"]["yaw_rad"]==.2 and result["command"]["fire_permission"] is False
    finally:a.close()
    assert a.shutdown_status["clean"] and a.shutdown_status["ownership"]["reaped"]
