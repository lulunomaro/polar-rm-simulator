"""Active-goal v2 MuJoCo/RobotIO/SDK protocol SIL, NOT navigation qualification.

Uses actual low-rate physics ray/IMU packets and four independent synthetic
decision/navigation subprocesses. No camera, model, ROS, WSL or GUI is started.
The backend UUID and velocity are synthetic, not Nav2 or team-algorithm evidence.
The moving pipeline joins each original intent, current selection, controller
UUID, original actuator DTO, SDK authorization and physical consumption. The
independent hold pipeline must return status, not a fabricated zero action.
Only isolated evaluation reads world positions, never a peer or SDK actor.
"""
from __future__ import annotations
import argparse
import copy
import gzip
import hashlib
import json
import math
from pathlib import Path
import secrets
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ROBOTS = {'red_infantry':'custom_active_goal_pipeline_supply', 'blue_sentry':'custom_active_goal_pipeline_heat'}
IDENTITY = ('robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline')
_EXPLICIT_SOURCES = ('tools/qa_active_goal_protocol_sil.py', 'examples/robotio_active_goal_plugins.json',
    'examples/robotio_active_goal_navigation.json','examples/robotio_protocol_decision.json',
    'tests/fixtures/decision_supply_v1.py','tests/fixtures/decision_heat_v2.py','tests/fixtures/active_goal_navigation_fixture.py',
    'rm_match/deployment/robotio_plugin.py','rm_match/deployment/navigation_plugin.py',
    'rm_match/deployment/decision_plugin.py','rm_match/deployment/json_adapter.py',
    'rm_match/deployment/json_owned_process.py','rm_match/deployment/windows_owned_job.py',
    'rm_match/integrations/navigation_jsonl_peer.py','rm_match/integrations/decision_jsonl_peer.py',
    'rm_match/integrations/goal_navigation_compute.py','rm_match/integrations/navigation_goal_lifecycle.py',
    'rm_match/platform_v2/goal_navigation_contracts.py',
    'rm_match/platform_v2/decision_contracts.py','rm_match/platform_v2/navigation_contracts.py',
    'rm_match/platform_v2/contracts.py','rm_match/platform_v2/adapters.py',
    'rm_match/platform_v2/control.py','rm_match/platform_v2/runtime.py','rm_match/platform_v2/backend.py',
    'rm_match/platform_v2/server.py','rm_match/platform_v2/client.py','rm_match/platform_v2/admission.py',
    'rm_match/navigation_sensors.py','rm_match/match_engine.py','rm_match/match_model.py')
# Capture the production dependency tree, including lazy-imported registration,
# peer ownership, judge/model and transport modules. The source XML is read by
# make_match_xml; do not archive only the directly imported Python files.
SOURCE_FILES = tuple(dict.fromkeys((*_EXPLICIT_SOURCES,
    *(p.relative_to(ROOT).as_posix() for p in sorted((ROOT/'rm_match').rglob('*.py'))),
    'rm_match/harness.xml')))


def write(path, value):
    path.write_text(json.dumps(value, allow_nan=False, indent=2)+'\n', encoding='utf8')


def source_key(value):
    return tuple((type(value[k]).__name__, value[k]) for k in IDENTITY)


def same_tree(left, right):
    if type(left) is not type(right): return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(same_tree(left[k], right[k]) for k in left)
    if type(left) is list:
        return len(left) == len(right) and all(same_tree(a,b) for a,b in zip(left,right))
    return left == right


