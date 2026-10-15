"""Opt-in real PB competition-tree decision to registered PB navigation SIL.

The healthy-running scenario uses actual own-referee observations and real BT4
ticks, not a Python policy fixture. Standalone native branch inputs are a
separate scope and never count as actual referee/physical acceptance. No camera,
aiming, firing, map alignment, RTF or complete match is qualified here. All
original 50 ms navigation and 150 ms SDK authority gates remain unchanged.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import secrets
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.qa_registered_pb_goal_sil import (
    RID, IDENTITY, write, digest, typed, source_key, host_input_path,
    peer_inputs as navigation_inputs, peer_spec_reference as navigation_spec_reference,
    copy_sources as registered_copy_sources, read_record, read_lines,
    audit_registered_route, audit_stages, audit_native_estimates, audit_emit_gates,
)


def decision_spec_reference(row):
    command = list(row['command'])
    if command[1:2] == ['-u']:
        command = [command[0], *command[2:]]
    if command[1:3] != ['-m', 'rm_match.integrations.pb_match_decision_peer']:
        raise ValueError('real_native_pb_match_decision_peer_required_no_fixture')
    if len(command) != 7 or command[3] != '--spec' or command[5] != '--sha256':
        raise ValueError('exact_reviewed_pb_match_peer_arguments_required')
    if type(command[6]) is not str or re.fullmatch('[a-f0-9]{64}', command[6]) is None:
        raise ValueError('strict_pb_match_peer_spec_sha256_required')
    return host_input_path(command[4]), command[6]


def validate_graph(graph, pipeline_id):
    """Require two explicitly registered real WSL peers and no aim authority."""
    pipelines = [p for p in graph['pipelines'] if p['adapter_id'] == pipeline_id]
    if len(pipelines) != 1 or pipelines[0]['supported_robots'] != [RID]:
        raise ValueError('one_explicit_red_sentry_pipeline_required')
    pipeline = pipelines[0]
    if graph['rows']['aim'] or len(graph['rows']['navigation']) != 1 or len(graph['rows']['decision']) != 1:
        raise ValueError('single_navigation_and_decision_scope_required')
    nav = graph['rows']['navigation'][0]
    decision = graph['rows']['decision'][0]
    if (nav['adapter_id'] != pipeline['navigation_plugin_id']
        or decision['adapter_id'] != pipeline['decision_plugin_id']):
        raise ValueError('original_registered_pipeline_components_required')
    if (nav['transport'] != 'wsl_jsonl_v1'
        or nav['capabilities']['schema'] != 'polar.sim.navigation-plugin.capabilities.v3'):
        raise ValueError('registered_real_pb_navigation_feedback_v3_required')
    if (decision['transport'] != 'wsl_jsonl_v1'
        or decision['capabilities']['schema'] != 'polar.sim.decision-plugin.capabilities.v2'):
        raise ValueError('registered_wsl_native_decision_feedback_v2_required')
    navigation_spec_reference(nav)
    decision_spec_reference(decision)
    return pipeline, nav, decision


def decision_inputs(row, peer_out):
    """Read the fixed local spec/source refs; native ELF proof is separate."""
    from rm_match.deployment.profile import read_json_snapshot
    from rm_match.deployment.wsl_jsonl import mounted_path
    from rm_match.integrations.pb_match_decision_peer import SPEC_SCHEMA, SOURCE_FILES, UPSTREAM
    path, expected = decision_spec_reference(row)
    spec, sha = read_json_snapshot(path)
    if sha != expected or spec.get('schema') != SPEC_SCHEMA:
        raise ValueError('pb_match_spec_identity_changed')
    if spec.get('out_linux') != mounted_path(peer_out):
        raise ValueError('pb_match_evidence_output_spec_mismatch')
    if typed(spec.get('expected_generation')) != typed(dict(robot_id=RID, episode=0, binding_epoch=1)):
        raise ValueError('probe_pb_match_generation')
    sources = spec.get('source_sha256')
    if type(sources) is not dict or not set(SOURCE_FILES) <= set(sources):
        raise ValueError('pb_match_source_roster_missing')
    paths = {path}
    for relative, expected in sources.items():
        if (type(relative) is not str or '..' in Path(relative).parts
            or '\\' in relative or Path(relative).is_absolute()):
            raise ValueError('pb_match_source_path')
        selected = (ROOT / relative).absolute()
        if not selected.is_relative_to(ROOT) or digest(selected) != expected:
            raise ValueError('pb_match_source_changed:' + relative)
        paths.add(selected)
    # Specs and JSON build/environment refs are mounted immutable inputs. The
    # actual ELF may live on ext4; never pretend a Windows path hash read it.
    for name in ('build_ref', 'environment_ref'):
        ref = spec[name]
        selected = host_input_path(ref['path'])
        if digest(selected) != ref['sha256']:
            raise ValueError('pb_match_' + name + '_changed')
        paths.add(selected)
    build = read_record(host_input_path(spec['build_ref']['path']), {})
    if (build.get('schema') != 'polar.pb.match-decision-build.v1'
        or build.get('passed') is not True or build.get('source_unchanged') is not True
        or typed(build.get('upstream')) != typed(UPSTREAM)
        or typed(build.get('native')) != typed(spec['native_ref'])
        or typed(build.get('xml')) != typed(spec['xml_ref'])
        or build.get('btcpp', {}).get('version') != '4.6.2'):
        raise ValueError('pb_match_actual_build_proof')
    mirror = host_input_path(spec['build_ref']['path']).parent
    source_path = mirror / 'SOURCE_IDENTITY.json'; xml_path = mirror / 'local_rmul_2025.xml'
    if digest(source_path) != build['source_manifest_ref']['sha256'] or digest(xml_path) != spec['xml_ref']['sha256']:
        raise ValueError('native_build_literal_source_or_xml_mirror_changed')
    paths.update((source_path, xml_path))
    source_identity = read_record(source_path, {})
    for linux, expected in source_identity['inputs'].items():
        selected = host_input_path(linux)
        if digest(selected) != expected:
            raise ValueError('native_build_original_source_input_changed')
        paths.add(selected)
    for name in ('ldd.stdout', 'ldd.stderr'):
        selected = mirror / name
        if not selected.is_file():
            raise ValueError('native_build_literal_loader_evidence_missing')
        paths.add(selected)
    return paths


def copy_sources(out, graph, extra_inputs=()):
    # The prior helper is read-only. Include this executing harness explicitly.
    return registered_copy_sources(out, graph, {Path(__file__).resolve(), *extra_inputs})


UPSTREAM_XML_SHA256 = '68e216c145949538444bd8b9f9e97cc1b79b1536ddbc52a37eb00252e20c34f9'
TICK_FIELDS = {'schema', 'tick_number', 'source', 'observation', 'intent', 'tree',
               'node_statuses', 'goal_events', 'anchor', 'mapped_referee'}
ORIGINAL_ACTIVATION_PERIOD_S = .05


def _exact(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError(label + '_exact_fields')


def _finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('native_audit_finite_number')
    return value


def activation_period_s(value):
    """Public SDK activation cadence; it grants no extra source lifetime."""
    try:
        if type(value) not in (str, int, float):
            raise ValueError('period_type')
        period = float(value)
        if not math.isfinite(period) or not .02 <= period <= .06:
            raise ValueError('period_range')
        return period
    except (TypeError, ValueError, OverflowError) as exc:
        raise argparse.ArgumentTypeError('activation-period-s must be finite in [.02, .06]') from exc


def python_switch_interval_s(value):
    """This probe's sole explicit interpreter scheduling opt-in is 1 ms."""
    try:
        if type(value) not in (str, int, float) or not math.isfinite(float(value)) or float(value) != .001:
            raise ValueError('switch_interval')
        return .001
    except (TypeError, ValueError, OverflowError) as exc:
        raise argparse.ArgumentTypeError('python-switch-interval-s only accepts .001; omit it to preserve scheduling') from exc


@contextmanager
def python_switch_interval_scope(requested, record):
    """Bound the opt-in to the real run, restoring even on readback failure."""
    if requested is not None:
        requested = python_switch_interval_s(requested)
    original = sys.getswitchinterval()
    record.update(scope_entered=True, original_s=original, requested_s=requested,
        actual_s=None, changed=False, restore_attempted=False, restored_s=None, restored=False,
        scope_error_type=None, restore_error_type=None,
        scope='CPython thread switch interval only; no source/sensor/SDK deadline changes')
    try:
        if requested is not None:
            sys.setswitchinterval(requested)
        actual = sys.getswitchinterval()
        record.update(actual_s=actual, changed=actual != original)
        if requested is not None and actual != requested:
            raise RuntimeError('python_switch_interval_readback_failed')
        yield record
    except BaseException as exc:
        record['scope_error_type'] = type(exc).__name__
        raise
    finally:
        try:
            if requested is not None:
                record['restore_attempted'] = True
                sys.setswitchinterval(original)
            restored = sys.getswitchinterval()
            record.update(restored_s=restored, restored=restored == original)
            if not record['restored']:
                raise RuntimeError('python_switch_interval_restore_readback_failed')
        except BaseException as exc:
            record['restore_error_type'] = type(exc).__name__
            raise


