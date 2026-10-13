"""Bounded Windows physics + actual owned WSL Humble navigation; opt-in only."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import secrets
import signal
import sys
import threading
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('environment','stack-config','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--seconds',type=float,default=30.)
    parser.add_argument('--run',action='store_true');parser.add_argument('--diagnostics',action='store_true')
    args=parser.parse_args(argv)
    if not 5<=args.seconds<=60:parser.error('bounded 5..60 seconds required')
    if not args.run:print(json.dumps(dict(scope=__doc__,status='plan_only',sensor_truth=False,hardware=False,training=False)));return 0
    if sys.platform!='win32':parser.error('actual Windows host required; Linux-only evidence is separately labelled')
    out=args.out.absolute()
    if out.exists() or any(p.is_symlink() for p in (out,*out.parents)) or not out.resolve().is_relative_to(ROOT/'artifacts'):parser.error('fresh repository artifacts output required')
    out.mkdir(parents=True)
    from tools.qa_pb_navigation_sil import audit_navigation_consumption
    from rm_match.integrations.pb_wsl_navigation_registry import register_pb_wsl_navigation,SCHEMA
    from rm_match.integrations.pb_wsl_navigation import SOURCE_FILES
    from rm_match.platform_v2.adapters import Registry
    from rm_match.platform_v2.backend import MuJoCoBackend
    from rm_match.platform_v2.runtime import PlatformRuntime
    from rm_match.platform_v2.admission import AdmissionPolicy
    from rm_match.platform_v2.server import PlatformHTTPServer,TransportConfig
    from rm_match.platform_v2.client import PlatformClient
    from rm_match.navigation_sensors import NavigationSensorConfig
    def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    source_names=list(SOURCE_FILES)+['tools/qa_pb_wsl_navigation_sil.py','rm_match/integrations/pb_wsl_navigation_registry.py',
        'rm_match/platform_v2/runtime.py','rm_match/platform_v2/backend.py','rm_match/navigation_sensors.py','rm_match/harness.xml']
    hashes=lambda:{n:sha(ROOT/n) for n in source_names}
    before=hashes();rows=[];errors=[];session=runtime=server=sdk=None;http=None;thread=None;stop=threading.Event()
    credential=secrets.token_hex(32)
    policy=AdmissionPolicy([dict(credential_sha256=hashlib.sha256(credential.encode()).hexdigest(),role='operator',allowed_robots=['red_sentry'],audit_authorized=False)])
    manifest=out/'MANIFEST.json'
    manifest.write_text(json.dumps(dict(schema=SCHEMA,config_ref=dict(path=str(args.stack_config.absolute()),sha256=sha(args.stack_config)),
        environment_ref=dict(path=str(args.environment.absolute()),sha256=sha(args.environment)),out=str(out/'session'),diagnostics=args.diagnostics),indent=2)+'\n',encoding='utf8')
    (out/'COMMAND.json').write_text(json.dumps(dict(argv=sys.argv if argv is None else argv,source_sha256=before,manifest_sha256=sha(manifest),
        scope='Windows MuJoCo authority and actual WSL ROS; not camera/native aim/full mission/match/HIL',host_clock='windows_perf_counter',
        linux_receive_clock='linux_local_only_never_subtracted_from_host_clock',reset_budget_s=2.,image_limit_s=.08,control_window_s=.15),indent=2)+'\n',encoding='utf8')
    def trace(row):
        if row['event'] in ('adapter_enqueue','adapter_result'):rows.append(copy.deepcopy(row));return
        if row['event']!='actuator_consumed' or row['robot_id']!='red_sentry' or row['phase']!='integration_entry':return
        auth=row['adapter_authorizations']['navigation']
        rows.append(dict(event='navigation_consumed',phase=row['phase'],consume_wall=row['consume_wall'],consume_sim_time=row['consume_sim_time'],
            target=copy.deepcopy(row['target']),action=copy.deepcopy(runtime.outputs.get(('red_sentry','navigation'))),
            navigation_budget=copy.deepcopy(runtime.output_budgets.get(('red_sentry','navigation'))),
            output_authorization=copy.deepcopy(runtime.output_authorizations.get(('red_sentry','navigation'))),
            authorization={k:auth.get(k) for k in ('epoch','activation_required','activation_seq','activation_expires','activation_window_id','activation_window_deadline')}))
        if len(rows)>200000:raise ValueError('bounded_trace_full')
    old={s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM)}
    def canceled(*_):
        stop.set()
        if session is not None:session.request_stop()
        if runtime is not None:runtime.request_stop()
    for sig in old:signal.signal(sig,canceled)
    elapsed=None;initial=final=None
    try:
        registry=Registry()
        prepared_at=time.perf_counter()
        session=register_pb_wsl_navigation(registry,manifest,repo_root=ROOT,relative_test_goal=True)
        (out/'PREPARE.json').write_text(json.dumps(dict(elapsed_s=time.perf_counter()-prepared_at,ready=session.ready,
            physics_steps=0,sensor_frames=0,algorithm_data_warmup=False),indent=2)+'\n',encoding='utf8')
        backend=MuJoCoBackend(navigation_sensors=NavigationSensorConfig())
        initial=backend._sim.data.qpos[backend._sim.qindices['red_sentry'][:3]].copy().tolist()
        runtime=PlatformRuntime(backend,registry=registry,trace=trace)
        server=PlatformHTTPServer(TransportConfig(port=0,admission_policy=policy),runtime)
        http=threading.Thread(target=server.serve_forever,name='wsl-sil-http',daemon=True);http.start()
        sdk=PlatformClient('http://127.0.0.1:'+str(server.server_address[1]),control_profile='server_window_v1',admission_credential=credential)
        sdk.open('operator');sdk.claim('red_sentry',['motion']);binding=sdk.bind('red_sentry','navigation','custom_pb_navigation',{})
        if binding['binding_epoch']!=1:raise ValueError('single_generation_binding')
        def deadman():
            renewed=time.perf_counter();next_tick=renewed
            try:
                while not stop.is_set():
                    if session.process.poll() is not None:raise RuntimeError('owned_wsl_supervisor_exited')
                    if time.perf_counter()-renewed>=.25:
                        begin=time.perf_counter();sdk.renew('red_sentry',['motion']);renewed=time.perf_counter()
                        rows.append(dict(event='sdk_lease_renewed',started_wall=begin,completed_wall=renewed))
                    window=sdk.control_window('red_sentry',['motion'])
                    activation=sdk.adapter_input('red_sentry','navigation',1,window_id=window['window_id'],valid_for_s=.15)
                    ack=time.perf_counter()
                    rows.append(dict(event='sdk_adapter_activation',wall_time=ack,
                        window={k:window[k] for k in ('window_id','issued_wall','expires_wall','valid_for_s','lease_epochs')},
                        activation={k:activation[k] for k in ('binding_epoch','seq','window_id','activation_expires')}))
                    next_tick+=.05
                    if next_tick<=ack:next_tick+=(math.floor((ack-next_tick)/.05)+1)*.05
                    stop.wait(max(0.,next_tick-time.perf_counter()))
            except BaseException as error:
                if not runtime.stop_event.is_set():errors.append('sdk:'+type(error).__name__+':'+str(error));(out/'SDK_FAILURE.txt').write_text(traceback.format_exc(),encoding='utf8')
                runtime.request_stop();stop.set()
        thread=threading.Thread(target=deadman,name='wsl-sil-sdk',daemon=True);thread.start()
        started=time.perf_counter();runtime.run(max_wall_seconds=args.seconds,real_time_factor=1.);elapsed=time.perf_counter()-started
        final=backend._sim.data.qpos[backend._sim.qindices['red_sentry'][:3]].copy().tolist()
    except BaseException as error:
        errors.append(type(error).__name__+':'+str(error));(out/'FAILURE.txt').write_text(traceback.format_exc(),encoding='utf8')
    finally:
        stop.set()
        if thread is not None:
            thread.join(.5)
            if thread.is_alive():errors.append('sdk_thread_not_reaped')
        if runtime is not None:
            try:runtime.close()
            except BaseException as error:errors.append('runtime_cleanup:'+type(error).__name__)
        if session is not None:
            try:session.close()
            except BaseException as error:errors.append('session_cleanup:'+type(error).__name__+':'+str(error))
        if sdk is not None:
            try:sdk.close()
            except BaseException as error:errors.append('sdk_close:'+type(error).__name__)
        if server is not None:
            server.shutdown();server.server_close();http.join(.5)
            if http.is_alive():errors.append('http_thread_not_reaped')
        for sig,handler in old.items():signal.signal(sig,handler)
    rosfile=out/'session/ROS_SOURCE.jsonl';goalfile=out/'session/GOAL_REPORT.json'
    ros=[] if not rosfile.is_file() else [json.loads(line) for line in rosfile.read_text().splitlines()]
    goal={} if not goalfile.is_file() else json.loads(goalfile.read_bytes())
    audit=audit_navigation_consumption(rows,ros)
    if session is not None:
        (out/'HOST_RPC_PHASES.json').write_text(json.dumps(dict(rows=session.phase_rows,
            clock='windows_local_perf_counter'),allow_nan=False)+'\n',encoding='utf8')
    (out/'TRACE.jsonl').write_text(''.join(json.dumps(r,allow_nan=False,separators=(',',':'))+'\n' for r in rows),encoding='utf8')
    result=dict(schema='polar.pb.windows-wsl-navigation-sil.v1',scope='single sentry/generation/relative goal; Windows physics+WSL Humble; not full mission/match/hardware',
        actual_steps=0 if runtime is None else runtime.steps,requested_seconds=args.seconds,wall_seconds=elapsed,
        simulation_seconds=0 if runtime is None else runtime.steps*runtime.backend.timestep,
        physics_rtf=None if elapsed is None else runtime.steps*runtime.backend.timestep/elapsed,
        source_sha256=before,source_unchanged=before==hashes(),consumption_audit=audit,observer_goal=goal,
        runtime_error=None if runtime is None else runtime.error,
        shutdown=None if runtime is None else getattr(runtime,'shutdown_status',None),session_cleanup=None if session is None else session.cleanup,
        isolated_postrun_groundtruth=dict(initial_qpos=initial,final_qpos=final,algorithm_input=False),errors=errors,
        clock_conversion=False,sensor_input_has_truth=False,image_limit_seconds=.08,control_window_seconds=.15,fire_permission=False,
        full_match_qualified=False,hardware_qualified=False)
    result['relative_goal_completed']=goal.get('follow_path_status')==4
    result['completed_requested_wall_duration']=elapsed is not None and elapsed>=args.seconds
    result['bounded_navigation_consumption_passed']=bool(audit['passed'] and not errors and result['runtime_error'] is None and result['completed_requested_wall_duration'] and result['source_unchanged'] and goal.get('planner_status')==4 and goal.get('follow_path_accepted')
        and result['shutdown'] and result['shutdown']['clean'] and result['session_cleanup'] and result['session_cleanup']['clean'])
    (out/'RESULT.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps({k:result[k] for k in ('bounded_navigation_consumption_passed','relative_goal_completed','actual_steps','physics_rtf','consumption_audit','errors')},indent=2))
    return 0 if result['bounded_navigation_consumption_passed'] else 2


if __name__=='__main__':raise SystemExit(main())
