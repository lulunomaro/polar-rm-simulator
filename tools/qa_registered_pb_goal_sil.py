"""Opt-in registered PB navigation plus synthetic estimated-feedback policy SIL.

The public SDK binds one registered RobotIO pipeline. Its separately owned
navigation peer receives actual 200 kpoint/s MuJoCo ray/IMU observations; its
decision peer receives only the exact returned estimate/goal feedback and own
referee state. No external goal client or special PB registry is used here.
World state is read only for isolated evaluation after authority has stopped.
This is neither PB match-tree, aiming, DDS timing, RTF nor complete-match proof.
"""
from __future__ import annotations

import argparse
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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
RID='red_sentry'
IDENTITY=('robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline')
PRODUCTION_TOOLS=(
    'tools/pb_navigation_stack.py','tools/qa_pb_navigation_sil.py',
    'tools/audit_navigation_goals.py','tools/prepare_nav2_goal_controller_overlay.py',
)


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes((json.dumps(value,allow_nan=False,indent=2)+'\n').encode('utf8'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def typed(value):
    if type(value) is dict:
        return (dict,tuple((k,typed(v)) for k,v in sorted(value.items())))
    if type(value) is list:return (list,tuple(typed(v) for v in value))
    if type(value) not in (str,int,float,bool,type(None)):
        raise ValueError('audit_non_json_value')
    if type(value) is float and not math.isfinite(value):raise ValueError('audit_nonfinite')
    return (type(value),value)


def source_key(value):
    from rm_match.platform_v2.contracts import identity
    identity(value)
    return tuple((type(value[k]).__name__,value[k]) for k in IDENTITY)


def host_input_path(linux):
    """Map a declared mounted local input for reading, never invoke a shell."""
    if type(linux) is not str or len(linux)<8 or not linux.startswith('/mnt/') or linux[6]!='/' or linux[5] not in 'abcdefghijklmnopqrstuvwxyz':
        raise ValueError('probe_input_must_be_explicit_mounted_local_file')
    path=Path(linux[5].upper()+':/'+linux[7:]).absolute()
    if not path.is_file() or not path.is_relative_to(ROOT):
        raise ValueError('probe_input_outside_repo_or_missing')
    return path


def peer_spec_reference(nav_row):
    command=list(nav_row['command'])
    if command[1:2]==['-u']:command=[command[0],*command[2:]]
    if command[1:3]!=['-m','rm_match.integrations.pb_goal_plugin_peer']:
        raise ValueError('explicit_real_pb_goal_plugin_peer_required')
    if len(command)!=7 or command[3]!='--spec' or command[5]!='--sha256':
        raise ValueError('exact_reviewed_pb_peer_arguments_required')
    return host_input_path(command[4]),command[6]


def peer_inputs(nav_row,peer_out):
    from rm_match.deployment.profile import read_json_snapshot
    from rm_match.deployment.wsl_jsonl import mounted_path
    path,expected=peer_spec_reference(nav_row);spec,sha=read_json_snapshot(path)
    if sha!=expected:raise ValueError('peer_spec_sha256_mismatch')
    if spec.get('out_linux')!=mounted_path(peer_out):raise ValueError('peer_evidence_output_spec_mismatch')
    if spec.get('expected_generation')!=dict(robot_id=RID,episode=0,binding_epoch=1):
        raise ValueError('probe_peer_generation')
    paths={path}
    for name in ('config_ref','environment_ref'):
        ref=spec[name];selected=host_input_path(ref['path'])
        if digest(selected)!=ref['sha256']:raise ValueError('peer_'+name+'_changed')
        paths.add(selected)
    for relative,expected in spec['source_sha256'].items():
        selected=(ROOT/relative).absolute()
        if not selected.is_relative_to(ROOT) or digest(selected)!=expected:
            raise ValueError('peer_source_changed:'+relative)
        paths.add(selected)
    return paths


def copy_sources(out,graph,extra_inputs=()):
    """Snapshot actual program and manifest bytes; no ELF/models/credentials."""
    selected={Path(__file__).resolve(),*(ROOT/p for p in PRODUCTION_TOOLS),ROOT/'rm_match/harness.xml'}
    selected.update((ROOT/'rm_match').rglob('*.py'))
    selected.update((ROOT/'rm_match').rglob('*.hpp'))
    selected.add(graph['path']);selected.update(graph['paths'].values())
    selected.update(extra_inputs)
    for rows in graph['rows'].values():
        for row in rows:
            # Capture explicit repo-local wrapper/fixture programs selected by
            # the manifest, not the Python executable or installed ROS assets.
            for arg in row['command'][1:]:
                candidate=Path(row['cwd'])/arg
                if candidate.suffix=='.py' and candidate.is_file() and candidate.resolve().is_relative_to(ROOT):
                    selected.add(candidate.resolve())
    records=[]
    for index,path in enumerate(sorted(selected,key=str)):
        raw=path.read_bytes()
        relative=path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else 'external-inputs/'+str(index)+'-'+path.name
        destination=out/'source'/relative;destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(raw)
        records.append(dict(path=str(path),archive_path=relative,size=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
    write(out/'SOURCE_MANIFEST.json',dict(files=records))
    return records


def validate_graph(graph,pipeline_id):
    """Require the explicit new registered route, not the legacy PB adapter."""
    pipelines=[p for p in graph['pipelines'] if p['adapter_id']==pipeline_id]
    if len(pipelines)!=1 or pipelines[0]['supported_robots']!=[RID]:
        raise ValueError('one_explicit_red_sentry_pipeline_required')
    pipeline=pipelines[0]
    nav=next(r for r in graph['rows']['navigation'] if r['adapter_id']==pipeline['navigation_plugin_id'])
    dec=next(r for r in graph['rows']['decision'] if r['adapter_id']==pipeline['decision_plugin_id'])
    if nav['transport']!='wsl_jsonl_v1' or nav['capabilities']['schema']!='polar.sim.navigation-plugin.capabilities.v3':
        raise ValueError('registered_wsl_navigation_feedback_v3_required')
    if dec['transport']!='jsonl_v1' or dec['capabilities']['schema']!='polar.sim.decision-plugin.capabilities.v2':
        raise ValueError('explicit_local_decision_feedback_v2_required')
    if graph['rows']['aim'] or len(graph['rows']['navigation'])!=1 or len(graph['rows']['decision'])!=1:
        raise ValueError('single_navigation_and_decision_scope_required')
    return pipeline,nav,dec


def audit_registered_route(rows,*,allow_incomplete_after=None):
    """Independent typed observe -> decision v2 -> staged act relationships.

    Each source has one original observe, never a latest/cache substitution.
    This validates routing of estimates, not their numeric authenticity; the
    separate native/TF/stage audit must prove the reviewed producer's evidence.
    """
    from rm_match.deployment.json_adapter import SCHEMA as JSONL_SCHEMA
    from rm_match.platform_v2.navigation_contracts import validate_navigation_observation
    from rm_match.platform_v2.navigation_feedback_contracts import validate_navigation_feedback,NavigationFeedbackHistory
    from rm_match.platform_v2.decision_contracts import build_decision_observation,validate_decision_intent
    from rm_match.platform_v2.goal_navigation_contracts import validate_goal_navigation_result,GoalNavigationResultHistory
    observations={};decisions={};results={};errors=[];late_aborts=[];histories={};goal_histories={}
    available=set();status_count=0;action_count=0;aborted_sources=set()
    for row in rows:
        event=row.get('event')
        if event=='peer_exchange_failed':
            if allow_incomplete_after is not None and row.get('completed_wall',-1)>=allow_incomplete_after:
                late_aborts.append(copy.deepcopy(row))
                try:
                    packet=row['packet']
                    aborted_sources.add(source_key(packet['source'] if 'source' in packet else packet['observation']))
                except (KeyError,TypeError,ValueError):errors.append('malformed_shutdown_aborted_source')
            else:errors.append('actual_peer_exchange_failed:'+str(row.get('error_type')))
            continue
        if event!='peer_exchange':continue
        try:
            packet=row['packet'];response=row['response'];op=packet['op'];peer=row['peer']
            if op not in ('observe','act'):continue
            if (type(response) is not dict or type(response.get('schema')) is not str or response['schema']!=JSONL_SCHEMA
                or type(response.get('op')) is not str or response['op']!=op or response.get('ok') is not True):
                raise ValueError('outer_response_identity')
            index=row['record_index']
            if type(index) is not int or index<0:raise ValueError('record_order_type')
            if peer=='navigation' and op=='observe':
                if set(packet)!={'op','observation'} or set(response)!={'schema','op','ok','feedback'}:
                    raise ValueError('observe_envelope_fields')
                original=validate_navigation_observation(packet['observation']);key=source_key(original)
                if key in observations:raise ValueError('ambiguous_duplicate_observe_source')
                feedback=validate_navigation_feedback(response['feedback'],original)
                generation=key[:3]
                histories.setdefault(generation,NavigationFeedbackHistory()).check(feedback)
                observations[key]=(original,feedback,index,row['started_wall'],row['completed_wall'])
                if feedback['navigation']['available']:available.add(key)
            elif peer=='decision' and op=='act':
                if set(packet)!={'op','observation'} or set(response)!={'schema','op','ok','intent'}:
                    raise ValueError('decision_envelope_fields')
                decision=packet['observation'];key=source_key(decision)
                if key in decisions:raise ValueError('ambiguous_duplicate_decision_source')
                original,feedback,observe_index,_,_=observations[key]
                expected=build_decision_observation(original,feedback,profile='own_referee_navigation_v2')
                if typed(expected)!=typed(decision) or observe_index>=index:
                    raise ValueError('original_feedback_decision_join')
                intent=validate_decision_intent(response['intent'],decision)
                decisions[key]=(intent,index)
            elif peer=='navigation' and op=='act':
                if set(packet)!={'op','source','intent'} or set(response)!={'schema','op','ok','result'}:
                    raise ValueError('staged_act_envelope_fields')
                key=source_key(packet['source'])
                if set(packet['source'])!=set(IDENTITY):raise ValueError('staged_act_source_fields')
                if key in results:raise ValueError('ambiguous_duplicate_act_source')
                original,_,observe_index,_,_=observations[key]
                intent,decision_index=decisions[key]
                if typed(intent)!=typed(packet['intent']) or not observe_index<decision_index<index:
                    raise ValueError('original_intent_staged_act_join')
                envelope=validate_goal_navigation_result(response['result'],original,intent)
                goal_histories.setdefault(key[:3],GoalNavigationResultHistory()).check(envelope)
                results[key]=envelope
                if 'action' in envelope:action_count+=1
                else:status_count+=1
            else:raise ValueError('unexpected_peer_operation')
            if peer=='navigation' and op=='act':deadline=observations[key][0]['wall_deadline']
            elif peer=='navigation':deadline=original['wall_deadline']
            else:deadline=decision['wall_deadline']
            start=row['started_wall'];end=row['completed_wall']
            if (type(start) not in (float,int) or type(end) not in (float,int)
                or not math.isfinite(start) or not math.isfinite(end) or not 0<=start<=end<deadline):
                raise ValueError('original_host_transaction_deadline')
        except (KeyError,TypeError,ValueError) as exc:
            errors.append('route:'+str(exc))
    for key,(original,_,_,start,_) in observations.items():
        if key not in decisions or key not in results:
            if key not in aborted_sources and (allow_incomplete_after is None or start<allow_incomplete_after):
                errors.append('incomplete_original_observe_decision_act')
    return dict(passed=bool(observations and decisions and results and available and action_count) and not errors,
        errors=errors,observations=len(observations),decision_intents=len(decisions),navigation_results=len(results),
        available_estimates=len(available),actions=action_count,statuses=status_count,
        shutdown_aborted_transactions=len(late_aborts))


def audit_stages(rows,stages,ros_rows):
    """Verify each actual action used the original Linux-local 50 ms stage."""
    from rm_match.platform_v2.navigation_contracts import validate_navigation_observation
    events={};errors=[];envelopes={};observations={};feedbacks={};native={};estimates={};localizations={}
    for row in rows:
        try:
            if row.get('event')!='peer_exchange' or row.get('peer')!='navigation':continue
            packet=row['packet']
            if packet['op']=='observe':
                original=validate_navigation_observation(packet['observation'])
                key=source_key(original)
                if key in observations:raise ValueError('stage_duplicate_original_observation')
                observations[key]=original
                feedbacks[key]=row['response']['feedback']
            elif packet['op']=='act':
                key=source_key(packet['source'])
                if key in envelopes:raise ValueError('stage_duplicate_original_act')
                envelopes[key]=row['response']['result']
        except (KeyError,TypeError,ValueError) as exc:errors.append('stage_route:'+str(exc))
    for row in ros_rows:
        try:
            kind=row.get('topic_kind');value=row.get('value')
            if kind=='controller_result':native.setdefault(source_key(value['action']),[]).append(row)
            elif kind=='estimated_transform':estimates.setdefault(source_key(value['source']),[]).append(row)
            elif kind=='localization':localizations.setdefault(source_key(value),[]).append(row)
        except (KeyError,TypeError,ValueError) as exc:errors.append('stage_native:'+str(exc))
    for row in stages:
        try:
            base={'event','source','scan','local_wall','local_deadline','clock'}
            extras={'stage_begin':{'begin_wall','response_timeout_s','published_count'},
                'stage_published':{'published_count'},'stage_feedback':{'available','reason'},
                'stage_act_enter':set(),'stage_act_exit':{'value_kind','goal_uuid','status'},
                'stage_action_withheld':{'value_kind','goal_uuid','reason'},
                'stage_discard':{'reason'}}
            if type(row) is not dict or row.get('event') not in extras or set(row)!=base|extras[row['event']]:
                raise ValueError('stage_exact_event_fields')
            key=source_key(row['source'])
            if row['event']=='stage_action_withheld' and key not in observations:
                raise ValueError('withheld_without_original_observation_source')
            if row['clock']!='linux_local_perf_counter':raise ValueError('stage_clock_domain')
            if type(row['local_wall']) not in (int,float) or not math.isfinite(row['local_wall']):
                raise ValueError('stage_local_clock')
            events.setdefault(key,[]).append(row)
        except (KeyError,TypeError,ValueError) as exc:errors.append('stage_record:'+str(exc))
    actions=0;withheld_native_actions=0;deadline_withheld_actions=0;unreturned_deadline_withholds=0
    for key,original in observations.items():
        try:
            recorded=events[key];begins=[e for e in recorded if e['event']=='stage_begin']
            if len(begins)!=1:raise ValueError('one_original_stage_begin_required')
            begin=begins[0];start=begin['begin_wall'];deadline=begin['local_deadline'];timeout=begin['response_timeout_s']
            if (type(start) not in (int,float) or type(deadline) not in (int,float)
                or type(timeout) not in (int,float) or not all(math.isfinite(v) for v in (start,deadline,timeout))
                or not 0<timeout<=.05 or abs(deadline-start-timeout)>1e-9
                or type(begin['published_count']) is not int or begin['published_count']!=0):
                raise ValueError('original_50ms_stage_budget')
            cloud=original['sensors']['pointcloud']
            expected_scan=dict(cloud_frame_id=cloud['frame_id'],acquisition_start_ns=cloud['acquisition_start_ns'],
                acquisition_end_ns=cloud['acquisition_end_ns'],profile_sha256=cloud['profile_sha256'])
            prior=start
            for event in recorded:
                if (typed(event['source'])!=typed({name:original[name] for name in IDENTITY})
                    or typed(event['scan'])!=typed(expected_scan)
                    or typed(event['local_deadline'])!=typed(deadline) or event['local_wall']<prior):
                    raise ValueError('stage_source_scan_deadline_or_order_changed')
                prior=event['local_wall']
            publications=[e for e in recorded if e['event']=='stage_published']
            if len(publications)!=1 or type(publications[0]['published_count']) is not int or publications[0]['published_count']!=1:
                raise ValueError('one_original_scan_publication_required')
            feedback_events=[e for e in recorded if e['event']=='stage_feedback']
            if len(feedback_events)!=1:raise ValueError('one_original_feedback_event_required')
            nav=feedbacks[key]['navigation'];feedback_event=feedback_events[0]
            if (typed(feedback_event['available'])!=typed(nav['available'])
                or typed(feedback_event['reason'])!=typed(nav['reason'])
                or (nav['available'] and not start<=feedback_event['local_wall']<deadline)):
                raise ValueError('original_feedback_stage_availability')
            if nav['available']:
                for kind,candidates in (('TF',estimates.get(key,[])),('LIO',localizations.get(key,[]))):
                    def within(candidate):
                        stamp=candidate['value'].get('requested_stamp_ns' if kind=='TF' else 'localization_stamp_ns')
                        return (type(stamp) is int and stamp==nav['stamp_ns']
                            and candidate.get('receive_clock')=='linux_local_perf_counter'
                            and type(candidate.get('receive_wall')) in (int,float)
                            and start<=candidate['receive_wall']<=feedback_event['local_wall'])
                    if not any(within(candidate) for candidate in candidates):
                        raise ValueError('available_feedback_without_stage_local_'+kind)
            result=envelopes.get(key)
            withheld=[e for e in recorded if e['event']=='stage_action_withheld']
            if len(withheld)>1:raise ValueError('one_stage_action_withheld_event_required')
            if withheld:
                enter=[e for e in recorded if e['event']=='stage_act_enter'];exits=[e for e in recorded if e['event']=='stage_act_exit']
                if len(enter)!=1 or len(exits)!=1:raise ValueError('withheld_original_staged_action_required')
                exit=exits[0];marker=withheld[0]
                if (marker['value_kind']!='action' or marker['reason']!='stage_exit_budget_expired'
                    or type(marker['goal_uuid']) is not str or re.fullmatch('[0-9a-f]{32}',marker['goal_uuid']) is None
                    or exit['value_kind']!='action' or exit['goal_uuid']!=marker['goal_uuid'] or exit['status'] is not None
                    or not start<=enter[0]['local_wall']<=exit['local_wall']<deadline<=marker['local_wall']
                    or recorded.index(marker)<=recorded.index(exit)):
                    raise ValueError('withheld_original_action_uuid_deadline_or_order_changed')
                from rm_match.platform_v2.contracts import validate_action
                native_match=False
                for candidate in native.get(key,[]):
                    if candidate['value']['source']['goal_uuid']!=marker['goal_uuid']:continue
                    validate_action(candidate['value']['action'],original,dict(kind='navigation',output_modes=['velocity_body']))
                    received=candidate.get('receive_wall')
                    if (candidate.get('receive_clock')=='linux_local_perf_counter'
                        and type(received) in (int,float) and math.isfinite(received) and start<=received<deadline):
                        native_match=True
                if not native_match:raise ValueError('withheld_without_original_native_action_in_stage')
                if result is not None:
                    from rm_match.platform_v2.navigation_contracts import validate_navigation_status
                    if ('action' in result or result.get('controller_goal_uuid') is not None
                        or result.get('status',{}).get('status')!='no_associated_command'):
                        raise ValueError('withheld_original_action_requires_final_public_status')
                    validate_navigation_status(result['status'],original)
                    deadline_withheld_actions+=1
                else:
                    # No public result means no delivered action/status claim.
                    # The composed audit must separately join ACT_RESULTS to
                    # an actual shutdown-aborted transaction for this source.
                    unreturned_deadline_withholds+=1
            if result is None:continue
            enter=[e for e in recorded if e['event']=='stage_act_enter'];exits=[e for e in recorded if e['event']=='stage_act_exit']
            if len(enter)!=1 or len(exits)!=1:raise ValueError('one_original_staged_act_required')
            exit=exits[0]
            if 'action' not in result:
                # STAGES records the actual sourced callback before the goal
                # helper checks current authority. A valid native action can
                # be withheld after cancellation/terminal/mismatched UUID; it
                # must remain a status in the delivered result, never zero.
                if exit['value_kind']=='action':
                    if type(exit['goal_uuid']) is not str or exit['status'] is not None:
                        raise ValueError('stage_withheld_native_action_shape')
                    withheld_native_actions+=1
                elif exit['value_kind']!='status' or exit['goal_uuid'] is not None or type(exit['status']) is not str:
                    raise ValueError('stage_status_dto_mismatch')
                continue
            actions+=1
            if (exit['value_kind']!='action' or exit['goal_uuid']!=result['controller_goal_uuid'] or exit['status'] is not None
                or not start<=enter[0]['local_wall']<=exit['local_wall']<deadline):
                raise ValueError('stage_action_expired_or_uuid_changed')
            matches=[r for r in native.get(key,[]) if typed(r['value']['action'])==typed(result['action'])
                and r['value']['source']['goal_uuid']==result['controller_goal_uuid']]
            if not matches:raise ValueError('stage_action_without_native_result')
            if not any(r.get('receive_clock')=='linux_local_perf_counter'
                and type(r.get('receive_wall')) in (int,float) and start<=r['receive_wall']<deadline for r in matches):
                raise ValueError('native_result_after_original_stage_deadline')
        except (KeyError,TypeError,ValueError) as exc:errors.append('stage:'+str(exc))
    return dict(passed=bool(observations and actions) and not errors,errors=errors,
        original_stages=len(observations),qualified_action_stages=actions,
        withheld_native_actions=withheld_native_actions,deadline_withheld_actions=deadline_withheld_actions,
        unreturned_deadline_withholds=unreturned_deadline_withholds)


def audit_native_estimates(rows,ros_rows,expected_provenance):
    """Join every delivered estimate to raw exact-stamp TF and LIO records."""
    from rm_match.platform_v2.navigation_feedback_contracts import validate_navigation_feedback
    localizations={};transforms={};errors=[];available=0;matched=0
    for row in ros_rows:
        try:
            if row.get('topic_kind')=='localization':
                if row.get('receive_clock')!='linux_local_perf_counter':raise ValueError('estimate_LIO_clock')
                localizations.setdefault(source_key(row['value']),[]).append(row['value'])
            elif row.get('topic_kind')=='estimated_transform':
                if row.get('receive_clock')!='linux_local_perf_counter':raise ValueError('estimate_TF_clock')
                transforms.setdefault(source_key(row['value']['source']),[]).append(row['value'])
        except (KeyError,TypeError,ValueError) as exc:errors.append('estimate_native:'+str(exc))
    for row in rows:
        if (row.get('event')!='peer_exchange' or row.get('peer')!='navigation'
            or row.get('packet',{}).get('op')!='observe'):continue
        try:
            original=row['packet']['observation']
            feedback=validate_navigation_feedback(row['response']['feedback'],original)
            nav=feedback['navigation']
            if not nav['available']:continue
            available+=1;key=source_key(original);scan=feedback['scan'];stamp=nav['stamp_ns']
            for name,expected in expected_provenance.items():
                if typed(nav['provenance'][name])!=typed(expected):raise ValueError('pinned_estimate_provenance_changed:'+name)
            locs=[loc for loc in localizations.get(key,[]) if type(loc['localization_stamp_ns']) is int and loc['localization_stamp_ns']==stamp
                and all(type(loc[k]) is type(scan[k]) and loc[k]==scan[k]
                    for k in ('cloud_frame_id','acquisition_start_ns','acquisition_end_ns'))]
            if not locs:raise ValueError('estimate_without_original_lio_context')
            candidates=[recorded for recorded in transforms.get(key,[])
                if typed(recorded['source'])==typed(feedback['source']) and typed(recorded['scan'])==typed(scan)]
            if len(candidates)!=1:raise ValueError('estimate_TF_lookup_missing_or_ambiguous')
            found=False
            for recorded in candidates:
                transform=recorded['transform'];header=transform['header'];tf=transform['transform']
                sec=header['stamp']['sec'];ns=header['stamp']['nanosec']
                if type(sec) is not int or type(ns) is not int or not 0<=ns<1000000000:continue
                position=[tf['translation'][k] for k in 'xyz'];rotation=[tf['rotation'][k] for k in 'xyzw']
                if (type(recorded['requested_stamp_ns']) is int and recorded['requested_stamp_ns']==stamp==sec*1000000000+ns
                    and header['frame_id']=='map' and transform['child_frame_id']=='base_link'
                    and typed(position)==typed(nav['position_m']) and typed(rotation)==typed(nav['rotation_xyzw'])):
                    found=True
            if not found:raise ValueError('estimate_without_exact_actual_TF_lookup')
            matched+=1
        except (KeyError,TypeError,ValueError) as exc:errors.append('estimate:'+str(exc))
    return dict(passed=available>0 and available==matched and not errors,errors=errors,
        delivered_available_estimates=available,exact_lio_TF_joins=matched)


def audit_emit_gates(rows,gates,stages):
    """Join final encoded public act replies to their original Linux deadline.

    The peer records only action candidates that pass its final before-write
    hook. A record without the corresponding actual host response is not a
    delivered action. This does not infer pipe-write completion from gate time.
    """
    from rm_match.integrations.ros2_bridge import encode_json,MAX_RESPONSE
    from rm_match.platform_v2.goal_navigation_contracts import validate_goal_navigation_result
    from rm_match.platform_v2.navigation_contracts import validate_navigation_observation
    originals={};public={};begins={};recorded={};errors=[];qualified=0;unmatched=0
    for row in rows:
        try:
            if row.get('event')!='peer_exchange' or row.get('peer')!='navigation':continue
            packet=row['packet']
            if packet['op']=='observe':
                original=validate_navigation_observation(packet['observation']);key=source_key(original)
                if key in originals:raise ValueError('emit_duplicate_original_observe')
                originals[key]=original
            elif packet['op']=='act':
                key=source_key(packet['source'])
                if key in public:raise ValueError('emit_duplicate_public_act_source')
                public[key]=row
        except (KeyError,TypeError,ValueError) as exc:errors.append('emit_route:'+str(exc))
    for stage in stages:
        try:
            if stage.get('event')=='stage_begin':begins.setdefault(source_key(stage['source']),[]).append(stage)
        except (KeyError,TypeError,ValueError) as exc:errors.append('emit_stage:'+str(exc))
    for gate in gates:
        try:
            expected={'source','scan','local_deadline','gate_wall','clock','result','encoded_sha256'}
            if type(gate) is not dict or set(gate)!=expected:raise ValueError('emit_gate_exact_fields')
            if type(gate['source']) is not dict or set(gate['source'])!=set(IDENTITY):
                raise ValueError('emit_gate_exact_source')
            key=source_key(gate['source'])
            recorded.setdefault(key,[]).append(gate)
        except (KeyError,TypeError,ValueError) as exc:errors.append('emit_record:'+str(exc))
    action_keys={key for key,row in public.items() if 'action' in row['response'].get('result',{})}
    for key in recorded:
        if key not in action_keys:
            unmatched+=len(recorded[key]);errors.append('emit_gate_without_actual_public_action')
    for key in action_keys:
        try:
            if len(recorded.get(key,[]))!=1:raise ValueError('one_final_emit_gate_per_public_action_required')
            if len(begins.get(key,[]))!=1:raise ValueError('one_original_emit_stage_begin_required')
            gate=recorded[key][0];begin=begins[key][0];original=originals[key];row=public[key]
            response=row['response'];result=validate_goal_navigation_result(response['result'],original,row['packet']['intent'])
            scan=original['sensors']['pointcloud']
            expected_scan=dict(cloud_frame_id=scan['frame_id'],acquisition_start_ns=scan['acquisition_start_ns'],
                acquisition_end_ns=scan['acquisition_end_ns'],profile_sha256=scan['profile_sha256'])
            if (typed(gate['source'])!=typed({name:original[name] for name in IDENTITY})
                or typed(gate['scan'])!=typed(expected_scan)
                or typed(gate['local_deadline'])!=typed(begin['local_deadline'])
                or typed(gate['result'])!=typed(result)):
                raise ValueError('final_emit_source_scan_deadline_or_result_changed')
            stamp=gate['gate_wall'];deadline=gate['local_deadline'];start=begin['begin_wall']
            if (type(gate['clock']) is not str or gate['clock']!='linux_local_perf_counter'
                or type(stamp) not in (int,float) or not math.isfinite(stamp)
                or not start<=stamp<deadline or not 0<begin['response_timeout_s']<=.05
                or abs(deadline-start-begin['response_timeout_s'])>1e-9):
                raise ValueError('final_emit_original_50ms_gate_expired_or_clock_changed')
            encoded=encode_json(response,MAX_RESPONSE-1)+b'\n'
            if (type(gate['encoded_sha256']) is not str or not re.fullmatch('[0-9a-f]{64}',gate['encoded_sha256'])
                or hashlib.sha256(encoded).hexdigest()!=gate['encoded_sha256']):
                raise ValueError('final_emit_actual_response_encoded_bytes_hash_changed')
            qualified+=1
        except (KeyError,TypeError,ValueError) as exc:errors.append('emit:'+str(exc))
    return dict(passed=bool(action_keys) and qualified==len(action_keys) and not errors,errors=errors,
        public_actions=len(action_keys),qualified_final_emit_gates=qualified,unmatched_gate_records=unmatched,
        scope='source-bound final before-write encoded action gate; not a pipe-write-completion timestamp')


def audit_estimated_goal_origins(rows,lifecycle):
    """Prove this synthetic policy requested original estimate map-x + 1 m."""
    observed={};decisions={};errors=[];checked=0
    for row in rows:
        if row.get('event')!='peer_exchange':continue
        try:
            packet=row['packet']
            if row['peer']=='navigation' and packet['op']=='observe':
                observed.setdefault(source_key(packet['observation']),[]).append(row['response']['feedback'])
            elif row['peer']=='decision' and packet['op']=='act':
                decisions.setdefault(source_key(packet['observation']),[]).append(row['response']['intent'])
        except (KeyError,TypeError,ValueError) as exc:errors.append('goal_origin_record:'+str(exc))
    for record in lifecycle.get('goals',[]):
        try:
            origin=record['origin_intent'];key=source_key(origin)
            if len(observed.get(key,[]))!=1 or len(decisions.get(key,[]))!=1:
                raise ValueError('goal_origin_feedback_or_intent_missing_or_ambiguous')
            if typed(decisions[key][0])!=typed(origin):raise ValueError('goal_origin_not_original_decision_intent')
            feedback=observed[key][0];nav=feedback['navigation'];status=feedback['goal_status']
            if not nav['available'] or not status['available'] or status['fault'] is not None or status['stop_requested']:
                raise ValueError('goal_origin_without_actual_available_estimate_and_lifecycle')
            x,y,_=nav['position_m'];qx,qy,qz,qw=nav['rotation_xyzw']
            expected=dict(frame='map',position_m=[x+1.0,y],
                yaw_rad=math.atan2(2*(qw*qz+qx*qy),1-2*(qy*qy+qz*qz)))
            if origin['command']['behavior']!='navigate_to_pose' or typed(origin['command']['goal'])!=typed(expected):
                raise ValueError('goal_origin_not_original_estimated_map_x_plus_1m')
            checked+=1
        except (KeyError,TypeError,ValueError) as exc:errors.append('goal_origin:'+str(exc))
    return dict(passed=checked>0 and not errors,errors=errors,exact_estimated_goal_origins=checked,
        scope='explicit_synthetic_map_x_plus_1m_policy_only_not_general_navigation_goal_constraint')


def run(out,args,graph):
    from rm_match.deployment.json_adapter import SharedCleanupBudget
    from rm_match.deployment.profile import digest as manifest_digest
    from rm_match.deployment.robotio_plugin import register_robotio_plugins,prepare_robotio_resources
    from rm_match.deployment.robotio_wsl import WslNavigationPluginAdapter
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
        original=WslNavigationPluginAdapter._exchange
        def prepare_exchange(peer,packet,**kwargs):
            return exchanged(lambda p,**kw:original(peer,p,**kw),'navigation',packet,**kwargs)
        WslNavigationPluginAdapter._exchange=prepare_exchange
        try:pools=prepare_robotio_resources(args.manifest,repo_root=ROOT,shared_root=out/'resources')
        except BaseException as exc:
            orphan=getattr(exc,'resources',None)
            if type(orphan) is dict:pools=orphan
            elif orphan is not None and hasattr(orphan,'close_unclaimed'):pools={'failed_preparation':orphan}
            raise
        finally:WslNavigationPluginAdapter._exchange=original
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
        # The local decision factory also finishes before the first physics
        # step. Navigation has already made its real WSL resource prepare ACK.
        instance.decision.prepare()
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
            if row['event'] in ('adapter_enqueue','adapter_result'):retain(row);return
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
                    window=client.control_window(RID,['motion'])
                    activation=client.adapter_input(RID,'navigation',1,window_id=window['window_id'],valid_for_s=.15)
                    ack=time.perf_counter()
                    retain(dict(event='sdk_adapter_activation',wall_time=ack,
                        window={k:window[k] for k in ('window_id','issued_wall','expires_wall','valid_for_s','lease_epochs')},
                        activation={k:activation[k] for k in ('binding_epoch','seq','window_id','activation_expires')}))
                    next_tick+=.05
                    if next_tick<=ack:next_tick+=(math.floor((ack-next_tick)/.05)+1)*.05
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
        qualification='registered_real_PB_navigation_synthetic_decision_not_match_or_RTF')


def read_record(path,default):
    if not path.is_file():return copy.deepcopy(default)
    from rm_match.deployment.wsl_jsonl_worker import strict_json
    raw=path.read_bytes()
    if len(raw)>8*1024*1024:raise ValueError('bounded_peer_record_exceeded')
    return strict_json(raw)


def read_lines(path):
    if not path.is_file():return []
    from rm_match.deployment.wsl_jsonl_worker import strict_json
    rows=[]
    with path.open('rb') as stream:
        while True:
            raw=stream.readline(2*1024*1024+1)
            if not raw:break
            if len(raw)>2*1024*1024 or not raw.endswith(b'\n'):raise ValueError('bounded_peer_line_exceeded_or_partial')
            if len(rows)>=100000:raise ValueError('bounded_peer_rows_exceeded')
            rows.append(strict_json(raw))
    return rows


def evaluate(out,args,execution):
    from tools.audit_navigation_goals import audit_goal_navigation_consumption
    from rm_match.deployment.robotio_plugin import load_robotio_plugins
    peer=args.peer_evidence_dir
    ros=read_lines(peer/'ROS_SOURCE.jsonl');stages=read_lines(peer/'STAGES.jsonl');gates=read_lines(peer/'EMIT_GATES.jsonl')
    goal=read_record(peer/'GOAL_REPORT.json',{});peer_cleanup=read_record(peer/'CLEANUP.json',{})
    lifecycle=goal.get('lifecycle',{})
    rows=execution.pop('rows');cleanup=execution['cleanup']
    route=audit_registered_route(rows,allow_incomplete_after=cleanup['shared_host_started_wall'])
    stage=audit_stages(rows,stages,ros)
    emit=audit_emit_gates(rows,gates,stages)
    native=audit_goal_navigation_consumption(rows,ros,lifecycle)
    # These are the first source-pinned manifest/spec/config bytes selected for
    # the actual registered peer; the main source guard checks them again.
    graph=load_robotio_plugins(args.manifest);_,nav,_=validate_graph(graph,args.pipeline_id)
    spec=read_record(peer_spec_reference(nav)[0],{})
    config=read_record(host_input_path(spec['config_ref']['path']),{})
    provenance=dict(producer_source_sha256=spec['source_sha256']['rm_match/integrations/pb_goal_plugin_source.py'],
        localization_binary_sha256=config['assets']['point_lio']['sha256'],
        mapping_binary_sha256=config['assets']['slam_toolbox']['sha256'])
    estimates=audit_native_estimates(rows,ros,provenance)
    origins=audit_estimated_goal_origins(rows,lifecycle)
    for name,value in (('ROUTE_AUDIT',route),('STAGE_AUDIT',stage),('GOAL_MOTION_AUDIT',native),
                       ('ESTIMATE_AUDIT',estimates),('ESTIMATED_GOAL_ORIGIN_AUDIT',origins),('EMIT_GATE_AUDIT',emit)):
        write(out/(name+'.json'),value)
    write(out/'PB_RESULT.json',dict(goal=goal,cleanup=peer_cleanup,expected_estimate_provenance=provenance))
    records=[]
    if peer.is_dir():
        for path in sorted(peer.rglob('*')):
            if path.is_file():records.append(dict(path=path.relative_to(peer).as_posix(),size=path.stat().st_size,sha256=digest(path)))
    write(out/'PEER_EVIDENCE_INDEX.json',dict(root=str(peer),files=records))
    completed={record['operation_id']:record for record in lifecycle.get('goals',[])
        if record.get('state')=='succeeded' and record.get('terminal') is True
        and record.get('stop_confirmed') is True and record.get('goal_uuids',{}).get('navigation')}
    hold_after_terminal=False
    for row in rows:
        if (row.get('event')!='peer_exchange' or row.get('peer')!='decision'
            or row.get('packet',{}).get('op')!='act'):continue
        intent=row['response']['intent']
        if intent['command']['behavior']!='hold':continue
        status=row['packet']['observation']['navigation']['goal_status']
        if not status['available']:continue
        for receipt in status['history']:
            final=completed.get(receipt['operation_id'])
            if (final is not None and receipt['state']=='succeeded' and receipt['terminal'] is True
                and receipt['stop_confirmed'] is True
                and typed(receipt['origin_intent'])==typed(final['origin_intent'])
                and typed(receipt['goal_uuids'])==typed(final['goal_uuids'])):
                hold_after_terminal=True
    cleanup_ok=bool(cleanup['runtime'] and cleanup['runtime'].get('clean') is True
        and cleanup['pipeline'] and cleanup['pipeline'].get('clean') is True
        and cleanup['sdk_stopped'] and cleanup['http_stopped'] and cleanup['http_workers_idle']
        and cleanup['finished_within_shared_host_budget'])
    prepare_acks=[r for r in rows if r.get('event')=='peer_exchange' and r['packet']['op']=='prepare']
    peer_clean=bool(peer_cleanup.get('clean') is True and peer_cleanup.get('goal_stop_confirmed') is True
        and peer_cleanup.get('source_unchanged') is True and peer_cleanup.get('gate_clean') is True
        and peer_cleanup.get('transport_clean') is True and peer_cleanup.get('stack',{}).get('clean') is True
        and type(peer_cleanup.get('elapsed_s')) in (int,float) and 0<=peer_cleanup['elapsed_s']<=1.3)
    checks=dict(original_2ms_timestep=execution['timestep']==.002,actual_physics_steps=execution['steps']>0,
        real_navigation_and_decision_resource_prepare_acks=len(prepare_acks)==2,
        actual_prepared_pipeline_sdk_handover=execution['pipeline_handed_over'],
        original_observe_decision_v2_staged_act_route=route['passed'],
        exact_native_LIO_TF_estimate_inputs=estimates['passed'],
        goal_origin_is_original_estimated_map_x_plus_1m=origins['passed'],
        original_linux_50ms_stage_without_republication=stage['passed'],
        final_encoded_public_action_within_original_linux_50ms=emit['passed'],
        accepted_native_uuid_sdk_sensor_physical_join=native['passed'],
        actual_goal_succeeded_stop_and_feedback_driven_final_hold=bool(completed) and hold_after_terminal,
        original_150ms_controlled_sdk_span=execution['sdk_elapsed_s'] is not None
            and args.seconds<=execution['sdk_elapsed_s']<=args.max_wall_seconds,
        actual_lifecycle_clean=lifecycle.get('clean') is True and lifecycle.get('fault') is None,
        actual_peer_cleanup_clean=peer_clean,
        all_host_resources_within_shared_1_5s=cleanup_ok,
        no_actual_adapter_fault=not any(r.get('event')=='adapter_result' and r.get('error') for r in rows),
        errors_empty=not execution['errors'])
    return dict(passed=all(checks.values()),checks=checks,errors=execution['errors'],steps=execution['steps'],
        controlled_sdk_span_s=execution['sdk_elapsed_s'],physical=native,route=route,stages=stage,estimates=estimates,
        estimated_goal_origins=origins,emit=emit,
        qualification=execution['qualification'],
        limitations=['actual PB navigation and explicit synthetic high-level policy only; not PB competition decision tree',
            'one registered goal only; cancellation, replacement and a second goal remain unqualified in this route',
            'no camera, aiming, neural model, firing, Qt, RTF, complete 3v3/7v7 or cross-machine DDS acceptance',
            'raw TF/LIO source joins and binary pins show this producer route, not ground-truth localization accuracy'])


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--pipeline-id',required=True)
    parser.add_argument('--peer-evidence-dir',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--seconds',type=float,default=15.)
    parser.add_argument('--max-wall-seconds',type=float,default=30.)
    parser.add_argument('--run',action='store_true')
    args=parser.parse_args(argv)
    if not args.run:raise RuntimeError('explicit_real_registered_PB_SIL_opt_in_required')
    if not math.isfinite(args.seconds) or not 15.<=args.seconds<=20.:raise ValueError('controlled_span_15_to_20_seconds')
    if not math.isfinite(args.max_wall_seconds) or not args.seconds<=args.max_wall_seconds<=40.:
        raise ValueError('bounded_runtime_15_to_40_seconds')
    args.manifest=args.manifest.absolute();args.out=args.out.absolute();args.peer_evidence_dir=args.peer_evidence_dir.absolute()
    if args.out.exists():raise RuntimeError('fresh_output_required')
    if (args.peer_evidence_dir.exists() or not args.peer_evidence_dir.is_relative_to(ROOT/'artifacts')
        or args.peer_evidence_dir==args.out):
        raise ValueError('peer_evidence_must_be_fresh_explicit_repo_artifact_directory')
    from rm_match.deployment.robotio_plugin import load_robotio_plugins
    graph=load_robotio_plugins(args.manifest);_,nav,_=validate_graph(graph,args.pipeline_id)
    inputs=peer_inputs(nav,args.peer_evidence_dir)
    args.out.mkdir(parents=True);records=[];started=time.perf_counter();result={};code=2
    try:
        records=copy_sources(args.out,graph,inputs)
        write(args.out/'COMMAND.json',dict(argv=sys.argv,manifest=str(args.manifest),pipeline_id=args.pipeline_id,
            peer_evidence_dir=str(args.peer_evidence_dir),seconds=args.seconds,max_wall_seconds=args.max_wall_seconds,
            unchanged_budgets=dict(sdk_s=.15,pb_navigation_s=.05,camera_s=.08),
            scope='registered real PB navigation plus explicit synthetic high-level estimated-feedback policy'))
        execution=run(args.out,args,graph)
        # Route/native-source audit is implemented independently below; no
        # protocol progress, goal UUID or world pose is invented on failure.
        result=evaluate(args.out,args,execution)
        code=0 if result['passed'] else 2
    except BaseException as exc:
        result=dict(passed=False,error_type=type(exc).__name__)
        (args.out/'failure.log').write_text(traceback.format_exc(),encoding='utf8')
    unchanged=all(Path(r['path']).is_file() and digest(r['path'])==r['sha256'] for r in records)
    result.update(source_unchanged=unchanged,elapsed_s=time.perf_counter()-started,exit_code=code)
    if not unchanged:result['passed']=False;result['exit_code']=code=2
    write(args.out/'RESULT.json',result)
    print(json.dumps(dict(passed=result['passed'],exit_code=code,out=str(args.out)),allow_nan=False))
    return code


if __name__=='__main__':raise SystemExit(main())
