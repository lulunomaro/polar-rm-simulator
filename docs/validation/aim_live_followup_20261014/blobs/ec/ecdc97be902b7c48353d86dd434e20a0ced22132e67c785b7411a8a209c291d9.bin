"""Compare original and candidate initial bay commands using fixed CPU fixtures.

Usage: python review_opening_egress_compatibility.py --baseline BASELINE --candidate CANDIDATE

Each directory must contain rm_match. Only match_controllers.py may differ among
package Python sources. This is a numerical/state check, not a physics replay.
No renderer, rollout, external service, or learned policy is invoked.
"""
import argparse
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import sys


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=88237)
    parser.add_argument('--samples-per-role-team', type=int, default=100)
    args = parser.parse_args()
    baseline, candidate = args.baseline.resolve(), args.candidate.resolve()
    sources = []
    for root in (baseline, candidate):
        sources.append({str(p.relative_to(root)): digest(p)
                        for p in (root/'rm_match').rglob('*.py')})
    differences = sorted(k for k in sources[0].keys() | sources[1].keys()
                         if sources[0].get(k) != sources[1].get(k))
    if differences != ['rm_match/match_controllers.py']:
        raise AssertionError(f'Unexpected Python source differences: {differences}')
    sys.path.insert(0, str(candidate))
    import math
    import numpy as np
    from rm_match.contracts import Observation
    from rm_match.match_controllers import MatchNavigationPolicy

    spec = importlib.util.spec_from_file_location(
        'rm_match._review_baseline', baseline/'rm_match/match_controllers.py')
    original = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = original
    spec.loader.exec_module(original)

    def observation(team, role, hp, ammo, t, xy):
        side = 1 if team == 'red' else -1
        return Observation(
            0, t, np.empty((0, 0, 3), dtype=np.uint8), 50., (0.,)*5,
            (0.,)*5, hp, ammo, robot_id=team+'_'+role,
            odom_xyyaw=(side*xy[0], side*xy[1], 0. if side == 1 else math.pi),
            odom_vxyw=(0., 0., 0.), ranges=(8.,)*64,
            range_angles=tuple(np.linspace(-math.pi, math.pi, 64, endpoint=False)),
            team=team, role=role, remaining_seconds=300-t,
        )

    rng = random.Random(args.seed)
    checks = 0
    for team in ('red', 'blue'):
        for role, hp, ammo in (('sentry', 400, 750), ('hero', 350, 5),
                               ('infantry', 300, 50)):
            for sample in range(args.samples_per_role_team):
                p, q = MatchNavigationPolicy(), original.MatchNavigationPolicy()
                o = observation(team, role, hp, ammo, rng.uniform(0, 30),
                                (rng.uniform(-5.8, -3.951), rng.uniform(-1.699, 3.8)))
                o = replace(o, odom_vxyw=(rng.uniform(-.5, .5), rng.uniform(-.5, .5), 0.),
                            ranges=tuple(rng.uniform(.05, 8.) for _ in range(64)))
                a, b = p.decide(o), q.decide(o)
                assert (a.command, a.mode, a.purchase_bundles) == (
                    b.command, b.mode, b.purchase_bundles), (team, role, sample, a, b)
                assert p.desired_velocity == q.desired_velocity, (team, role, sample)
                checks += 1
    print(json.dumps({
        'status': 'passed',
        'fixture_seed': args.seed,
        'samples_per_role_team': args.samples_per_role_team,
        'checks_passed': checks,
        'checks_expected': 6*args.samples_per_role_team,
        'teams': ['red', 'blue'],
        'roles': ['sentry', 'hero', 'infantry'],
        'equal_fields': ['command', 'mode', 'purchase_bundles', 'desired_velocity'],
        'production_python_differences': differences,
        'baseline_controller_sha256': sources[0]['rm_match/match_controllers.py'],
        'candidate_controller_sha256': sources[1]['rm_match/match_controllers.py'],
        'scope': 'Initial bay synthetic numerical equality only; no physics or rendering',
    }, indent=2))


if __name__ == '__main__':
    main()