class ObservedAdapterFault(RuntimeError):
    """Stop this failed probe at its actual fault, retaining partial evidence."""


def stop_on_adapter_fault(row, *, sdk_stop, claim_cleanup, request_stop):
    """Revoke authority and leave the runtime loop using the original budget.

    A normal navigation status is not an adapter fault. No background cleanup
    or fresh deadline is created here; the owner unwinds through run.finally.
    """
    if (row.get('robot_id') != RID or row.get('event') != 'adapter_result' or not row.get('error')):
        return False
    sdk_stop.set()
    claim_cleanup()
    request_stop()
    raise ObservedAdapterFault('actual_adapter_fault:' + str(row['error']))


def _near(a, b):
    return abs(_finite(a) - _finite(b)) <= 1e-12


def _pose(value):
    _exact(value, ('header', 'position_m', 'rotation_xyzw'), 'native_pose')
    _exact(value['header'], ('frame_id', 'stamp'), 'native_pose_header')
    _exact(value['header']['stamp'], ('sec', 'nanosec'), 'native_pose_stamp')
    if type(value['header']['frame_id']) is not str or value['header']['frame_id'] != 'map':
        raise ValueError('native_goal_not_map')
    stamp = value['header']['stamp']
    if (type(stamp['sec']) is not int or stamp['sec'] < 0 or type(stamp['nanosec']) is not int
        or not 0 <= stamp['nanosec'] < 1000000000):
        raise ValueError('native_pose_stamp_type')
    for key, count in (('position_m', 3), ('rotation_xyzw', 4)):
        if type(value[key]) is not list or len(value[key]) != count:
            raise ValueError('native_pose_vector')
        for number in value[key]:
            _finite(number)
    if abs(sum(v * v for v in value['rotation_xyzw']) - 1.) > 1e-5:
        raise ValueError('native_pose_rotation')
    return value


def _yaw(q):
    x, y, z, w = q
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


def _goal_matches_pose(goal, pose):
    return (goal['frame'] == 'map' and len(goal['position_m']) == 2
            and all(_near(a, b) for a, b in zip(goal['position_m'], pose['position_m'][:2]))
            and _near(goal['yaw_rad'], _yaw(pose['rotation_xyzw'])))


def audit_xml_overlay(raw_original, raw_overlay, source_identity, spec):
    """Only the five explicit I/O/local waypoint XML edits are permitted."""
    import xml.etree.ElementTree as ET
    errors = []; changes = 0
    try:
        if (hashlib.sha256(raw_original).hexdigest() != UPSTREAM_XML_SHA256
            or hashlib.sha256(raw_overlay).hexdigest() != spec['xml_ref']['sha256']
            or source_identity['original_xml_sha256'] != UPSTREAM_XML_SHA256
            or source_identity['overlay_xml_sha256'] != spec['xml_ref']['sha256']):
            raise ValueError('original_or_overlay_xml_hash_changed')
        original = ET.fromstring(raw_original); overlay = ET.fromstring(raw_overlay)
        def compare(before, after):
            nonlocal changes
            tag = before.tag; attributes = dict(before.attrib)
            if tag == 'PublishSpinSpeed':
                tag = 'AlwaysSuccess'; attributes = dict(name='spin_disabled_explicit_overlay'); changes += 1
            elif tag == 'PublishTwist':
                if any(float(before.attrib[k]) != 0. for k in ('v_x', 'v_y', 'v_yaw', 'duration')):
                    raise ValueError('upstream_stop_not_zero')
                tag = 'ScopedHold'; attributes = dict(name='game_safety_hold'); changes += 1
            elif tag == 'PubNav2Goal':
                goal = attributes['goal']
                if goal == '0;0;0':
                    attributes.update(goal='{@supply_pose}', name='supply_goal')
                elif goal == '4.65;-3.5;0':
                    attributes.update(goal='{@attack_pose}', name='attack_goal')
                else:
                    raise ValueError('upstream_unreviewed_goal')
                attributes['topic_name'] = 'goal_pose_audit'; changes += 1
            if (after.tag != tag or after.attrib != attributes or len(before) != len(after)
                or (before.text or '').strip() != (after.text or '').strip()):
                raise ValueError('xml_overlay_changed_original_tree_beyond_reviewed_io_edits')
            for left, right in zip(before, after):
                compare(left, right)
        compare(original, overlay)
        if changes != 5 or len(source_identity['overlay']) != 5:
            raise ValueError('exact_five_explicit_overlay_edits_required')
    except (KeyError, TypeError, ValueError, ET.ParseError) as exc:
        errors.append('xml_overlay:' + str(exc))
    return dict(passed=changes == 5 and not errors, errors=errors, explicit_edits=changes,
        scope='same original PB conditions/control tree; spin disabled, source hold and estimated-anchor local waypoints explicit')


def audit_native_identity(ready, cleanup, spec, build):
    """Join native self-/proc/exe and checked XML proof, not just wrapper ACK."""
    from rm_match.integrations.pb_match_decision_peer import UPSTREAM
    errors = []
    try:
        _exact(ready, ('schema', 'run_uuid', 'native_ref', 'xml_ref', 'build_ref',
                       'btcpp_version', 'tick_count', 'goal_sent'), 'native_ready')
        if (ready['schema'] != 'polar.pb.match-decision-native-ready.v1'
            or ready['run_uuid'] != spec['run_uuid'] or ready['btcpp_version'] != '4.6.2'
            or type(ready['tick_count']) is not int or ready['tick_count'] != 0
            or ready['goal_sent'] is not False):
            raise ValueError('native_ready_identity_or_no_warmup')
        for key in ('native_ref', 'xml_ref', 'build_ref'):
            if typed(ready[key]) != typed(spec[key]):
                raise ValueError('native_ready_' + key + '_changed')
        for key in ('native_ref', 'xml_ref', 'build_ref'):
            _exact(spec[key], ('path', 'sha256'), 'native_ref')
            if (type(spec[key]['path']) is not str or not spec[key]['path'].startswith('/')
                or type(spec[key]['sha256']) is not str
                or re.fullmatch('[0-9a-f]{64}', spec[key]['sha256']) is None):
                raise ValueError('native_pinned_ref')
        if (build.get('schema') != 'polar.pb.match-decision-build.v1' or build.get('passed') is not True
            or build.get('source_unchanged') is not True or typed(build.get('upstream')) != typed(UPSTREAM)
            or typed(build.get('native')) != typed(spec['native_ref'])
            or typed(build.get('xml')) != typed(spec['xml_ref'])
            or build.get('btcpp', {}).get('version') != '4.6.2'
            or build.get('ldd', {}).get('all_resolved') is not True):
            raise ValueError('actual_native_build_and_dependencies_unproved')
        commands = build['commands']
        if type(commands) is not list or not commands:
            raise ValueError('actual_native_build_commands_missing')
        for command in commands:
            if (type(command.get('exit_code')) is not int or command['exit_code'] != 0
                or command.get('reaped') is not True):
                raise ValueError('actual_native_build_failed_or_unreaped')
        _exact(cleanup, ('schema', 'clean', 'tick_count', 'tree_halted', 'node_destroyed',
                         'context_shutdown', 'elapsed_s', 'actuator_authority', 'protocol_interrupted'), 'native_cleanup')
        if (cleanup['schema'] != 'polar.pb.match-decision-native-cleanup.v1' or cleanup['clean'] is not True
            or cleanup['tree_halted'] is not True or cleanup['node_destroyed'] is not True
            or cleanup['context_shutdown'] is not True or cleanup['actuator_authority'] != 'none'
            or type(cleanup['protocol_interrupted']) is not bool
            or type(cleanup['tick_count']) is not int or cleanup['tick_count'] < 1
            or not 0 <= _finite(cleanup['elapsed_s']) < 1.3):
            raise ValueError('native_cleanup_unproved')
    except (KeyError, TypeError, ValueError) as exc:
        errors.append('native_identity:' + str(exc))
    return dict(passed=not errors, errors=errors,
        scope='source-pinned native /proc/self/exe + original checked XML + BT4 build/readiness; no localization accuracy claim')


