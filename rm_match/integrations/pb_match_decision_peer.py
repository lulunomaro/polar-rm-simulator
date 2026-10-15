"""Verify a local PB/BT4 decision build, then replace this owned peer with it.

There is no Python decision policy or second process here. The native runner
implements the existing decision JSONL protocol and owns its bounded tick log.
Prepare initializes the real tree without a tick; only original observations
authorize ticks. Foreign host deadlines remain opaque in Linux. This verifier
does not qualify a build, arbitrary code sandbox, match, or sensor provenance.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import math
import os
from pathlib import Path, PurePosixPath
import re
import sys

from ..deployment.decision_plugin import NAVIGATION_CAPABILITIES, validate_capabilities
from ..deployment.profile import read_json_snapshot
from ..platform_v2.contracts import ContractError, exact, identity

ROOT = Path(__file__).resolve().parents[2]
SPEC_SCHEMA = "polar.pb.match-decision-peer-spec.v1"
BUILD_SCHEMA = "polar.pb.match-decision-build.v1"
WAYPOINT_SCHEMA = "polar.pb.local-waypoints.v1"
UPSTREAM = dict(behavior_revision="d111b635d326775c6c19aa12500a0bbd6a27a588",
    btcpp_revision="2a8a226fbbd99f524f0796e0d8a3145773c61c06",
    ros2_revision="7d177dcfbd7dbb7f5e5cd79c4e5e3e744e389c56")
SOURCE_FILES = ("rm_match/integrations/pb_match_decision_peer.py",
    "rm_match/deployment/profile.py", "rm_match/deployment/decision_plugin.py",
    "rm_match/platform_v2/contracts.py", "rm_match/platform_v2/decision_contracts.py",
    "rm_match/platform_v2/navigation_feedback_contracts.py")
_SPEC_KEYS = ("schema", "run_uuid", "root_linux", "out_linux", "namespace", "domain_id",
    "native_ref", "xml_ref", "build_ref", "environment_ref", "source_sha256",
    "expected_generation", "waypoints", "capabilities")


def _hex(value, size=64):
    if type(value) is not str or re.fullmatch("[a-f0-9]{" + str(size) + "}", value) is None:
        raise ContractError("pb_match_peer_hash_or_run_identity")


def no_alias(value):
    if type(value) is not str and not isinstance(value, Path):
        raise ContractError("pb_match_peer_absolute_unaliased_path")
    path = Path(value)
    if (not path.is_absolute() or ".." in path.parts or path != path.resolve()
        or any(p.is_symlink() or bool(getattr(p.lstat(), "st_file_attributes", 0) & 0x400)
               for p in (path, *path.parents) if p.exists() or p.is_symlink())):
        raise ContractError("pb_match_peer_absolute_unaliased_path")
    return path


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checked_ref(ref, *, json_value=False, limit=16 * 1024 * 1024):
    exact(ref, ("path", "sha256"), "pb_match_peer_reference")
    _hex(ref["sha256"])
    path = no_alias(ref["path"])
    if not path.is_file():
        raise ContractError("pb_match_peer_reference_file")
    if json_value:
        value, digest = read_json_snapshot(path, limit)
    else:
        value, digest = path, sha(path)
    if digest != ref["sha256"]:
        raise ContractError("pb_match_peer_reference_changed")
    return value


def _environment(ref):
    value = checked_ref(ref, json_value=True)
    if type(value) is not dict or type(value.get("process_environment")) is not dict:
        raise ContractError("pb_match_peer_environment")
    settings = value["process_environment"]
    if len(settings) > 32:
        raise ContractError("pb_match_peer_environment")
    for key, item in settings.items():
        if (type(key) is not str or re.fullmatch("[A-Z][A-Z0-9_]{0,63}", key) is None
            or key in ("PYTHONPATH", "PYTHONHOME", "WSLENV")
            or re.search("CREDENTIAL|SECRET|TOKEN|PASSWORD", key)
            or type(item) is not str or len(item) > 8192 or "\0" in item):
            raise ContractError("pb_match_peer_environment")
    return copy.deepcopy(settings)


def _waypoints(value):
    exact(value, ("schema", "attack_offset_m", "supply_offset_m", "yaw_offset_rad"), "pb_match_waypoints")
    if type(value["schema"]) is not str or value["schema"] != WAYPOINT_SCHEMA:
        raise ContractError("pb_match_peer_waypoint_schema")
    for key in ("attack_offset_m", "supply_offset_m"):
        if (type(value[key]) is not list or len(value[key]) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 100000 for v in value[key])):
            raise ContractError("pb_match_peer_waypoint_geometry")
    yaw = value["yaw_offset_rad"]
    if type(yaw) not in (int, float) or not math.isfinite(yaw) or abs(yaw) > math.pi:
        raise ContractError("pb_match_peer_waypoint_geometry")


def _build(spec):
    build = checked_ref(spec["build_ref"], json_value=True)
    required = {"schema", "passed", "upstream", "source_manifest_sha256", "source_manifest_ref",
                "native", "xml", "btcpp", "commands", "source_unchanged", "runtime_environment"}
    if (type(build) is not dict or not required <= set(build)
        or type(build["schema"]) is not str or build["schema"] != BUILD_SCHEMA
        or build["passed"] is not True or build["source_unchanged"] is not True
        or type(build["upstream"]) is not dict or build["upstream"] != UPSTREAM
        or build["native"] != spec["native_ref"] or build["xml"] != spec["xml_ref"]):
        raise ContractError("pb_match_peer_build_identity")
    _hex(build["source_manifest_sha256"])
    exact(build["upstream"], UPSTREAM, "pb_match_upstream")
    if any(type(build["upstream"][k]) is not str for k in UPSTREAM):
        raise ContractError("pb_match_peer_build_identity")
    if (type(build["btcpp"]) is not dict or build["btcpp"].get("version") != "4.6.2"
        or type(build["btcpp"].get("prefix")) is not str
        or not build["btcpp"]["prefix"].startswith("/")
        or build["btcpp"]["prefix"].startswith("//")
        or "\\" in build["btcpp"]["prefix"]
        or ".." in PurePosixPath(build["btcpp"]["prefix"]).parts
        or str(PurePosixPath(build["btcpp"]["prefix"])) != build["btcpp"]["prefix"]
        or type(build["commands"]) is not list or not build["commands"]):
        raise ContractError("pb_match_peer_build_proof")
    for row in build["commands"]:
        if (type(row) is not dict or not {"argv", "exit_code", "reaped", "elapsed_s"} <= set(row)
            or type(row["exit_code"]) is not int or row["exit_code"] != 0 or row["reaped"] is not True
            or type(row["argv"]) is not list or not row["argv"]
            or any(type(item) is not str or not item or "\0" in item for item in row["argv"])
            or type(row["elapsed_s"]) not in (int, float) or not math.isfinite(row["elapsed_s"])
            or row["elapsed_s"] < 0):
            raise ContractError("pb_match_peer_failed_build_command")
    manifest = checked_ref(build["source_manifest_ref"], json_value=True)
    if (build["source_manifest_ref"]["sha256"] != build["source_manifest_sha256"]
        or type(manifest) is not dict or manifest.get("schema") != "polar.pb.match-decision-source.v1"
        or manifest.get("upstream") != UPSTREAM
        or manifest.get("overlay_xml_sha256") != spec["xml_ref"]["sha256"]):
        raise ContractError("pb_match_peer_source_manifest_identity")
    runtime_env = build["runtime_environment"]
    if (type(runtime_env) is not dict or any(type(k) is not str or type(v) is not str for k,v in runtime_env.items())
        or runtime_env != _environment(spec["environment_ref"])):
        raise ContractError("pb_match_peer_runtime_environment_identity")


def load_spec(path, expected_sha256):
    path = no_alias(path)
    _hex(expected_sha256)
    value, digest = read_json_snapshot(path, 4 * 1024 * 1024)
    if digest != expected_sha256:
        raise ContractError("pb_match_peer_spec_changed")
    exact(value, _SPEC_KEYS, "pb_match_peer_spec")
    if type(value["schema"]) is not str or value["schema"] != SPEC_SCHEMA:
        raise ContractError("pb_match_peer_spec_schema")
    _hex(value["run_uuid"], 32)
    if no_alias(value["root_linux"]) != ROOT:
        raise ContractError("pb_match_peer_repository")
    context = value["expected_generation"]
    exact(context, ("robot_id", "episode", "binding_epoch"), "pb_match_peer_generation")
    identity(dict(context, observed_seq=0, sim_time=0., wall_deadline=0.))
    if (type(value["namespace"]) is not str
        or value["namespace"] != "/polar_match_" + value["run_uuid"] + "/" + context["robot_id"]
        or type(value["domain_id"]) is not int or value["domain_id"] != 84):
        raise ContractError("pb_match_peer_namespace")
    out = no_alias(value["out_linux"])
    if out == ROOT / "artifacts" or not out.is_relative_to(ROOT / "artifacts") or out.exists():
        raise ContractError("pb_match_peer_fresh_output_required")
    if not path.is_relative_to(ROOT / "artifacts"):
        raise ContractError("pb_match_peer_spec_scope")
    capabilities = validate_capabilities(value["capabilities"])
    if capabilities != NAVIGATION_CAPABILITIES:
        raise ContractError("pb_match_peer_capabilities_v2_required")
    _waypoints(value["waypoints"])
    sources = value["source_sha256"]
    if type(sources) is not dict or not set(SOURCE_FILES) <= set(sources) or len(sources) > 256:
        raise ContractError("pb_match_peer_source_roster")
    for name, digest in sources.items():
        _hex(digest)
        if type(name) is not str or name.startswith("/") or ".." in Path(name).parts or "\\" in name:
            raise ContractError("pb_match_peer_source_scope")
        selected = no_alias(ROOT / name)
        if not selected.is_relative_to(ROOT) or not selected.is_file() or sha(selected) != digest:
            raise ContractError("pb_match_peer_source_changed")
    native = checked_ref(value["native_ref"])
    with native.open("rb") as stream:
        header = stream.read(20)
    if (len(header) != 20 or header[:6] != b"\x7fELF\x02\x01"
        or int.from_bytes(header[18:20], "little") != 62 or not os.access(native, os.X_OK)):
        raise ContractError("pb_match_peer_native_elf64_required")
    xml = checked_ref(value["xml_ref"])
    if xml.stat().st_size > 1024 * 1024:
        raise ContractError("pb_match_peer_tree_oversized")
    _build(value)
    _environment(value["environment_ref"])
    return value, out


def _linux_host():
    return sys.platform == "linux"


def execute(path, expected_sha256):
    if not _linux_host():
        raise ContractError("pb_match_peer_linux_only")
    spec, out = load_spec(path, expected_sha256)
    env = {k:v for k,v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "WSLENV")
           and re.search("CREDENTIAL|SECRET|TOKEN|PASSWORD", k, re.I) is None}
    env.update(_environment(spec["environment_ref"]))
    # Recheck all pinned raw inputs at the final ownership handover boundary.
    # Native also loads this exact spec and verifies its own input references.
    spec, out = load_spec(path, expected_sha256)
    out.mkdir(parents=True, exist_ok=False)
    native = str(spec["native_ref"]["path"])
    os.chdir(ROOT)
    os.execve(native, [native, "--spec", str(path), "--sha256", expected_sha256], env)
    raise RuntimeError("pb_match_peer_exec_returned")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args(argv)
    execute(args.spec, args.sha256)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
