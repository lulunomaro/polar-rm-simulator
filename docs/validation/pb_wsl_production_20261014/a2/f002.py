"""Independent production Gate/external action/SDK consumption evidence audit.

Read frozen files only. Counts are computed, never supplied as success constants.
No ROS/WSL/physics/helper-harness execution or cross-wall-clock subtraction.
"""
import argparse
import collections
import gzip
import hashlib
import json
import math
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
FIELDS=('robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline')


def sha(raw):return hashlib.sha256(raw).hexdigest()
def finite(v):return type(v) in (int,float) and math.isfinite(v)
def same(a,b):return type(a) is type(b) and a==b
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
def uuid(v):assert type(v) is str and re.fullmatch('[a-f0-9]{32}',v)
def stamp(v):
    assert set(v)=={'sec','nanosec'} and type(v['sec']) is type(v['nanosec']) is int
    assert 0<=v['sec']<=2147483647 and 0<=v['nanosec']<1000000000
    return v['sec']*1000000000+v['nanosec']
def vector(v,fields):assert set(v)==set(fields) and all(finite(x) and abs(x)<=1e6 for x in v.values())
def header(v):
    assert set(v)=={'stamp','frame_id'} and v['frame_id']=='map';return stamp(v['stamp'])
def pose(v):
    assert set(v)=={'header','pose'} and set(v['pose'])=={'position','orientation'}
    header(v['header']);vector(v['pose']['position'],'xyz');vector(v['pose']['orientation'],'xyzw')
def transform(v):
    assert set(v)=={'header','child_frame_id','transform'} and v['child_frame_id']=='base_link'
    assert set(v['transform'])=={'translation','rotation'}
    header(v['header']);vector(v['transform']['translation'],'xyz');vector(v['transform']['rotation'],'xyzw')
def identical_fields(a,b,fields):assert all(k in a and k in b and same(a[k],b[k]) for k in fields)
def deep_same(a,b):
    if type(a) is not type(b):return False
    if type(a) is dict:return set(a)==set(b) and all(deep_same(a[k],b[k]) for k in a)
    if type(a) is list:return len(a)==len(b) and all(deep_same(x,y) for x,y in zip(a,b))
    return a==b