def audit_native_ticks(ticks, spec, *, rows=None, required_branches=(), allow_incomplete_after=None,
                       scope='standalone_native_protocol_inputs'):
    """Audit original real-runner ledgers. Python test ledgers stay test inputs.

    With rows, every public intent must have one original native tick; failed
    shutdown transactions may leave a recorded native tick without a public
    response. This never infers a latest source, RFID, world pose or old goal.
    """
    from rm_match.platform_v2.decision_contracts import validate_decision_observation, validate_decision_intent
    errors = []
    observations = {}; public = {}; ledger = {}; branches = {}; anchor = None; first_estimate = None
    source_order = {}; public_joined = 0; healthy_goals = 0; raw_goals = 0; aborted = set()
    if rows is not None:
        for row in rows:
            try:
                if (row.get('event') == 'peer_exchange_failed' and row.get('peer') == 'decision'
                    and row.get('packet', {}).get('op') == 'act' and allow_incomplete_after is not None
                    and _finite(row['completed_wall']) >= allow_incomplete_after):
                    aborted.add(source_key(row['packet']['observation']))
                if row.get('event') != 'peer_exchange' or row.get('peer') != 'decision' or row['packet']['op'] != 'act':
                    continue
                original = row['packet']['observation']; key = source_key(original)
                if key in observations:
                    raise ValueError('duplicate_public_decision_source')
                observations[key] = original
                public[key] = row['response']['intent']
            except (KeyError, TypeError, ValueError) as exc:
                errors.append('native_public:' + str(exc))
    if type(ticks) is not list or not ticks:
        return dict(passed=False, errors=['native_ticks_missing'], ticks=0, public_intent_joins=0,
                    healthy_current_tick_goals=0, branches={}, scope=scope)
    for index, tick in enumerate(ticks):
        try:
            _exact(tick, TICK_FIELDS, 'native_tick')
            if tick['schema'] != 'polar.pb.match-decision-tick.v1' or type(tick['tick_number']) is not int or tick['tick_number'] != index + 1:
                raise ValueError('native_tick_number_or_schema')
            _exact(tick['source'], IDENTITY, 'native_tick_source')
            original = validate_decision_observation(tick['observation'], profile='own_referee_navigation_v2')
            source = {k: original[k] for k in IDENTITY}; key = source_key(source)
            if typed({k: source[k] for k in ('robot_id', 'episode', 'binding_epoch')}) != typed(spec['expected_generation']):
                raise ValueError('native_tick_not_fixed_generation')
            if typed(source) != typed(tick['source']) or key in ledger:
                raise ValueError('native_tick_original_source_changed_or_duplicate')
            generation = key[:3]; previous = source_order.get(generation)
            if previous is not None and (source['observed_seq'] <= previous['observed_seq'] or source['sim_time'] < previous['sim_time']):
                raise ValueError('native_tick_source_replay')
            source_order[generation] = source
            intent = validate_decision_intent(tick['intent'], original)
            ledger[key] = tick
            if rows is not None and key in public:
                if typed(original) != typed(observations[key]) or typed(intent) != typed(public[key]):
                    raise ValueError('native_tick_not_original_public_observation_and_intent')
                public_joined += 1
            _exact(tick['tree'], ('tree_id', 'xml_sha256', 'upstream_xml_sha256', 'root_status', 'tick_steps'), 'native_tree')
            tree = tick['tree']
            if (tree['tree_id'] != 'rmul_2025' or tree['xml_sha256'] != spec['xml_ref']['sha256']
                or tree['upstream_xml_sha256'] != UPSTREAM_XML_SHA256 or tree['root_status'] != 'RUNNING'
                or type(tree['tick_steps']) is not int or tree['tick_steps'] != 1):
                raise ValueError('native_tree_identity_or_single_tick')
            nodes = tick['node_statuses']
            if type(nodes) is not list or not nodes or len(nodes) > 256:
                raise ValueError('native_real_node_statuses_missing_or_unbounded')
            by_id = {}
            for node in nodes:
                _exact(node, ('path', 'node_id', 'status'), 'native_node')
                if (any(type(node[k]) is not str or not node[k] for k in ('path', 'node_id', 'status'))
                    or node['status'] not in ('SUCCESS', 'FAILURE', 'RUNNING', 'SKIPPED')):
                    raise ValueError('native_node_status_type')
                by_id.setdefault(node['node_id'], []).append(node['status'])
            if 'IsGameStatus' not in by_id or any(k in by_id for k in ('PublishSpinSpeed', 'PublishTwist', 'SendNav2Goal', 'CalculateAttackPose')):
                raise ValueError('native_original_condition_or_explicit_output_overlay')
            nav = original['navigation']['navigation']; own = original['own']; ref = original['referee']
            mapped = dict(game_progress={'running': 4, 'countdown': 3, 'finished': 5}.get(ref['phase'], 0),
                stage_remain_time=math.floor(ref['remaining_seconds']), current_hp=math.floor(own['hp']),
                projectile_allowance_17mm=math.floor(own['ammo']), shooter_17mm_1_barrel_heat=math.ceil(own['heat']),
                integer_policy='hp_ammo_time_floor_heat_ceil', rfid_available=False, perception_available=False)
            if ref['emergency_stop'] or not own['alive']:
                mapped['game_progress'] = 0
            if typed(mapped) != typed(tick['mapped_referee']):
                raise ValueError('native_original_referee_mapping_or_unavailable_rfid')
            if nav['available'] and first_estimate is None:
                first_estimate = copy.deepcopy(original)
            current_anchor = tick['anchor']
            if first_estimate is None:
                if current_anchor is not None:
                    raise ValueError('native_anchor_without_original_estimate')
            else:
                _exact(current_anchor, ('source', 'stamp_ns', 'position_m', 'rotation_xyzw', 'attack_pose', 'supply_pose'), 'native_anchor')
                base = first_estimate['navigation']['navigation']
                if (typed(current_anchor['source']) != typed({k: first_estimate[k] for k in IDENTITY})
                    or typed(current_anchor['stamp_ns']) != typed(base['stamp_ns'])
                    or typed(current_anchor['position_m']) != typed(base['position_m'])
                    or typed(current_anchor['rotation_xyzw']) != typed(base['rotation_xyzw'])):
                    raise ValueError('native_anchor_not_first_original_estimated_feedback')
                for pose_name, offset_name in (('attack_pose', 'attack_offset_m'), ('supply_pose', 'supply_offset_m')):
                    pose = _pose(current_anchor[pose_name]); offset = spec['waypoints'][offset_name]
                    yaw = _yaw(base['rotation_xyzw']) + spec['waypoints']['yaw_offset_rad']
                    if (not all(_near(pose['position_m'][i], base['position_m'][i] + offset[i]) for i in (0, 1))
                        or not _near(pose['position_m'][2], 0.) or pose['header']['stamp'] != dict(sec=0, nanosec=0)
                        or not all(_near(a, b) for a, b in zip(pose['rotation_xyzw'], (0., 0., math.sin(yaw / 2), math.cos(yaw / 2))))):
                        raise ValueError('native_explicit_local_waypoint_overlay_changed')
                if anchor is not None and typed(current_anchor) != typed(anchor):
                    raise ValueError('native_anchor_changed_between_ticks')
                anchor = copy.deepcopy(current_anchor)
            events = tick['goal_events']
            if type(events) is not list or len(events) > 2:
                raise ValueError('native_goal_events_shape')
            allowed = []
            for event in events:
                _exact(event, ('source', 'node_name', 'base_set_message_called', 'allowed', 'reason', 'message'), 'native_goal_event')
                if (typed(event['source']) != typed(source) or event['node_name'] not in ('attack_goal', 'supply_goal')
                    or type(event['base_set_message_called']) is not bool or type(event['allowed']) is not bool
                    or type(event['reason']) is not str):
                    raise ValueError('native_goal_event_original_scoped_source')
                if event['base_set_message_called']:
                    message = _pose(event['message']); raw_goals += 1
                    template = current_anchor['attack_pose' if event['node_name'] == 'attack_goal' else 'supply_pose']
                    if (typed(message['position_m']) != typed(template['position_m'])
                        or typed(message['rotation_xyzw']) != typed(template['rotation_xyzw'])):
                        raise ValueError('native_base_set_message_not_original_overlay_pose')
                elif event['message'] is not None or event['allowed'] or event['reason'] != 'pending_navigation':
                    raise ValueError('native_message_without_upstream_set_message')
                if event['allowed']:
                    if not nav['available'] or not event['base_set_message_called'] or event['reason'] != 'allowed' or event['node_name'] != 'attack_goal':
                        raise ValueError('native_unavailable_or_supply_goal_authorized')
                    allowed.append(event)
                elif event['base_set_message_called'] and event['reason'] not in ('rfid_unavailable', 'upstream_set_message_failed'):
                    raise ValueError('native_rejected_goal_reason')
            if events and by_id.get('PubNav2Goal') != ['SUCCESS' if allowed else 'FAILURE']:
                raise ValueError('native_goal_event_without_real_pub_node_tick')
            game_ok = mapped['game_progress'] == 4 and 0 <= mapped['stage_remain_time'] <= 420
            status_ok = mapped['current_hp'] >= 200 and mapped['shooter_17mm_1_barrel_heat'] <= 350
            if by_id['IsGameStatus'] != ['SUCCESS' if game_ok else 'FAILURE']:
                raise ValueError('native_real_game_condition_status')
            command = intent['command']; branch = 'pending_navigation'
            if not game_ok:
                branch = 'safety_hold'
                if (allowed or events or command['behavior'] != 'hold' or command['reason'] != 'pb_game_or_safety_hold'
                    or by_id.get('ScopedHold') != ['SUCCESS'] or 'IsStatusOK' in by_id):
                    raise ValueError('native_safety_hold_without_current_tree_stop')
            elif not status_ok:
                if by_id.get('IsStatusOK') != ['FAILURE'] or by_id.get('IsRfidDetected') != ['FAILURE'] or allowed:
                    raise ValueError('native_low_status_and_unavailable_rfid_node_path')
                if command['behavior'] != 'hold':
                    raise ValueError('native_rfid_unavailable_not_hold')
                if nav['available']:
                    branch = 'low_status_rfid_unavailable'
                    if (command['reason'] != 'pb_rfid_unavailable' or len(events) != 1
                        or events[0]['node_name'] != 'supply_goal' or events[0]['reason'] != 'rfid_unavailable'
                        or events[0]['base_set_message_called'] is not True):
                        raise ValueError('native_supply_rejection_not_actual_upstream_output')
            else:
                if by_id.get('IsStatusOK') != ['SUCCESS'] or 'IsRfidDetected' in by_id:
                    raise ValueError('native_healthy_original_status_path')
                if nav['available']:
                    branch = 'healthy_current_goal'
                    if (len(allowed) != 1 or len(events) != 1 or command['behavior'] != 'navigate_to_pose'
                        or command['reason'] != 'pb_rmul_2025_current_tick'
                        or not _goal_matches_pose(command['goal'], allowed[0]['message'])):
                        raise ValueError('native_current_set_message_goal_not_original_intent')
                    healthy_goals += 1
                elif command['behavior'] != 'hold' or command['reason'] != 'pb_navigation_unavailable' or allowed:
                    raise ValueError('native_pending_estimate_not_hold')
            branches[branch] = branches.get(branch, 0) + 1
            if branch == 'safety_hold':
                if ref['phase'] == 'paused':
                    branches['paused_hold'] = branches.get('paused_hold', 0) + 1
                if ref['emergency_stop']:
                    branches['emergency_stop_hold'] = branches.get('emergency_stop_hold', 0) + 1
        except (KeyError, TypeError, ValueError) as exc:
            errors.append('native_tick[' + str(index) + ']:' + str(exc))
    if rows is not None:
        missing = set(public) - set(ledger)
        if missing or public_joined != len(public):
            errors.append('native_public_intent_missing_or_unjoined')
        if set(ledger) - set(public) - aborted:
            errors.append('native_unreturned_tick_without_actual_shutdown_abort')
    for branch in required_branches:
        if not branches.get(branch):
            errors.append('native_required_branch_missing:' + branch)
    return dict(passed=bool(ticks) and not errors, errors=errors, ticks=len(ticks),
        public_intent_joins=public_joined, unreturned_native_ticks=len(set(ledger) - set(public)) if rows is not None else 0,
        healthy_current_tick_goals=healthy_goals, original_base_set_message_events=raw_goals,
        branches=branches, scope=scope,
        limitations=['branch protocol inputs are not actual referee ticks unless joined to the real runtime trace',
                     'explicit spin-disabled, sync hold and estimated-anchor local waypoint XML overlay; no official field map alignment'])


