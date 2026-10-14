"""JSONL peer for a reviewed real navigation callback, without ideal pose.

Foreign wall_deadline is opaque here. Only the host checks its own clock.
The factory must finish actual resource initialization before prepare ACK;
neither prepare nor reset supplies a scan or performs dummy inference.
"""
from __future__ import annotations
import copy
import os
import sys
from .ros2_bridge import parse_json, encode_json, MAX_REQUEST, MAX_RESPONSE, JSONL_SCHEMA
from ..deployment.navigation_plugin import (
    CAPABILITIES, validate_capabilities, validate_intent, validate_result_for_intent, navigation_status_for)
from ..platform_v2.contracts import ContractError, exact, identity
from ..platform_v2.navigation_contracts import validate_navigation_observation


def serve_navigation_plugin(compute, input_stream, output_stream, *, goal_input_modes=()):
    capabilities = copy.deepcopy(CAPABILITIES)
    capabilities['goal_input_modes'] = list(goal_input_modes)
    capabilities = validate_capabilities(capabilities)
    context = None; last_seq = -1; prepared = False
    while True:
        raw = input_stream.readline(MAX_REQUEST + 1)
        if not raw: return
        if len(raw) > MAX_REQUEST or not raw.endswith(b'\n'):
            raise ContractError('navigation_jsonl_line_oversized_or_partial')
        request = parse_json(raw, MAX_REQUEST)
        if type(request) is not dict or type(request.get('schema')) is not str or request['schema'] != JSONL_SCHEMA or type(request.get('op')) is not str:
            raise ContractError('navigation_jsonl_schema_or_operation')
        op = request['op']
        if op == 'prepare':
            exact(request, ('schema', 'op', 'config'), 'navigation_peer_prepare')
            exact(request['config'], (), 'navigation_peer_config')
            if prepared or context is not None: raise ContractError('navigation_peer_prepare_once_before_reset')
            prepared = True
            response = dict(schema=JSONL_SCHEMA, op=op, ok=True)
        elif op == 'reset':
            exact(request, ('schema', 'op', 'context', 'config'), 'navigation_peer_reset')
            exact(request['context'], ('episode', 'robot_id', 'binding_epoch'), 'navigation_peer_context')
            exact(request['config'], (), 'navigation_peer_config')
            if context is not None: raise ContractError('navigation_peer_reset_once')
            identity(dict(request['context'], observed_seq=0, sim_time=0., wall_deadline=0.))
            next_context = dict(request['context'])
            reset = getattr(compute, 'reset', None)
            if reset is not None:
                if not callable(reset): raise ContractError('navigation_compute_reset_callable_required')
                reset(dict(next_context))
            context = next_context
            response = dict(schema=JSONL_SCHEMA, op=op, ok=True, capabilities=copy.deepcopy(capabilities))
        elif op == 'act':
            has_intent = 'intent' in request
            fields = ('schema', 'op', 'observation', 'intent') if has_intent else ('schema', 'op', 'observation')
            exact(request, fields, 'navigation_peer_act')
            if context is None: raise ContractError('navigation_peer_reset_required')
            o = validate_navigation_observation(request['observation'])
            if any(type(o[k]) is not type(v) or o[k] != v for k, v in context.items()):
                raise ContractError('navigation_peer_generation')
            if o['observed_seq'] <= last_seq: raise ContractError('navigation_peer_replayed_observation')
            if has_intent and not capabilities['goal_input_modes']:
                raise ContractError('navigation_peer_goal_input_unsupported')
            intent = validate_intent(request['intent'], o) if has_intent else None
            if capabilities['goal_input_modes'] and not has_intent:
                value = navigation_status_for(o)
            else:
                value = compute(copy.deepcopy(o), copy.deepcopy(intent))
            field, value = validate_result_for_intent(value, o, intent)
            last_seq = o['observed_seq']
            response = dict(schema=JSONL_SCHEMA, op=op, ok=True, **{field: value})
        else: raise ContractError('navigation_peer_operation')
        output_stream.write(encode_json(response, MAX_RESPONSE - 1) + b'\n')
        output_stream.flush()


def run_navigation_plugin(compute_factory, *, goal_input_modes=()):
    """Keep algorithm/library stdout off the protocol; report shutdown failure."""
    sys.stdout.flush()
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), 'wb', buffering=0)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    compute = None; code = 0
    try:
        compute = compute_factory()
        if not callable(compute): raise ContractError('navigation_compute_callable_required')
        serve_navigation_plugin(compute, sys.stdin.buffer, protocol, goal_input_modes=goal_input_modes)
    except KeyboardInterrupt: code = 130
    except Exception:
        print('navigation_plugin_failed', file=sys.stderr, flush=True); code = 2
    finally:
        try:
            close = getattr(compute, 'close', None)
            if close is not None: close()
        except Exception:
            print('navigation_plugin_shutdown_incomplete', file=sys.stderr, flush=True); code = 2
        finally: protocol.close()
    return code
