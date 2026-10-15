"""Synthetic protocol backend/velocity, not ROS, localization or navigation.

The artificial UUID is intentionally created by this test backend. It is not
evidence about any real team's controller, action server or accepted goal.
"""
import copy
from pathlib import Path
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rm_match.integrations.navigation_goal_lifecycle import BACKEND_SCHEMA, NavigationGoalLifecycle
from rm_match.integrations.goal_navigation_compute import GoalNavigationCompute
from rm_match.integrations.navigation_jsonl_peer import run_navigation_plugin
from rm_match.deployment.navigation_plugin import navigation_status_for
from rm_match.platform_v2.contracts import action_for


class SyntheticBackend:
    def __init__(self):
        self.current = None

    def start(self, goal, source, *, operation_id):
        self.current = dict(schema=BACKEND_SCHEMA, operation_id=operation_id, source=copy.deepcopy(source),
            state='active', goal_uuids=dict(planner=None, navigation=secrets.token_hex(16)),
            terminal=False, cancel_acknowledged=False, stop_confirmed=False, error_code=None)
        return self.current

    def poll(self, operation):
        return copy.deepcopy(operation)

    def cancel(self, operation):
        operation.update(state='canceled', terminal=True, cancel_acknowledged=True, stop_confirmed=True)


def factory():
    backend = SyntheticBackend()
    lifecycle = NavigationGoalLifecycle(backend, deadline_mode='opaque')
    def controller(observation, intent):
        current = backend.current
        if intent['command']['behavior'] != 'navigate_to_pose' or current is None or current['terminal']:
            return dict(value=navigation_status_for(observation), goal_uuid=None)
        return dict(value=action_for(observation, 'navigation', 'velocity_body', dict(
            frame='base_link', vx_mps=.2, vy_mps=0., wz_rps=0.)),
            goal_uuid=current['goal_uuids']['navigation'])
    return GoalNavigationCompute(lifecycle, controller)


if __name__ == '__main__':
    raise SystemExit(run_navigation_plugin(factory, goal_input_modes=['decision_intent_v1'],
        goal_result_profile='active_goal_v1'))