def audit_bt_goal_origins(rows, ticks, lifecycle):
    """Every accepted navigation operation starts at an actual current BT goal."""
    decisions = {}; native = {}; errors = []; origins = 0
    for row in rows:
        if (row.get('event') == 'peer_exchange' and row.get('peer') == 'decision'
            and row.get('packet', {}).get('op') == 'act'):
            try:
                key = source_key(row['packet']['observation'])
                if key in decisions:
                    raise ValueError('duplicate_origin_decision')
                decisions[key] = row['response']['intent']
            except (KeyError, TypeError, ValueError) as exc:
                errors.append('bt_origin_decision:' + str(exc))
    for tick in ticks:
        try:
            key = source_key(tick['source'])
            if key in native:
                raise ValueError('duplicate_origin_native_tick')
            native[key] = tick
        except (KeyError, TypeError, ValueError) as exc:
            errors.append('bt_origin_tick:' + str(exc))
    for record in lifecycle.get('goals', []):
        try:
            origin = record['origin_intent']; key = source_key(origin); tick = native[key]
            allowed = [event for event in tick['goal_events'] if event['allowed'] is True]
            if (typed(origin) != typed(decisions[key]) or typed(origin) != typed(tick['intent'])
                or origin['command']['behavior'] != 'navigate_to_pose' or len(allowed) != 1
                or allowed[0]['base_set_message_called'] is not True
                or typed(allowed[0]['source']) != typed({k: origin[k] for k in IDENTITY})
                or not _goal_matches_pose(origin['command']['goal'], _pose(allowed[0]['message']))
                or typed(record['goal']) != typed(origin['command']['goal'])):
                raise ValueError('accepted_goal_not_original_current_native_set_message')
            origins += 1
        except (KeyError, TypeError, ValueError) as exc:
            errors.append('bt_origin:' + str(exc))
    return dict(passed=origins > 0 and not errors, errors=errors, original_native_goal_origins=origins,
        scope='actual scoped upstream setMessage -> original decision intent -> accepted navigation operation')


def audit_public_consumption(rows):
    """Status and withheld native candidates cannot stand in for public actions."""
    public = {}; errors = []; steps = set(); nonzero = set(); source_results = set()
    for row in rows:
        if (row.get('event') != 'peer_exchange' or row.get('peer') != 'navigation'
            or row.get('packet', {}).get('op') != 'act'):
            continue
        try:
            result = row['response']['result']; key = source_key(result['source'])
            if key in source_results:
                raise ValueError('duplicate_public_source_result')
            source_results.add(key)
            if 'action' in result:
                public[(key, typed(result['action']))] = result['controller_goal_uuid']
        except (KeyError, TypeError, ValueError) as exc:
            errors.append('public_action:' + str(exc))
    for row in rows:
        if row.get('event') != 'navigation_consumed' or row.get('phase') != 'integration_entry':
            continue
        try:
            motion = row['target'].get('motion')
            if motion is None:
                continue
            action = row['action']; key = (source_key(action), typed(action))
            if key not in public or typed(motion) != typed(action['command']):
                raise ValueError('physical_consumption_without_exact_returned_public_action')
            step = (action['robot_id'], row['consume_sim_time'])
            if step in steps:
                raise ValueError('duplicate_public_physical_step')
            steps.add(step)
            if any(abs(motion[k]) > 1e-8 for k in ('vx_mps', 'vy_mps', 'wz_rps')):
                nonzero.add(step)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append('public_consumption:' + str(exc))
    return dict(passed=bool(public and nonzero) and not errors, errors=errors,
        returned_public_actions=len(public), exact_public_physical_steps=len(steps), nonzero_public_steps=len(nonzero),
        scope='actual returned complete action only; statuses and failed/withheld native candidates grant no consumption')


