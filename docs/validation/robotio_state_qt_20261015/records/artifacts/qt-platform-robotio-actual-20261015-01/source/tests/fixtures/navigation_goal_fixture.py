"""Synthetic goal-aware velocity fixture, not localization or navigation."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rm_match.integrations.navigation_jsonl_peer import run_navigation_plugin
from rm_match.platform_v2.contracts import action_for

POLICY_VERSION = 'synthetic_goal_velocity_v1'


def factory():
    def compute(observation, intent):
        behavior = intent['command']['behavior']
        # This deterministic value proves the intent arrived. It is not a
        # planner, localization estimate, or distance to a map goal.
        vx = .2 if behavior == 'navigate_to_pose' else 0.
        return action_for(observation, 'navigation', 'velocity_body', dict(
            frame='base_link', vx_mps=vx, vy_mps=0., wz_rps=0.))
    return compute


if __name__ == '__main__':
    raise SystemExit(run_navigation_plugin(factory, goal_input_modes=['decision_intent_v1']))
