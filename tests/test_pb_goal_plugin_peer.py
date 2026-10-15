"""Production peer boundaries using controlled resources, never real ROS."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rm_match.integrations import pb_goal_plugin_peer as module
from rm_match.integrations.navigation_goal_lifecycle import NavigationGoalLifecycle
from rm_match.integrations.goal_navigation_compute import GoalNavigationCompute
from rm_match.integrations.ros2_bridge import JSONL_SCHEMA, MAX_RESPONSE, encode_json
from rm_match.platform_v2.contracts import ContractError
from test_goal_navigation_compute import Backend, action, intent
from test_pb_goal_plugin_source import Clock, CONTEXT, observation


def write(path, value):
    path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
    return dict(path=str(path), sha256=module.sha(path))


@pytest.fixture
def pinned_spec(tmp_path, monkeypatch):
    root = tmp_path / "repo";root.mkdir()
    prep = root / "artifacts" / "prep";prep.mkdir(parents=True)
    (root / "fixture_source.py").write_text("# source fixture\n", encoding="utf-8")
    environment = write(prep / "environment.json", dict(venv_python="unused", process_environment={}))
    config = write(prep / "config.json", dict(schema="polar.pb-stack-config.v2", environment=environment))
    spec = dict(schema=module.SPEC_SCHEMA, run_uuid="a" * 32,
        namespace="/polar_sil_" + "a" * 32 + "/red_sentry", domain_id=84,
        root_linux=str(root), out_linux=str(prep / "peer-evidence"), config_ref=config,
        environment_ref=environment, source_sha256={"fixture_source.py": module.sha(root / "fixture_source.py")},
        expected_generation=copy.deepcopy(CONTEXT), diagnostics=True)
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "SOURCE_FILES", ("fixture_source.py",))
    # Only the spec boundary is under test; real build proof checking remains
    # in the original stack and its independently tested profile validator.
    monkeypatch.setattr("tools.pb_navigation_stack.controller_result_settings",
        lambda _: dict(result_profile="follow_path_uuid_v2"))
    path = prep / "PEER_SPEC.json";write(path, spec)
    return root, path, spec


def test_load_spec_is_read_only_and_returns_fresh_exact_owned_scope(pinned_spec):
    _, path, spec = pinned_spec
    actual, out = module.load_spec(path, module.sha(path))
    assert actual == spec and out == Path(spec["out_linux"]) and not out.exists()


@pytest.mark.parametrize("change", [
    lambda s: s.update(domain_id=True), lambda s: s.update(diagnostics=1),
    lambda s: s["expected_generation"].update(episode=False),
    lambda s: s["expected_generation"].update(binding_epoch=1.),
    lambda s: s.update(namespace=s["namespace"] + "/other"),
    lambda s: s.update(out_linux=str(Path(s["out_linux"]).parent / "other")),
    lambda s: s.update(unreviewed_command=["curl", "https://invalid"]),
])
def test_malformed_spec_never_creates_resources_or_output(pinned_spec, change):
    _, path, spec = pinned_spec;change(spec);write(path, spec)
    with pytest.raises((ContractError, ValueError)):
        module.load_spec(path, module.sha(path))
    assert not Path(spec["out_linux"]).exists()


@pytest.mark.parametrize("target", ["spec", "source", "environment", "config", "out"])
def test_changed_pinned_files_and_reused_output_fail_before_resources(pinned_spec, target):
    root, path, spec = pinned_spec;before = module.sha(path)
    if target == "spec":path.write_text(path.read_text() + " ", encoding="utf-8")
    elif target == "source":(root / "fixture_source.py").write_text("# changed\n", encoding="utf-8")
    elif target == "out":Path(spec["out_linux"]).mkdir()
    else:Path(spec[target + "_ref"]["path"]).write_text("{}", encoding="utf-8")
    with pytest.raises(ContractError):module.load_spec(path, before)


def resource_peer(pinned_spec):
    _, _, spec = pinned_spec;out = Path(spec["out_linux"]);out.mkdir()
    clock = Clock();peer = module.PBGoalPluginPeer(spec, out, clock=clock)
    calls = []
    class Source:
        def reset(self, context, config):calls.append(("source_reset", copy.deepcopy(context), config))
        def discard_stage(self, reason):calls.append(("discard", reason))
        def close(self):calls.append(("source_close",))
    class Transport:
        def wait_ready(self, timeout):calls.append(("wait_ready", timeout))
        def close(self, *, deadline):calls.append(("transport_close", deadline))
    class Gate:
        def close(self, *, deadline):calls.append(("gate_close", deadline));return True
    class Stack:
        def poll_health(self):calls.append(("health",))
        def stop(self, grace_s, *, deadline):
            calls.append(("stack_close", grace_s, deadline));return dict(clean=clock() < deadline)
    backend = Backend(cancel_settles=True)
    backend.destroy = lambda: calls.append(("backend_destroy",))
    peer.source, peer.transport, peer.gate, peer.stack = Source(), Transport(), Gate(), Stack()
    peer.backend = backend
    peer.lifecycle = NavigationGoalLifecycle(backend, clock=clock, deadline_mode="opaque")
    peer.compute = SimpleNamespace(reset=peer.lifecycle.reset)
    peer.raw_spin = lambda timeout: setattr(clock, "now", clock() + max(.001, timeout))
    return peer, clock, calls


def test_reset_checks_generation_once_and_supplies_no_sensor_or_goal(pinned_spec):
    peer, _, calls = resource_peer(pinned_spec)
    peer.reset(CONTEXT)
    assert peer.context == CONTEXT and peer.lifecycle.records == [] and peer.native_rows == []
    assert calls == [("source_reset", CONTEXT, {}), ("wait_ready", 1.)]
    with pytest.raises(ContractError, match="reset_once"):peer.reset(CONTEXT)
    assert peer.close()["clean"]


@pytest.mark.parametrize("change", [dict(episode=False), dict(binding_epoch=1.), dict(robot_id="blue_sentry")])
def test_reset_typed_generation_mismatch_does_not_touch_resources(pinned_spec, change):
    peer, _, calls = resource_peer(pinned_spec)
    with pytest.raises(ContractError, match="generation"):peer.reset(dict(CONTEXT, **change))
    assert calls == [] and peer.context is None and peer.lifecycle.records == []


def test_reset_deadline_has_no_dummy_observation_or_renewal(pinned_spec):
    peer, clock, calls = resource_peer(pinned_spec)
    def slow_graph(timeout):
        calls.append(("wait_ready", timeout));clock.now += 2.01
    peer.transport.wait_ready = slow_graph
    with pytest.raises(TimeoutError, match="reset_deadline"):peer.reset(CONTEXT)
    assert peer.context is None and not peer.lifecycle.records and not peer.native_rows
    assert peer.close()["clean"]


def test_close_before_reset_is_empty_proof_and_does_not_warm_or_fabricate_reset(pinned_spec):
    peer, _, calls = resource_peer(pinned_spec)
    result = peer.close()
    assert result["clean"] and result["goal_stop_confirmed"] and peer.lifecycle.context is None
    report = json.loads((peer.out / "GOAL_REPORT.json").read_text())
    assert report["lifecycle"]["goals"] == [] and report["sensor_published"] is False
    assert not any(c[0] in ("source_reset", "wait_ready", "health") for c in calls)
    assert peer.close() == result


def test_close_uses_one_earlier_deadline_for_real_terminal_and_all_resources(pinned_spec):
    peer, clock, calls = resource_peer(pinned_spec);peer.reset(CONTEXT)
    peer.lifecycle.submit(intent(observation()))
    assert peer.lifecycle.current is not None
    end = clock() + .8
    result = peer.close(deadline=end)
    assert result["clean"] and peer.lifecycle.snapshot()["goals"][0]["state"] == "canceled"
    assert peer.lifecycle.snapshot()["goals"][0]["stop_confirmed"] is True
    assert [c[1] for c in calls if c[0] in ("gate_close", "transport_close")] == [end, end]
    stack = next(c for c in calls if c[0] == "stack_close")
    assert stack[2] == end and stack[1] <= .15


def test_cancel_ack_without_terminal_never_clean_and_does_not_restart_cleanup_budget(pinned_spec):
    peer, clock, calls = resource_peer(pinned_spec);peer.backend.cancel_settles = False
    peer.reset(CONTEXT);peer.lifecycle.submit(intent(observation()))
    original_poll = peer.backend.poll
    def ack_only(op):
        value = original_poll(op)
        if op["canceled"]:value.update(state="canceling", cancel_acknowledged=True)
        return value
    peer.backend.poll = ack_only
    start = clock();end = start + .08
    with pytest.raises(ContractError, match="cleanup_unproved"):peer.close(deadline=end)
    assert peer.cleanup["goal_stop_confirmed"] is False and not peer.cleanup["clean"]
    assert not any(c[0] == "backend_destroy" for c in calls)
    assert next(c for c in calls if c[0] == "stack_close")[2] == end
    count = len(calls)
    with pytest.raises(ContractError, match="cleanup_unproved"):peer.close(deadline=clock() + 1.3)
    assert len(calls) == count


def test_source_removed_during_run_is_recorded_unclean_not_missing_cleanup(pinned_spec):
    root, _, _ = pinned_spec;peer, _, _ = resource_peer(pinned_spec)
    (root / "fixture_source.py").unlink()
    with pytest.raises(ContractError, match="cleanup_unproved"):peer.close()
    assert peer.cleanup["source_unchanged"] is False
    assert json.loads((peer.out / "CLEANUP.json").read_text())["errors"] == ["peer_source_changed"]


@pytest.mark.parametrize("deadline", [True, float("nan"), float("inf"), "tomorrow"])
def test_invalid_cleanup_deadline_does_not_begin_close(pinned_spec, deadline):
    peer, _, calls = resource_peer(pinned_spec)
    with pytest.raises(ContractError, match="cleanup_deadline"):peer.close(deadline=deadline)
    assert not peer.closed and not calls


def test_bootstrap_preserves_pinned_venv_symlink_and_checks_reexecuted_python310(monkeypatch):
    # Model the ordinary Linux venv/bin/python -> /usr/bin/python3.10 link.
    # A real link needs Windows privilege; only interpreter path metadata is
    # injected, while bootstrap's ENV, exec argv and ABI checks execute.
    python = "/fixture/venv/bin/python"
    class InterpreterPath:
        def __init__(self, value):self.value = str(value);self.parts = tuple(self.value.split("/"))
        def is_absolute(self):return self.value.startswith("/")
        def is_file(self):return True
        def absolute(self):return self
        def resolve(self):return InterpreterPath("/usr/bin/python3.10")
        def is_symlink(self):return self.value == python
        def __eq__(self, other):return self.value == other.value
    env = dict(venv_python=python, process_environment={"AMENT_PREFIX_PATH": "/fixture/humble"})
    spec = dict(run_uuid="a" * 32, environment_ref={"sha256": "b" * 64})
    monkeypatch.setattr(module, "checked_ref", lambda _: copy.deepcopy(env))
    monkeypatch.setattr(module, "Path", InterpreterPath)
    monkeypatch.setattr(module.os, "access", lambda path, mode: path == python and mode == module.os.X_OK)
    monkeypatch.setattr(module.sys, "executable", "/fixture/original-python")
    monkeypatch.setenv("PYTHONPATH", "/untrusted");monkeypatch.setenv("PYTHONHOME", "/untrusted")
    calls = []
    class Reexecuted(Exception):pass
    def execve(path, argv, process_env):
        calls.append((path, argv, process_env));raise Reexecuted
    monkeypatch.setattr(module.os, "execve", execve)
    assert InterpreterPath(python).is_symlink() and InterpreterPath(python).resolve() != InterpreterPath(python)
    with pytest.raises(Reexecuted):module.bootstrap(spec, ["--spec", "/fixture/spec", "--sha256", "c" * 64])
    path, argv, process_env = calls[0]
    assert path == python and argv[:5] == [python, "-u", "-m", "rm_match.integrations.pb_goal_plugin_peer", "--spec"]
    assert "PYTHONPATH" not in process_env and "PYTHONHOME" not in process_env
    assert process_env["AMENT_PREFIX_PATH"] == "/fixture/humble"
    assert process_env["POLAR_PB_GOAL_PEER_ENV"] == "a" * 32 + ":" + "b" * 64
    monkeypatch.setattr(module.sys, "executable", python)
    monkeypatch.delenv("PYTHONPATH");monkeypatch.delenv("PYTHONHOME")
    for key in ("AMENT_PREFIX_PATH", "POLAR_PB_GOAL_PEER_ENV"):monkeypatch.setenv(key, process_env[key])
    monkeypatch.setattr(module.sys, "version_info", (3, 10, 12))
    module.bootstrap(spec, [])
    monkeypatch.setattr(module.sys, "version_info", (3, 11, 0))
    with pytest.raises(ContractError, match="python310_required"):module.bootstrap(spec, [])
    assert len(calls) == 1


@pytest.mark.parametrize("cost_stage", ["compute", "append"])
@pytest.mark.parametrize("after_deadline", [0., .001])
def test_timely_native_action_is_not_delivered_after_later_work_exhausts_original_stage(
        pinned_spec, cost_stage, after_deadline):
    peer, clock, _ = resource_peer(pinned_spec);peer.reset(CONTEXT)
    end = clock() + .05;peer.source._deadline = end
    original = dict(action={"fixture": "already validated native result"})
    def compute(o, i):
        assert clock() < end  # Native/source callback was timely.
        if cost_stage == "compute":clock.now = end + after_deadline
        return copy.deepcopy(original)
    peer.compute = compute
    append = peer._append
    def costly_append(rows, value):
        append(rows, value)
        if rows is peer.result_rows:clock.now = end + after_deadline
    if cost_stage == "append":peer._append = costly_append
    with pytest.raises(ContractError, match="original_stage_expired"):
        peer(observation(), intent(observation()))
    assert peer.source._deadline == end and peer.result_rows == []
    assert peer.rejected_result_rows == [dict(reason="original_stage_deadline_expired",
        original_deadline=end, rejected_wall=end + after_deadline, result=original)]


def test_timely_action_keeps_same_receipt_and_does_not_renew_stage(pinned_spec):
    peer, clock, _ = resource_peer(pinned_spec);peer.reset(CONTEXT)
    end = clock() + .05;peer.source._deadline = end
    original = dict(action={"fixture": "already validated native result"})
    def compute(o, i):clock.now = end - .001;return copy.deepcopy(original)
    peer.compute = compute
    assert peer(observation(), intent(observation())) == original
    assert peer.result_rows == [original] and peer.rejected_result_rows == []
    assert peer.source._deadline == end


def test_expired_stage_status_remains_legal_without_a_second_same_sequence_receipt(pinned_spec):
    peer, clock, _ = resource_peer(pinned_spec);peer.reset(CONTEXT)
    end = clock() - .01;peer.source._deadline = end
    original = dict(status={"fixture": "already validated pending localization"})
    peer.compute = lambda o, i: copy.deepcopy(original)
    assert peer(observation(), intent(observation())) == original
    assert peer.result_rows == [original] and peer.rejected_result_rows == []
    assert peer.source._deadline == end


def emit_candidate(pinned_spec):
    peer, clock, _ = resource_peer(pinned_spec)
    peer.compute = GoalNavigationCompute(peer.lifecycle,
        lambda o, i: dict(value=action(o), goal_uuid=peer.backend.operations[-1]["uuid"]))
    peer.reset(CONTEXT);peer.source._deadline = clock() + .05
    o = observation();result = peer(o, intent(o))
    response = dict(schema=JSONL_SCHEMA, op="act", ok=True, result=result)
    encoded = encode_json(response, MAX_RESPONSE - 1) + b"\n"
    return peer, clock, response, encoded


def test_emit_gate_records_original_source_scan_and_exact_encoded_candidate(pinned_spec):
    peer, clock, response, encoded = emit_candidate(pinned_spec)
    clock.now = peer.source._deadline - .001
    peer.before_emit(response, encoded)
    assert len(peer.emit_gate_rows) == 1 and not peer.rejected_result_rows
    gate = peer.emit_gate_rows[0]
    assert gate["source"] == response["result"]["source"] and gate["result"] == response["result"]
    assert gate["scan"]["cloud_frame_id"] == 1 and gate["gate_wall"] < gate["local_deadline"]
    assert gate["clock"] == "linux_local_perf_counter"
    import hashlib
    assert gate["encoded_sha256"] == hashlib.sha256(encoded).hexdigest()
    with pytest.raises(ContractError, match="emit_source_or_result_changed"):
        peer.before_emit(response, encoded)


@pytest.mark.parametrize("cost_stage", ["encode", "emit_log"])
@pytest.mark.parametrize("after_deadline", [0., .001])
def test_encoding_or_final_log_cost_cannot_extend_original_stage(pinned_spec, cost_stage, after_deadline):
    peer, clock, response, encoded = emit_candidate(pinned_spec)
    end = peer.source._deadline
    if cost_stage == "encode":clock.now = end + after_deadline
    else:
        append = peer._append
        def costly_emit_log(rows, value):
            append(rows, value)
            if rows is peer.emit_gate_rows:clock.now = end + after_deadline
        peer._append = costly_emit_log
    with pytest.raises(ContractError, match="original_stage_expired"):peer.before_emit(response, encoded)
    assert peer.emit_gate_rows == [] and peer.source._deadline == end
    assert peer.rejected_result_rows[-1]["reason"] == "encoded_stage_deadline_expired"
    # The original computed receipt remains immutable; there is no same-seq
    # manufactured status and the generic server must not write this candidate.
    assert peer.result_rows[-1] == response["result"]


@pytest.mark.parametrize("part", ["source", "typed_source", "action", "selection", "encoding"])
def test_emit_gate_rejects_changed_source_result_or_encoded_bytes(pinned_spec, part):
    peer, _, response, encoded = emit_candidate(pinned_spec)
    if part == "source":response["result"]["source"]["robot_id"] = "blue_sentry"
    elif part == "typed_source":response["result"]["source"]["episode"] = False
    elif part == "action":response["result"]["action"]["command"]["vx_mps"] += .01
    elif part == "selection":response["result"]["selection"]["goal_uuids"]["navigation"] = "f" * 32
    else:
        changed = copy.deepcopy(response);changed["result"]["source"]["robot_id"] = "blue_sentry"
        encoded = encode_json(changed, MAX_RESPONSE - 1) + b"\n"
    with pytest.raises(ContractError, match="emit_source_or_result_changed|emit_encoding_changed"):
        peer.before_emit(response, encoded)
    assert peer.emit_gate_rows == [] and peer._emit_pending is None


def test_emit_gate_status_and_nonact_messages_need_no_fake_action_proof(pinned_spec):
    peer, clock, _ = resource_peer(pinned_spec);peer.reset(CONTEXT)
    clock.now += 1.
    peer.before_emit(dict(op="prepare", ok=True), b"unused")
    peer.before_emit(dict(op="act", result=dict(status={"status": "pending_localization"})), b"unused")
    assert not peer.emit_gate_rows and not peer.rejected_result_rows