def audit_final_navigation_results(rows, finals, rejected, stages, *, ros_rows=(), allow_incomplete_after=None):
    """Join final wire receipts and late rejected actions independently.

    Expired native actions may become same-source status; they do not receive
    a new 50 ms gate or actuator authority. A final producer record alone is
    never counted as a public response or physical consumption.
    """
    from rm_match.platform_v2.goal_navigation_contracts import validate_goal_navigation_result
    from rm_match.integrations.ros2_bridge import encode_json, MAX_RESPONSE
    from rm_match.deployment.json_adapter import SCHEMA as JSONL_SCHEMA
    originals = {}; requests = {}; public = {}; aborted = set(); begins = {}; recorded = {}; errors = []
    rejected_keys = set(); joined = 0; withheld = 0
    for row in rows:
        try:
            event = row.get('event'); packet = row.get('packet', {})
            if row.get('peer') != 'navigation' or event not in ('peer_exchange', 'peer_exchange_failed'):
                continue
            if packet.get('op') == 'observe' and event == 'peer_exchange':
                original = packet['observation']; key = source_key(original)
                if key in originals:
                    raise ValueError('duplicate_final_original_observe')
                originals[key] = original
            elif packet.get('op') == 'act':
                key = source_key(packet['source'])
                if key in requests:
                    raise ValueError('duplicate_final_act_request')
                requests[key] = packet
                if event == 'peer_exchange':
                    public[key] = row['response']['result']
                elif (allow_incomplete_after is not None
                      and _finite(row['completed_wall']) >= allow_incomplete_after):
                    aborted.add(key)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append('final_route:' + str(exc))
    for stage in stages:
        if stage.get('event') == 'stage_begin':
            try:
                begins.setdefault(source_key(stage['source']), []).append(stage)
            except (KeyError, TypeError, ValueError) as exc:
                errors.append('final_stage:' + str(exc))
    for final in finals:
        try:
            key = source_key(final['source'])
            if key in recorded:
                raise ValueError('duplicate_final_wire_receipt')
            value = validate_goal_navigation_result(final, originals[key], requests[key]['intent'])
            recorded[key] = value
            if key in public:
                if typed(value) != typed(public[key]):
                    raise ValueError('final_wire_receipt_not_actual_public_result')
                joined += 1
            elif key not in aborted:
                raise ValueError('final_wire_receipt_without_actual_response_or_shutdown_abort')
        except (KeyError, TypeError, ValueError) as exc:
            errors.append('final_record:' + str(exc))
    if set(public) - set(recorded) or joined != len(public):
        errors.append('actual_public_result_missing_final_wire_receipt')
    for rejection in rejected:
        try:
            base = {'reason', 'original_deadline', 'rejected_wall', 'result'}
            if type(rejection) is not dict or set(rejection) not in (base, base | {'encoded_sha256'}):
                raise ValueError('rejected_original_candidate_fields')
            candidate = rejection['result']; key = source_key(candidate['source'])
            if key in rejected_keys:
                raise ValueError('duplicate_rejected_original_candidate')
            rejected_keys.add(key)
            validate_goal_navigation_result(candidate, originals[key], requests[key]['intent'])
            if 'action' not in candidate or len(begins.get(key, [])) != 1:
                raise ValueError('rejected_original_action_or_stage_missing')
            begin = begins[key][0]
            if (typed(rejection['original_deadline']) != typed(begin['local_deadline'])
                or not 0 < _finite(begin['response_timeout_s']) <= .05
                or abs(begin['local_deadline'] - begin['begin_wall'] - begin['response_timeout_s']) > 1e-9
                or _finite(rejection['rejected_wall']) < begin['local_deadline']
                or rejection['reason'] not in ('original_stage_deadline_expired', 'encoded_stage_deadline_expired')):
                raise ValueError('rejected_original_50ms_deadline_not_proved')
            candidates = [row for row in ros_rows if row.get('topic_kind') == 'controller_result'
                and typed(row.get('value', {}).get('action')) == typed(candidate['action'])
                and row.get('value', {}).get('source', {}).get('goal_uuid') == candidate['controller_goal_uuid']]
            if not any(row.get('receive_clock') == 'linux_local_perf_counter'
                and begin['begin_wall'] <= _finite(row['receive_wall']) < begin['local_deadline'] for row in candidates):
                raise ValueError('rejected_original_candidate_missing_actual_native_action_in_stage')
            if 'encoded_sha256' in rejection:
                response = dict(schema=JSONL_SCHEMA, op='act', ok=True, result=candidate)
                if hashlib.sha256(encode_json(response, MAX_RESPONSE - 1) + b'\n').hexdigest() != rejection['encoded_sha256']:
                    raise ValueError('rejected_original_encoded_candidate_hash_changed')
            final = recorded.get(key)
            if final is None:
                if key not in aborted:
                    raise ValueError('rejected_candidate_without_final_status_or_shutdown_abort')
            elif (set(final) != {'schema', 'source', 'intent', 'selection', 'controller_goal_uuid', 'status'}
                  or final['controller_goal_uuid'] is not None or final['status']['status'] != 'no_associated_command'
                  or any(typed(final[name]) != typed(candidate[name]) for name in ('source', 'intent', 'selection'))):
                raise ValueError('rejected_candidate_retagged_or_final_action_instead_of_status')
            else:
                withheld += 1
        except (KeyError, TypeError, ValueError) as exc:
            errors.append('rejected_record:' + str(exc))
    for row in rows:
        if (row.get('event') == 'navigation_consumed' and row.get('phase') == 'integration_entry'
            and row.get('target', {}).get('motion') is not None):
            try:
                if source_key(row['action']) in rejected_keys:
                    errors.append('rejected_original_action_was_physically_consumed')
            except (KeyError, TypeError, ValueError) as exc:
                errors.append('rejected_consumption:' + str(exc))
    return dict(passed=bool(public) and joined == len(public) and not errors, errors=errors,
        public_final_result_joins=joined, final_wire_receipts=len(recorded), rejected_action_candidates=len(rejected_keys),
        rejected_actions_withheld_as_final_status=withheld,
        scope='same original source/intent/selection; expired action -> no_associated_command status; no extra actuator gate')

