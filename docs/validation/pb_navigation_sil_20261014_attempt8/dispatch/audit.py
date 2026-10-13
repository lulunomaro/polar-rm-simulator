"""Read-only comparison of original ROS recorder rows; no nodes or benchmark."""
import collections
import hashlib
import json
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
IDENTITY=('robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline')
JOIN=('adapter_id',*IDENTITY,'cloud_frame_id','acquisition_start_ns','acquisition_end_ns')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def exact(a,b,keys):return all(k in a and k in b and type(a[k]) is type(b[k]) and a[k]==b[k] for k in keys)
def dist(values):
    a=sorted(values)
    if not a:return None
    def q(f):return a[min(len(a)-1,math.floor((len(a)-1)*f))]
    return dict(count=len(a),min=a[0],p50=q(.5),p95=q(.95),p99=q(.99),max=a[-1])
def audit(attempt):
    source=REPO/f'artifacts/pb-navigation-sil-actual-20261014-attempt{attempt}/ROS_SOURCE.jsonl'
    raw=source.read_bytes();rows=[json.loads(line) for line in raw.splitlines()]
    requests={};localizations={};latest=None;kinds=collections.Counter()
    request_order=[];errors=[];lag=collections.Counter();delay=[];deadline_late=[];offset=collections.Counter()
    diagnostics=[];result_rows=[];loc_match=0;loc_on_time=0
    for index,row in enumerate(rows):
        kind=row['topic_kind'];kinds[kind]+=1;v=row['value']
        if kind=='request':
            seq=v['observed_seq']
            if type(seq) is not int or seq in requests:errors.append(dict(row=index,error='duplicate_or_noninteger_request'))
            if request_order and (seq<=request_order[-1]['observed_seq'] or v['cloud_frame_id']<=request_order[-1]['cloud_frame_id'] or v['acquisition_start_ns']<=request_order[-1]['acquisition_start_ns']):
                errors.append(dict(row=index,error='request_nonincreasing'))
            requests[seq]=row;request_order.append(v);latest=seq
        elif kind=='localization':
            q=requests.get(v['observed_seq'])
            valid=q is not None and exact(v,q['value'],JOIN)
            stamp=v['localization_stamp_ns']
            valid=valid and type(stamp) is int and v['acquisition_start_ns']<=stamp<=v['acquisition_end_ns']
            if not valid:errors.append(dict(row=index,error='original_localization_request_join_failed'))
            else:
                loc_match+=1;delay.append((row['receive_wall']-q['receive_wall'])*1000)
                late=(row['receive_wall']-v['wall_deadline'])*1000
                deadline_late.append(late);loc_on_time+=late<0
            lag[str(None if latest is None else latest-v['observed_seq'])]+=1
            offset[str(v['acquisition_end_ns']-stamp)]+=1
            localizations.setdefault(v['observed_seq'],[]).append(row)
        elif kind=='dispatch_diagnostic':diagnostics.append(row)
        elif kind=='controller_result':result_rows.append(row)
    results=[]
    for row in result_rows:
        v=row['value'];a=v['action'];s=v['source'];q=requests.get(a['observed_seq'])
        valid=q is not None and exact(a,q['value'],IDENTITY)
        valid=valid and type(s['cloud_frame_id']) is int and s['cloud_frame_id']==q['value']['cloud_frame_id']
        matching_loc=[l for l in localizations.get(a['observed_seq'],[]) if exact(l['value'],q['value'],JOIN) and type(s['localization_stamp_ns']) is int and l['value']['localization_stamp_ns']==s['localization_stamp_ns']]
        valid=valid and bool(matching_loc) and type(s['controller_stamp_ns']) is int and s['localization_stamp_ns']<=s['controller_stamp_ns']<=round(a['sim_time']*1e9)
        if not valid:errors.append(dict(error='controller_original_request_or_localization_join_failed',seq=a['observed_seq']))
        results.append(dict(observed_seq=a['observed_seq'],cloud_frame_id=s['cloud_frame_id'],joined=valid,
                            original_deadline_margin_ms=(a['wall_deadline']-row['receive_wall'])*1000))
    diag=[];prev=None;intervals=[]
    for row in diagnostics:
        v=row['value'];q=requests.get(v['observed_seq'])
        if q is None or not exact(v,q['value'],('robot_id','episode','binding_epoch','observed_seq','cloud_frame_id')):
            errors.append(dict(error='dispatch_original_request_join_failed',seq=v['observed_seq']))
        if v['schema']!='polar.pb.dispatch.v1' or v['strategy']!='spin_all' or v['clock_domain']!='linux_steady_diagnostic_only' or type(v['dispatch_budget_ns']) is not int or v['dispatch_budget_ns']!=1000000:
            errors.append(dict(error='dispatch_schema_or_clock'))
        for key in ('dispatch_calls_total','dispatch_calls_since_scan','imu_callbacks_total','imu_accepted_total','raw_callbacks_total','last_imu_callbacks_per_dispatch','max_imu_callbacks_per_dispatch','last_dispatch_duration_ns','max_dispatch_duration_ns','exceeded_budget_calls_since_scan'):
            if type(v[key]) is not int or v[key]<0:errors.append(dict(error='dispatch_scalar_type_or_range',key=key))
        if v['imu_callbacks_total']!=v['imu_accepted_total']:errors.append(dict(error='reported_imu_callback_not_accepted',seq=v['observed_seq']))
        if v['max_dispatch_duration_ns']<v['last_dispatch_duration_ns'] or v['max_imu_callbacks_per_dispatch']<v['last_imu_callbacks_per_dispatch']:
            errors.append(dict(error='dispatch_max_inconsistent'))
        if prev:
            for key in ('dispatch_calls_total','imu_callbacks_total','imu_accepted_total','raw_callbacks_total'):
                if v[key]<prev['value'][key]:errors.append(dict(error='cumulative_callback_regression',key=key))
            intervals.append((row['receive_wall']-prev['receive_wall'])*1000)
        prev=row;diag.append(v)
    summary=dict(source_path=str(source),source_sha256=hashlib.sha256(raw).hexdigest(),source_unchanged=sha(source)==hashlib.sha256(raw).hexdigest(),
      counts=dict(kinds),strict_original_localization_join_count=loc_match,request_order_strictly_increasing=not any(e['error']=='request_nonincreasing' for e in errors),
      observer_request_to_localization_ms=dist(delay),observer_localization_minus_original_deadline_ms=dist(deadline_late),
      observer_localization_before_original_deadline=loc_on_time,observer_latest_request_minus_localization_seq=dict(lag),
      original_acquisition_end_minus_localization_ns=dict(offset),controller_original_joins=results,
      controller_deadline_margin_ms=dist([r['original_deadline_margin_ms'] for r in results]),errors=errors)
    if diag:
        summary['actual_dispatch_diagnostic']=dict(reports=len(diag),reported_intervals_with_callback_burst=sum(v['max_imu_callbacks_per_dispatch']>1 for v in diag),
          max_imu_callbacks_per_dispatch=dist([v['max_imu_callbacks_per_dispatch'] for v in diag]),
          last_imu_callbacks_per_dispatch=dist([v['last_imu_callbacks_per_dispatch'] for v in diag]),
          reported_scan_interval_max_dispatch_ms=dist([v['max_dispatch_duration_ns']/1e6 for v in diag]),
          last_dispatch_ms=dist([v['last_dispatch_duration_ns']/1e6 for v in diag]),
          reported_intervals_with_dispatch_budget_excess=sum(v['exceeded_budget_calls_since_scan']>0 for v in diag),
          sum_exceeded_budget_calls_in_reported_intervals=sum(v['exceeded_budget_calls_since_scan'] for v in diag),
          largest_reported_dispatch_budget_excess_ms=max(0.,max(v['max_dispatch_duration_ns'] for v in diag)/1e6-1.),
          first_report=diag[0],last_report=diag[-1],observer_receive_interval_ms=dist(intervals),
          coverage='At most 10 Hz reports; each reports its scan interval. Throttled successful-scan intervals are not represented in per-scan maxima/excess, so these are reported-interval bounds, not an exhaustive full-run maximum.',
          clocks='Callback counts and dispatch durations are actual C++ diagnostics. They use Linux steady time locally. Observer receive deltas are separate proxies and are never subtracted from Linux steady timestamps.')
    else:summary['actual_dispatch_diagnostic']=None
    return summary
result=dict(schema='polar.pb.dispatch-readonly-audit.v1',scope='Read-only actual SIL recorder comparison, no fixture substitution, no physics truth input',
            quantile_method='sorted nearest lower rank floor((n-1)*q)',attempt7=audit(7),attempt8=audit(8))
result['passed']=all(not result[a]['errors'] and result[a]['source_unchanged'] for a in ('attempt7','attempt8'))
out=HERE/'RESULT.json'
if out.exists():raise RuntimeError('fresh audit output required')
out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
print(json.dumps(result,indent=2))