def audit_costmap(events,namespace,goal_record,goal_receive_wall):
    """Recompute geometry only; no unavailable raw-data/cell-cost hash claim."""
    receipts={};decisions=[]
    for event in events:
        if event['event']=='global_costmap_received':
            grid=event['grid']
            assert set(grid)=={'schema','receipt_id','source','topic','message_type','header','metadata','data_bytes','data_sha256','receive_wall','receive_clock'}
            assert grid['schema']=='polar.pb.actual-global-costmap.v1'
            rid=grid['receipt_id'];assert type(rid) is int and 1<=rid<=128 and rid not in receipts
            assert grid['source']=='actual_raw_costmap_subscription' and grid['topic']==namespace+'/global_costmap/costmap_raw'
            assert grid['message_type']=='nav2_msgs/msg/Costmap' and grid['receive_clock']==event['receive_clock']=='linux_local_perf_counter'
            assert finite(grid['receive_wall']) and grid['receive_wall']<=event['receive_wall'];header(grid['header'])
            meta=grid['metadata'];assert set(meta)=={'size_x','size_y','resolution','origin','layer','map_load_time','update_time'}
            assert type(meta['size_x']) is type(meta['size_y']) is int and 1<=meta['size_x']<=4096 and 1<=meta['size_y']<=4096
            assert finite(meta['resolution']) and 0<meta['resolution']<=10
            assert set(meta['origin'])=={'position','orientation'}
            vector(meta['origin']['position'],'xyz');vector(meta['origin']['orientation'],'xyzw')
            assert deep_same(meta['origin']['orientation'],{'x':0.,'y':0.,'z':0.,'w':1.})
            assert type(meta['layer']) is str and len(meta['layer'])<=128
            stamp(meta['map_load_time']);stamp(meta['update_time'])
            assert type(grid['data_bytes']) is int and grid['data_bytes']==meta['size_x']*meta['size_y']
            assert type(grid['data_sha256']) is str and re.fullmatch('[a-f0-9]{64}',grid['data_sha256'])
            receipts[rid]=(event,grid)
        elif event['event']=='global_costmap_readiness':
            value=event['decision']
            assert set(value)=={'schema','grid_receipt_id','grid_data_sha256','grid_header','actual_tf','actual_goal','start_cell','goal_cell','ready','predicate','costs_affect_predicate','planner_feasibility_qualified'}
            assert value['schema']=='polar.pb.global-costmap-readiness.v1'
            rid=value['grid_receipt_id'];assert type(rid) is int and rid in receipts
            original_event,grid=receipts[rid]
            assert original_event['receive_wall']<=event['receive_wall']
            assert same(value['grid_data_sha256'],grid['data_sha256']) and deep_same(value['grid_header'],grid['header'])
            transform(value['actual_tf']);pose(value['actual_goal'])
            assert deep_same(value['actual_goal']['header'],value['actual_tf']['header'])
            assert value['predicate']=='same_published_map_geometry_half_open_bounds'
            assert value['costs_affect_predicate'] is False and value['planner_feasibility_qualified'] is False
            meta=grid['metadata'];origin=meta['origin']['position'];resolution=meta['resolution'];computed=[]
            for name,point in (('start_cell',value['actual_tf']['transform']['translation']),('goal_cell',value['actual_goal']['pose']['position'])):
                cell=value[name];assert set(cell)=={'in_bounds','index_xy','cost'}
                x=(point['x']-origin['x'])/resolution;y=(point['y']-origin['y'])/resolution
                inside=0<=x<meta['size_x'] and 0<=y<meta['size_y'];indices=[math.floor(x),math.floor(y)]
                assert same(cell['in_bounds'],inside) and type(cell['index_xy']) is list and len(cell['index_xy'])==2
                assert all(type(v) is int for v in cell['index_xy']) and cell['index_xy']==indices
                if inside:assert type(cell['cost']) is int and 0<=cell['cost']<=255
                else:assert cell['cost'] is None
                computed.append(inside)
            assert same(value['ready'],all(computed))
            decisions.append((event,value))
    accepted=[(event,value) for event,value in decisions if value['ready'] is True]
    assert receipts and decisions and len(accepted)==1,'one recorded accepted geometry decision required'
    event,value=accepted[0]
    assert event['receive_wall']<=goal_receive_wall
    assert deep_same(value['actual_tf'],goal_record['transform']) and deep_same(value['actual_goal'],goal_record['goal'])
    return dict(raw_receipt_count=len(receipts),decision_count=len(decisions),accepted_decision=event,
                accepted_raw_receipt=receipts[value['grid_receipt_id']][0],half_open_bounds_independently_recomputed=True,
                geometry_indices_independently_recomputed=True,data_sha256_continuity_verified=True,
                whole_raw_grid_bytes_preserved=False,data_sha256_independently_recomputed=False,
                cell_costs_independently_recomputed=False,costs_do_not_affect_bounds_predicate=True,
                planner_feasibility_qualified=False)


