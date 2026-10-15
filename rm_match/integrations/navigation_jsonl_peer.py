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
    CAPABILITIES, GOAL_CAPABILITIES, FEEDBACK_CAPABILITIES, validate_capabilities, validate_intent,
    validate_result_for_intent, navigation_status_for, same_typed_tree)
from ..platform_v2.contracts import ContractError, IDENTITY, exact, identity
from ..platform_v2.navigation_contracts import validate_navigation_observation


def serve_navigation_plugin(compute, input_stream, output_stream, *, goal_input_modes=(), goal_result_profile='none'):
    if type(goal_result_profile) is not str or goal_result_profile not in ('none', 'active_goal_v1', 'staged_scan_v1'):
        raise ContractError('navigation_peer_goal_result_profile')
    staged_profile = goal_result_profile == 'staged_scan_v1'
    goal_profile = goal_result_profile in ('active_goal_v1', 'staged_scan_v1')
    capabilities = copy.deepcopy(FEEDBACK_CAPABILITIES if staged_profile else GOAL_CAPABILITIES if goal_profile else CAPABILITIES)
    capabilities['goal_input_modes'] = list(goal_input_modes)
    capabilities = validate_capabilities(capabilities)
    from ..platform_v2.goal_navigation_contracts import GoalNavigationResultHistory
    goal_history = GoalNavigationResultHistory()
    context = None; last_seq = -1; prepared = False
    staged_observation = None; last_observed_seq = -1; last_observed_sim = -1.; feedback_history = None
    while True:
        raw = input_stream.readline(MAX_REQUEST + 1)
        if not raw: return
        if len(raw) > MAX_REQUEST or not raw.endswith(b'\n'):
            raise ContractError('navigation_jsonl_line_oversized_or_partial')
        request = parse_json(raw, MAX_REQUEST)
        if type(request) is not dict or type(request.get('schema')) is not str or request['schema'] != JSONL_SCHEMA or type(request.get('op')) is not str:
            raise ContractError('navigation_jsonl_schema_or_operation')
        op = request['op']
        next_goal_history = None
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
        elif op == 'observe':
            if not staged_profile: raise ContractError('navigation_peer_feedback_unsupported')
            exact(request, ('schema', 'op', 'observation'), 'navigation_peer_observe')
            if context is None: raise ContractError('navigation_peer_reset_required')
            o = validate_navigation_observation(request['observation'])
            if any(type(o[k]) is not type(v) or o[k] != v for k, v in context.items()):
                raise ContractError('navigation_peer_generation')
            if o['observed_seq'] <= max(last_seq, last_observed_seq) or o['sim_time'] < last_observed_sim:
                raise ContractError('navigation_peer_replayed_observation')
            observe = getattr(compute, 'observe', None)
            if not callable(observe): raise ContractError('navigation_peer_observe_callback_required')
            staged_observation = None
            callback_input = copy.deepcopy(o)
            value = observe(callback_input)
            if not same_typed_tree(callback_input, o): raise ContractError('navigation_peer_observe_mutated_input')
            from ..platform_v2.navigation_feedback_contracts import validate_navigation_feedback, NavigationFeedbackHistory
            value = validate_navigation_feedback(value, o)
            if feedback_history is None: feedback_history = NavigationFeedbackHistory()
            feedback_history.check(value)
            staged_observation = copy.deepcopy(o)
            last_observed_seq = o['observed_seq']; last_observed_sim = o['sim_time']
            response = dict(schema=JSONL_SCHEMA, op=op, ok=True, feedback=value)
        elif op == 'act':
            has_intent = 'intent' in request
            fields = (('schema', 'op', 'source', 'intent') if staged_profile else
                ('schema', 'op', 'observation', 'intent') if has_intent else ('schema', 'op', 'observation'))
            exact(request, fields, 'navigation_peer_act')
            if context is None: raise ContractError('navigation_peer_reset_required')
            if staged_profile:
                if staged_observation is None: raise ContractError('navigation_peer_staged_observation_required')
                exact(request['source'], IDENTITY, 'navigation_peer_act_source'); identity(request['source'])
                if not same_typed_tree(request['source'], {k:staged_observation[k] for k in IDENTITY}):
                    raise ContractError('navigation_peer_staged_source_mismatch')
                o = staged_observation; staged_observation = None
            else: o = validate_navigation_observation(request['observation'])
            if any(type(o[k]) is not type(v) or o[k] != v for k, v in context.items()):
                raise ContractError('navigation_peer_generation')
            if o['observed_seq'] <= last_seq: raise ContractError('navigation_peer_replayed_observation')
            if has_intent and not capabilities['goal_input_modes']:
                raise ContractError('navigation_peer_goal_input_unsupported')
            intent = validate_intent(request['intent'], o) if has_intent else None
            if goal_profile and not has_intent:
                raise ContractError('navigation_peer_goal_result_intent_required')
            if capabilities['goal_input_modes'] and not has_intent:
                value = navigation_status_for(o)
            else:
                value = compute(copy.deepcopy(o), copy.deepcopy(intent))
            if goal_profile:
                from ..platform_v2.goal_navigation_contracts import validate_goal_navigation_result
                value = validate_goal_navigation_result(value, o, intent)
                next_goal_history = goal_history.checked_copy(value)
                field = 'result'
            else:
                field, value = validate_result_for_intent(value, o, intent)
            last_seq = o['observed_seq']
            response = dict(schema=JSONL_SCHEMA, op=op, ok=True, **{field: value})
        else: raise ContractError('navigation_peer_operation')
        encoded = encode_json(response, MAX_RESPONSE - 1) + b'\n'
        # A staged producer may own a stricter local computation budget than
        # the foreign host deadline. Check after validation/history/encoding,
        # immediately before writing; the host still bounds actual I/O. A
        # final local expiry may withhold an action, committing only the
        # source-bound status to history. It cannot rewrite an emitted receipt.
        before_emit = getattr(compute, 'before_emit', None) if staged_profile else None
        if before_emit is not None:
            if not callable(before_emit): raise ContractError('navigation_peer_emit_guard_callable_required')
            replacement = before_emit(copy.deepcopy(response), encoded)
            if replacement is not None:
                if op != 'act' or not goal_profile:
                    raise ContractError('navigation_peer_emit_replacement_requires_action')
                original = parse_json(encoded, MAX_RESPONSE)
                original_result = original['result']
                exact(replacement, ('schema', 'op', 'ok', 'result'), 'navigation_peer_emit_replacement')
                if (type(replacement['schema']) is not str or replacement['schema'] != JSONL_SCHEMA
                        or type(replacement['op']) is not str or replacement['op'] != 'act'
                        or replacement['ok'] is not True or 'action' not in original_result):
                    raise ContractError('navigation_peer_emit_replacement_requires_action')
                replacement_value = validate_goal_navigation_result(replacement['result'], o, intent)
                if (any(not same_typed_tree(replacement_value[k], original_result[k])
                        for k in ('schema', 'source', 'intent', 'selection'))
                        or replacement_value['controller_goal_uuid'] is not None
                        or not same_typed_tree(replacement_value.get('status'), navigation_status_for(o))):
                    raise ContractError('navigation_peer_emit_replacement_must_withhold')
                # Start from committed history, not the discarded action preview.
                next_goal_history = goal_history.checked_copy(replacement_value)
                response = dict(schema=JSONL_SCHEMA, op='act', ok=True, result=replacement_value)
                encoded = encode_json(response, MAX_RESPONSE - 1) + b'\n'
        if next_goal_history is not None:
            goal_history = next_goal_history
        output_stream.write(encoded)
        output_stream.flush()


def run_navigation_plugin(compute_factory, *, goal_input_modes=(), goal_result_profile='none'):
    """Keep algorithm/library stdout off the protocol; report shutdown failure."""
    sys.stdout.flush()
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), 'wb', buffering=0)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    compute = None; code = 0
    try:
        compute = compute_factory()
        if not callable(compute): raise ContractError('navigation_compute_callable_required')
        serve_navigation_plugin(compute, sys.stdin.buffer, protocol, goal_input_modes=goal_input_modes,
            goal_result_profile=goal_result_profile)
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
