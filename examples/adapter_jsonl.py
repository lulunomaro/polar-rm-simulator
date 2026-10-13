#!/usr/bin/env python3
"""Standard-library JSONL fixture; replace compute() with your reviewed algorithm.

This example deliberately emits zero motion or inactive hold. It is not a
navigation / detection implementation and is never in the default registry.
"""
import argparse
import json
import math
import sys

SCHEMA = 'polar.sim.adapter.jsonl.v1'
IDENTITY = ('robot_id', 'episode', 'binding_epoch', 'observed_seq', 'sim_time', 'wall_deadline')


def compute(observation, kind):
    if kind == 'navigation':
        mode = 'velocity_body'
        command = dict(frame='base_link', vx_mps=0., vy_mps=0., wz_rps=0.)
    else:
        mode = 'gimbal_target'
        q = observation['own']['qpos']
        command = dict(frame='base_link', yaw_rad=math.atan2(math.sin(q[3]), math.cos(q[3])),
                       pitch_rad=max(-math.pi / 2, min(math.pi / 2, q[4])),
                       active=False, confidence=None, fire_permission=False)
    return dict(schema='polar.sim.action.v2', **{k: observation[k] for k in IDENTITY},
                kind=kind, mode=mode, command=command)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kind', choices=('navigation', 'aim'), required=True)
    args = parser.parse_args()
    context = None
    for raw in sys.stdin:
        request = json.loads(raw)
        if request['schema'] != SCHEMA:
            raise ValueError('Unknown protocol')
        op = request['op']
        response = dict(schema=SCHEMA, op=op, ok=True)
        if op == 'reset':
            context = request['context']
            config = request['config']  # Local binding config; never a command.
        elif op == 'act':
            o = request['observation']
            if context is None or any(o[k] != v for k, v in context.items()):
                raise ValueError('Context changed without reset')
            response['action'] = compute(o, args.kind)
        else:
            raise ValueError('Unknown operation')
        print(json.dumps(response, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
