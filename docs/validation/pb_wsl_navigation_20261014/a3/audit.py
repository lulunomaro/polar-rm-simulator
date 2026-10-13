"""Independent read-only cross-clock receipt and original ROS action evidence audit."""
import collections
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT))
FIELDS=('robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline')

def sha(raw):return hashlib.sha256(raw).hexdigest()
def finite(v):return type(v) in (int,float) and math.isfinite(v)
def typed_equal(a,b):return type(a) is type(b) and a==b
def key(v):
    assert type(v['robot_id']) is str
    assert all(type(v[k]) is int for k in ('episode','binding_epoch','observed_seq'))
    assert all(finite(v[k]) for k in ('sim_time','wall_deadline'))
    return tuple((type(v[k]).__name__,v[k]) for k in FIELDS)
def parse(raw):
    def pairs(items):
        value={}
        for k,v in items:
            assert k not in value,'duplicate JSON key';value[k]=v
        return value
    def number(text):
        value=float(text);assert math.isfinite(value);return value
    def constant(_):raise AssertionError('nonfinite JSON')
    return json.loads(raw,object_pairs_hook=pairs,parse_float=number,parse_constant=constant)
def stamp(v):
    assert set(v)=={'sec','nanosec'} and type(v['sec']) is type(v['nanosec']) is int
    assert 0<=v['sec']<=2147483647 and 0<=v['nanosec']<1000000000
    return v['sec']*1000000000+v['nanosec']
def vector(v,fields):
    assert set(v)==set(fields) and all(finite(x) and abs(x)<=1e6 for x in v.values())
def header(v):
    assert set(v)=={'stamp','frame_id'} and v['frame_id']=='map'
    return stamp(v['stamp'])
def pose(v):
    assert set(v)=={'header','pose'} and set(v['pose'])=={'position','orientation'}
    header(v['header']);vector(v['pose']['position'],'xyz');vector(v['pose']['orientation'],'xyzw')
def transform(v):
    assert set(v)=={'header','child_frame_id','transform'} and v['child_frame_id']=='base_link'
    assert set(v['transform'])=={'translation','rotation'}
    header(v['header']);vector(v['transform']['translation'],'xyz');vector(v['transform']['rotation'],'xyzw')