def audit(rows):
    """Join current goal selection to original DTO/SDK/physical receipts.

    UUID provenance is synthetic in this harness. The strict result validator
    proves the declared relationships, not any native controller's algorithm.
    Status replies are counted separately and cannot be physical action input.
    """
    from rm_match.platform_v2.navigation_contracts import validate_navigation_observation
    from rm_match.platform_v2.decision_contracts import build_decision_observation,validate_decision_intent
    from rm_match.platform_v2.goal_navigation_contracts import (
        GoalNavigationResultHistory, validate_goal_navigation_result)
    from rm_match.deployment.json_adapter import SCHEMA as JSONL_SCHEMA
    nav_requests = {}; decisions = {}; nav_actions = {}; activations = {}; enqueues = {}; errors = []
    histories = {}; envelopes = {}; status_keys = set()
    protocol = {rid:dict(actions=0,statuses=0,operations=set(),controller_uuids=set(),
        behaviors=set(),pointcloud_frames=set()) for rid in ROBOTS}
    receipts = {rid:[] for rid in ROBOTS}; nonzero = {rid:set() for rid in ROBOTS}
    for row in rows:
        try:
            if row['event'] == 'peer_exchange' and row['packet']['op'] == 'act':
                packet = row['packet']; response = row['response']; value = packet['observation']
                key = source_key(value)
                if (type(response) is not dict or type(response.get('schema')) is not str
                    or response['schema'] != JSONL_SCHEMA or type(response.get('op')) is not str
                    or response['op'] != 'act' or response.get('ok') is not True):
                    raise ValueError('peer_response_identity')
                if row['peer'] not in ('decision','navigation'):
                    raise ValueError('unexpected_protocol_peer')
                if row['peer'] == 'decision':
                    if set(response) != {'schema','op','ok','intent'}:
                        raise ValueError('decision_response_fields')
                    intent = validate_decision_intent(response['intent'], value)
                    if key in decisions: raise ValueError('duplicate_decision_source')
                    decisions[key] = (value, intent)
                else:
                    o = validate_navigation_observation(value)
                    decision_o = build_decision_observation(o)
                    intent = validate_decision_intent(packet['intent'], decision_o)
                    if key in nav_requests: raise ValueError('duplicate_navigation_source')
                    if set(response) != {'schema','op','ok','result'} or response['ok'] is not True:
                        raise ValueError('goal_result_response_envelope')
                    envelope = validate_goal_navigation_result(response['result'],o,intent)
                    history_key = (o['robot_id'],o['episode'],o['binding_epoch'])
                    histories.setdefault(history_key,GoalNavigationResultHistory()).check(envelope)
                    rid = row['robot_id']
                    if rid != o['robot_id'] or rid not in ROBOTS: raise ValueError('peer_robot_mismatch')
                    nav_requests[key] = (o,intent); envelopes[key] = envelope
                    detail = protocol[rid]
                    detail['behaviors'].add(intent['command']['behavior'])
                    detail['pointcloud_frames'].add(o['sensors']['pointcloud']['frame_id'])
                    if envelope['selection'] is not None:
                        detail['operations'].add(envelope['selection']['operation_id'])
                    if 'action' in envelope:
                        nav_actions[key] = envelope['action']; detail['actions'] += 1
                        detail['controller_uuids'].add(envelope['controller_goal_uuid'])
                    else:
                        if envelope['status']['status'] != 'no_associated_command':
                            raise ValueError('unexpected_synthetic_status')
                        status_keys.add(key); detail['statuses'] += 1
            if row['event'] == 'adapter_enqueue' and row['kind'] == 'navigation':
                original = dict(robot_id=row['robot_id'],episode=row['episode'],
                    binding_epoch=row['binding_epoch'],observed_seq=row['observed_seq'],
                    sim_time=row['observation_sim_time'],wall_deadline=row['wall_deadline'])
                key = source_key(original)
                if key in enqueues: raise ValueError('duplicate_original_scan_enqueue')
                enqueues[key] = row
            if row['event'] == 'sdk_activation':
                w = row['window']; a = row['activation']
                if not 0 < w['valid_for_s'] <= .15 or abs(w['expires_wall']-w['issued_wall']-w['valid_for_s']) > 1e-6:
                    raise ValueError('original_sdk_window')
                if a['window_id'] != w['window_id'] or a['activation_expires'] != w['expires_wall']:
                    raise ValueError('sdk_window_ack_mismatch')
                activations[(row['robot_id'],a['binding_epoch'],a['seq'],a['window_id'])] = w
        except Exception as exc: errors.append(row['event']+':'+type(exc).__name__+':'+str(exc))
    for key,(o,intent) in nav_requests.items():
        if key not in decisions or not same_tree(list(decisions[key]),[build_decision_observation(o),intent]):
            errors.append('decision_navigation_original_source_join')
    for row in rows:
        if row['event'] != 'actuator_consumed': continue
        rid = row['robot_id']; target = row['target']['motion']
        if target is None: continue
        try:
            action = row['source_action']; key = source_key(action)
            if key in status_keys: raise ValueError('status_cannot_be_action_consumption')
            if not same_tree(nav_actions.get(key),action): raise ValueError('unknown_original_peer_action')
            o,intent = nav_requests[key]
            enqueue = enqueues[key]; budget = enqueue['sensor_budget']
            cloud = o['sensors']['pointcloud']; acquisition = enqueue['cloud_acquisition']
            if (budget['source'] != 'navigation_sensor_v1'
                or budget['frame_id'] != cloud['frame_id']
                or budget['profile_sha256'] != cloud['profile_sha256']
                or not same_tree(budget['capture_sim_time'],cloud['capture_sim_time'])
                or not same_tree(acquisition,dict(frame_id=cloud['frame_id'],
                    acquisition_start_ns=cloud['acquisition_start_ns'],
                    acquisition_end_ns=cloud['acquisition_end_ns'],profile_sha256=cloud['profile_sha256']))
                or abs(budget['wall_deadline']-budget['capture_wall']-.15)>1e-6
                or abs(budget['sim_deadline']-budget['capture_sim_time']-.15)>1e-9
                or action['wall_deadline']>budget['wall_deadline']):
                raise ValueError('original_scan_capture_budget')
            envelope = envelopes[key]
            if (envelope['selection'] is None or envelope['controller_goal_uuid'] is None
                or envelope['controller_goal_uuid'] != envelope['selection']['goal_uuids']['navigation']):
                raise ValueError('physical_current_goal_join')
            if not same_tree(target,action['command']) or row['episode'] != action['episode'] or row['target']['fire'] is not False:
                raise ValueError('physical_target_mismatch_or_fire')
            auth = row['adapter_output_authorizations']['navigation']
            current = row['adapter_authorizations']['navigation']
            if auth['epoch'] != action['binding_epoch'] or current['epoch'] != action['binding_epoch'] or current['adapter_id'] != ROBOTS[rid]:
                raise ValueError('physical_binding_epoch_mismatch')
            w = activations[(rid, auth['epoch'], auth['activation_seq'], auth['activation_window_id'])]
            now = row['consume_wall']; sim = row['consume_sim_time']
            if not now < min(action['wall_deadline'],w['expires_wall'],current['activation_expires']):
                raise ValueError('original_wall_deadline_or_sdk150_exceeded')
            if not 0 <= sim-action['sim_time'] <= .15: raise ValueError('original_sim_budget_exceeded')
            if not (budget['capture_wall']<=now<budget['wall_deadline']
                and budget['capture_sim_time']<=sim<=budget['sim_deadline']):
                raise ValueError('original_scan_capture_deadline_exceeded')
            if w['lease_epochs']['motion'] != row['manual_inputs']['motion']['epoch']:
                raise ValueError('physical_motion_lease_mismatch')
            receipts[rid].append((row['phase'], sim, key))
            if any(abs(target[k]) > 1e-9 for k in ('vx_mps','vy_mps','wz_rps')):
                nonzero[rid].add(sim)
        except Exception as exc: errors.append('consumption:'+type(exc).__name__+':'+str(exc))
    # Sets are summarized after all typed receipt joins, never relabeled as
    # controller provenance or localization/goal-reaching evidence.
    for value in protocol.values():
        for name in ('operations','controller_uuids','behaviors','pointcloud_frames'):
            value[name] = sorted(value[name])
    return dict(errors=errors, decision_results=len(decisions), navigation_results=len(envelopes),
        navigation_actions=len(nav_actions),navigation_statuses=len(status_keys),protocol=protocol,
        physical={rid:dict(receipts=len(value), distinct_sim_steps=len({x[1] for x in value}),
            distinct_source_actions=len({x[2] for x in value}), phases=sorted({x[0] for x in value}),
            nonzero_sim_steps=len(nonzero[rid])) for rid,value in receipts.items()})


