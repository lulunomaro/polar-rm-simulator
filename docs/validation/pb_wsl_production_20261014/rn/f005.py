"""Read saved evidence only. No simulator imports, subprocesses or live tests."""
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).parent
SOURCES=('rm_match/integrations/pb_wsl_navigation.py','rm_match/integrations/pb_wsl_navigation_worker.py',
    'rm_match/integrations/pb_wsl_navigation_registry.py','rm_match/integrations/pb_navigation_bridge.py',
    'rm_match/integrations/pb_navigation_transport.py','tools/pb_navigation_stack.py',
    'tools/qa_pb_wsl_navigation_sil.py','rm_match/platform_v2/__main__.py')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
before={p:sha(ROOT/p) for p in SOURCES}
proof={}
def load(p):
    proof[p.relative_to(ROOT).as_posix()]=sha(p)
    return json.loads(p.read_bytes())
def dist(xs):
    xs=sorted(xs)
    if not xs:return {'count':0}
    return dict(count=len(xs),p50=statistics.median(xs),p95=xs[math.ceil(.95*len(xs))-1],
        p99=xs[math.ceil(.99*len(xs))-1],max=xs[-1],min=xs[0])
def stages(rows,clock,pairs):
    by_id=defaultdict(dict);errors=[]
    for row in rows:
        if row.get('clock')!=clock:errors.append('unexpected_clock')
        if row.get('op')!='act':continue
        serial=row.get('id');phase=row.get('phase');stamp=row.get('local_wall')
        if type(serial) is not int or type(stamp) not in (int,float) or not math.isfinite(stamp):
            errors.append('invalid_scalar');continue
        if phase in by_id[serial]:errors.append('duplicate_phase')
        by_id[serial][phase]=stamp
    result={}
    for name,(start,end) in pairs.items():
        values=[];missing=[]
        for serial,row in by_id.items():
            if start not in row or end not in row:missing.append(serial);continue
            duration=(row[end]-row[start])*1000
            if duration<0:errors.append('negative_same_clock_duration')
            values.append(duration)
        result[name]=dict(milliseconds=dist(values),missing_ids=missing)
    return dict(act_transaction_count=len(by_id),metrics=result,errors=errors)
attempts={}
for n in (2,3,4):
    directory=ROOT/f'artifacts/pb-wsl-navigation-sil-actual-20261014-attempt{n}'
    report=load(directory/'RESULT.json');ready=load(directory/'PREPARE.json')
    cleanup=load(directory/'session/CLEANUP.json')
    trace_path=directory/'TRACE.jsonl';proof[trace_path.relative_to(ROOT).as_posix()]=sha(trace_path)
    trace=[json.loads(s) for s in trace_path.read_text(encoding='utf8').splitlines()]
    results=[r for r in trace if r['event']=='adapter_result']
    faults=[r for r in results if r.get('error')]
    summary=dict(scope=report['scope'],relative_test_goal=load(directory/'session/SESSION_SPEC.json')['relative_test_goal'],
        actual_steps=report['actual_steps'],reported_pass=report['bounded_navigation_consumption_passed'],
        host_source_unchanged=report['source_unchanged'],runtime_shutdown_clean=report['shutdown']['clean'],
        worker_cleanup_clean=cleanup['clean'],owned_groups=cleanup['owned_groups'],
        cleanup_identity_matches_ready=all(type(cleanup[k]) is type(ready['ready'][k]) and cleanup[k]==ready['ready'][k]
            for k in ('run_uuid','config_sha256','supervisor_pid','start_ticks','boot_id')),
        adapter_result_count=len(results),faults=faults,
        host_act_ms=dist([r['admission_timings']['act_s']*1000 for r in results if r.get('admission_timings',{}).get('act_s') is not None]),
        host_original_deadline_margin_ms=dist([(r['wall_deadline']-r['completed_wall'])*1000 for r in results]),
        prepare_wall_seconds=ready['elapsed_s'])
    if n in (3,4):
        hp=load(directory/'HOST_RPC_PHASES.json');lp=load(directory/'session/LINUX_RPC_PHASES.json')
        summary['host_phases']=stages(hp['rows'],'windows_local_perf_counter',{
            'encode':('encode_begin','encode_end'),'writer_admission':('encode_end','stdin_write_begin'),
            'pipe_write':('stdin_write_begin','stdin_write_end'),
            'written_to_reply_received':('stdin_write_end','stdout_line_received'),
            'reader_to_caller':('stdout_line_received','caller_received'),
            'encode_to_caller':('encode_begin','caller_received')})
        summary['linux_phases']=stages(lp['rows'],'linux_local_perf_counter',{
            'parsed_to_exchange':('rpc_parsed','bridge_exchange_begin'),
            'bridge_exchange':('bridge_exchange_begin','bridge_exchange_end'),
            'reply_serialization_admission':('bridge_exchange_end','stdout_emit_begin'),
            'stdout_write':('stdout_emit_begin','stdout_emit_end'),
            'parsed_to_stdout_complete':('rpc_parsed','stdout_emit_end')})
        summary['stop_poll']={k:lp[k] for k in ('stop_poll_count','max_stop_poll_seconds','slow_stop_polls')}
        parsed=[r['local_wall'] for r in lp['rows'] if r.get('op')=='act' and r['phase']=='rpc_parsed']
        summary['stop_poll']['first_act_parsed_local_wall']=min(parsed)
        completed=[r['local_wall'] for r in lp['rows'] if r.get('op')=='act' and r['phase']=='stdout_emit_end']
        summary['stop_poll']['last_act_stdout_complete_local_wall']=max(completed)
        summary['stop_poll']['slow_poll_before_first_act_count']=sum(r['local_wall']<min(parsed) for r in lp['slow_stop_polls'])
        summary['stop_poll']['slow_poll_after_last_act_count']=sum(r['local_wall']>max(completed) for r in lp['slow_stop_polls'])
        summary['stop_poll']['slow_poll_during_act_span_count']=sum(min(parsed)<=r['local_wall']<=max(completed) for r in lp['slow_stop_polls'])
        summary['ledger_capacity_not_hit']=len(hp['rows'])<4096 and len(lp['rows'])<4096
    attempts[str(n)]=summary
after={p:sha(ROOT/p) for p in SOURCES}
report=dict(schema='polar.pb-wsl-navigation-readonly-review.v1',source_sha256=before,
    source_unchanged_during_review=before==after,evidence_sha256=proof,
    percentile_definition='median P50; nearest-rank P95/P99; all durations in milliseconds',
    no_cross_clock_subtraction=True,production_gate_exercised_by_these_attempts=False,attempts=attempts)
(OUT/'METRICS.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf8')
for n,row in attempts.items():
    print('attempt',n,'pass',row['reported_pass'],'faults',len(row['faults']),'host_act_ms',row['host_act_ms'])
    if 'host_phases' in row:
        print('host', {k:v['milliseconds'] for k,v in row['host_phases']['metrics'].items()})
        print('linux',{k:v['milliseconds'] for k,v in row['linux_phases']['metrics'].items()})
        print('stop_poll_max_ms',row['stop_poll']['max_stop_poll_seconds']*1000)