def run(out,args,graph):
    from rm_match.deployment.json_adapter import SharedCleanupBudget
    from rm_match.deployment.profile import digest as manifest_digest
    from rm_match.deployment.robotio_plugin import register_robotio_plugins,prepare_robotio_resources
    from rm_match.deployment.robotio_wsl import WslNavigationPluginAdapter,WslDecisionPluginAdapter
    from rm_match.platform_v2.adapters import Registry
    from rm_match.platform_v2.backend import MuJoCoBackend
    from rm_match.platform_v2.runtime import PlatformRuntime
    from rm_match.platform_v2.server import PlatformHTTPServer,TransportConfig
    from rm_match.platform_v2.admission import AdmissionPolicy
    from rm_match.platform_v2.client import PlatformClient
    from rm_match.navigation_sensors import NavigationSensorConfig

    pipeline_row,nav_row,_=validate_graph(graph,args.pipeline_id)
    rows=[];lock=threading.Lock();errors=[];pools={};instance=None;unclaimed=True;transferred=False
    runtime=backend=server=http=sdk_thread=None
    sdk_stop=threading.Event();sdk_done=threading.Event();budget=SharedCleanupBudget()
    prepared=[];cleanup_started=None;cleanup_deadline=None;binding=None;sdk_elapsed=None
    def retain(row):
        with lock:
            if len(rows)>=60000:raise RuntimeError('bounded_registered_trace_full')
            saved=copy.deepcopy(row);saved['record_index']=len(rows);rows.append(saved)
    def claim_cleanup():
        nonlocal cleanup_started,cleanup_deadline
        if cleanup_deadline is None:
            cleanup_deadline=budget.claim();cleanup_started=cleanup_deadline-1.5
        sdk_stop.set()
        return cleanup_deadline
    def remaining():return max(0.,claim_cleanup()-time.perf_counter())
    def exchanged(original,peer_name,packet,**kwargs):
        started=time.perf_counter()
        try:response=original(packet,**kwargs)
        except BaseException as exc:
            retain(dict(event='peer_exchange_failed',peer=peer_name,packet=packet,
                started_wall=started,completed_wall=time.perf_counter(),error_type=type(exc).__name__))
            raise
        retain(dict(event='peer_exchange',peer=peer_name,packet=packet,response=response,
            started_wall=started,completed_wall=time.perf_counter()))
        return response
    def snapshot_peers():
        return {} if instance is None else {name:copy.deepcopy(getattr(instance,name).shutdown_status)
            for name in ('navigation','decision')}
    def close_unclaimed():
        nonlocal unclaimed
        limit=claim_cleanup()
        if instance is not None and unclaimed:
            instance.close()
            if not instance.shutdown_status or not instance.shutdown_status.get('clean'):
                raise RuntimeError('unclaimed_pipeline_cleanup_unproved')
            unclaimed=False
        for pool in pools.values():pool.close_unclaimed(deadline=limit)

    prepare_started=time.perf_counter()
    try:
        # Instrument the actual pool's prepare exchange. This preserves all
        # arguments, responses and ownership; no prepare/reset ACK is cached.
        prepare_classes={'navigation':WslNavigationPluginAdapter,'decision':WslDecisionPluginAdapter}
        originals={name:cls._exchange for name,cls in prepare_classes.items()}
        for name,cls in prepare_classes.items():
            original=originals[name]
            def prepare_exchange(peer,packet,name=name,original=original,**kwargs):
                return exchanged(lambda p,**kw:original(peer,p,**kw),name,packet,**kwargs)
            cls._exchange=prepare_exchange
        try:pools=prepare_robotio_resources(args.manifest,repo_root=ROOT,shared_root=out/'resources')
        except BaseException as exc:
            orphan=getattr(exc,'resources',None)
            if type(orphan) is dict:pools=orphan
            elif orphan is not None and hasattr(orphan,'close_unclaimed'):pools={'failed_preparation':orphan}
            raise
        finally:
            for name,cls in prepare_classes.items():cls._exchange=originals[name]
        registry=Registry()
        registration=register_robotio_plugins(registry,args.manifest,wsl_prepared=pools)
        write(out/'REGISTRATION.json',dict(result=registration,descriptors=registry.descriptors(),catalog=registry.plugin_catalog()))
        spec=registry.get(args.pipeline_id);instance=spec.factory({})
        instance._budget=budget
        for peer in (instance.navigation,instance.decision):peer._resource_budget=budget
        for name in ('navigation','decision'):
            peer=getattr(instance,name);original_exchange=peer._exchange
            def observe_exchange(packet,name=name,original_exchange=original_exchange,**kwargs):
                return exchanged(original_exchange,name,packet,**kwargs)
            peer._exchange=observe_exchange
        # Both actual WSL peers completed a real prepare ACK in the pool.
        # A second prepare would discard native state and is forbidden.
        if not instance.decision._prepared:raise RuntimeError('native_decision_not_prepared_in_pool')
        for name in ('navigation','decision'):
            peer=getattr(instance,name)
            if peer.process is None or peer.process.poll() is not None:raise RuntimeError('prepared_peer_unavailable')
            prepared.append(dict(peer=name,prepared=True,process_identity=getattr(peer.process,'pid',None),
                ownership_hello=copy.deepcopy(getattr(peer._owned_process,'hello',None)),
                capabilities=peer.registration['capabilities'],sensor_frames=0,policy_calls=0))
        def handover(config):
            nonlocal unclaimed,transferred
            if type(config) is not dict or config or not unclaimed:raise RuntimeError('prepared_pipeline_handover_once')
            for path,sha in graph['hashes'].items():
                if manifest_digest(Path(path))!=sha:raise RuntimeError('prepared_pipeline_graph_changed')
            for peer in (instance.navigation,instance.decision):
                if peer.failed or peer._cancelled.is_set() or peer.process is None or peer.process.poll() is not None:
                    raise RuntimeError('prepared_pipeline_resource_unavailable')
            unclaimed=False
            transferred=True
            return instance
        registry._specs[args.pipeline_id]=type(spec)(spec.descriptor,handover)
        write(out/'PREPARE.json',dict(passed=True,peers=prepared,elapsed_s=time.perf_counter()-prepare_started,
            physics_steps=0,sensor_frames=0,algorithm_data_warmup=False))

        config=NavigationSensorConfig(robot_ids=(RID,),point_rate_hz=200000)
        backend=MuJoCoBackend(navigation_sensors=config)
        def trace(row):
            if row.get('robot_id')!=RID:return
            if row['event'] in ('adapter_enqueue','adapter_result'):
                retain(row)
                stop_on_adapter_fault(row, sdk_stop=sdk_stop, claim_cleanup=claim_cleanup,
                                      request_stop=runtime.request_stop)
                return
            if row['event']!='actuator_consumed' or row['phase']!='integration_entry':return
            auth=row['adapter_authorizations']['navigation']
            retain(dict(event='navigation_consumed',phase=row['phase'],consume_wall=row['consume_wall'],
                consume_sim_time=row['consume_sim_time'],target=row['target'],
                action=runtime.outputs.get((RID,'navigation')),navigation_budget=runtime.output_budgets.get((RID,'navigation')),
                output_authorization=runtime.output_authorizations.get((RID,'navigation')),
                authorization={k:auth.get(k) for k in ('epoch','activation_required','activation_seq',
                    'activation_expires','activation_window_id','activation_window_deadline')}))
        runtime=PlatformRuntime(backend,registry=registry,trace=trace,action_ttl=.15)
        credential=secrets.token_urlsafe(32)
        policy=AdmissionPolicy([dict(credential_sha256=hashlib.sha256(credential.encode()).hexdigest(),
            role='operator',allowed_robots=[RID],audit_authorized=False)])
        server=PlatformHTTPServer(TransportConfig(port=0,admission_policy=policy),runtime)
        http=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},name='registered-pb-http',daemon=True)
        http.start();base='http://127.0.0.1:'+str(server.server_address[1])
        def actor():
            nonlocal binding,sdk_elapsed
            client=PlatformClient(base,admission_credential=credential,control_profile='server_window_v1',timeout=.25)
            claimed=False;started=None
            try:
                client.open('operator');client.claim(RID,['motion']);claimed=True
                binding=client.bind_pipeline(RID,args.pipeline_id)
                if type(binding['binding_epoch']) is not int or binding['binding_epoch']!=1:
                    raise RuntimeError('single_actual_binding_generation_required')
                retain(dict(event='sdk_pipeline_bound',robot_id=RID,pipeline_id=args.pipeline_id,binding=binding))
                started=time.perf_counter();deadline=started+args.seconds;next_tick=started;renewed=started
                while not sdk_stop.is_set() and time.perf_counter()<deadline:
                    now=time.perf_counter()
                    if now-renewed>=.25:client.renew(RID,['motion']);renewed=time.perf_counter()
                    if sdk_stop.is_set():break
                    window=client.control_window(RID,['motion'])
                    if sdk_stop.is_set():break
                    activation=client.adapter_input(RID,'navigation',1,window_id=window['window_id'],valid_for_s=.15)
                    ack=time.perf_counter()
                    retain(dict(event='sdk_adapter_activation',wall_time=ack,
                        window={k:window[k] for k in ('window_id','issued_wall','expires_wall','valid_for_s','lease_epochs')},
                        activation={k:activation[k] for k in ('binding_epoch','seq','window_id','activation_expires')}))
                    next_tick+=args.activation_period_s
                    if next_tick<=ack:
                        next_tick+=(math.floor((ack-next_tick)/args.activation_period_s)+1)*args.activation_period_s
                    sdk_stop.wait(min(max(0.,deadline-time.perf_counter()),max(0.,next_tick-time.perf_counter())))
                sdk_elapsed=time.perf_counter()-started
            except BaseException as exc:
                errors.append('sdk:'+type(exc).__name__)
                (out/'SDK_FAILURE.log').write_text(traceback.format_exc(),encoding='utf8')
            finally:
                limit=claim_cleanup()
                for name,callback in (('release',lambda:client.release(RID,['motion']) if claimed else None),('close',client.close)):
                    try:
                        left=limit-time.perf_counter()
                        if left<=0:raise TimeoutError('original_shared_cleanup_expired')
                        client.timeout=min(.25,left);callback()
                    except BaseException as exc:errors.append('sdk_'+name+':'+type(exc).__name__)
                sdk_done.set()
                runtime.request_stop()
        sdk_thread=threading.Thread(target=actor,name='registered-pb-sdk',daemon=True)
        sdk_thread.start()
        runtime.run(max_wall_seconds=args.max_wall_seconds,real_time_factor=1.)
        if not sdk_done.is_set():raise RuntimeError('controlled_sdk_span_incomplete')
    except BaseException as exc:
        errors.append(type(exc).__name__)
        (out/'FAILURE.log').write_text(traceback.format_exc(),encoding='utf8')
    finally:
        limit=claim_cleanup()
        if runtime is not None and not runtime._closed:
            try:runtime.close()
            except BaseException as exc:errors.append('runtime_cleanup:'+type(exc).__name__)
        elif runtime is None and backend is not None:
            try:backend.close()
            except BaseException as exc:errors.append('backend_cleanup:'+type(exc).__name__)
        if sdk_thread is not None:sdk_thread.join(remaining())
        try:close_unclaimed()
        except BaseException as exc:errors.append('unclaimed_cleanup:'+type(exc).__name__)
        if server is not None:
            try:
                if http is not None and http.is_alive():server.shutdown()
                server.server_close()
                if http is not None:http.join(remaining())
            except BaseException as exc:errors.append('http_cleanup:'+type(exc).__name__)
        cleanup=dict(runtime=None if runtime is None else runtime.shutdown_status,
            pipeline=None if instance is None else instance.shutdown_status,peers=snapshot_peers(),
            pools={name:copy.deepcopy(pool.cleanup_status) for name,pool in pools.items()},
            sdk_stopped=sdk_thread is None or not sdk_thread.is_alive(),
            http_stopped=http is None or not http.is_alive(),
            http_workers_idle=server is None or server._slots._value==server.config.max_http_workers,
            shared_host_budget_s=1.5,cleanup_elapsed_s=time.perf_counter()-cleanup_started,
            shared_host_started_wall=cleanup_started,
            finished_within_shared_host_budget=time.perf_counter()<=limit)
        write(out/'CLEANUP.json',cleanup)

    with lock:captured=copy.deepcopy(rows)
    with (out/'TRACE.jsonl.gz').open('wb') as raw:
        with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as stream:
            for row in captured:stream.write(json.dumps(row,allow_nan=False,separators=(',',':')).encode()+b'\n')
    # The only world-state read in this tool is isolated evaluation after
    # authority, workers and peer ownership have stopped.
    if runtime is not None:
        write(out/'EVAL.json',dict(source='isolated_post_shutdown_evaluation_never_peer_input',
            robot=next(r for r in runtime.cached['robots'] if r['robot_id']==RID)))
    return dict(errors=errors,rows=captured,cleanup=cleanup,sdk_elapsed_s=sdk_elapsed,
        steps=0 if runtime is None else runtime.steps,
        timestep=None if backend is None else backend.timestep,
        pipeline_handed_over=transferred,
        qualification='registered_real_PB_BT4_healthy_running_one_route_not_complete_match_or_RTF')


def _peer_index(peer):
    return dict(root=str(peer), files=[dict(path=p.relative_to(peer).as_posix(), size=p.stat().st_size, sha256=digest(p))
        for p in sorted(peer.rglob('*')) if p.is_file()] if peer.is_dir() else [])


