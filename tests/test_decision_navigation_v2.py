"""Estimated-feedback policy/owned JSONL units; no PB, ROS, SLAM or physics."""
import copy
import io
import json
from pathlib import Path
import sys
import time

import pytest

from rm_match.deployment.decision_plugin import (
    CAPABILITIES, NAVIGATION_CAPABILITIES, MANIFEST_SCHEMA, DecisionPluginAdapter,
    capabilities_for_profile, load_decision_plugins, validate_capabilities,
)
from rm_match.integrations.decision_jsonl_peer import serve_decision_plugin
from rm_match.integrations.ros2_bridge import JSONL_SCHEMA
from rm_match.platform_v2.contracts import ContractError, IDENTITY
from rm_match.platform_v2.decision_contracts import (
    DECISION_INTENT_SCHEMA, DECISION_OBSERVATION_SCHEMA, DECISION_NAVIGATION_OBSERVATION_SCHEMA,
    DECISION_PROFILE_V2, build_decision_observation, decision_intent_for,
    validate_decision_intent, validate_decision_observation,
)
from rm_match.platform_v2.navigation_feedback_contracts import (
    navigation_feedback, unavailable_navigation_feedback,
)
from test_navigation_feedback_contracts import estimate, original


FIXTURE = Path(__file__).parent / "fixtures" / "decision_navigation_feedback_v2.py"


def decision_input(o=None, *, available=True, goal_status=None):
    o = original() if o is None else o
    feedback = (navigation_feedback(o, estimate(), goal_status=goal_status) if available
                else unavailable_navigation_feedback(o, "pending_navigation", goal_status=goal_status))
    return build_decision_observation(o, feedback, profile=DECISION_PROFILE_V2)


def empty_goals():
    return dict(available=True, selection=None, history=[], operation_count=0,
                stop_requested=False, fault=None)


def packets(o):
    context = {name: o[name] for name in ("robot_id", "episode", "binding_epoch")}
    return [dict(schema=JSONL_SCHEMA, op="prepare", config={}),
            dict(schema=JSONL_SCHEMA, op="reset", context=context, config={}),
            dict(schema=JSONL_SCHEMA, op="act", observation=o)]


def peer(values, compute, *, profile=DECISION_PROFILE_V2):
    stream = io.BytesIO(b"".join((json.dumps(row) + "\n").encode() for row in values))
    output = io.BytesIO()
    serve_decision_plugin(compute, stream, output, profile=profile)
    return [json.loads(line) for line in output.getvalue().splitlines()]


def test_v1_default_remains_exact_and_v2_is_explicit_with_original_feedback():
    o = original()
    v1 = build_decision_observation(o)
    assert v1["schema"] == DECISION_OBSERVATION_SCHEMA
    assert v1["navigation"] == dict(available=False, reason="not_provided_in_own_referee_v1")
    with pytest.raises(ContractError):
        build_decision_observation(o, unavailable_navigation_feedback(o))
    v2 = build_decision_observation(o, profile=DECISION_PROFILE_V2)
    assert v2["schema"] == DECISION_NAVIGATION_OBSERVATION_SCHEMA
    assert v2["navigation"]["source"] == {name: o[name] for name in IDENTITY}
    assert v2["navigation"]["navigation"] == dict(available=False, reason="not_provided")
    assert v2["navigation"]["goal_status"] == dict(available=False, reason="not_provided")
    assert v2["perception"] == v1["perception"]
    for wrong, profile in ((v1, DECISION_PROFILE_V2), (v2, "own_referee_v1")):
        with pytest.raises(ContractError):
            validate_decision_observation(wrong, profile=profile)


