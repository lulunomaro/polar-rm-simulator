"""Read original receipts/ROS/SDK acknowledgements; never run ROS or physics."""
import collections
import hashlib
import json
import math
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];sys.path.insert(0,str(ROOT))
SOURCE=ROOT/'artifacts/pb-navigation-sil-actual-20261014-attempt8'
FIELDS=('robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def key(v):
    assert type(v['robot_id']) is str
    assert all(type(v[k]) is int for k in ('episode','binding_epoch','observed_seq'))
    assert all(type(v[k]) in (int,float) and math.isfinite(v[k]) for k in ('sim_time','wall_deadline'))
    return tuple((type(v[k]).__name__,v[k]) for k in FIELDS)
def finite(v):return type(v) in (int,float) and math.isfinite(v)
def main():
    files=[SOURCE/'TRACE.jsonl',SOURCE/'ROS_SOURCE.jsonl',SOURCE/'RESULT.json',SOURCE/'stack/controller_server.log']
    before={str(p.relative_to(ROOT)):sha(p) for p in files}
    raw=json.loads(files[2].read_bytes());qa=ROOT/'tools/qa_pb_navigation_sil.py'
    assert sha(qa)==raw['source_sha256']['tools/qa_pb_navigation_sil.py'],'recorded audit implementation changed'
    from tools.qa_pb_navigation_sil import audit_navigation_consumption
    rows=[json.loads(s) for s in files[0].read_text().splitlines()];ros=[json.loads(s) for s in files[1].read_text().splitlines()]
    original_audit=audit_navigation_consumption(rows,ros)
    req=collections.defaultdict(list);loc=collections.defaultdict(list);res=collections.defaultdict(list)
    enqueue=collections.defaultdict(list);acks={};proofs=[];steps=set();commands=set();ages=[];errors=[]
    for r in ros:
        v=r['value']
        if r['topic_kind']=='request':req[key(v)].append(v)
        if r['topic_kind']=='localization':loc[key(v)].append(v)
        if r['topic_kind']=='controller_result':res[key(v['action'])].append(v)
    for r in rows:
        if r['event']=='sdk_adapter_activation':
            a=r['activation'];w=r['window'];acks[a['binding_epoch'],a['seq'],a['window_id']]=w
        if r['event']=='adapter_enqueue' and r['kind']=='navigation':
            v={k:r['observation_sim_time'] if k=='sim_time' else r[k] for k in FIELDS};enqueue[key(v)].append(r)
        if r['event']=='adapter_result' and r['kind']=='navigation' and r.get('error'):errors.append('adapter_fault')
    for r in rows:
        if r['event']!='navigation_consumed' or r['phase']!='integration_entry' or r['target']['motion'] is None:continue
        a=r['action'];k=key(a);b=r['navigation_budget'];wall=r['consume_wall'];sim=r['consume_sim_time']
        assert a['robot_id']=='red_sentry' and a['episode']==0 and a['binding_epoch']==1
        assert a['schema']=='polar.sim.action.v2' and a['kind']=='navigation' and a['mode']=='velocity_body'
        assert r['target']['motion']==a['command'] and r['target']['fire'] is False
        assert finite(wall) and finite(sim) and type(b['frame_id']) is int
        assert b['capture_wall']<=wall<min(b['wall_deadline'],a['wall_deadline'])
        assert b['capture_sim_time']<=sim<=b['sim_deadline']
        assert 0<b['wall_deadline']-b['capture_wall']<=.150001 and 0<b['sim_deadline']-b['capture_sim_time']<=.150001
        assert a['command']['frame']=='base_link'
        assert all(finite(a['command'][c]) for c in ('vx_mps','vy_mps','wz_rps'))
        assert math.hypot(a['command']['vx_mps'],a['command']['vy_mps'])<=1 and abs(a['command']['wz_rps'])<=2
        assert any(abs(a['command'][c])>1e-8 for c in ('vx_mps','vy_mps','wz_rps'))
        for name in ('authorization','output_authorization'):
            auth=r[name];assert auth['activation_required'] is True
            assert all(type(auth[c]) is int for c in ('epoch','activation_seq','activation_window_id'))
            assert auth['epoch']==1
            w=acks[auth['epoch'],auth['activation_seq'],auth['activation_window_id']]
            assert w['lease_epochs']=={'motion':1} and type(w['lease_epochs']['motion']) is int
            assert finite(w['issued_wall']) and finite(w['expires_wall']) and 0<w['valid_for_s']<=.15
            assert abs(w['expires_wall']-w['issued_wall']-w['valid_for_s'])<=1e-6
            assert w['issued_wall']<=wall<auth['activation_expires']==auth['activation_window_deadline']==w['expires_wall']
        assert a['wall_deadline']<=r['output_authorization']['activation_expires']
        e=[x for x in enqueue[k] if x['sensor_budget']==b];q=req[k]
        assert len(e)==len(q)==1
        cloud=e[0]['cloud_acquisition'];q=q[0]
        assert cloud['frame_id']==b['frame_id']==q['cloud_frame_id']
        assert cloud['profile_sha256']==b['profile_sha256']
        assert cloud['acquisition_start_ns']==q['acquisition_start_ns'] and cloud['acquisition_end_ns']==q['acquisition_end_ns']==round(b['capture_sim_time']*1e9)
        exact_l=[x for x in loc[k] if all(type(x[f]) is type(q[f]) and x[f]==q[f] for f in (*FIELDS,'adapter_id','cloud_frame_id','acquisition_start_ns','acquisition_end_ns'))]
        exact_r=[x for x in res[k] if x['action']==a and x['source']['cloud_frame_id']==b['frame_id']]
        assert len(exact_l)==len(exact_r)==1
        l=exact_l[0];s=exact_r[0]['source']
        assert s['controller_id']=='pb_controller_sourced_v1'
        assert all(type(s[f]) is int for f in ('cloud_frame_id','localization_stamp_ns','controller_stamp_ns'))
        assert l['localization_stamp_ns']==s['localization_stamp_ns']
        assert q['acquisition_start_ns']<=s['localization_stamp_ns']<=s['controller_stamp_ns']<=q['acquisition_end_ns']
        steps.add(sim);commands.add(k);ages.append(wall-b['capture_wall'])
        proofs.append(dict(observed_seq=a['observed_seq'],frame_id=b['frame_id'],consume_wall=wall,consume_sim_time=sim,
            localization_stamp_ns=s['localization_stamp_ns'],controller_stamp_ns=s['controller_stamp_ns'],
            current_sdk_window_id=r['authorization']['activation_window_id'],original_output_sdk_window_id=r['output_authorization']['activation_window_id']))
    assert len(commands)==18 and len(steps)==779
    assert not errors and original_audit['passed'] and original_audit['consumed_steps']==779 and original_audit['actual_controller_results']==18
    goal=raw['observer_goal'];assert goal['source']=='actual_algorithm_map_to_base_link_tf' and goal['frame']=='map'
    assert goal['relative_offset_m']==[1.,0.] and goal['planner_status']==4 and goal['follow_path_status']==4 and goal['follow_path_accepted'] is True
    assert 'Reached the goal!' in files[3].read_text()
    assert all(sha(ROOT/p)==h for p,h in before.items())
    record=dict(scope='independent pure Python full receipt/ROS/SDK join; no ROS or physics executed',
        passed=True,commands=len(commands),consumed_steps=len(steps),nonzero_steps=len(steps),
        ROS_counts=dict(collections.Counter(r['topic_kind'] for r in ros)),original_audit=original_audit,
        capture_age_wall_s=dict(min=min(ages),max=max(ages)),goal=goal,controller_goal_log_confirmed=True,
        source_files_sha256=before,qa_source_sha256=sha(qa),sources_unchanged=True,
        all_receipts_verified=True,proofs=proofs)
    output=HERE/'INDEPENDENT_AUDIT.json'
    if output.exists():raise ValueError('fresh audit result required')
    output.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k!='proofs'},indent=2))
if __name__=='__main__':main()