def _decision_records(peer, spec):
    build = read_record(host_input_path(spec['build_ref']['path']), {})
    if digest(host_input_path(spec['build_ref']['path'])) != spec['build_ref']['sha256']:
        raise ValueError('actual_decision_build_changed')
    return (read_record(peer / 'READY.json', {}), read_record(peer / 'CLEANUP.json', {}),
            read_lines(peer / 'native_ticks.jsonl'), build)


def audit_build_mirror(spec, build):
    """Read-only Windows mirror retains original ext4 paths and literal bytes."""
    errors = []; overlay = dict(passed=False, errors=['not_read'])
    try:
        mirror = host_input_path(spec['build_ref']['path']).parent
        raw_identity = (mirror / 'SOURCE_IDENTITY.json').read_bytes()
        if hashlib.sha256(raw_identity).hexdigest() != build['source_manifest_ref']['sha256']:
            raise ValueError('literal_build_source_manifest_mirror_hash_changed')
        source_identity = read_record(mirror / 'SOURCE_IDENTITY.json', {})
        if source_identity.get('schema') != 'polar.pb.match-decision-source.v1':
            raise ValueError('actual_build_source_manifest_schema')
        from rm_match.integrations.pb_match_decision_peer import UPSTREAM
        if typed(source_identity['upstream']) != typed(UPSTREAM):
            raise ValueError('actual_build_upstream_changed')
        for linux, expected in source_identity['inputs'].items():
            if digest(host_input_path(linux)) != expected:
                raise ValueError('actual_native_build_input_changed')
        raw_original = (ROOT / 'artifacts/pb-match-behavior-audit-20261014-01/pb2025_sentry_behavior/behavior_trees/rmul_2025.xml').read_bytes()
        overlay = audit_xml_overlay(raw_original, (mirror / 'local_rmul_2025.xml').read_bytes(), source_identity, spec)
        if not overlay['passed']:
            raise ValueError('actual_native_xml_overlay_audit_failed')
        loader = (mirror / 'ldd.stdout').read_bytes()
        if not loader or b'not found' in loader or (mirror / 'ldd.stderr').read_bytes().strip():
            raise ValueError('actual_native_loader_log_unresolved')
    except (KeyError, TypeError, ValueError, OSError) as exc:
        errors.append('build_mirror:' + str(exc))
    return dict(passed=not errors and overlay['passed'], errors=errors, overlay=overlay,
        scope='literal build-result/source/XML/loader mirrors; native readiness separately proves actual ext4 self-read')