def test_v2_embeds_exact_feedback_not_renamed_old_pose_and_keeps_intent_v1():
    o = original()
    fb = navigation_feedback(o, estimate())
    value = build_decision_observation(o, fb, profile=DECISION_PROFILE_V2)
    intent = decision_intent_for(value, dict(behavior="hold", reason="synthetic test"))
    assert intent["schema"] == DECISION_INTENT_SCHEMA
    assert validate_decision_intent(intent, value) == intent
    fb["navigation"]["position_m"][0] = 99.0
    assert value["navigation"]["navigation"]["position_m"][0] == 0.2
    newer = dict(o, observed_seq=4)
    with pytest.raises(ContractError):
        build_decision_observation(newer, value["navigation"], profile=DECISION_PROFILE_V2)
    value["observed_seq"] = 4
    with pytest.raises(ContractError):
        validate_decision_observation(value)


def test_v2_no_perception_truth_or_unversioned_navigation_fields():
    for change in ("enemy", "world", "ideal", "unavailable_pose"):
        value = decision_input()
        if change == "enemy":
            value["perception"] = dict(available=True, target_position_m=[1.0, 2.0, 0.0])
        elif change == "world":
            value["world_robots"] = []
        elif change == "ideal":
            value["own"]["odom"] = [0.0, 0.0, 0.0]
        else:
            value["navigation"] = dict(available=False, reason="not_provided_in_own_referee_v1")
        with pytest.raises(ContractError):
            validate_decision_observation(value)


def test_v2_capabilities_are_explicit_detached_and_not_v1_negotiation():
    selected = capabilities_for_profile(DECISION_PROFILE_V2)
    assert selected == NAVIGATION_CAPABILITIES and selected != CAPABILITIES
    assert selected["sensor_profile"] == DECISION_PROFILE_V2
    assert selected["source_association"] == "exact_observation_and_navigation_feedback_v1"
    selected["output_modes"].clear()
    assert capabilities_for_profile(DECISION_PROFILE_V2)["output_modes"] == ["navigation_intent"]
    for change in (dict(sensor_profile="ideal_odom"), dict(fire_authority="algorithm"),
                   dict(observation_schema=DECISION_OBSERVATION_SCHEMA), dict(extra=True)):
        bad = dict(copy.deepcopy(NAVIGATION_CAPABILITIES), **change)
        with pytest.raises(ContractError):
            validate_capabilities(bad)


def test_v2_peer_actual_prepare_reset_caps_and_source_echo_without_clock_rewrite():
    value = decision_input()
    seen = []
    def compute(o):
        seen.append(copy.deepcopy(o))
        return decision_intent_for(o, dict(behavior="hold", reason="synthetic pure peer"))
    responses = peer(packets(value), compute)
    assert responses[0]["capabilities"] == responses[1]["capabilities"] == NAVIGATION_CAPABILITIES
    assert seen == [value]
    assert {name: responses[-1]["intent"][name] for name in IDENTITY} == {name: value[name] for name in IDENTITY}
    for default_input, profile in ((value, "own_referee_v1"),
                                   (build_decision_observation(original()), DECISION_PROFILE_V2)):
        with pytest.raises(ContractError):
            peer(packets(default_input), compute, profile=profile)
    assert len(seen) == 1


def test_synthetic_policy_waits_for_real_available_estimate_and_original_terminal():
    sys.path.insert(0, str(FIXTURE.parent))
    try:
        from decision_navigation_feedback_v2 import EstimatedMapGoalPolicy, COMPLETE_REASON
        policy = EstimatedMapGoalPolicy()
        o = original()
        context = {name: o[name] for name in ("robot_id", "episode", "binding_epoch")}
        policy.reset(context)
        waiting = decision_input(o, available=False, goal_status=empty_goals())
        assert policy(waiting)["command"] == dict(behavior="hold", reason="synthetic_feedback_wait_pending_navigation")
        active = decision_input(original(4), goal_status=empty_goals())
        first = policy(active)
        assert first["command"]["goal"] == dict(frame="map", position_m=[1.2, -0.1], yaw_rad=0.0)
        moved = decision_input(original(5), goal_status=empty_goals())
        moved["navigation"]["navigation"]["position_m"][0] = 4.0
        assert policy(moved)["command"]["goal"] == first["command"]["goal"]
        record = dict(operation_id="1" * 32, origin_intent=first,
                      latest_authorization={name: first[name] for name in IDENTITY},
                      goal_uuids=dict(planner="2" * 32, navigation="3" * 32), state="active",
                      cancel_requested=False, terminal=False, stop_confirmed=False)
        g = dict(empty_goals(), history=[record], operation_count=1, selection=record)
        assert policy(decision_input(original(6), goal_status=g))["command"]["behavior"] == "navigate_to_pose"
        record.update(state="succeeded", terminal=True, stop_confirmed=True)
        g["selection"] = None
        ended = policy(decision_input(original(7), goal_status=g))
        assert ended["command"] == dict(behavior="hold", reason=COMPLETE_REASON)
        assert policy.done and policy.succeeded
    finally:
        sys.path.remove(str(FIXTURE.parent))