def run(out, duration):
    from rm_match.deployment.robotio_plugin import register_robotio_plugins
    from rm_match.platform_v2.adapters import Registry
    from rm_match.platform_v2.backend import MuJoCoBackend
    from rm_match.platform_v2.runtime import PlatformRuntime
    from rm_match.platform_v2.server import PlatformHTTPServer,TransportConfig
    from rm_match.platform_v2.admission import AdmissionPolicy
    from rm_match.platform_v2.client import PlatformClient
    from rm_match.navigation_sensors import NavigationSensorConfig
    rows = []; lock = threading.Lock(); instances = []; errors = []; actor_stop = threading.Event()
    def retain(value):
        with lock:
            if len(rows) >= 60000: raise RuntimeError('bounded_protocol_evidence_full')
            rows.append(copy.deepcopy(value))
    registry = Registry()
    register_robotio_plugins(registry, ROOT/'examples/robotio_active_goal_plugins.json')
    from rm_match.deployment.json_adapter import SharedCleanupBudget
    from rm_match.deployment.profile import digest
    prepared = {}; transferred = set(); prepare_rows = []
    shared_cleanup = SharedCleanupBudget()
    prepare_started = time.perf_counter(); prepare_deadline = prepare_started+15.
    def close_unclaimed():
        proof = {}; failures = []
        # All four peers share one original cleanup deadline, including partial
        # preparation failure. Unclean resources remain owned and observable.
        shared_cleanup.claim()
        for rid,instance in tuple(prepared.items()):
            try:
                instance.close()
                if not instance.shutdown_status or instance.shutdown_status.get('clean') is not True:
                    raise RuntimeError('unclaimed_pipeline_cleanup_unproved')
                prepared.pop(rid)
            except Exception as exc: failures.append(rid+':'+type(exc).__name__)
            proof[rid] = copy.deepcopy(instance.shutdown_status)
        write(out/'UNCLAIMED_CLEANUP.json',dict(proofs=proof,errors=failures,shared_budget_s=1.5))
        if failures: raise RuntimeError('unclaimed_prepared_resource_cleanup_unproved')
    try:
        for rid,aid in ROBOTS.items():
            spec = registry.get(aid)
            instance = spec.factory({})
            prepared[rid] = instance
            instance._budget = shared_cleanup
            for peer in (instance.decision,instance.navigation):peer._resource_budget = shared_cleanup
            with lock: instances.append(instance)
            for name in ('decision','navigation'):
                peer = getattr(instance,name); original_exchange = peer._exchange
                def exchange(packet, peer_name=name, original_exchange=original_exchange, robot_id=rid, **kwargs):
                    if packet['op']=='prepare':
                        kwargs['timeout']=min(kwargs['timeout'],prepare_deadline-time.perf_counter())
                    returned = original_exchange(packet,**kwargs)
                    retain(dict(event='peer_exchange',robot_id=robot_id,peer=peer_name,packet=packet,response=returned))
                    return returned
                peer._exchange = exchange
            def factory(config, rid=rid):
                if type(config) is not dict or config:raise ValueError('empty_fixture_binding_config_required')
                with lock:
                    if rid not in prepared:raise RuntimeError('prepared_fixture_handover_once')
                    instance = prepared[rid]
                    for peer in (instance.decision,instance.navigation):
                        if peer.failed or peer._cancelled.is_set() or peer.process is None or peer.process.poll() is not None:
                            raise RuntimeError('prepared_fixture_resource_unavailable')
                        if digest(peer.manifest)!=peer.manifest_sha:raise RuntimeError('prepared_fixture_manifest_changed')
                    transferred.add(rid)
                    return prepared.pop(rid)
            # Same descriptor, actual resource handover only; no cached reset.
            registry._specs[aid] = type(spec)(spec.descriptor, factory)
        for rid,instance in prepared.items():
            for name in ('decision','navigation'):
                if time.perf_counter()>=prepare_deadline:raise TimeoutError('fixture_total_prepare_15s_expired')
                peer = getattr(instance,name); started = time.perf_counter()
                if name=='decision':
                    peer.prepare()  # Real capabilities-bearing prepare ACK.
                else:
                    original_open = peer._open_owned_process
                    state = {'ready':False,'process':None,'owner':None}
                    def prepared_open(peer=peer, original_open=original_open, state=state):
                        if not state['ready']:return original_open()
                        if (peer.failed or peer._cancelled.is_set() or peer.process is not state['process']
                            or peer._owned_process is not state['owner'] or peer.process.poll() is not None):
                            raise RuntimeError('prepared_navigation_resource_unavailable')
                        if digest(peer.manifest)!=peer.manifest_sha:raise RuntimeError('prepared_navigation_manifest_changed')
                    peer._open_owned_process = prepared_open
                    peer._open_owned_process()
                    peer._exchange(dict(op='prepare',config={}),timeout=min(2.,prepare_deadline-time.perf_counter()))
                    state.update(ready=True,process=peer.process,owner=peer._owned_process)
                ended = time.perf_counter()
                prepare_rows.append(dict(robot_id=rid,peer=name,pid=peer.process.pid,started_wall=started,ack_wall=ended,
                    elapsed_s=ended-started,operation='prepare',sensor_messages=0,policy_calls=0))
                if ended>=prepare_deadline:raise TimeoutError('fixture_total_prepare_15s_expired')
        write(out/'PREPARE.json',dict(rows=prepare_rows,elapsed_s=time.perf_counter()-prepare_started,
            budget_s=15.,completed=True,scope='actual resource-only prepare ACK, no context/reset/sensor/policy/inference'))
    except BaseException:
        write(out/'PREPARE.json',dict(rows=prepare_rows,elapsed_s=time.perf_counter()-prepare_started,
            budget_s=15.,completed=False))
        try:close_unclaimed()
        finally:
            with (out/'PREPARE_PROTOCOL.jsonl').open('wb') as stream:
                for row in rows:stream.write(json.dumps(row,allow_nan=False,separators=(',',':')).encode()+b'\n')
        raise
    config = NavigationSensorConfig(robot_ids=tuple(ROBOTS),point_rate_hz=1000)
    backend = None; runtime = None; server = None; http = None; actors = []
    def trace(value):
        rid = value.get('robot_id')
        if rid not in ROBOTS: return
        if value['event'] == 'actuator_consumed':
            if value['target']['motion'] is None: return
            action = runtime.outputs.get((rid,'navigation'))
            retain(dict(value,source_action=copy.deepcopy(action)))
        elif value['event'] in ('adapter_enqueue','adapter_result'): retain(value)
    try:
        backend = MuJoCoBackend(navigation_sensors=config)
        initial = backend.display_snapshot()
        runtime = PlatformRuntime(backend, registry=registry, trace=trace, action_ttl=.15)
        credentials = {rid:secrets.token_urlsafe(32) for rid in ROBOTS}
        admission = AdmissionPolicy([dict(credential_sha256=hashlib.sha256(secret.encode()).hexdigest(),
            role='operator',allowed_robots=[rid],audit_authorized=False) for rid,secret in credentials.items()])
        server = PlatformHTTPServer(TransportConfig(port=0,admission_policy=admission),runtime)
        http = threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.05},name='active-goal-protocol-http',daemon=True)
        http.start(); base = 'http://127.0.0.1:'+str(server.server_address[1])
    except BaseException as setup_error:
        setup_cleanup_errors = []
        callbacks = []
        if server is not None: callbacks.append(('http',server.server_close))
        if runtime is not None: callbacks.append(('runtime',runtime.close))
        elif backend is not None: callbacks.append(('backend',backend.close))
        callbacks.append(('unclaimed',close_unclaimed))
        for name,callback in callbacks:
            try:callback()
            except BaseException as exc:setup_cleanup_errors.append(name+':'+type(exc).__name__)
        write(out/'SETUP_CLEANUP.json',dict(errors=setup_cleanup_errors,
            runtime=runtime.shutdown_status if runtime is not None else None))
        if setup_cleanup_errors:raise RuntimeError('fixture_setup_cleanup_unproved') from setup_error
        raise
    # Release while authority/HTTP are still open. runtime.run closes sessions
    # at its wall limit; racing SDK release against that closure is not a
    # successful lifecycle demonstration, even if all peer trees were reaped.
    actor_deadline = time.perf_counter()+duration-.75
    def actor(rid):
        client = PlatformClient(base,admission_credential=credentials[rid],control_profile='server_window_v1',timeout=.25)
        claimed = False
        try:
            client.open('operator'); client.claim(rid,['motion']); claimed = True
            binding = client.bind_pipeline(rid,ROBOTS[rid])
            while not actor_stop.is_set() and time.perf_counter()<actor_deadline:
                client.renew(rid,['motion'])
                window = client.control_window(rid,['motion'])
                activation = client.adapter_input(rid,'navigation',binding['binding_epoch'],window_id=window['window_id'],valid_for_s=.15)
                retain(dict(event='sdk_activation',robot_id=rid,window=window,activation=activation))
                actor_stop.wait(.025)
        except Exception as exc:
            if not runtime.stop_event.is_set(): errors.append('actor:'+rid+':'+type(exc).__name__)
        finally:
            try:
                if claimed: client.release(rid,['motion'])
                client.close()
            except Exception as exc: errors.append('actor_cleanup:'+rid+':'+type(exc).__name__)
    runtime_started = time.perf_counter()
    try:
        for rid in ROBOTS:
            thread = threading.Thread(target=actor,args=(rid,),name='active-goal-protocol-sdk-'+rid,daemon=True)
            actors.append(thread);thread.start()
        runtime.run(max_wall_seconds=duration,real_time_factor=1.)
    except BaseException as exc:
        errors.append('runtime:'+type(exc).__name__)
        (out/'runtime_failure.log').write_text(traceback.format_exc(),encoding='utf8')
    finally:
        actor_stop.set()
        # HTTP remains available until each memory-only SDK actor has released.
        deadline = time.perf_counter()+1.5
        for thread in actors:
            if thread.ident is not None: thread.join(max(0.,deadline-time.perf_counter()))
        if http.is_alive(): server.shutdown()
        server.server_close();http.join(max(0.,deadline-time.perf_counter()))
        if not runtime._closed:
            try:runtime.close()
            except Exception as exc:errors.append('runtime_cleanup:'+type(exc).__name__)
        try:close_unclaimed()
        except Exception as exc:errors.append('unclaimed_cleanup:'+type(exc).__name__)
    # Persist actual cleanup proof before any evidence serialization/audit can
    # fail. A failed audit cannot erase a successfully observed resource close.
    cleanup = dict(runtime=runtime.shutdown_status,http_thread_stopped=not http.is_alive(),
        http_workers_idle=server._slots._value==server.config.max_http_workers,
        sdk_threads_stopped=all(not t.is_alive() for t in actors),
        pipelines=[copy.deepcopy(i.shutdown_status) for i in instances])
    write(out/'CLEANUP.json',cleanup)
    with lock: captured = copy.deepcopy(rows)
    # Disk evidence is written only after the authority/SDK/peer run has ended.
    with (out/'PROTOCOL_TRACE.jsonl.gz').open('wb') as stream:
        with gzip.GzipFile(filename='',mode='wb',fileobj=stream,mtime=0) as gz:
            for row in captured:gz.write(json.dumps(row,allow_nan=False,separators=(',',':')).encode()+b'\n')
    independent = audit(captured); write(out/'AUDIT.json',independent)
    final = runtime.cached
    xy0 = {r['robot_id']:r['xy'] for r in initial['robots'] if r['robot_id'] in ROBOTS}
    xy1 = {r['robot_id']:r['xy'] for r in final['robots'] if r['robot_id'] in ROBOTS}
    evaluation = dict(source='isolated_actual_physics_evaluation_not_peer_input',initial_xy=xy0,final_xy=xy1,
        displacement_m={rid:math.dist(xy0[rid],xy1[rid]) for rid in ROBOTS})
    write(out/'EVAL.json',evaluation)
    checks = dict(original_2ms_timestep=backend.timestep==.002,actual_physics_steps=runtime.steps>0,
        both_independent_pipelines_created=len(instances)==2,
        four_real_resource_prepare_acks=len(prepare_rows)==4,
        four_independent_peer_processes=len({row['pid'] for row in prepare_rows})==4,
        both_prepared_pipelines_handed_over=transferred==set(ROBOTS),
        moving_robot_has_physical_receipts=independent['physical']['red_infantry']['receipts']>0,
        supply_has_nonzero_physical_consumption=independent['physical']['red_infantry']['nonzero_sim_steps']>0,
        supply_has_current_goal_uuid_actions=independent['protocol']['red_infantry']['actions']>0
            and bool(independent['protocol']['red_infantry']['controller_uuids']),
        heat_hold_has_real_status_replies=independent['protocol']['blue_sentry']['statuses']>0,
        heat_hold_has_no_actuator_dto=independent['protocol']['blue_sentry']['actions']==0,
        heat_hold_has_no_physical_motion_receipts=independent['physical']['blue_sentry']['receipts']==0,
        heat_hold_has_zero_nonzero_consumption=independent['physical']['blue_sentry']['nonzero_sim_steps']==0,
        both_robots_have_actual_scan_frames=all(independent['protocol'][r]['pointcloud_frames'] for r in ROBOTS),
        original_source_current_goal_sdk150_receipt_join=not independent['errors'],
        no_adapter_fault=not any(r['event']=='adapter_result' and r.get('error') for r in captured),
        runtime_clean=bool(runtime.shutdown_status and runtime.shutdown_status['clean']),
        all_pipeline_children_clean=all(i.shutdown_status and i.shutdown_status['clean'] for i in instances),
        sdk_http_threads_stopped=cleanup['http_thread_stopped'] and cleanup['sdk_threads_stopped'] and cleanup['http_workers_idle'],errors_empty=not errors)
    return dict(passed=all(checks.values()),checks=checks,errors=errors,steps=runtime.steps,sim_time=final['sim_time'],
        wall_run_plus_cleanup_s=time.perf_counter()-runtime_started,sensor_profile=config.identity()[0],
        physical=independent['physical'],protocol=independent['protocol'],
        qualification='active_goal_v2_two_robot_actual_MuJoCo_low_rate_protocol_SIL_only',
        limitations=['synthetic decision, backend UUID and constant velocity fixtures, not team algorithms',
            '1000 points/s, not MID360 or SLAM qualification','no camera/NN/ROS/WSL/GUI',
            'not native UUID, DDS, RTF, match, moving aim, firing, localization accuracy or goal-reaching acceptance',
            'v1 decision observation still has no estimated localization or goal-status feedback'])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--duration',type=float,default=4.)
    p.add_argument('--run',action='store_true')
    args = p.parse_args(argv)
    if not args.run: raise RuntimeError('explicit_active_goal_protocol_fixture_run_required')
    if not math.isfinite(args.duration) or not 3.<=args.duration<=5.:raise ValueError('duration_must_be_3_to_5_seconds')
    out = args.out.absolute()
    if out.exists():raise RuntimeError('fresh_output_required')
    out.mkdir(parents=True);records=[];code=2;started=time.perf_counter()
    try:
        for relative in SOURCE_FILES:
            raw=(ROOT/relative).read_bytes();target=out/'source'/relative
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            records.append(dict(path=relative,size=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
        write(out/'SOURCE_MANIFEST.json',dict(files=records))
        write(out/'COMMAND.json',dict(argv=sys.argv,duration_s=args.duration,
            scope='explicit synthetic active-goal protocol fixtures over real low-rate physics; no secrets recorded'))
        result=run(out,args.duration);code=0 if result['passed'] else 2
    except BaseException as exc:
        result=dict(passed=False,error_type=type(exc).__name__)
        (out/'failure.log').write_text(traceback.format_exc(),encoding='utf8')
    unchanged=all(hashlib.sha256((ROOT/r['path']).read_bytes()).hexdigest()==r['sha256'] for r in records)
    result.update(source_unchanged=unchanged,elapsed_seconds=time.perf_counter()-started,exit_code=code)
    if not unchanged:result['passed']=False;result['exit_code']=code=2
    write(out/'RESULT.json',result)
    print(json.dumps(dict(passed=result['passed'],exit_code=code,out=str(out)),allow_nan=False))
    return code


if __name__=='__main__':raise SystemExit(main())
