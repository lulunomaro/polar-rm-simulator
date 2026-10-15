"""Synthetic one-goal policy using declared actual estimated map feedback.

Not PB match behavior, a planner, SLAM, an aiming model or a truth reader. It
waits for this scan's available navigation, requests map-x +1m once, then holds
only after the producer reports that original goal's real terminal/stop proof.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rm_match.platform_v2.contracts import ContractError, exact, identity
from rm_match.platform_v2.decision_contracts import (DECISION_PROFILE_V2,
    decision_intent_for, validate_decision_observation)


GOAL_REASON = "synthetic_estimated_map_goal_v2"
COMPLETE_REASON = "synthetic_estimated_goal_completed"
ENDED_REASON = "synthetic_estimated_goal_ended"


def _same(a, b):
    if type(a) is not type(b):
        return False
    if type(a) is dict:
        return set(a) == set(b) and all(_same(a[key], b[key]) for key in a)
    if type(a) is list:
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


class EstimatedMapGoalPolicy:
    def __init__(self):
        self.context = None
        self.goal = None
        self.done = False
        self.succeeded = False

    def reset(self, context):
        if self.context is not None:
            raise ContractError("synthetic_feedback_policy_reset_once")
        exact(context, ("robot_id", "episode", "binding_epoch"), "synthetic_feedback_policy_context")
        identity(dict(context, observed_seq=0, sim_time=0.0, wall_deadline=0.0))
        self.context = copy.deepcopy(context)

    def __call__(self, observation):
        o = validate_decision_observation(observation, profile=DECISION_PROFILE_V2)
        if self.context is None or any(type(o[key]) is not type(value) or o[key] != value
                                       for key, value in self.context.items()):
            raise ContractError("synthetic_feedback_policy_generation")
        def hold(reason):
            return decision_intent_for(o, dict(behavior="hold", reason=reason))
        if self.done:
            return hold(COMPLETE_REASON if self.succeeded else ENDED_REASON)
        feedback = o["navigation"]
        nav, goals = feedback["navigation"], feedback["goal_status"]
        if not nav["available"]:
            return hold("synthetic_feedback_wait_" + nav["reason"])
        if not goals["available"]:
            return hold("synthetic_feedback_wait_goal_status")
        if goals["fault"] is not None or goals["stop_requested"]:
            return hold("synthetic_feedback_lifecycle_unavailable")
        if self.goal is None:
            if goals["selection"] is not None:
                return hold("synthetic_feedback_existing_operation")
            x, y, _ = nav["position_m"]
            qx, qy, qz, qw = nav["rotation_xyzw"]
            yaw = math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz))
            self.goal = dict(frame="map", position_m=[x + 1.0, y], yaw_rad=yaw)
        for record in goals["history"]:
            if (_same(record["origin_intent"]["command"]["goal"], self.goal)
                    and record["terminal"] and record["stop_confirmed"]):
                self.done = True
                self.succeeded = record["state"] == "succeeded"
                return hold(COMPLETE_REASON if self.succeeded else ENDED_REASON)
        return decision_intent_for(o, dict(behavior="navigate_to_pose", reason=GOAL_REASON,
                                          goal=copy.deepcopy(self.goal)))


if __name__ == "__main__":
    from rm_match.integrations.decision_jsonl_peer import run_decision_plugin
    raise SystemExit(run_decision_plugin(EstimatedMapGoalPolicy, profile=DECISION_PROFILE_V2))