def test_actual_owned_jsonl_v2_policy_uses_feedback_then_echoes_terminal_hold(tmp_path):
    row = dict(adapter_id="custom_feedback_decision_fixture", label="Synthetic feedback policy",
               command=[sys.executable, "-u", str(FIXTURE.resolve())], cwd=str(FIXTURE.parent.resolve()),
               supported_robots=["blue_sentry"], transport="jsonl_v1", capabilities=copy.deepcopy(NAVIGATION_CAPABILITIES))
    manifest = tmp_path / "decision.json"
    manifest.write_text(json.dumps(dict(schema=MANIFEST_SCHEMA, adapters=[row])), encoding="utf8")
    rows, digest = load_decision_plugins(manifest)
    adapter = DecisionPluginAdapter({}, registration=rows[0], manifest=manifest, manifest_sha=digest)
    child = None
    try:
        adapter.prepare()
        context_o = original()
        adapter.reset({name: context_o[name] for name in ("robot_id", "episode", "binding_epoch")})
        current = original()
        current["wall_deadline"] = time.perf_counter() + 0.15
        first = adapter.act(decision_input(current, goal_status=empty_goals()))
        assert first["command"]["behavior"] == "navigate_to_pose"
        record = dict(operation_id="1" * 32, origin_intent=first,
                      latest_authorization={name: first[name] for name in IDENTITY},
                      goal_uuids=dict(planner="2" * 32, navigation="3" * 32), state="succeeded",
                      cancel_requested=False, terminal=True, stop_confirmed=True)
        next_o = original(4)
        next_o["wall_deadline"] = time.perf_counter() + 0.15
        last = adapter.act(decision_input(next_o, goal_status=dict(empty_goals(), history=[record], operation_count=1)))
        assert last["command"]["behavior"] == "hold"
        assert last["command"]["reason"] == "synthetic_estimated_goal_completed"
        child = adapter.process
    finally:
        child = child or adapter.process
        adapter.close()
    assert child is not None and child.poll() is not None
    assert adapter.shutdown_status["clean"]
    assert not adapter.thread.is_alive()


def test_v2_adapter_rejects_capability_mismatch_before_intent_is_accepted(tmp_path):
    row = dict(adapter_id="custom_feedback_decision_fixture", label="Synthetic feedback policy",
               command=[sys.executable, "-u", str(FIXTURE.resolve())], cwd=str(FIXTURE.parent.resolve()),
               supported_robots=["blue_sentry"], transport="jsonl_v1", capabilities=copy.deepcopy(NAVIGATION_CAPABILITIES))
    manifest = tmp_path / "decision.json"
    manifest.write_text(json.dumps(dict(schema=MANIFEST_SCHEMA, adapters=[row])), encoding="utf8")
    rows, digest = load_decision_plugins(manifest)
    adapter = DecisionPluginAdapter({}, registration=rows[0], manifest=manifest, manifest_sha=digest)
    try:
        with pytest.raises(ContractError):
            adapter._validate_response(dict(schema=JSONL_SCHEMA, op="reset", ok=True, capabilities=CAPABILITIES), dict(op="reset"))
    finally:
        adapter.close()
