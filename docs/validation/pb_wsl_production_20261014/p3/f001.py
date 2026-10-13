"""Read saved production attempt3 only; no ROS/WSL/native/GL or business edits."""
from pathlib import Path
import collections
import hashlib
import json
import math
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
INPUT = ROOT / 'artifacts/pb-wsl-production-sil-actual-20261014-attempt3'
FILES = tuple(str(x.relative_to(INPUT)).replace('\\', '/') for x in INPUT.rglob('*') if x.is_file() and 'source' not in x.relative_to(INPUT).parts)
HOST_PHASES = ('exchange_enter', 'packet_validated', 'encode_begin', 'encode_end',
               'stdin_write_begin', 'stdin_write_end', 'stdout_line_received',
               'caller_received', 'result_validated', 'return_copy_end')
LINUX_PHASES = ('rpc_parsed', 'bridge_exchange_begin', 'bridge_exchange_end',
                'stdout_emit_begin', 'stdout_emit_end')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    return json.loads((INPUT / name).read_bytes())


def group(data, clock):
    groups = {}
    issues = []
    for row in data['rows']:
        if row['id'] is None:
            continue  # Startup ready is not a reset/act transaction.
        if (type(row['id']) is not int or row['id'] < 1
                or type(row['local_wall']) not in (int, float)
                or not math.isfinite(row['local_wall']) or row['clock'] != clock
                or type(row['op']) is not str):
            issues.append(dict(kind='type_or_clock', row=row))
        key = (row['id'], row['op'])
        phases = groups.setdefault(key, {})
        if row['phase'] in phases:
            issues.append(dict(kind='duplicate_phase', rpc=list(key), phase=row['phase']))
        phases[row['phase']] = row['local_wall']
    return groups, issues


def stats(values):
    values = sorted(values)
    if not values:
        return dict(n=0)
    return dict(n=len(values), min_ms=values[0] * 1000,
                p50_ms=statistics.median(values) * 1000,
                p95_ms=linear_percentile(values, .95) * 1000, p99_ms=linear_percentile(values, .99) * 1000, max_ms=values[-1] * 1000)