def uuid(v):assert type(v) is str and re.fullmatch('[a-f0-9]{32}',v)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--attempt',type=int,choices=(3,4),default=3)
    args=parser.parse_args();expected_steps={3:553,4:514}[args.attempt];expected_results={3:42,4:55}[args.attempt]
    SOURCE=ROOT/f'artifacts/pb-wsl-navigation-sil-actual-20261014-attempt{args.attempt}'
    result_path=HERE/'RESULT.json'
    assert not result_path.exists(),'fresh audit output required'
    names=['TRACE.jsonl','session/ROS_SOURCE.jsonl','RESULT.json','session/SESSION_SPEC.json',
           'session/GOAL_REPORT.json','session/stack/controller_server.log','session/CLEANUP.json','session/stack/CLEANUP.json']
    originals={name:(SOURCE/name).read_bytes() for name in names}
    before={name:sha(raw) for name,raw in originals.items()}
    raw=parse(originals['RESULT.json']);spec=parse(originals['session/SESSION_SPEC.json'])
    qa=ROOT/'tools/qa_pb_navigation_sil.py';qa_sha=sha(qa.read_bytes())
    assert qa_sha==raw['source_sha256']['tools/qa_pb_navigation_sil.py']
    from tools.qa_pb_navigation_sil import audit_navigation_consumption
    rows=[parse(line) for line in originals['TRACE.jsonl'].splitlines()]
    ros=[parse(line) for line in originals['session/ROS_SOURCE.jsonl'].splitlines()]
    original_audit=audit_navigation_consumption(rows,ros)
    req=collections.defaultdict(list);loc=collections.defaultdict(list);res=collections.defaultdict(list)
    enqueues=collections.defaultdict(list);acks=collections.defaultdict(list);proofs=[];steps=set();commands=set();ages=[]
    for row in ros:
        assert row['receive_clock']=='linux_local_perf_counter' and finite(row['receive_wall'])
        value=row['value'];kind=row['topic_kind']
        if kind=='request':req[key(value)].append(value)
        elif kind=='localization':loc[key(value)].append(value)
        elif kind=='controller_result':res[key(value['action'])].append(value)
    assert sum(map(len,req.values()))==299 and sum(map(len,loc.values()))==297 and sum(map(len,res.values()))==expected_results
    for row in rows:
        if row['event']=='sdk_adapter_activation':
            a=row['activation'];acks[a['binding_epoch'],a['seq'],a['window_id']].append(row['window'])
        elif row['event']=='adapter_enqueue' and row['kind']=='navigation':
            value={k:row['observation_sim_time'] if k=='sim_time' else row[k] for k in FIELDS}
            enqueues[key(value)].append(row)
        elif row['event']=='adapter_result' and row['kind']=='navigation':assert not row.get('error'),'sticky adapter fault'
    for row in rows:
        if row['event']!='navigation_consumed' or row['phase']!='integration_entry' or row['target']['motion'] is None:continue
        a=row['action'];k=key(a);b=row['navigation_budget'];wall=row['consume_wall'];sim=row['consume_sim_time']
        assert a['robot_id']=='red_sentry' and a['episode']==0 and a['binding_epoch']==1
        assert a['schema']=='polar.sim.action.v2' and a['kind']=='navigation' and a['mode']=='velocity_body'
        assert row['target']['motion']==a['command'] and row['target']['fire'] is False
        assert finite(wall) and finite(sim) and type(b['frame_id']) is int
        assert all(finite(b[x]) for x in ('capture_wall','capture_sim_time','wall_deadline','sim_deadline'))
        assert b['source']=='navigation_sensor_v1' and re.fullmatch('[a-f0-9]{64}',b['profile_sha256'])
        assert b['capture_wall']<=wall<min(b['wall_deadline'],a['wall_deadline'])
        assert b['capture_sim_time']<=sim<=b['sim_deadline']
        assert 0<b['wall_deadline']-b['capture_wall']<=.150001 and 0<b['sim_deadline']-b['capture_sim_time']<=.150001
        c=a['command'];assert c['frame']=='base_link' and all(finite(c[x]) for x in ('vx_mps','vy_mps','wz_rps'))
        assert math.hypot(c['vx_mps'],c['vy_mps'])<=1 and abs(c['wz_rps'])<=2
        assert any(abs(c[x])>1e-8 for x in ('vx_mps','vy_mps','wz_rps'))
        for name in ('authorization','output_authorization'):
            auth=row[name];assert auth['activation_required'] is True
            assert all(type(auth[x]) is int for x in ('epoch','activation_seq','activation_window_id')) and auth['epoch']==1
            windows=acks[auth['epoch'],auth['activation_seq'],auth['activation_window_id']];assert len(windows)==1
            w=windows[0];assert w['lease_epochs']=={'motion':1} and type(w['lease_epochs']['motion']) is int
            assert finite(w['issued_wall']) and finite(w['expires_wall']) and finite(w['valid_for_s']) and 0<w['valid_for_s']<=.15
            assert abs(w['expires_wall']-w['issued_wall']-w['valid_for_s'])<=1e-6
            assert w['issued_wall']<=wall<auth['activation_expires']==auth['activation_window_deadline']==w['expires_wall']
        assert a['wall_deadline']<=row['output_authorization']['activation_expires']
        e=[x for x in enqueues[k] if x['sensor_budget']==b];q=req[k];assert len(e)==len(q)==1
        cloud=e[0]['cloud_acquisition'];q=q[0]
        assert type(cloud['frame_id']) is int
        assert all(type(cloud[x]) is type(q[x]) is int for x in ('acquisition_start_ns','acquisition_end_ns'))
        assert cloud['frame_id']==b['frame_id']==q['cloud_frame_id'] and type(q['cloud_frame_id']) is int
        assert cloud['profile_sha256']==b['profile_sha256']
        assert cloud['acquisition_start_ns']==q['acquisition_start_ns'] and cloud['acquisition_end_ns']==q['acquisition_end_ns']==round(b['capture_sim_time']*1e9)
        matching_l=[x for x in loc[k] if all(typed_equal(x[f],q[f]) for f in (*FIELDS,'adapter_id','cloud_frame_id','acquisition_start_ns','acquisition_end_ns'))]
        matching_r=[x for x in res[k] if key(x['action'])==k and x['action']==a and x['source']['cloud_frame_id']==b['frame_id']]
        assert len(matching_l)==len(matching_r)==1
        l=matching_l[0];s=matching_r[0]['source'];assert s['controller_id']=='pb_controller_sourced_v1'
        assert all(type(s[x]) is int for x in ('cloud_frame_id','localization_stamp_ns','controller_stamp_ns'))
        assert typed_equal(l['localization_stamp_ns'],s['localization_stamp_ns'])
        assert q['acquisition_start_ns']<=s['localization_stamp_ns']<=s['controller_stamp_ns']<=q['acquisition_end_ns']
        assert sim not in steps,'duplicate physical consumption step'
        steps.add(sim);commands.add(k);ages.append(wall-b['capture_wall'])
        proofs.append(dict(original_identity={f:a[f] for f in FIELDS},cloud=cloud,consume_wall=wall,consume_sim_time=sim,
            localization_stamp_ns=s['localization_stamp_ns'],controller_stamp_ns=s['controller_stamp_ns'],
            current_sdk_window_id=row['authorization']['activation_window_id'],output_sdk_window_id=row['output_authorization']['activation_window_id']))
    assert len(steps)==expected_steps and original_audit['passed'] and original_audit['consumed_steps']==expected_steps
    action_kinds=('goal_source_tf','planner_goal_accepted','planner_path_result','follow_path_goal_accepted','follow_path_result','ending_estimated_tf')
    actions={name:[r for r in ros if r['topic_kind']==name] for name in action_kinds}
    assert all(len(value)==1 for value in actions.values())
    values={name:actions[name][0]['value'] for name in action_kinds};base=values['goal_source_tf']
    uuid(base['action_request_id']);previous=-1
    for name in action_kinds:
        row=actions[name][0];v=row['value']
        assert v['schema']=='polar.pb.algorithm-action-evidence.v1' and v['namespace']==spec['namespace']
        assert v['action_request_id']==base['action_request_id'] and type(v['action_request_seq']) is int and v['action_request_seq']==1
        assert previous<=row['receive_wall'];previous=row['receive_wall']  # Linux-only ordering, no Windows subtraction
        assert len(json.dumps(v,allow_nan=False).encode())<=2*1024*1024
    transform(base['transform']);pose(base['goal']);assert base['source_kind']=='actual_tf_buffer_lookup'
    assert base['goal']['header']==base['transform']['header'] and base['relative_offset_m']==[1.,0.]
    translation=base['transform']['transform']['translation'];position=base['goal']['pose']['position']
    recomputed=[translation['x']+1.,translation['y']]
    assert [position['x'],position['y']]==recomputed and position['z']==0.
    assert base['goal']['pose']['orientation']==base['transform']['transform']['rotation']
    assert base['planner_id']=='GridBased' and base['use_start'] is False
    accepted=values['planner_goal_accepted'];planned=values['planner_path_result']
    uuid(accepted['goal_uuid']);assert accepted['accepted'] is True and planned['goal_uuid']==accepted['goal_uuid']
    assert type(planned['status']) is int and planned['status']==4 and planned['planner_id']=='GridBased' and planned['use_start'] is False
    for name in action_kinds[:3]:assert values[name]['action_name']==spec['namespace']+'/compute_path_to_pose'
    path=planned['path'];path_stamp=header(path['header']);assert 2<=len(path['poses'])<=4096
    for p in path['poses']:pose(p)
    stamp(planned['planning_time'])
    follow=values['follow_path_goal_accepted'];done=values['follow_path_result'];uuid(follow['goal_uuid'])
    assert follow['accepted'] is True and follow['planner_goal_uuid']==accepted['goal_uuid'] and follow['goal_uuid']!=accepted['goal_uuid']
    assert follow['controller_id']=='FollowPath' and follow['goal_checker_id']=='general_goal_checker'
    assert done['goal_uuid']==follow['goal_uuid'] and done['planner_goal_uuid']==accepted['goal_uuid'] and type(done['status']) is int and done['status']==4
    for name in action_kinds[3:5]:assert values[name]['action_name']==spec['namespace']+'/follow_path'
    ending=values['ending_estimated_tf'];transform(ending['transform'])
    assert ending['source_kind']=='actual_tf_buffer_lookup' and ending['postprocess_only'] is True
    assert ending['algorithm_input'] is False and ending['groundtruth_frame_comparison_qualified'] is False
    assert header(base['transform']['header'])<=header(ending['transform']['header'])<=round(raw['simulation_seconds']*1e9)
    assert 'Reached the goal!' in originals['session/stack/controller_server.log'].decode()
    goal=raw['observer_goal'];assert goal['goal_xy']==recomputed and goal['source_stamp_ns']==header(base['transform']['header'])
    assert goal['path_poses']==len(path['poses'])==14 and goal['planner_status']==planned['status'] and goal['follow_path_status']==done['status']
    assert parse(originals['session/GOAL_REPORT.json'])==goal
    assert parse(originals['session/CLEANUP.json'])['clean'] is True and parse(originals['session/stack/CLEANUP.json'])['clean'] is True
    assert all((SOURCE/name).read_bytes()==value for name,value in originals.items()) and sha(qa.read_bytes())==qa_sha
    record=dict(schema='polar.pb.windows-wsl-independent-audit.v1',passed=True,
        attempt=args.attempt,qualification='read-only original receipts/ROS/SDK/action chain; no ROS/physics run, no Linux/Windows wall clock subtraction; two passes do not establish the root cause of earlier intermittent timeout',
        clock_domains=dict(receipt_and_sdk='Windows host QPC',observer='Linux local perf_counter',ros_stamps='original simulation clock',cross_domain_subtraction=False),
        commands=len(commands),nonzero_consumed_steps=len(steps),ROS_counts=dict(collections.Counter(r['topic_kind'] for r in ros)),
        original_audit=original_audit,capture_age_host_wall_s=dict(min=min(ages),max=max(ages)),
        goal_evidence=dict(original_records=actions,recomputed_goal_xy=recomputed,path_pose_count=len(path['poses']),
            path_header_stamp_ns=path_stamp,planner_uuid=accepted['goal_uuid'],follow_uuid=follow['goal_uuid'],raw_controller_goal_log=True,
            ending_estimate_postprocess_only=True,groundtruth_frame_comparison_qualified=False),
        physics_rtf_qualification='Attempt3 original physics_rtf includes runtime.close; attempt4 separately measures physics run and run+cleanup. No independent physical performance run in this audit.',
        source_files_sha256=before,qa_source_sha256=qa_sha,audit_script_sha256=sha(Path(__file__).read_bytes()),sources_unchanged=True,proofs=proofs)
    result_path.write_text(json.dumps(record,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in record.items() if k not in ('proofs','goal_evidence')},indent=2))

if __name__=='__main__':main()