def evaluate(out, args, execution, graph):
    from tools.audit_navigation_goals import audit_goal_navigation_consumption
    _, nav, decision = validate_graph(graph, args.pipeline_id)
    nav_spec = read_record(navigation_spec_reference(nav)[0], {})
    decision_spec = read_record(decision_spec_reference(decision)[0], {})
    config = read_record(host_input_path(nav_spec['config_ref']['path']), {})
    provenance = dict(producer_source_sha256=nav_spec['source_sha256']['rm_match/integrations/pb_goal_plugin_source.py'],
        localization_binary_sha256=config['assets']['point_lio']['sha256'],
        mapping_binary_sha256=config['assets']['slam_toolbox']['sha256'])
    peer = args.peer_evidence_dir
    ros = read_lines(peer / 'ROS_SOURCE.jsonl'); stages = read_lines(peer / 'STAGES.jsonl')
    gates = read_lines(peer / 'EMIT_GATES.jsonl')
    final_results = read_lines(peer / 'ACT_RESULTS.jsonl'); rejected_results = read_lines(peer / 'REJECTED_RESULTS.jsonl')
    goal = read_record(peer / 'GOAL_REPORT.json', {}); peer_cleanup = read_record(peer / 'CLEANUP.json', {})
    lifecycle = goal.get('lifecycle', {})
    ready, native_cleanup, ticks, build = _decision_records(args.decision_evidence_dir, decision_spec)
    rows = execution.pop('rows'); cleanup = execution['cleanup']; cutoff = cleanup['shared_host_started_wall']
    route = audit_registered_route(rows, allow_incomplete_after=cutoff)
    stage = audit_stages(rows, stages, ros)
    emit = audit_emit_gates(rows, gates, stages)
    motion = audit_goal_navigation_consumption(rows, ros, lifecycle)
    estimates = audit_native_estimates(rows, ros, provenance)
    identity = audit_native_identity(ready, native_cleanup, decision_spec, build)
    build_mirror = audit_build_mirror(decision_spec, build)
    native = audit_native_ticks(ticks, decision_spec, rows=rows, required_branches=('healthy_current_goal',),
        allow_incomplete_after=cutoff, scope='actual_registered_runtime_own_referee_and_estimated_navigation_trace')
    origins = audit_bt_goal_origins(rows, ticks, lifecycle)
    public = audit_public_consumption(rows)
    final_wire = audit_final_navigation_results(rows, final_results, rejected_results, stages,
        ros_rows=ros, allow_incomplete_after=cutoff)
    audits = dict(ROUTE_AUDIT=route, STAGE_AUDIT=stage, EMIT_GATE_AUDIT=emit, GOAL_MOTION_AUDIT=motion,
        ESTIMATE_AUDIT=estimates, NATIVE_IDENTITY_AUDIT=identity, NATIVE_BUILD_MIRROR_AUDIT=build_mirror, NATIVE_TICK_AUDIT=native,
        BT_GOAL_ORIGIN_AUDIT=origins, PUBLIC_CONSUMPTION_AUDIT=public, FINAL_NAVIGATION_RESULTS_AUDIT=final_wire)
    for name, value in audits.items():
        write(out / (name + '.json'), value)
    write(out / 'PB_RESULT.json', dict(goal=goal, cleanup=peer_cleanup, expected_estimate_provenance=provenance))
    write(out / 'DECISION_RESULT.json', dict(ready=ready, cleanup=native_cleanup, expected_spec=decision_spec))
    write(out / 'NAVIGATION_EVIDENCE_INDEX.json', _peer_index(peer))
    write(out / 'DECISION_EVIDENCE_INDEX.json', _peer_index(args.decision_evidence_dir))
    prepare_acks = [r for r in rows if r.get('event') == 'peer_exchange' and r['packet']['op'] == 'prepare']
    actual_goals = lifecycle.get('goals', [])
    goal_stops = bool(actual_goals) and all(r.get('terminal') is True and r.get('stop_confirmed') is True
        and r.get('goal_uuids', {}).get('navigation') for r in actual_goals)
    peer_clean = bool(peer_cleanup.get('clean') is True and peer_cleanup.get('goal_stop_confirmed') is True
        and peer_cleanup.get('source_unchanged') is True and peer_cleanup.get('gate_clean') is True
        and peer_cleanup.get('transport_clean') is True and peer_cleanup.get('stack', {}).get('clean') is True
        and type(peer_cleanup.get('elapsed_s')) in (int, float) and 0 <= peer_cleanup['elapsed_s'] <= 1.3)
    cleanup_ok = bool(cleanup['runtime'] and cleanup['runtime'].get('clean') is True
        and cleanup['pipeline'] and cleanup['pipeline'].get('clean') is True
        and cleanup['sdk_stopped'] and cleanup['http_stopped'] and cleanup['http_workers_idle']
        and cleanup['finished_within_shared_host_budget'])
    checks = dict(original_2ms_timestep=execution['timestep'] == .002, actual_physics_steps=execution['steps'] > 0,
        actual_two_distinct_owned_wsl_prepare_acks=len(prepare_acks) == 2 and {r['peer'] for r in prepare_acks} == {'navigation', 'decision'},
        actual_prepared_registered_pipeline_sdk_handover=execution['pipeline_handed_over'],
        original_observe_decision_v2_compact_act_route=route['passed'],
        original_actual_native_LIO_exact_TF_estimates=estimates['passed'],
        actual_native_ELF_XML_BT4_and_cleanup_identity=identity['passed'],
        actual_literal_build_source_XML_loader_proof=build_mirror['passed'],
        actual_current_tick_original_PB_condition_goal_route=native['passed'],
        original_upstream_setMessage_to_accepted_goal=origins['passed'],
        original_linux_50ms_stage_without_republication=stage['passed'],
        final_encoded_action_within_original_50ms=emit['passed'],
        native_UUID_SDK_sensor_physical_join=motion['passed'],
        physical_receipts_only_from_actual_public_actions=public['passed'],
        final_wire_results_and_expired_candidate_status_join=final_wire['passed'],
        all_original_goal_handles_terminal_stop_before_cleanup=goal_stops,
        native_cleanup_tick_count_matches_ledger=native_cleanup.get('tick_count') == len(ticks),
        original_150ms_controlled_sdk_span=execution['sdk_elapsed_s'] is not None
            and args.seconds <= execution['sdk_elapsed_s'] <= args.max_wall_seconds,
        actual_lifecycle_clean=lifecycle.get('clean') is True and lifecycle.get('fault') is None,
        actual_navigation_peer_cleanup_clean=peer_clean, all_host_resources_within_shared_1_5s=cleanup_ok,
        no_actual_adapter_fault=not any(r.get('event') == 'adapter_result' and r.get('error') for r in rows),
        errors_empty=not execution['errors'])
    return dict(passed=all(checks.values()), checks=checks, errors=execution['errors'], steps=execution['steps'],
        controlled_sdk_span_s=execution['sdk_elapsed_s'], audits={name: value for name, value in audits.items()},
        qualification=execution['qualification'],
        limitations=['healthy running actual PB BT4 route with explicit XML I/O/local waypoint overlay only',
            'standalone low-status/RFID/pause/e-stop inputs are separate; no actual runtime negative branch acceptance here',
            'PB original tree has no receipt completion policy; no synthetic final policy hold is required or inferred',
            'no camera, aiming, firing, Qt, RTF, field-map alignment, complete 3v3/7v7 or cross-machine DDS acceptance',
            'exact TF/LIO source and ELF pins show the producer route, not ground-truth localization accuracy'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--pipeline-id')
    parser.add_argument('--peer-evidence-dir', type=Path)
    parser.add_argument('--decision-evidence-dir', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=15.)
    parser.add_argument('--max-wall-seconds', type=float, default=30.)
    parser.add_argument('--activation-period-s', type=activation_period_s, default=ORIGINAL_ACTIVATION_PERIOD_S,
                        help='real public SDK window/activation cadence, [.02,.06] seconds; original source gates unchanged')
    parser.add_argument('--python-switch-interval-s', type=python_switch_interval_s, default=None,
                        help='explicit .001 CPython scheduling opt-in for actual run; default preserves interpreter setting')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--audit-native-only', action='store_true')
    parser.add_argument('--decision-spec', type=Path)
    parser.add_argument('--decision-spec-sha256')
    parser.add_argument('--require-branch', action='append', default=[])
    args = parser.parse_args(argv)
    if args.run == args.audit_native_only:
        parser.error('choose exactly one explicit --run or --audit-native-only')
    if args.audit_native_only and args.python_switch_interval_s is not None:
        parser.error('python-switch-interval-s applies only to an explicit actual --run')
    args.out = args.out.absolute(); args.decision_evidence_dir = args.decision_evidence_dir.absolute()
    if args.out.exists() or not args.out.is_relative_to(ROOT / 'artifacts'):
        raise ValueError('fresh_explicit_repo_artifact_output_required')
    if not args.decision_evidence_dir.is_relative_to(ROOT / 'artifacts') or args.decision_evidence_dir == args.out:
        raise ValueError('explicit_separate_repo_decision_evidence_required')
    records = []; started = time.perf_counter(); result = {}; code = 2
    if args.audit_native_only:
        if args.decision_spec is None or args.decision_spec_sha256 is None:
            parser.error('native-only audit requires fixed --decision-spec and --decision-spec-sha256')
        spec_path = args.decision_spec.absolute()
        if digest(spec_path) != args.decision_spec_sha256:
            raise ValueError('native_only_original_spec_hash_changed')
        spec = read_record(spec_path, {})
        args.out.mkdir(parents=True)
        try:
            inputs = {spec_path, Path(__file__).resolve(), ROOT / 'tools/qa_registered_pb_goal_sil.py',
                host_input_path(spec['build_ref']['path'])}
            mirror = host_input_path(spec['build_ref']['path']).parent
            inputs.update(mirror / name for name in ('SOURCE_IDENTITY.json', 'local_rmul_2025.xml', 'ldd.stdout', 'ldd.stderr'))
            for linux, expected in read_record(mirror / 'SOURCE_IDENTITY.json', {})['inputs'].items():
                selected = host_input_path(linux)
                if digest(selected) != expected:
                    raise ValueError('native_only_original_build_source_changed')
                inputs.add(selected)
            for relative, expected in spec['source_sha256'].items():
                selected = (ROOT / relative).absolute()
                if not selected.is_relative_to(ROOT) or digest(selected) != expected:
                    raise ValueError('native_only_pinned_source_changed')
                inputs.add(selected)
            inputs.update(p for p in args.decision_evidence_dir.rglob('*') if p.is_file())
            records = [dict(path=str(p), sha256=digest(p)) for p in sorted(inputs)]
            write(args.out / 'INPUT_HASHES.json', dict(files=records))
            write(args.out / 'COMMAND.json', dict(argv=sys.argv, mode='audit_native_only',
                decision_spec=str(spec_path), decision_spec_sha256=args.decision_spec_sha256,
                decision_evidence_dir=str(args.decision_evidence_dir), required_branches=args.require_branch,
                scope='read-only audit; no process, ROS, physics or referee-state injection'))
            ready, cleanup, ticks, build = _decision_records(args.decision_evidence_dir, spec)
            identity = audit_native_identity(ready, cleanup, spec, build)
            build_mirror = audit_build_mirror(spec, build)
            native = audit_native_ticks(ticks, spec, required_branches=args.require_branch)
            unchanged = all(Path(r['path']).is_file() and digest(r['path']) == r['sha256'] for r in records)
            result = dict(passed=identity['passed'] and build_mirror['passed'] and native['passed']
                    and cleanup.get('tick_count') == len(ticks) and unchanged,
                input_unchanged=unchanged,
                native_identity=identity, native_build_mirror=build_mirror, native_ticks=native,
                qualification='actual_native_runner_with_explicit_standalone_protocol_inputs_no_runtime_or_physics_acceptance')
            code = 0 if result['passed'] else 2
        except BaseException as exc:
            result = dict(passed=False, error_type=type(exc).__name__)
            (args.out / 'failure.log').write_text(traceback.format_exc(), encoding='utf8')
    else:
        if any(value is None for value in (args.manifest, args.pipeline_id, args.peer_evidence_dir)):
            parser.error('actual run requires manifest, pipeline-id and navigation peer-evidence-dir')
        if not math.isfinite(args.seconds) or not 15. <= args.seconds <= 20.:
            raise ValueError('controlled_span_15_to_20_seconds')
        if not math.isfinite(args.max_wall_seconds) or not args.seconds <= args.max_wall_seconds <= 40.:
            raise ValueError('bounded_runtime_15_to_40_seconds')
        args.manifest = args.manifest.absolute(); args.peer_evidence_dir = args.peer_evidence_dir.absolute()
        if (args.peer_evidence_dir.exists() or args.decision_evidence_dir.exists()
            or not args.peer_evidence_dir.is_relative_to(ROOT / 'artifacts')
            or args.peer_evidence_dir in (args.out, args.decision_evidence_dir)):
            raise ValueError('two_fresh_separate_peer_evidence_directories_required')
        from rm_match.deployment.robotio_plugin import load_robotio_plugins
        graph = load_robotio_plugins(args.manifest); _, nav, decision = validate_graph(graph, args.pipeline_id)
        inputs = navigation_inputs(nav, args.peer_evidence_dir) | decision_inputs(decision, args.decision_evidence_dir)
        args.out.mkdir(parents=True)
        switch_record = dict(scope_entered=False, requested_s=args.python_switch_interval_s,
                             original_s=None, actual_s=None, restored_s=None, restored=False)
        command = None
        try:
            records = copy_sources(args.out, graph, inputs)
            command = dict(argv=sys.argv, manifest=str(args.manifest), pipeline_id=args.pipeline_id,
                peer_evidence_dir=str(args.peer_evidence_dir), decision_evidence_dir=str(args.decision_evidence_dir),
                seconds=args.seconds, max_wall_seconds=args.max_wall_seconds, activation_period_s=args.activation_period_s,
                original_activation_period_s=ORIGINAL_ACTIVATION_PERIOD_S,
                unchanged_budgets=dict(sdk_s=.15, pb_navigation_s=.05, camera_s=.08),
                python_switch_interval=switch_record,
                scope='registered actual native PB BT4 healthy running one-route; no synthetic high-level policy')
            with python_switch_interval_scope(args.python_switch_interval_s, switch_record):
                write(args.out / 'COMMAND.json', command)
                execution = run(args.out, args, graph)
            result = evaluate(args.out, args, execution, graph)
            code = 0 if result['passed'] else 2
        except BaseException as exc:
            result = dict(passed=False, error_type=type(exc).__name__)
            (args.out / 'failure.log').write_text(traceback.format_exc(), encoding='utf8')
        finally:
            result['python_switch_interval'] = copy.deepcopy(switch_record)
            if command is not None:
                # Finalize this run's own command metadata with the actual
                # restoration readback; never edit any previous run's record.
                write(args.out / 'COMMAND.json', command)
        unchanged = bool(records) and all(Path(r['path']).is_file() and digest(r['path']) == r['sha256'] for r in records)
        result['source_unchanged'] = unchanged
        if not unchanged:
            result['passed'] = False; code = 2
    result.update(elapsed_s=time.perf_counter() - started, exit_code=code)
    write(args.out / 'RESULT.json', result)
    print(json.dumps(dict(passed=result['passed'], exit_code=code, out=str(args.out)), allow_nan=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())



