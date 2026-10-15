"""Synthetic supply policy v1; no perception or navigation algorithm claim."""
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rm_match.integrations.decision_jsonl_peer import run_decision_plugin
from rm_match.platform_v2.decision_contracts import decision_intent_for

POLICY_VERSION = 'synthetic_supply_v1'


def factory():
    os.write(1, (POLICY_VERSION + ' resource initialization\n').encode())

    def supply_policy(observation):
        if observation['referee']['phase'] != 'running' or not observation['own']['alive']:
            command = dict(behavior='hold', reason='synthetic_not_running')
        else:
            position = [0., 0.] if observation['own']['hp'] < 200 else [2., -1.]
            command = dict(behavior='navigate_to_pose', reason='synthetic_supply_or_patrol',
                           goal=dict(frame='map', position_m=position, yaw_rad=0.))
        print(POLICY_VERSION + ' callback', flush=True)
        return decision_intent_for(observation, command)

    return supply_policy


if __name__ == '__main__':
    raise SystemExit(run_decision_plugin(factory))
