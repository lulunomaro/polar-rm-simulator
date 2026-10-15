"""Bounded JSONL entry for independent decision implementations.

The callback receives a detached own-referee observation and returns a complete
intent with the same identity. Foreign wall_deadline is an opaque echo here;
the original host enforces it. No fallback, perception synthesis, or actuation.
"""
from __future__ import annotations

import copy
import os
import sys

from .ros2_bridge import JSONL_SCHEMA, MAX_REQUEST, MAX_RESPONSE, encode_json, parse_json
from ..deployment.decision_plugin import CAPABILITIES, capabilities_for_profile
from ..platform_v2.contracts import ContractError, exact, identity
from ..platform_v2.decision_contracts import (DECISION_PROFILE_V1, DECISION_PROFILE_V2,
    validate_decision_intent, validate_decision_observation)


def serve_decision_plugin(compute, input_stream, output_stream, *, profile=DECISION_PROFILE_V1):
    if not callable(compute):
        raise ContractError('decision_compute_callable_required')
    capabilities = capabilities_for_profile(profile)
    feedback_history = None
    if profile == DECISION_PROFILE_V2:
        from ..platform_v2.navigation_feedback_contracts import NavigationFeedbackHistory
        feedback_history = NavigationFeedbackHistory()
    context = None
    prepared = False
    last_seq = -1
    last_sim_time = -1.
    while True:
        raw = input_stream.readline(MAX_REQUEST + 1)
        if not raw:
            return
        if len(raw) > MAX_REQUEST or not raw.endswith(b'\n'):
            raise ContractError('decision_jsonl_line_oversized_or_partial')
        request = parse_json(raw, MAX_REQUEST)
        if (type(request) is not dict or type(request.get('schema')) is not str or
                request['schema'] != JSONL_SCHEMA):
            raise ContractError('decision_jsonl_schema')
        op = request.get('op')
        if op == 'prepare':
            exact(request, ('schema', 'op', 'config'), 'decision_peer_prepare')
            exact(request['config'], (), 'decision_peer_config')
            if prepared or context is not None:
                raise ContractError('decision_peer_prepare_once_before_reset')
            prepared = True
            response = dict(schema=JSONL_SCHEMA, op=op, ok=True,
                            capabilities=copy.deepcopy(capabilities))
        elif op == 'reset':
            exact(request, ('schema', 'op', 'context', 'config'), 'decision_peer_reset')
            exact(request['context'], ('episode', 'robot_id', 'binding_epoch'), 'decision_peer_context')
            exact(request['config'], (), 'decision_peer_config')
            if context is not None:
                raise ContractError('decision_peer_reset_once')
            identity(dict(request['context'], observed_seq=0, sim_time=0., wall_deadline=0.))
            next_context = copy.deepcopy(request['context'])
            reset = getattr(compute, 'reset', None)
            if reset is not None:
                if not callable(reset):
                    raise ContractError('decision_compute_reset_callable_required')
                reset(copy.deepcopy(next_context))
            context = next_context
            response = dict(schema=JSONL_SCHEMA, op=op, ok=True,
                            capabilities=copy.deepcopy(capabilities))
        elif op == 'act':
            exact(request, ('schema', 'op', 'observation'), 'decision_peer_act')
            if context is None:
                raise ContractError('decision_peer_reset_required')
            observation = validate_decision_observation(request['observation'], profile=profile)
            if any(type(observation[name]) is not type(wanted) or observation[name] != wanted
                   for name, wanted in context.items()):
                raise ContractError('decision_peer_generation')
            if observation['observed_seq'] <= last_seq or observation['sim_time'] < last_sim_time:
                raise ContractError('decision_peer_replayed_observation')
            if feedback_history is not None:
                feedback_history.check(observation['navigation'])
            intent = validate_decision_intent(compute(copy.deepcopy(observation)), observation)
            last_seq = observation['observed_seq']
            last_sim_time = observation['sim_time']
            response = dict(schema=JSONL_SCHEMA, op=op, ok=True, intent=intent)
        else:
            raise ContractError('decision_peer_operation')
        output_stream.write(encode_json(response, MAX_RESPONSE - 1) + b'\n')
        output_stream.flush()


def run_decision_plugin(compute_factory, *, profile=DECISION_PROFILE_V1):
    """Initialize only the locally reviewed callback with protocol-safe stdout."""
    sys.stdout.flush()
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), 'wb', buffering=0)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    compute, code = None, 0
    try:
        compute = compute_factory()
        serve_decision_plugin(compute, sys.stdin.buffer, protocol, profile=profile)
    except KeyboardInterrupt:
        code = 130
    except Exception:
        print('decision_plugin_failed', file=sys.stderr, flush=True)
        code = 2
    finally:
        try:
            close = getattr(compute, 'close', None)
            if close is not None:
                if not callable(close):
                    raise ContractError('decision_compute_close_callable_required')
                close()
        except Exception:
            print('decision_plugin_shutdown_incomplete', file=sys.stderr, flush=True)
            code = 2
        finally:
            protocol.close()
    return code