def audit(source):
    frozen={}
    def read(name):
        path=source/name
        if not path.is_file():path=Path(str(path)+'.gz')
        assert path.is_file(),'missing frozen evidence '+name
        raw=path.read_bytes();frozen[path.relative_to(source).as_posix()]=raw
        return gzip.decompress(raw) if path.suffix=='.gz' else raw
    def document(name):return parse(read(name))
    raw=document('RESULT.json');spec=document('session/SESSION_SPEC.json')
    gate=document('session/PRODUCTION_GATE_STATUS.json')
    peer_spec=document('peer/EXTERNAL_SPEC.json');peer=document('peer/RESULT.json')
    peer_ready=document('peer/READY.json');peer_goal=document('peer/GOAL_REPORT.json')
    peer_clean=document('peer/CLEANUP.json');peer_supervisor=document('peer/SUPERVISOR_CLEANUP.json')
    peer_started=document('peer/SUPERVISOR_STARTED.json');peer_spawn=document('peer/SPAWN.json')
    session_started=document('session/WORKER_STARTED.json');session_clean=document('session/CLEANUP.json')
    stack_clean=document('session/stack/CLEANUP.json')
    controller_log=read('session/stack/controller_server.log').decode('utf8',errors='replace')
    planner_log=read('session/stack/planner_server.log').decode('utf8',errors='replace')
    trace=[parse(line) for line in read('TRACE.jsonl').splitlines() if line]
    ros=[parse(line) for line in read('peer/ROS_SOURCE.jsonl').splitlines() if line]
    events=[parse(line) for line in read('peer/EXTERNAL_EVENTS.jsonl').splitlines() if line]
    assert raw['schema']=='polar.pb.windows-wsl-production-sil.v1' and raw['internal_test_goal'] is False
    assert spec['relative_test_goal'] is False
    uuid(spec['run_uuid']);namespace='/polar_sil_'+spec['run_uuid']+'/red_sentry'
    assert spec['namespace']==namespace==peer_spec['namespace']==peer['namespace']==peer_ready['namespace']==gate['namespace']
    assert spec['expected_generation']=={'robot_id':'red_sentry','episode':0,'binding_epoch':1}
    for field,v in spec['expected_generation'].items():assert same(v,{'robot_id':'red_sentry','episode':0,'binding_epoch':1}[field])
    assert gate['production_gate'] is True and gate['stack_state']=='ACTIVE' and gate['activation_started'] is True
    assert type(gate['map_messages']) is type(gate['odometry_messages']) is int and gate['map_messages']>0 and gate['odometry_messages']>0
    assert type(gate['latest_odom_stamp_ns']) is int and 0<=gate['latest_odom_stamp_ns']<=round(raw['simulation_seconds']*1e9)
    assert gate['errors']==[] and gate['clock_domain']=='linux_local_receive_only'
    assert raw['production_gate_status']==gate
    for value in (peer_spec,peer,peer_ready):
        uuid(value['run_uuid']);assert value['run_uuid']==peer_spec['run_uuid'] and value['session_run_uuid']==spec['run_uuid']
    assert peer_spec['domain_id']==peer_ready['domain_id']==84 and type(peer_spec['domain_id']) is type(peer_ready['domain_id']) is int
    assert peer_spec['environment_ref']==spec['environment_ref']==peer['environment_ref']
    assert peer_ready['environment_sha256']==spec['environment_ref']['sha256']
    assert sha(frozen['peer/EXTERNAL_SPEC.json'])==peer_ready['spec_sha256']==peer_started['spec_sha256']==peer_supervisor['spec_sha256']
    for field in ('lifecycle_changed','sensor_published'):
        assert peer[field] is False and peer_ready[field] is False
    assert peer['cmd_vel_published'] is False and peer['algorithm_input_has_truth'] is False and peer_ready['goal_sent'] is False
    assert peer_ready['state']=='OBSERVING_NO_INPUT_PUBLISHED'
    assert peer_ready['source_sha256']==peer_spec['source_sha256']==peer['source_sha256']
    assert all(name in raw['source_sha256'] and same(digest,raw['source_sha256'][name]) for name,digest in peer_spec['source_sha256'].items())
    assert raw['external_client_result']==peer and raw['external_supervisor_cleanup']==peer_supervisor
    # Peer owns only its own client; services observed are GetState, not ChangeState.
    states={}
    for event in events:
        # Metadata may be appended by both the ROS callback and the main client
        # thread. Require actual per-receipt causality, not global list ordering.
        assert event['receive_clock']=='linux_local_perf_counter' and finite(event['receive_wall'])
        if event['event']=='gate_state_observed':
            assert event['node'] in ('controller_server','planner_server')
            assert event['service']==namespace+'/'+event['node']+'/get_state' and type(event['state']) is int
            states[event['node']]=event['state']
        assert 'change_state' not in json.dumps(event).lower(),'external lifecycle change evidence'
    assert states=={'controller_server':3,'planner_server':3}
    active_rows=[e for e in events if e['event']=='gate_state_observed' and e['state']==3]
    assert len(active_rows)>=2
    # Session and client/supervisor/group identities are independently linked.
    assert session_clean['schema']=='polar.pb.wsl-session-cleanup.v1' and session_clean['run_uuid']==spec['run_uuid']
    assert session_clean['config_sha256']==spec['config_ref']['sha256']
    identical_fields(session_started,session_clean,('supervisor_pid','start_ticks','boot_id'))
    assert session_clean['clean'] is True and session_clean['errors']==[] and session_clean['owned_groups']==[]
    assert stack_clean['clean'] is True and stack_clean['errors']==[] and stack_clean['assets_unchanged'] is True
    assert len(stack_clean['processes'])==9 and len({p['pid'] for p in stack_clean['processes']})==9
    assert all(type(p['pid']) is int and p['pid']>1 and type(p['returncode']) is int and p['remaining_members']==[] for p in stack_clean['processes'])
    assert all(asset['unchanged'] is True and asset['actual_sha256']==asset['expected_sha256'] for asset in stack_clean['assets_after'].values())
    assert peer_supervisor['clean'] is True and peer_supervisor['errors']==[] and peer_supervisor['returncode']==0
    identical_fields(peer_started,peer_supervisor,('run_uuid','supervisor_pid','start_ticks','boot_id','spec_sha256'))
    owned=peer_spawn['identity'];group=peer_supervisor['group']
    identical_fields(owned,group,('run_id','supervisor_pid','boot_id','pid','pgid','leader_start_ticks'))
    assert group['clean'] is True and group['reaped'] is True and group['group_empty'] is True and group['remaining_members']==[] and group['errors']==[] and group['returncode']==0
    assert same(group['pid'],group['pgid']) and group['supervisor_pid']==peer_started['supervisor_pid']
    assert peer_clean['run_uuid']==peer_spec['run_uuid'] and peer_supervisor['client_cleanup']==peer_clean==peer['cleanup']
    assert peer_clean['clean'] is True and peer_clean['errors']==[] and peer_clean['observer_thread_alive'] is False and peer_clean['session_node_processes_owned'] is False
    identical_fields(peer_clean,peer_ready,('pid','start_ticks','boot_id'))
    assert same(peer_clean['pid'],group['pid']) and same(peer_clean['start_ticks'],group['leader_start_ticks'])
    assert peer_clean['boot_id']==group['boot_id']==session_clean['boot_id']
    assert len(peer_spawn['argv'])>=2 and Path(peer_spawn['argv'][0]).is_absolute() and '--run' in peer_spawn['argv']
    # Independent typed six-identity, cloud acquisition, LIO and SDK join.
    req=collections.defaultdict(list);loc=collections.defaultdict(list);res=collections.defaultdict(list)
    enqueues=collections.defaultdict(list);acks=collections.defaultdict(list);steps=set();commands=set();proofs=[];ages=[]
    for row in ros:
        assert row['receive_clock']=='linux_local_perf_counter' and finite(row['receive_wall'])
        value=row['value'];kind=row['topic_kind']
        if kind=='request':req[key(value)].append(value)
        elif kind=='localization':loc[key(value)].append(value)
        elif kind=='controller_result':res[key(value['action'])].append(value)
    for row in trace:
        if row['event']=='sdk_adapter_activation':
            a=row['activation'];acks[a['binding_epoch'],a['seq'],a['window_id']].append(row['window'])
        elif row['event']=='adapter_enqueue' and row['kind']=='navigation':
            value={k:row['observation_sim_time'] if k=='sim_time' else row[k] for k in FIELDS};enqueues[key(value)].append(row)
        elif row['event']=='adapter_result' and row['kind']=='navigation':assert not row.get('error'),'adapter fault'
    for row in trace:
        if row['event']!='navigation_consumed' or row['phase']!='integration_entry' or row['target']['motion'] is None:continue
        a=row['action'];c=a['command']
        assert all(finite(c[f]) for f in ('vx_mps','vy_mps','wz_rps'))
        if not any(abs(c[f])>1e-8 for f in ('vx_mps','vy_mps','wz_rps')):continue
        k=key(a);b=row['navigation_budget'];wall=row['consume_wall'];sim=row['consume_sim_time']
        identical_fields(a,spec['expected_generation'],('robot_id','episode','binding_epoch'))
        assert a['schema']=='polar.sim.action.v2' and a['kind']=='navigation' and a['mode']=='velocity_body'
        assert row['target']['motion']==c and row['target']['fire'] is False
        assert finite(wall) and finite(sim) and type(b['frame_id']) is int
        assert all(finite(b[f]) for f in ('capture_wall','capture_sim_time','wall_deadline','sim_deadline'))
        assert b['source']=='navigation_sensor_v1' and re.fullmatch('[a-f0-9]{64}',b['profile_sha256'])
        assert b['capture_wall']<=wall<min(b['wall_deadline'],a['wall_deadline']) and b['capture_sim_time']<=sim<=b['sim_deadline']
        assert 0<b['wall_deadline']-b['capture_wall']<=.150001 and 0<b['sim_deadline']-b['capture_sim_time']<=.150001
        assert c['frame']=='base_link' and all(finite(c[f]) for f in ('vx_mps','vy_mps','wz_rps'))
        assert math.hypot(c['vx_mps'],c['vy_mps'])<=1 and abs(c['wz_rps'])<=2
        for name in ('authorization','output_authorization'):
            auth=row[name];assert auth['activation_required'] is True
            assert all(type(auth[f]) is int for f in ('epoch','activation_seq','activation_window_id')) and auth['epoch']==a['binding_epoch']
            matching=acks[auth['epoch'],auth['activation_seq'],auth['activation_window_id']];assert len(matching)==1
            w=matching[0];assert w['lease_epochs']=={'motion':auth['epoch']} and type(w['lease_epochs']['motion']) is int
            assert all(finite(w[f]) for f in ('issued_wall','expires_wall','valid_for_s')) and 0<w['valid_for_s']<=.15
            assert abs(w['expires_wall']-w['issued_wall']-w['valid_for_s'])<=1e-6
            assert w['issued_wall']<=wall<auth['activation_expires']==auth['activation_window_deadline']==w['expires_wall']
        assert a['wall_deadline']<=row['output_authorization']['activation_expires']
        e=[x for x in enqueues[k] if x['sensor_budget']==b];q=req[k];assert len(e)==len(q)==1
        q=q[0];cloud=e[0]['cloud_acquisition']
        assert type(cloud['frame_id']) is type(q['cloud_frame_id']) is int and cloud['frame_id']==b['frame_id']==q['cloud_frame_id']
        for field in ('acquisition_start_ns','acquisition_end_ns'):assert type(cloud[field]) is type(q[field]) is int and cloud[field]==q[field]
        assert cloud['profile_sha256']==b['profile_sha256'] and q['acquisition_end_ns']==round(b['capture_sim_time']*1e9)
        matching_l=[l for l in loc[k] if all(same(l[f],q[f]) for f in (*FIELDS,'adapter_id','cloud_frame_id','acquisition_start_ns','acquisition_end_ns'))]
        matching_r=[r for r in res[k] if key(r['action'])==k and r['action']==a and same(r['source']['cloud_frame_id'],b['frame_id'])]
        assert len(matching_l)==len(matching_r)==1
        l=matching_l[0];s=matching_r[0]['source'];assert s['controller_id']=='pb_controller_sourced_v1'
        assert all(type(s[f]) is int for f in ('cloud_frame_id','localization_stamp_ns','controller_stamp_ns'))
        assert same(l['localization_stamp_ns'],s['localization_stamp_ns'])
        assert q['acquisition_start_ns']<=s['localization_stamp_ns']<=s['controller_stamp_ns']<=q['acquisition_end_ns']
        assert sim not in steps,'duplicate integration consumption';steps.add(sim);commands.add(k);ages.append(wall-b['capture_wall'])
        proofs.append(dict(identity={f:a[f] for f in FIELDS},cloud=cloud,consume_wall=wall,consume_sim_time=sim,
            localization_stamp_ns=s['localization_stamp_ns'],controller_stamp_ns=s['controller_stamp_ns'],
            current_sdk_window_id=row['authorization']['activation_window_id'],output_sdk_window_id=row['output_authorization']['activation_window_id']))
    counts=dict(request=sum(map(len,req.values())),localization=sum(map(len,loc.values())),controller_result=sum(map(len,res.values())))
    original=raw['consumption_audit']
    assert original['actual_sensor_requests']==counts['request'] and original['actual_localizations']==counts['localization'] and original['actual_controller_results']==counts['controller_result']
    assert original['nonzero_consumed_steps']==len(steps) and len(steps)>0 and original['passed'] is True and original['errors']==[]
    # External action sequence: GetState ACTIVE precedes goal, immutable request and UUID chain.
    kinds=('goal_source_tf','planner_goal_accepted','planner_path_result','follow_path_goal_accepted','follow_path_result','ending_estimated_tf')
    actions={name:[r for r in ros if r['topic_kind']==name] for name in kinds}
    assert all(len(v)==1 for v in actions.values())
    values={name:actions[name][0]['value'] for name in kinds};base=values['goal_source_tf'];previous=-1
    assert base['action_request_id']==peer_spec['run_uuid'];uuid(base['action_request_id'])
    for name in kinds:
        row=actions[name][0];value=row['value']
        assert value['schema']=='polar.pb.algorithm-action-evidence.v1' and value['namespace']==namespace
        assert same(value['action_request_id'],base['action_request_id']) and type(value['action_request_seq']) is int and value['action_request_seq']==1
        assert previous<=row['receive_wall'];previous=row['receive_wall']
    assert max(e['receive_wall'] for e in active_rows)<=actions['goal_source_tf'][0]['receive_wall']
    costmap_proof=audit_costmap(events,namespace,base,actions['goal_source_tf'][0]['receive_wall'])
    transform(base['transform']);pose(base['goal']);assert base['source_kind']=='actual_tf_buffer_lookup'
    assert base['goal']['header']==base['transform']['header'] and base['relative_offset_m']==peer_spec['goal_offset_m']==[1.,0.]
    translation=base['transform']['transform']['translation'];position=base['goal']['pose']['position'];xy=[translation['x']+1.,translation['y']]
    assert [position['x'],position['y']]==xy and position['z']==0. and base['goal']['pose']['orientation']==base['transform']['transform']['rotation']
    accepted=values['planner_goal_accepted'];planned=values['planner_path_result'];uuid(accepted['goal_uuid'])
    assert accepted['accepted'] is True and planned['goal_uuid']==accepted['goal_uuid'] and type(planned['status']) is int and planned['status']==4
    assert base['planner_id']==planned['planner_id']=='GridBased' and base['use_start'] is planned['use_start'] is False
    for name in kinds[:3]:assert values[name]['action_name']==namespace+'/compute_path_to_pose'
    path=planned['path'];path_stamp=header(path['header']);assert 2<=len(path['poses'])<=4096
    for item in path['poses']:pose(item)
    stamp(planned['planning_time'])
    follow=values['follow_path_goal_accepted'];done=values['follow_path_result'];uuid(follow['goal_uuid'])
    assert follow['accepted'] is True and follow['planner_goal_uuid']==accepted['goal_uuid'] and follow['goal_uuid']!=accepted['goal_uuid']
    assert follow['controller_id']=='FollowPath' and follow['goal_checker_id']=='general_goal_checker'
    assert done['goal_uuid']==follow['goal_uuid'] and done['planner_goal_uuid']==accepted['goal_uuid'] and type(done['status']) is int and done['status']==4
    for name in kinds[3:5]:assert values[name]['action_name']==namespace+'/follow_path'
    ending=values['ending_estimated_tf'];transform(ending['transform'])
    assert ending['postprocess_only'] is True and ending['algorithm_input'] is False and ending['groundtruth_frame_comparison_qualified'] is False
    assert header(base['transform']['header'])<=header(ending['transform']['header'])<=round(raw['simulation_seconds']*1e9)
    assert peer_goal==peer['goal_report']==raw['observer_goal'] and peer_goal['goal_xy']==xy and peer_goal['source_stamp_ns']==header(base['transform']['header'])
    assert peer_goal['path_poses']==len(path['poses']) and peer_goal['planner_status']==4 and peer_goal['follow_path_status']==4
    assert 'Reached the goal!' in controller_log
    assert peer['goal_completed'] is True and raw['runtime_error'] is None and raw['errors']==[]
    assert raw['completed_requested_wall_duration'] is True and raw['bounded_navigation_consumption_passed'] is True
    assert raw['source_unchanged'] is True and raw['sensor_input_has_truth'] is False and raw['fire_permission'] is False
    assert raw['shutdown']['clean'] is True and raw['shutdown']['unfinished_slots']==[] and raw['shutdown']['lifecycle_errors']==[]
    assert all((source/name).read_bytes()==data for name,data in frozen.items()),'frozen original bytes changed'
    return dict(schema='polar.pb.production-independent-audit.v1',passed=True,source=str(source.relative_to(ROOT)),
        scope='Read-only production Gate/external raw action→original SDK→all nonzero physical consumption; no new run/mission/hardware/accuracy acceptance',
        internal_test_goal=False,production_gate=gate,external_state_observations=active_rows,
        actual_costmap_geometry=costmap_proof,
        ROS_counts=counts,nonzero_consumed_steps=len(steps),consumed_command_identities=len(commands),
        capture_age_host_wall_s=dict(min=min(ages),max=max(ages)),proofs=proofs,
        external_action_evidence=dict(original_records=actions,goal_xy=xy,path_pose_count=len(path['poses']),
            path_stamp_ns=path_stamp,planner_uuid=accepted['goal_uuid'],follow_uuid=follow['goal_uuid']),
        resource_cleanup=dict(session=session_clean,stack=stack_clean,peer=peer_clean,external_supervisor=peer_supervisor),
        clock_domains=dict(host='Windows QPC receipt/SDK',peer='Linux local perf_counter',sensor_and_ros='original sim clock',cross_domain_subtraction=False),
        original_files_sha256={name:sha(data) for name,data in frozen.items()},originals_unchanged=True,
        algorithm_source_sha256=raw['source_sha256'],audit_script_sha256=sha(Path(__file__).read_bytes()))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True)
    args=parser.parse_args();source=args.source.absolute()
    assert source.resolve().is_relative_to(ROOT/'artifacts') and not source.is_symlink()
    result=HERE/'RESULT.json';assert not result.exists(),'fresh audit output required'
    try:report=audit(source)
    except Exception as exc:
        report=dict(schema='polar.pb.production-independent-audit.v1',passed=False,error_type=type(exc).__name__,error=str(exc),
                    source=str(source.relative_to(ROOT)),audit_script_sha256=sha(Path(__file__).read_bytes()),scope='Read-only evidence rejection; no rerun')
    result.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('proofs','external_action_evidence','resource_cleanup')},indent=2))
    return 0 if report['passed'] else 2


if __name__=='__main__':raise SystemExit(main())