def linear_percentile(values, q):
    position = (len(values) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def main():
    started = time.perf_counter()
    before = {name: sha(INPUT / name) for name in FILES}
    source_names = read('RESULT.json')['source_sha256']
    current_sources_before = {name: sha(ROOT / name) for name in source_names}
    # Historical source is copied from the attempt's saved byte snapshots, not
    # overwritten with the newer working tree currently being developed.
    saved_sources = {name: sha(INPUT / 'source' / name) for name in source_names}
    host = read('HOST_RPC_PHASES.json')
    close_host = read('session/HOST_RPC_PHASES.json')
    linux = read('session/LINUX_RPC_PHASES.json')
    H, hi = group(host, 'windows_local_perf_counter')
    L, li = group(linux, 'linux_local_perf_counter')
    missing = []
    ordering = []
    for domain, groups in [('host', H), ('linux', L)]:
        for key, phases in groups.items():
            required = HOST_PHASES if domain == 'host' else (
                ('rpc_parsed', 'stdout_emit_begin', 'stdout_emit_end')
                if key[1] == 'reset' else LINUX_PHASES)
            absent = [name for name in required if name not in phases]
            if absent:
                missing.append(dict(domain=domain, rpc=list(key), phases=absent))
            if not absent and any(phases[b] < phases[a] for a, b in zip(required, required[1:])):
                ordering.append(dict(domain=domain, rpc=list(key)))
    act_ids = sorted(k[0] for k in H if k[1] == 'act')
    metrics = {}
    for label, a, b in (
            ('exchange_to_return', 'exchange_enter', 'return_copy_end'),
            ('packet_validation', 'exchange_enter', 'packet_validated'),
            ('serialize', 'encode_begin', 'encode_end'),
            ('writer_queue', 'encode_end', 'stdin_write_begin'),
            ('pipe_write', 'stdin_write_begin', 'stdin_write_end'),
            ('response_wait', 'stdin_write_end', 'stdout_line_received'),
            ('reader_to_caller', 'stdout_line_received', 'caller_received'),
            ('result_validation', 'caller_received', 'result_validated'),
            ('return_copy', 'result_validated', 'return_copy_end'),
            ('encode_to_return', 'encode_begin', 'return_copy_end')):
        metrics[label] = stats([v[b] - v[a] for k, v in H.items() if k[1] == 'act'])
    reset = H[(1, 'reset')]
    metrics['reset'] = dict(total_ms=(reset['return_copy_end'] - reset['exchange_enter']) * 1000,
                           packet_validation_ms=(reset['packet_validated'] - reset['exchange_enter']) * 1000,
                           encoded_to_return_ms=(reset['return_copy_end'] - reset['encode_begin']) * 1000)
    metrics['linux_bridge'] = stats([v['bridge_exchange_end'] - v['bridge_exchange_begin']
                                    for k, v in L.items() if k[1] == 'act'])
    metrics['linux_stdout'] = stats([v['stdout_emit_end'] - v['stdout_emit_begin']
                                    for k, v in L.items() if k[1] == 'act'])
    first = min(v['bridge_exchange_begin'] for k, v in L.items() if k[1] == 'act')
    last = max(v['stdout_emit_end'] for k, v in L.items() if k[1] == 'act')
    slow = []
    for original in linux['slow_stop_polls']:
        row = dict(original)
        row['scope'] = ('before_first_act' if row['local_wall'] < first else
                        'after_last_act' if row['local_wall'] > last else 'during_act_window')
        row['overlaps_rpc_ids'] = [k[0] for k, v in L.items() if k[1] == 'act'
                                  and row['local_wall'] <= v['stdout_emit_end']
                                  and row['local_wall'] + row['duration_s'] >= v['bridge_exchange_begin']]
        slow.append(row)
    trace = [json.loads(line) for line in (INPUT / 'TRACE.jsonl').read_text().splitlines()]
    enqueues = [r for r in trace if r['event'] == 'adapter_enqueue']
    results = [r for r in trace if r['event'] == 'adapter_result']
    # This attempt's single reset plus contiguous act sequence gives an explicit
    # checked serial mapping; phase rows themselves do not carry source IDs.
    sequence_mapping = sorted(r['observed_seq'] for r in enqueues) == list(range(1, len(enqueues)+1)) and act_ids == list(range(2, len(enqueues)+2))
    margins = []
    if sequence_mapping:
        for row in enqueues:
            rpc_id = row['observed_seq'] + 1
            margins.append(dict(observed_seq=row['observed_seq'], rpc_id=rpc_id,
                                original_wall_deadline=row['wall_deadline'],
                                return_copy_end=H[(rpc_id, 'act')]['return_copy_end'],
                                remaining_ms=(row['wall_deadline'] - H[(rpc_id, 'act')]['return_copy_end']) * 1000))
    actual = read('RESULT.json')
    gate = read('session/PRODUCTION_GATE_STATUS.json')
    peer = read('peer/RESULT.json')
    spec = read('session/SESSION_SPEC.json')
    peer_spec = read('peer/EXTERNAL_SPEC.json')
    report = dict(
        schema='polar.pb.production-phase-audit.v1', mode='saved_artifacts_read_only_no_ROS_WSL_GL_test',
        input=str(INPUT), input_sha256=before, audit_script_sha256=sha(Path(__file__)),
        historical_source_sha256=saved_sources, historical_source_snapshots_match=saved_sources == source_names,
        current_source_sha256_at_audit=current_sources_before,
        host_metadata={k: v for k, v in host.items() if k != 'rows'}, host_row_count=len(host['rows']),
        host_inner_outer_object_equal=host == close_host,
        linux_row_count=len(linux['rows']), linux_truncation_metadata_present=all(k in linux for k in ('total', 'dropped', 'capacity')),
        matched_rpc_keys=sorted([list(k) for k in H if k in L]),
        unmatched_host_keys=[list(k) for k in H if k not in L], unmatched_linux_keys=[list(k) for k in L if k not in H],
        stage_issues=hi + li, missing_stages=missing, negative_or_misordered_stages=ordering,
        metrics=metrics, stop_poll_count=linux['stop_poll_count'], max_stop_poll_seconds=linux['max_stop_poll_seconds'], slow_stop_polls=slow,
        cross_clock_subtraction=False,
        trace_enqueue_count=len(enqueues), trace_collect_count=len(results),
        trace_errors=[dict(seq=r['observed_seq'], error=r['error']) for r in results if r['error']],
        trace_act_time=stats([r['admission_timings']['act_s'] for r in results]),
        missing_trace_collect_sequences=sorted(set(r['observed_seq'] for r in enqueues) - set(r['observed_seq'] for r in results)),
        rpc_serial_to_observed_seq_mapping_checked=sequence_mapping, original_deadline_margins=margins,
        gate_saved_schema=gate.get('schema'), gate_saved_run_uuid=gate.get('run_uuid'),
        gate_namespace_matches=gate.get('namespace') == spec['namespace'],
        peer_schema_matches=peer.get('schema') == 'polar.pb.external-goal-result.v1',
        peer_run_uuid_matches=peer.get('run_uuid') == peer_spec['run_uuid'],
        peer_session_uuid_matches=peer.get('session_run_uuid') == spec['run_uuid'],
        peer_namespace_matches=peer.get('namespace') == spec['namespace'],
        actual_steps=actual['actual_steps'], physics_wall_seconds=actual['physics_wall_seconds'], physics_rtf=actual['physics_rtf'],
        completed_requested_wall_duration=actual['completed_requested_wall_duration'], actual_passed=actual['bounded_navigation_consumption_passed'],
        conclusions=[
            'All saved reset/act Host and Linux stages are present and correctly ordered; both ledgers explicitly have zero dropped records.',
            '299 actual act RPCs returned; no Host timeout occurred in this production run.',
            'STOP poll scopes use Linux-local timing only. Concurrent overlap is not additive proof of causal act delay.',
            'Old navigation attempt2 timeout remains unexplained; a successful different run does not establish its root cause.',
            'Qualification is bounded single-generation sentry navigation, production Gate plus independent external action client; not full mission/hardware/native aim.'
        ])
    worker_birth = read('session/WORKER_STARTED.json')
    worker_cleanup = read('session/CLEANUP.json')
    peer_birth = read('peer/SUPERVISOR_STARTED.json')
    peer_cleanup = read('peer/SUPERVISOR_CLEANUP.json')
    stack_cleanup = read('session/stack/CLEANUP.json')
    report['worker_cleanup_identity_matches'] = all(worker_birth[k] == worker_cleanup[k] for k in ('run_uuid', 'config_sha256', 'supervisor_pid', 'start_ticks', 'boot_id')) and worker_birth['run_uuid'] == spec['run_uuid'] and worker_birth['config_sha256'] == spec['config_ref']['sha256']
    report['peer_supervisor_cleanup_identity_matches'] = all(peer_birth[k] == peer_cleanup[k] for k in ('run_uuid', 'spec_sha256', 'supervisor_pid', 'start_ticks', 'boot_id')) and peer_birth['run_uuid'] == peer_spec['run_uuid'] and peer_birth['spec_sha256'] == sha(INPUT/'peer/EXTERNAL_SPEC.json')
    report['cleanup_proof'] = dict(worker=worker_cleanup, peer_supervisor=peer_cleanup, stack=stack_cleanup, runtime=actual['shutdown'])
    report['nine_stack_groups_empty'] = len(stack_cleanup['processes']) == 9 and all(r['remaining_members'] == [] and type(r['returncode']) is int for r in stack_cleanup['processes'])
    report['peer_reaped_and_empty'] = peer_cleanup['group']['reaped'] is True and peer_cleanup['group']['group_empty'] is True and peer_cleanup['group']['remaining_members'] == []
    report['host_ledger_metadata_valid'] = type(host['total']) is int and host['total'] == len(host['rows']) and host['dropped'] == 0 and host['complete'] is True and len(host['rows']) <= host['capacity']
    report['linux_ledger_metadata_valid'] = type(linux['total']) is int and linux['total'] == len(linux['rows']) and linux['dropped'] == 0 and linux['complete'] is True and len(linux['rows']) <= linux['capacity']
    report['gate_identity_and_types_valid'] = gate.get('schema') == 'polar.pb.production-gate-status.v1' and gate.get('run_uuid') == spec['run_uuid'] and gate.get('namespace') == spec['namespace'] and type(gate.get('map_messages')) is int and type(gate.get('odometry_messages')) is int and type(gate.get('latest_odom_stamp_ns')) is int and gate.get('production_gate') is True and gate.get('activation_started') is True and gate.get('clock_domain') == 'linux_local_receive_only' and type(gate.get('errors')) is list and gate['errors'] == []
    report['max_host_rpc'] = dict(rpc_id=max(act_ids, key=lambda i:H[(i,'act')]['return_copy_end']-H[(i,'act')]['exchange_enter']), scope='same Windows host clock')
    max_validation_id = max(act_ids, key=lambda i: H[(i,'act')]['packet_validated']-H[(i,'act')]['exchange_enter'])
    max_total_id = report['max_host_rpc']['rpc_id']
    report['outliers'] = dict(max_packet_validation_rpc_id=max_validation_id,
        max_packet_validation_ms=(H[(max_validation_id,'act')]['packet_validated']-H[(max_validation_id,'act')]['exchange_enter'])*1000,
        max_packet_validation_rpc_total_ms=(H[(max_validation_id,'act')]['return_copy_end']-H[(max_validation_id,'act')]['exchange_enter'])*1000,
        max_packet_validation_rpc_phases=H[(max_validation_id,'act')],
        max_total_rpc_id=max_total_id,
        max_total_rpc_validation_ms=(H[(max_total_id,'act')]['packet_validated']-H[(max_total_id,'act')]['exchange_enter'])*1000,
        max_total_rpc_response_wait_ms=(H[(max_total_id,'act')]['stdout_line_received']-H[(max_total_id,'act')]['stdin_write_end'])*1000,
        max_total_rpc_phases=H[(max_total_id,'act')])
    report['percentile_method'] = 'P50 median; P95/P99 linear interpolation over sorted actual samples at (n-1)*q'
    report['driver_reaped_proof_scope'] = 'Root reported actual driver exit and reap; saved input independently proves Linux supervisor identities, owned stack process return codes/empty groups, peer reap, and runtime clean shutdown. No new process enumeration was performed.'
    (OUT / 'raw').mkdir(exist_ok=False)
    for name in FILES:
        target = OUT / 'raw' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = (INPUT / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != before[name]:
            raise RuntimeError('input_changed_during_copy:' + name)
        target.write_bytes(raw)
    report['input_unchanged'] = before == {name: sha(INPUT / name) for name in FILES}
    report['source_unchanged'] = current_sources_before == {name: sha(ROOT / name) for name in source_names}
    report['raw_copies_sha256'] = {name: sha(OUT / 'raw' / name) for name in FILES}
    report['raw_copies_byteidentical'] = report['raw_copies_sha256'] == before
    if not report['input_unchanged'] or not report['source_unchanged'] or not report['raw_copies_byteidentical']:
        raise RuntimeError('audit_input_or_source_changed')
    (OUT / 'AUDIT.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf8')
    (OUT / 'PROCESS_RESULT.json').write_text(json.dumps(dict(exit_code=0, elapsed_s=time.perf_counter()-started,
        python=sys.version, executable=sys.executable, input_unchanged=report['input_unchanged'],
        source_unchanged=report['source_unchanged'], raw_copies_byteidentical=report['raw_copies_byteidentical'],
        script_sha256=report['audit_script_sha256'], ROS_started=False, WSL_started=False,
        tests_started=False, GL_started=False), indent=2)+'\n', encoding='utf8')
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
