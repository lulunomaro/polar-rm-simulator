"""Summarize bounded local phase samples after teardown, without changing them.

Thread CPU differences only use start/end from the same thread and exact typed
source. Inclusive spans overlap. Wall minus CPU is a signed residual, not a
measurement of GIL wait, lock contention, native compute or another machine.
"""
from __future__ import annotations
from collections import Counter,defaultdict
import math


def _distribution_ns(values):
    ordered=sorted(values)
    def percentile(fraction):
        if not ordered:return None
        position=(len(ordered)-1)*fraction;low=int(position);high=min(low+1,len(ordered)-1)
        return (ordered[low]+(ordered[high]-ordered[low])*(position-low))/1e6
    return dict(count=len(ordered),p50_ms=percentile(.5),p95_ms=percentile(.95),p99_ms=percentile(.99),
        min_ms=None if not ordered else ordered[0]/1e6,max_ms=None if not ordered else ordered[-1]/1e6)


def _key(row,phase):
    fields=('thread_id','request_id','robot_id','episode','binding_epoch','observed_seq','sim_time',
            'wall_deadline','frame_id','pixel_sha256','original_deadline','detail')
    return (phase,)+tuple((type(row.get(k)).__name__,row.get(k)) for k in fields)


def _linked_interval(rows,start_phase,end_phase,*,match_detail=False,start_detail=None,end_detail=None):
    """Exact typed original source join. CPU exists only for a same-thread pair."""
    fields=('request_id','robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline',
            'frame_id','pixel_sha256','original_deadline')+ (('detail',) if match_detail else ())
    starts=defaultdict(list);ends=defaultdict(list)
    for row in rows:
        if row['phase']==start_phase and (start_detail is None or row.get('detail')==start_detail):target=starts
        elif row['phase']==end_phase and (end_detail is None or row.get('detail')==end_detail):target=ends
        else:continue
        if row.get('request_id') is None:continue
        target[tuple((type(row.get(k)).__name__,row.get(k)) for k in fields)].append(row)
    wall=[];cpu=[];ambiguous=0;cross_thread=0
    for key in starts.keys() & ends.keys():
        if len(starts[key])!=1 or len(ends[key])!=1:ambiguous+=1;continue
        a=starts[key][0];b=ends[key][0];wall.append(b['wall_ns']-a['wall_ns'])
        if a['thread_id']==b['thread_id']:cpu.append(b['thread_cpu_ns']-a['thread_cpu_ns'])
        else:cross_thread+=1
    return dict(start=start_phase,end=end_phase,wall=_distribution_ns(wall),same_thread_cpu=_distribution_ns(cpu),
        cross_thread_count=cross_thread,ambiguous_source_count=ambiguous,
        unmatched_start_sources=len(starts.keys()-ends.keys()),unmatched_end_sources=len(ends.keys()-starts.keys()),
        negative_wall_count=sum(v<0 for v in wall),
        scope='Original typed source/request/frame/SHA join; cross-thread intervals have wall only; signed durations retained')


def summarize(snapshot):
    if type(snapshot) is not dict or snapshot.get('schema')!='polar.sim.numeric-phase-probe.v1':
        raise ValueError('Expected bounded numeric phase snapshot')
    rows=snapshot.get('rows')
    if type(rows) is not list:raise ValueError('Expected detached phase rows')
    pending=defaultdict(list);groups=defaultdict(list);counts=Counter();unmatched=[]
    span_names={r['phase'].rsplit('_',1)[0] for r in rows if type(r) is dict and
                type(r.get('phase')) is str and r['phase'].endswith(('_start','_begin'))}
    if any(type(r) is dict and r.get('phase')=='async_queue_put' for r in rows):span_names.add('async_queue_put')
    for row in rows:
        if type(row) is not dict or type(row.get('phase')) is not str:raise ValueError('Invalid phase row')
        if any(type(row.get(k)) is not int or row[k]<0 for k in ('wall_ns','thread_cpu_ns','thread_id')):
            raise ValueError('Invalid local phase clock')
        for value in row.values():
            if type(value) not in (str,int,float,type(None)) or type(value) is float and not math.isfinite(value):
                raise ValueError('Phase payload must contain finite scalars only')
        phase=row['phase'];counts[phase]+=1
        if phase.endswith(('_start','_begin')) or phase=='async_queue_put':
            name=phase if phase=='async_queue_put' else phase.rsplit('_',1)[0]
            pending[_key(row,name)].append(row)
        elif phase.endswith('_end') and phase[:-4] in span_names:
            name=phase[:-4];key=_key(row,name)
            if not pending[key]:
                unmatched.append(dict(phase=name,thread_id=row['thread_id'],reason='end_without_same_thread_source_start'))
                continue
            start=pending[key].pop()
            wall=row['wall_ns']-start['wall_ns'];cpu=row['thread_cpu_ns']-start['thread_cpu_ns']
            groups[name,row['thread_id']].append((wall,cpu,wall-cpu))
    remaining=sum(len(v) for v in pending.values());spans=[]
    for (name,thread_id),values in sorted(groups.items()):
        wall,cpu,residual=zip(*values)
        spans.append(dict(phase=name,thread_id=thread_id,count=len(values),wall_sum_s=sum(wall)/1e9,
            thread_cpu_sum_s=sum(cpu)/1e9,wall_minus_thread_cpu_sum_s=sum(residual)/1e9,
            wall=_distribution_ns(wall),thread_cpu=_distribution_ns(cpu),wall_minus_thread_cpu=_distribution_ns(residual),
            negative_wall_count=sum(v<0 for v in wall),negative_cpu_count=sum(v<0 for v in cpu),
            negative_residual_count=sum(v<0 for v in residual)))
    thread_cpu_values=defaultdict(set)
    for row in rows:thread_cpu_values[row['thread_id']].add(row['thread_cpu_ns'])
    observed_clock=[]
    for thread_id,values in sorted(thread_cpu_values.items()):
        ordered=sorted(values);increments=[b-a for a,b in zip(ordered,ordered[1:])]
        observed_clock.append(dict(thread_id=thread_id,distinct_cpu_samples=len(ordered),
            min_positive_observed_increment_ns=min(increments) if increments else None,
            sampled_cpu_range_s=(ordered[-1]-ordered[0])/1e9 if ordered else None,
            note='Observed sampled accounting increments, not a precision guarantee; zero subphase deltas are unresolved'))
    return dict(schema='polar.sim.numeric-phase-summary.v1',retained=len(rows),
        capacity=snapshot.get('capacity'),dropped=snapshot.get('dropped'),attempted=snapshot.get('attempted'),
        retention_complete=snapshot.get('complete') is True,
        unmatched_end_count=len(unmatched),unmatched_start_count=remaining,unmatched_end_examples=unmatched[:16],
        phase_counts=dict(sorted(counts.items())),spans=spans,
        observed_thread_cpu_accounting=observed_clock,sampling=snapshot.get('sampling'),
        linked_intervals=dict(outgoing_queue=_linked_interval(rows,'async_queue_put','async_queue_get'),
            reader_parse_validate=_linked_interval(rows,'async_reader_entry','async_reader_validated',match_detail=True),
            original_call=_linked_interval(rows,'async_queue_put','async_caller_return'),
            validated_result_to_accepted_caller=_linked_interval(rows,'async_reader_validated','async_caller_return',
                start_detail='result',end_detail='accepted')),
        scope='Same process/thread/source inclusive spans only; signed wall-minus-thread-CPU is preserved, not GIL wait. Do not add overlapping spans or subtract CPU across threads/machines.')
