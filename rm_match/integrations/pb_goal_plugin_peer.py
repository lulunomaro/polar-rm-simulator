"""Source-pinned production PB resource peer for generic staged navigation.

Launch only through the owned local JSONL supervisor. Resource preparation
configures the original stack; no scan, goal or dummy input is sent at prepare.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import threading
import time

from ..platform_v2.contracts import ContractError, IDENTITY, exact, identity
from .pb_goal_controller_source import _same_tree
from .ros2_bridge import JSONL_SCHEMA, MAX_RESPONSE, parse_json

ROOT = Path(__file__).resolve().parents[2]
SPEC_SCHEMA = "polar.pb.goal-plugin-peer-spec.v1"
SOURCE_FILES = (
    "rm_match/integrations/pb_goal_plugin_peer.py", "rm_match/integrations/pb_goal_plugin_source.py",
    "rm_match/integrations/pb_goal_controller_source.py", "rm_match/integrations/pb_navigation_bridge.py",
    "rm_match/integrations/pb_navigation_transport.py", "rm_match/integrations/pb_wsl_navigation_worker.py",
    "rm_match/integrations/pb_navigation_phases.py", "rm_match/integrations/goal_navigation_compute.py",
    "rm_match/integrations/navigation_goal_lifecycle.py", "rm_match/integrations/nav2_goal_backend.py",
    "rm_match/integrations/navigation_jsonl_peer.py", "rm_match/integrations/ros2_bridge.py",
    "rm_match/platform_v2/navigation_feedback_contracts.py", "rm_match/platform_v2/goal_navigation_contracts.py",
    "rm_match/platform_v2/navigation_contracts.py", "rm_match/platform_v2/decision_contracts.py",
    "rm_match/platform_v2/contracts.py", "rm_match/deployment/navigation_plugin.py",
    "rm_match/deployment/robotio_plugin.py", "rm_match/deployment/decision_plugin.py",
    "rm_match/integrations/decision_jsonl_peer.py", "rm_match/deployment/json_adapter.py",
    "rm_match/deployment/json_owned_process.py", "rm_match/deployment/wsl_jsonl.py",
    "rm_match/deployment/wsl_jsonl_worker.py", "rm_match/deployment/wsl_jsonl_owned_tree.py",
    "rm_match/integrations/owned_linux_group.py", "rm_match/deployment/profile.py", "rm_match/integrations/pb_request_context.hpp",
    "rm_match/integrations/pb_goal_controller_context.hpp", "tools/pb_navigation_stack.py", "rm_match/harness.xml",
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def no_alias(path):
    if type(path) not in (str, Path) and not isinstance(path, Path):
        raise ContractError("pb_goal_peer_absolute_unaliased_path")
    path = Path(path)
    if (not path.is_absolute() or ".." in path.parts or path != path.resolve()
        or any(p.is_symlink() for p in (path, *path.parents))):
        raise ContractError("pb_goal_peer_absolute_unaliased_path")
    return path


def checked_ref(ref):
    from ..deployment.profile import read_json_snapshot
    exact(ref, ("path", "sha256"), "pb_goal_peer_reference")
    if type(ref["sha256"]) is not str or not re.fullmatch("[a-f0-9]{64}", ref["sha256"]):
        raise ContractError("pb_goal_peer_reference_hash")
    path = no_alias(ref["path"])
    if not path.is_file():
        raise ContractError("pb_goal_peer_reference_file")
    value, digest = read_json_snapshot(path, 16 * 1024 * 1024)
    if digest != ref["sha256"]:
        raise ContractError("pb_goal_peer_reference_changed")
    return value


def load_spec(path, expected_sha256):
    from ..deployment.profile import read_json_snapshot
    from tools.pb_navigation_stack import namespace_checked, controller_result_settings
    path = no_alias(path)
    value, digest = read_json_snapshot(path)
    if type(expected_sha256) is not str or digest != expected_sha256:
        raise ContractError("pb_goal_peer_spec_changed")
    exact(value, ("schema", "run_uuid", "namespace", "domain_id", "root_linux", "out_linux",
        "config_ref", "environment_ref", "source_sha256", "expected_generation", "diagnostics"), "pb_goal_peer_spec")
    if type(value["schema"]) is not str or value["schema"] != SPEC_SCHEMA:
        raise ContractError("pb_goal_peer_spec_schema")
    if type(value["run_uuid"]) is not str or not re.fullmatch("[a-f0-9]{32}", value["run_uuid"]):
        raise ContractError("pb_goal_peer_run_identity")
    if type(value["domain_id"]) is not int or value["domain_id"] != 84 or type(value["diagnostics"]) is not bool:
        raise ContractError("pb_goal_peer_scope")
    context = value["expected_generation"]
    exact(context, ("robot_id", "episode", "binding_epoch"), "pb_goal_peer_generation")
    identity(dict(context, observed_seq=0, sim_time=0., wall_deadline=0.))
    if namespace_checked(value["namespace"]) != "/polar_sil_" + value["run_uuid"] + "/" + context["robot_id"]:
        raise ContractError("pb_goal_peer_namespace_identity")
    if no_alias(value["root_linux"]) != ROOT:
        raise ContractError("pb_goal_peer_repository")
    out = no_alias(value["out_linux"])
    if (out.exists() or not out.is_relative_to(ROOT / "artifacts") or out.parent != path.parent
        or out.name != "peer-evidence"):
        raise ContractError("pb_goal_peer_owned_output")
    sources = value["source_sha256"]
    exact(sources, SOURCE_FILES, "pb_goal_peer_sources")
    for name, digest in sources.items():
        if type(digest) is not str or not re.fullmatch("[a-f0-9]{64}", digest) or sha(no_alias(ROOT / name)) != digest:
            raise ContractError("pb_goal_peer_source_changed:" + name)
    config = checked_ref(value["config_ref"])
    checked_ref(value["environment_ref"])
    if (config.get("schema") != "polar.pb-stack-config.v2"
        or controller_result_settings(config)["result_profile"] != "follow_path_uuid_v2"
        or config.get("environment") != value["environment_ref"]):
        raise ContractError("pb_goal_peer_build_bound_v2_required")
    return value, out


def bootstrap(spec, argv):
    environment = checked_ref(spec["environment_ref"])
    python, settings = environment["venv_python"], environment["process_environment"]
    # Standard venv interpreters are symlinks. The pinned ENV selects this
    # executable explicitly; retain its venv path for exec/prefix discovery.
    # Source/spec/config/output paths still use the stricter no_alias rule.
    if (type(python) is not str or not Path(python).is_absolute() or ".." in Path(python).parts
        or not Path(python).is_file() or not os.access(python, os.X_OK) or type(settings) is not dict
        or any(type(k) is not str or type(v) is not str for k, v in settings.items())
        or any(k in settings for k in ("PYTHONPATH", "PYTHONHOME"))):
        raise ContractError("pb_goal_peer_verified_environment")
    marker = spec["run_uuid"] + ":" + spec["environment_ref"]["sha256"]
    if (Path(sys.executable).absolute() != Path(python).absolute()
        or os.environ.get("POLAR_PB_GOAL_PEER_ENV") != marker
        or any(os.environ.get(k) != v for k, v in settings.items())
        or any(k in os.environ for k in ("PYTHONPATH", "PYTHONHOME"))):
        env = dict(os.environ, **settings)
        env.pop("PYTHONPATH", None);env.pop("PYTHONHOME", None)
        env["POLAR_PB_GOAL_PEER_ENV"] = marker
        os.execve(python, [python, "-u", "-m", "rm_match.integrations.pb_goal_plugin_peer", *argv], env)
    if sys.version_info[:2] != (3, 10):
        raise ContractError("pb_goal_peer_python310_required")


class PeerGuard:
    def __init__(self):
        self.stop = threading.Event()

    def check(self):
        if self.stop.is_set():
            raise InterruptedError("pb_goal_peer_stop_requested")


class PBGoalPluginPeer:
    """One binding, one owned transport/executor and original PB stack."""
    def __init__(self, spec, out, *, clock=time.perf_counter):
        self.spec, self.out, self.clock = copy.deepcopy(spec), Path(out), clock
        self.stack = self.transport = self.source = self.gate = self.backend = None
        self.lifecycle = self.compute = self.raw_spin = None
        self.guard = PeerGuard();self.context = None
        self.closing = self.closed = False;self.cleanup = None
        self.native_rows = [];self.feedback_rows = [];self.stage_rows = [];self.result_rows = []
        self.rejected_result_rows = []
        self.emit_gate_rows = [];self._emit_pending = None
        self.rejected_localizations = 0

    @staticmethod
    def _append(rows, value):
        if len(rows) >= 8192:
            raise RuntimeError("pb_goal_peer_evidence_capacity")
        rows.append(copy.deepcopy(value))

    def record_native(self, row):
        self._append(self.native_rows, row)

    def record_stage(self, row):
        self._append(self.stage_rows, row)

    def spin(self, timeout):
        if not self.closing:
            self.guard.check();self.stack.poll_health()
        self.raw_spin(timeout)
        if self.gate is not None and not self.closing:
            self.gate.poll(self.source)

    def reset(self, context):
        if self.context is not None or self.closed:
            raise ContractError("pb_goal_peer_reset_once")
        exact(context, ("robot_id", "episode", "binding_epoch"), "pb_goal_peer_reset")
        if any(type(context[k]) is not type(v) or context[k] != v for k, v in self.spec["expected_generation"].items()):
            raise ContractError("pb_goal_peer_reset_generation")
        end = self.clock() + 2.
        self.source.reset(context, {})
        self.transport.wait_ready(min(1., max(0., end - self.clock())))
        self.compute.reset(context)
        if self.clock() >= end:
            raise TimeoutError("pb_goal_peer_reset_deadline")
        self.context = copy.deepcopy(context)

    def observe(self, observation):
        if self.context is None or self.closed:
            raise ContractError("pb_goal_peer_reset_required")
        self._emit_pending = None
        value = self.source.observe(observation, self.transport)
        self._append(self.feedback_rows, value)
        return value

    def __call__(self, observation, intent):
        if self.context is None or self.closed:
            raise ContractError("pb_goal_peer_reset_required")
        self._emit_pending = None
        original_deadline = self.source._deadline
        result = self.compute(observation, intent)
        self._append(self.result_rows, result)
        if "action" in result:
            cloud = observation["sensors"]["pointcloud"]
            pending = dict(source={k:copy.deepcopy(observation[k]) for k in IDENTITY},
                scan=dict(cloud_frame_id=cloud["frame_id"], acquisition_start_ns=cloud["acquisition_start_ns"],
                    acquisition_end_ns=cloud["acquisition_end_ns"], profile_sha256=cloud["profile_sha256"]),
                local_deadline=original_deadline, result=copy.deepcopy(result))
            returned_at = self.clock()
            if returned_at >= original_deadline:
                # History has already accepted this one immutable receipt.
                # Reject delivery instead of replacing it with another same-seq
                # status or allowing later compute/journal work to renew time.
                self.result_rows.pop()
                self._append(self.rejected_result_rows, dict(reason="original_stage_deadline_expired",
                    original_deadline=original_deadline, rejected_wall=returned_at, result=result))
                raise ContractError("pb_goal_peer_original_stage_expired")
            self._emit_pending = pending
        return result

    def before_emit(self, response, encoded):
        """Final 50 ms gate after encoding, immediately before JSONL write.

        This proves a delivery candidate at this boundary, not completed I/O;
        the host still enforces its unchanged 150 ms deadline independently.
        """
        if type(response) is not dict or response.get("op") != "act":
            return
        result = response.get("result")
        if type(result) is not dict or "action" not in result:
            self._emit_pending = None
            return
        pending = self._emit_pending;self._emit_pending = None
        exact(response, ("schema", "op", "ok", "result"), "pb_goal_peer_emit_response")
        if (type(response["schema"]) is not str or response["schema"] != JSONL_SCHEMA
            or type(response["op"]) is not str or response["op"] != "act" or response["ok"] is not True
            or pending is None or not _same_tree(result, pending["result"])
            or not _same_tree(result.get("source"), pending["source"])):
            raise ContractError("pb_goal_peer_emit_source_or_result_changed")
        if type(encoded) is not bytes or not _same_tree(parse_json(encoded, MAX_RESPONSE), response):
            raise ContractError("pb_goal_peer_emit_encoding_changed")
        row = dict(source=pending["source"], scan=pending["scan"], local_deadline=pending["local_deadline"],
            gate_wall=self.clock(), clock="linux_local_perf_counter", result=result,
            encoded_sha256=hashlib.sha256(encoded).hexdigest())
        self._append(self.emit_gate_rows, row)
        gate_wall = self.clock()
        if gate_wall >= pending["local_deadline"]:
            self.emit_gate_rows.pop()
            self._append(self.rejected_result_rows, dict(reason="encoded_stage_deadline_expired",
                original_deadline=pending["local_deadline"], rejected_wall=gate_wall,
                encoded_sha256=row["encoded_sha256"], result=result))
            raise ContractError("pb_goal_peer_original_stage_expired")
        self.emit_gate_rows[-1]["gate_wall"] = gate_wall

    def _save(self, name, value):
        raw = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()
        with (self.out / name).open("xb") as stream:
            stream.write(raw)

    def close(self, *, deadline=None):
        if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
            raise ContractError("pb_goal_peer_cleanup_deadline")
        if self.closed:
            if self.cleanup is None or not self.cleanup["clean"]:
                raise ContractError("pb_goal_peer_cleanup_unproved")
            return copy.deepcopy(self.cleanup)
        self.closed = True;self.closing = True;self.guard.stop.set()
        start = self.clock();end = min(start + 1.3, deadline) if deadline is not None else start + 1.3
        errors = [];goal_clean = self.lifecycle is None
        stack_cleanup = None;gate_clean = self.gate is None;transport_clean = self.transport is None
        if self.source is not None:
            try:self.source.discard_stage("closed")
            except BaseException:errors.append("stage_close_failed")
        if self.lifecycle is not None:
            try:
                snapshot = self.lifecycle.request_stop()
                # Before reset no goal can have been submitted. Do not fabricate
                # a reset/scan merely to prove this empty original lifecycle.
                if self.context is not None:
                    while self.clock() < end:
                        self.spin(min(.002, max(0., end - self.clock())))
                        snapshot = self.lifecycle.poll()
                        if snapshot["clean"] or snapshot["fault"]:
                            break
                goal_clean = snapshot["clean"] is True and snapshot["fault"] is None
                if not goal_clean:errors.append("goal_stop_unproved")
                elif self.backend is not None:self.backend.destroy()
            except BaseException:errors.append("goal_close_failed");goal_clean = False
        if self.gate is not None:
            try:gate_clean = self.gate.close(deadline=end)
            except BaseException:gate_clean = False
            if not gate_clean:errors.append("gate_close_unproved")
        if self.transport is not None:
            try:self.transport.close(deadline=end);transport_clean = True
            except BaseException:errors.append("transport_close_unproved")
        if self.stack is not None:
            try:
                stack_cleanup = self.stack.stop(grace_s=min(.15, max(0., end - self.clock())), deadline=end)
                if stack_cleanup.get("clean") is not True:errors.append("stack_close_unproved")
            except BaseException:errors.append("stack_close_failed")
        if self.source is not None:
            try:self.source.close()
            except BaseException:errors.append("source_close_failed")
        try:unchanged = all(sha(ROOT / name) == digest for name, digest in self.spec["source_sha256"].items())
        except (OSError, ValueError):unchanged = False
        if not unchanged:errors.append("peer_source_changed")
        elapsed = self.clock() - start
        if self.clock() > end:errors.append("peer_cleanup_deadline_exceeded")
        snapshot = None if self.lifecycle is None else self.lifecycle.snapshot()
        self.cleanup = dict(schema="polar.pb.goal-plugin-peer-cleanup.v1", run_uuid=self.spec["run_uuid"],
            clean=not errors and goal_clean and gate_clean and transport_clean, errors=errors,
            goal_stop_confirmed=goal_clean, gate_clean=gate_clean, transport_clean=transport_clean,
            stack=stack_cleanup, elapsed_s=elapsed, source_unchanged=unchanged,
            config_sha256=self.spec["config_ref"]["sha256"], environment_sha256=self.spec["environment_ref"]["sha256"])
        for name, rows in (("ROS_SOURCE.jsonl", self.native_rows), ("FEEDBACK.jsonl", self.feedback_rows),
            ("STAGES.jsonl", self.stage_rows), ("ACT_RESULTS.jsonl", self.result_rows),
            ("REJECTED_RESULTS.jsonl", self.rejected_result_rows), ("EMIT_GATES.jsonl", self.emit_gate_rows)):
            with (self.out / name).open("xb") as stream:
                for row in rows:stream.write(json.dumps(row, allow_nan=False, separators=(",", ":")).encode() + b"\n")
        self._save("GOAL_REPORT.json", dict(lifecycle=snapshot,
            sensor_published=any(row["topic_kind"] == "request" for row in self.native_rows),
            feedback_count=len(self.feedback_rows), result_count=len(self.result_rows),
            rejected_localizations=self.rejected_localizations,
            scope="registered staged PB estimated feedback and original source-bound goal results"))
        self._save("CLEANUP.json", self.cleanup)
        if not self.cleanup["clean"]:
            raise ContractError("pb_goal_peer_cleanup_unproved")
        return copy.deepcopy(self.cleanup)


def create_peer(spec, out):
    """Initialize real resources. This function supplies no sensor or goal."""
    from tools.pb_navigation_stack import PBNavigationStack, controller_result_settings
    from .pb_navigation_bridge import NavigationSettings
    from .pb_navigation_transport import HumbleNavigationTransport
    from .pb_wsl_navigation_worker import NavigationGate
    from .pb_goal_plugin_source import PBGoalPluginSource
    from .nav2_goal_backend import Nav2GoalBackend, Nav2GoalSettings
    from .navigation_goal_lifecycle import NavigationGoalLifecycle
    from .goal_navigation_compute import GoalNavigationCompute
    peer = PBGoalPluginPeer(spec, out)
    class Gate(NavigationGate):
        def close(self, *, deadline):
            self.transport.executor.remove_node(self.node)
            self.listener.unregister();self.node.destroy_node()
            if self.thread is not None:self.thread.join(min(.1, max(0., deadline - peer.clock())))
            return self.thread is None or not self.thread.is_alive()
    try:
        config = checked_ref(spec["config_ref"])
        peer.stack = PBNavigationStack(config, Path(out) / "stack", namespace=spec["namespace"],
            environment=spec["environment_ref"], diagnostics=spec["diagnostics"])
        original_health = peer.stack.poll_health
        def health(generation=None):
            peer.guard.check();return original_health(generation)
        peer.stack.poll_health = health
        ready = peer.stack.start()
        if any(type(peer.stack.generation[k]) is not type(v) or peer.stack.generation[k] != v
               for k, v in spec["expected_generation"].items()):
            raise ContractError("pb_goal_peer_stack_generation")
        cfg = controller_result_settings(config);topics = ready["topics"]
        settings = NavigationSettings(node_name="polar_goal_peer_" + spec["run_uuid"][:16], domain_id=84,
            cloud_topic=topics["cloud"], pointcloud_topic=topics["cloud"] + "/pointcloud", imu_topic=topics["imu"],
            request_topic=topics["request"], result_topic=topics["result"], odom_topic=topics["odom"],
            clock_topic=topics["clock"], tf_static_topic=topics["tf_static"], response_timeout=.05,
            expected_robot_id=spec["expected_generation"]["robot_id"], expected_episode=spec["expected_generation"]["episode"],
            expected_binding_epoch=spec["expected_generation"]["binding_epoch"], **cfg)
        def lookup(stamp):
            from rclpy.time import Time
            from tf2_ros import TransformException
            try:value = peer.gate.buffer.lookup_transform("map", "base_link", Time(nanoseconds=stamp))
            except TransformException:return None
            return dict(header=dict(stamp=dict(sec=value.header.stamp.sec, nanosec=value.header.stamp.nanosec),
                frame_id=value.header.frame_id), child_frame_id=value.child_frame_id,
                transform=dict(translation={k: getattr(value.transform.translation, k) for k in "xyz"},
                    rotation={k: getattr(value.transform.rotation, k) for k in "xyzw"}))
        peer.source = PBGoalPluginSource(settings, lookup_estimate=lookup,
            provenance=dict(producer_source_sha256=spec["source_sha256"]["rm_match/integrations/pb_goal_plugin_source.py"],
                localization_binary_sha256=config["assets"]["point_lio"]["sha256"],
                mapping_binary_sha256=config["assets"]["slam_toolbox"]["sha256"]),
            navigation_ready=lambda: peer.stack.state == "ACTIVE" and peer.backend.ready(),
            goal_snapshot=lambda: peer.lifecycle.poll(), record=peer.record_native, record_stage=peer.record_stage)
        peer.transport = HumbleNavigationTransport(settings, peer.source)
        peer.raw_spin = peer.transport.spin_once;peer.transport.spin_once = peer.spin
        peer.gate = Gate(peer.transport, peer.stack, peer.guard)
        from std_msgs.msg import String
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
        def localization(message):
            try:peer.source.receive_localization(message.data)
            except ValueError:peer.rejected_localizations += 1
        peer.localization_subscription = peer.transport.node.create_subscription(String, topics["localization"], localization,
            QoSProfile(depth=8, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.VOLATILE))
        peer.backend = Nav2GoalBackend(peer.transport.node, Nav2GoalSettings("compute_path_then_follow",
            planner_action=spec["namespace"] + "/compute_path_to_pose", controller_action=spec["namespace"] + "/follow_path",
            planner_id="GridBased", controller_id="FollowPath", goal_checker_id="general_goal_checker"))
        peer.lifecycle = NavigationGoalLifecycle(peer.backend, deadline_mode="opaque", history_capacity=256)
        peer.compute = GoalNavigationCompute(peer.lifecycle,
            lambda o, i: peer.source.consume_sourced(o, peer.transport), poll_hook=lambda: peer.spin(0.))
        peer._save("READY.json", dict(schema="polar.pb.goal-plugin-peer-ready.v1", run_uuid=spec["run_uuid"],
            namespace=spec["namespace"], domain_id=84, expected_generation=spec["expected_generation"],
            config_sha256=spec["config_ref"]["sha256"], environment_sha256=spec["environment_ref"]["sha256"],
            source_sha256=spec["source_sha256"], state="CONFIGURED", sensor_published=False, goal_sent=False))
        return peer
    except BaseException:
        try:peer.close()
        except BaseException:pass
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True);parser.add_argument("--sha256", required=True)
    args = parser.parse_args(argv)
    if sys.platform != "linux":raise ContractError("pb_goal_peer_requires_linux")
    spec, out = load_spec(args.spec, args.sha256)
    bootstrap(spec, sys.argv[1:] if argv is None else argv)
    if out.exists():raise ContractError("pb_goal_peer_owned_output_reused")
    out.mkdir()
    from .navigation_jsonl_peer import run_navigation_plugin
    holder = {}
    def factory():
        peer = create_peer(spec, out);holder["peer"] = peer;return peer
    old = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    def stop(*_):
        peer = holder.get("peer")
        if peer is not None:peer.guard.stop.set()
        raise KeyboardInterrupt
    for sig in old:signal.signal(sig, stop)
    try:
        return run_navigation_plugin(factory, goal_input_modes=["decision_intent_v1"], goal_result_profile="staged_scan_v1")
    finally:
        for sig, value in old.items():signal.signal(sig, value)


if __name__ == "__main__":
    raise SystemExit(main())
