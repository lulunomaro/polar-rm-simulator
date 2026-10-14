"""Independent synthetic heat policy v2; no real match decision claim."""
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rm_match.integrations.decision_jsonl_peer import run_decision_plugin
from rm_match.platform_v2.decision_contracts import decision_intent_for

POLICY_VERSION = 'synthetic_heat_v2'


class HeatGuard:
    def __call__(self, observation):
        referee = observation['referee']
        if referee['emergency_stop'] or referee['phase'] != 'running':
            command = dict(behavior='cancel', reason='synthetic_referee_stop')
        elif observation['own']['heat'] >= 100:
            command = dict(behavior='cancel', reason='synthetic_heat_guard')
        else:
            command = dict(behavior='hold', reason='synthetic_await_perception')
        print(POLICY_VERSION + ' callback', flush=True)
        return decision_intent_for(observation, command)


def factory():
    os.write(1, (POLICY_VERSION + ' resource initialization\n').encode())
    return HeatGuard()


if __name__ == '__main__':
    raise SystemExit(run_decision_plugin(factory))
