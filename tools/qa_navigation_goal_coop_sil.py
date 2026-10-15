"""Opt-in original Qt infantry and real Nav2 source-bound goal cancellation SIL."""
from __future__ import annotations
import argparse,copy,gzip,hashlib,json,math,os,secrets,sys,threading,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
RID='red_infantry'
SOURCE_FILES=('tools/qa_navigation_goal_coop_sil.py','tools/navigation_goal_session.py','tools/qa_navigation_goal_client.py','tools/qa_navigation_goal_supervisor.py','rm_match/integrations/navigation_goal_lifecycle.py','rm_match/integrations/nav2_goal_backend.py','rm_match/platform_v2/decision_contracts.py','tools/pb_coop_cleanup.py','tools/pb_external_goal_session.py','tools/qa_pb_navigation_sil.py','rm_match/integrations/pb_wsl_navigation_registry.py','rm_match/integrations/pb_wsl_navigation.py','rm_match/navigation_sensors.py','tools/qa_qt_manual_peer.py','tools/audit_qt_manual.py',
 'rm_match/platform_v2/runtime.py','rm_match/platform_v2/backend.py','rm_match/platform_v2/control.py',
 'rm_match/platform_v2/server.py','rm_match/platform_v2/client.py','rm_match/platform_v2/camera.py',
 'rm_match/platform_v2/host_scheduling.py','rm_match/platform_v2/admission.py','rm_match/camera_profile.py',
 'rm_match/platform_v2/adapters.py','rm_match/match_engine.py','rm_match/match_model.py','rm_match/harness.xml',
 'rm_match/deployment/windows_owned_job.py','rm_match/deployment/coop_launcher.py','rm_match/deployment/launcher.py')
CLIENT_FILES=('rm_client/sim_platform_client.py','rm_client/sim_platform_transport.py','rm_client/sim_platform_handoff.py',
 'rm_client/sim_platform_runtime.py','rm_client/sim_platform_input.py','rm_client/sim_operator_runtime.py',
 'rm_client/ui/sim_platform_window.py','rm_client/ui/sim_operator_window.py')
def write(path,value):path.write_bytes((json.dumps(value,indent=2,allow_nan=False)+'\n').encode())
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def run(out,args,identity):
    from rm_match.deployment.coop_launcher import CappedStderr
    from rm_match.deployment.json_adapter import SharedCleanupBudget
    from rm_match.deployment.windows_owned_job import WindowsOwnedJobProcess
    from rm_match.deployment.launcher import check_client
    from rm_match.platform_v2.backend import MuJoCoBackend
    from rm_match.platform_v2.runtime import PlatformRuntime
    from rm_match.platform_v2.camera import CameraProvider
    from rm_match.platform_v2.server import PlatformHTTPServer,TransportConfig
    from rm_match.platform_v2.admission import AdmissionPolicy
    from tools.audit_qt_manual import audit
    from tools.qa_pb_navigation_sil import audit_navigation_consumption
    from tools.navigation_goal_session import NavigationGoalSession as ExternalGoalSession
    from tools.qa_navigation_goal_client import SOURCE_FILES as PEER_SOURCES, SCHEMA as PEER_SCHEMA
    from rm_match.integrations.pb_wsl_navigation_registry import register_pb_wsl_navigation, SCHEMA
    from rm_match.platform_v2.adapters import Registry
    from rm_match.platform_v2.client import PlatformClient
    from rm_match.navigation_sensors import NavigationSensorConfig
    from tools.pb_coop_cleanup import close_pb_sessions
    session=peer=nav_sdk=nav_thread=peer_cleanup_thread=None;peer_cleanup=None;nav_stop=threading.Event();nav_go=threading.Event();cleanup_lock=threading.Lock()
    rows=[];lock=threading.Lock();errors=[];stages=[];child=reader=stderr=http=server=backend=camera=runtime=None
    qt_ready=qt_finished=qt_proof=None;camera_clean=None;budget=SharedCleanupBudget();initial=None
    def retain(row):
        with lock:
            if len(rows)>=100000:raise RuntimeError('manual_trace_capacity')
            rows.append(copy.deepcopy(row))
    def begin_cleanup():
        nonlocal peer_cleanup_thread
        with cleanup_lock:
            deadline=budget.claim();nav_stop.set()
            if peer is not None and peer_cleanup_thread is None:
                peer.request_stop()
                def close_peer():
                    nonlocal peer_cleanup
                    try:peer_cleanup=close_pb_sessions(external_goal=peer,deadline=deadline)
                    except BaseException as exc:errors.append('external_cleanup:'+type(exc).__name__)
                peer_cleanup_thread=threading.Thread(target=close_peer,name='coop-external-owner-cleanup')
                peer_cleanup_thread.start()
        if runtime is not None:runtime.request_stop()
        return deadline
    try:
        registry=Registry();prepared=time.perf_counter()
        manifest=out/'PB_MANIFEST.json'
        write(manifest,dict(schema=SCHEMA,config_ref=dict(path=str(args.stack_config),sha256=digest(args.stack_config)),
            environment_ref=dict(path=str(args.environment),sha256=digest(args.environment)),out=str(out/'session'),diagnostics=True))
        session=register_pb_wsl_navigation(registry,manifest,repo_root=ROOT,relative_test_goal=False)
        peer_out=out/'peer';peer_out.mkdir();peer_spec=peer_out/'EXTERNAL_SPEC.json'
        write(peer_spec,dict(schema=PEER_SCHEMA,run_uuid=secrets.token_hex(16),session_run_uuid=session.run_uuid,
            session_ref=dict(path=session._map(session.spec_path),sha256=session.spec_sha256),namespace=session.namespace,
            domain_id=84,root_linux=session._map(ROOT),out_linux=session._map(peer_out),environment_ref=session.spec['environment_ref'],
            source_sha256={n:digest(ROOT/n) for n in PEER_SOURCES},goal_offset_m=[1.,0.],max_wall_seconds=60.))
        peer=ExternalGoalSession(ROOT,peer_out,peer_spec,digest(peer_spec));peer.prepare()
        write(out/'PREPARE.json',dict(elapsed_s=time.perf_counter()-prepared,ready=session.ready,external_ready=peer.ready,
            physics_steps=0,sensor_frames=0,algorithm_data_warmup=False))
        backend=MuJoCoBackend(camera=True,navigation_sensors=NavigationSensorConfig());initial=backend.display_snapshot()
        camera=CameraProvider(backend._sim,total_fps=15,max_views=1)
        def trace(row):
            if row['event'] in ('adapter_enqueue','adapter_result'):retain(row);return
            if row['event']!='actuator_consumed' or row['phase']!='integration_entry':return
            if row.get('robot_id')==RID:retain(row);return
            if row.get('robot_id')!='red_sentry':return
            auth=row['adapter_authorizations']['navigation']
            retain(dict(event='navigation_consumed',phase=row['phase'],consume_wall=row['consume_wall'],consume_sim_time=row['consume_sim_time'],
                target=copy.deepcopy(row['target']),action=copy.deepcopy(runtime.outputs.get(('red_sentry','navigation'))),
                navigation_budget=copy.deepcopy(runtime.output_budgets.get(('red_sentry','navigation'))),
                output_authorization=copy.deepcopy(runtime.output_authorizations.get(('red_sentry','navigation'))),
                authorization={k:auth.get(k) for k in ('epoch','activation_required','activation_seq','activation_expires','activation_window_id','activation_window_deadline')}))
        runtime=PlatformRuntime(backend,registry=registry,camera=camera,trace=trace,action_ttl=.15)
        credential=secrets.token_urlsafe(32)
        nav_credential=secrets.token_urlsafe(32)
        policy=AdmissionPolicy([dict(credential_sha256=hashlib.sha256(token.encode()).hexdigest(),role='operator',allowed_robots=[rid],audit_authorized=False) for token,rid in ((credential,RID),(nav_credential,'red_sentry'))])
        server=PlatformHTTPServer(TransportConfig(port=0,admission_policy=policy),runtime)
        http=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},name='manual-sil-http');http.start()
        nav_sdk=PlatformClient('http://127.0.0.1:'+str(server.server_address[1]),control_profile='server_window_v1',admission_credential=nav_credential)
        nav_sdk.open('operator');nav_sdk.claim('red_sentry',['motion']);binding=nav_sdk.bind('red_sentry','navigation','custom_pb_navigation',{})
        if type(binding['binding_epoch']) is not int or binding['binding_epoch']!=1:raise RuntimeError('single_nav_generation_required')
        def deadman():
            renewed=time.perf_counter();next_tick=renewed
            try:
                while not nav_stop.is_set():
                    if session.process.poll() is not None or peer.child.poll() is not None:raise RuntimeError('owned_PB_supervisor_exited_early')
                    if time.perf_counter()-renewed>=.25:
                        begin=time.perf_counter();nav_sdk.renew('red_sentry',['motion']);renewed=time.perf_counter()
                        retain(dict(event='sdk_lease_renewed',started_wall=begin,completed_wall=renewed))
                    # Keep the independent motion lease alive, but authorize PB
                    # only after the original Qt two-F2 stage. No warm sensor
                    # input or goal action is fabricated to make overlap pass.
                    if not nav_go.is_set():
                        nav_stop.wait(.05);next_tick=time.perf_counter();continue
                    window=nav_sdk.control_window('red_sentry',['motion'])
                    activation=nav_sdk.adapter_input('red_sentry','navigation',1,window_id=window['window_id'],valid_for_s=.15)
                    ack=time.perf_counter();retain(dict(event='sdk_adapter_activation',wall_time=ack,
                        window={k:window[k] for k in ('window_id','issued_wall','expires_wall','valid_for_s','lease_epochs')},
                        activation={k:activation[k] for k in ('binding_epoch','seq','window_id','activation_expires')}))
                    next_tick+=.05
                    if next_tick<=ack:next_tick+=(math.floor((ack-next_tick)/.05)+1)*.05
                    nav_stop.wait(max(0.,next_tick-time.perf_counter()))
            except BaseException as exc:
                if not nav_stop.is_set():errors.append('nav_sdk:'+type(exc).__name__);(out/'NAV_SDK_FAILURE.log').write_text(traceback.format_exc(),encoding='utf8')
                begin_cleanup()
        nav_thread=threading.Thread(target=deadman,name='coop-real-PB-sdk');nav_thread.start()
        if check_client(args.client_root,patch_manifest=args.patch_manifest)!=identity:raise RuntimeError('client_changed_before_spawn')
        env=dict(os.environ)
        for key in tuple(env):
            if any(part in key.upper() for part in ('CREDENTIAL','TOKEN','SECRET','PASSWORD')) or key in ('PYTHONPATH','PYTHONHOME'):env.pop(key,None)
        env.update(QT_QPA_PLATFORM='offscreen',POLAR_SIM_ADMISSION_CREDENTIAL=credential)
        command=[str(args.client_python),'-u',str(ROOT/'tools/qa_qt_manual_peer.py'),'--client-root',str(args.client_root),
            '--manifest',str(args.patch_manifest),'--url','http://127.0.0.1:'+str(server.server_address[1]),'--robot-id',RID,
            '--out',str(out/'qt'),'--max-wall-seconds',str(args.max_wall_seconds),'--run-seconds',str(args.seconds)]
        if args.host_opencv_threads is not None:command+=['--host-opencv-threads',str(args.host_opencv_threads)]
        if args.host_python_switch_interval_ms is not None:command+=['--host-python-switch-interval-ms',str(args.host_python_switch_interval_ms)]
        write(out/'CHILD_COMMAND.json',dict(argv=command,credential_transport='memory/environment_only'))
        stderr=CappedStderr(out/'qt.stderr.log');child=WindowsOwnedJobProcess(command,cwd=str(ROOT),env=env,stderr=stderr.writer);stderr.writer.close()
        def collect():
            nonlocal qt_ready,qt_finished
            try:
                count=0
                while True:
                    raw=child.stdout.readline(16385)
                    if not raw:break
                    count+=1
                    if count>4096 or len(raw)>16384 or not raw.endswith(b'\n'):raise RuntimeError('bounded_stdout')
                    from rm_match.integrations.ros2_bridge import parse_json
                    row=parse_json(raw,16384);event=row.get('event')
                    if event in ('qt_watch_ready','qt_plan_selected','qt_claimed_hud','qt_manual_armed'):
                        if row.get('robot_id')!=RID or len(stages)>=8:raise RuntimeError('manual_stage_identity')
                        stages.append(row)
                        if event=='qt_manual_armed':
                            if qt_ready is not None or type(row.get('f2_count')) is not int or row['f2_count']!=2:raise RuntimeError('manual_arm_identity')
                            qt_ready=row;nav_go.set();retain(dict(event='original_Qt_armed_starts_PB',host_wall=time.perf_counter()))
                            child.stdin.write(b'{"op":"go"}\n');child.stdin.flush()
                    elif event=='sdk_manual_batch':
                        if set(row)!={'event','robot_id','window','request','ack','entered_host_wall','returned_host_wall'} or row['robot_id']!=RID:raise RuntimeError('manual_batch_event')
                        retain(row)
                    elif event=='qt_finished':
                        if set(row)!={'event','clean','errors','exit_code'} or qt_finished is not None:raise RuntimeError('manual_finish_identity')
                        qt_finished=row;begin_cleanup()
                    else:raise RuntimeError('unknown_manual_event')
            except BaseException as exc:
                errors.append('reader:'+type(exc).__name__);begin_cleanup()
        reader=threading.Thread(target=collect,name='manual-sil-reader');reader.start()
        runtime.run(max_wall_seconds=args.max_wall_seconds,real_time_factor=1.)
        if qt_ready is None or qt_finished is None:raise RuntimeError('manual_run_incomplete')
    except BaseException as exc:
        errors.append(type(exc).__name__);(out/'FAILURE.log').write_text(traceback.format_exc(),encoding='utf8')
    finally:
        deadline=begin_cleanup()
        if child is not None:
            if child.poll() is None:
                try:child.stdin.write(b'{"op":"stop"}\n');child.stdin.flush()
                except Exception as exc:errors.append('stop:'+type(exc).__name__)
            try:child.wait(timeout=max(0.,deadline-time.perf_counter()-.2))
            except Exception as exc:errors.append('qt_wait:'+type(exc).__name__)
            try:qt_proof=child.cleanup(deadline)
            except Exception as exc:errors.append('qt_job:'+type(exc).__name__)
            try:
                if reader is not None:reader.join(max(0.,deadline-time.perf_counter()))
                child.stdin.close();child.stdout.close();child.release_handles()
            except Exception as exc:errors.append('qt_handles:'+type(exc).__name__)
        if stderr is not None:
            try:stderr.close_until(deadline)
            except Exception as exc:errors.append('stderr:'+type(exc).__name__)
        if runtime is not None and not runtime._closed:runtime.close()
        elif runtime is None and backend is not None:backend.close()
        if nav_thread is not None:
            nav_thread.join(max(0.,deadline-time.perf_counter()))
            if nav_thread.is_alive():errors.append('nav_sdk_thread_not_reaped')
        if session is not None and not session._closed:
            # A live runtime slot exclusively owns its session close. Never race it.
            live=runtime is not None and any(getattr(slot,'thread',None) is not None and slot.thread.is_alive() for slot in runtime.slots.values())
            if live:errors.append('live_runtime_owns_navigation_cleanup')
            else:
                nav_cleanup=close_pb_sessions(navigation=session,deadline=deadline)
                if not nav_cleanup.get('clean'):errors.append('navigation_cleanup_unproved')
        if peer_cleanup_thread is not None:
            peer_cleanup_thread.join(max(0.,deadline-time.perf_counter()))
            if peer_cleanup_thread.is_alive():errors.append('external_cleanup_observer_not_joined')
        if nav_sdk is not None:
            try:nav_sdk.close()
            except Exception as exc:errors.append('nav_sdk_close:'+type(exc).__name__)
        if camera is not None:
            try:camera_clean=camera.wait_closed(max(0.,deadline-time.perf_counter()))
            except Exception as exc:errors.append('camera:'+type(exc).__name__)
            write(out/'CAMERA.json',dict(status=camera.status(),timings=camera.timing_report(),clean=camera_clean))
        if server is not None:
            try:
                if http is not None and http.is_alive():server.shutdown()
                server.server_close()
                if http is not None:http.join(max(0.,deadline-time.perf_counter()))
            except Exception as exc:errors.append('http:'+type(exc).__name__)
        cleanup=dict(qt_job=qt_proof,qt_finished=qt_finished,runtime=None if runtime is None else runtime.shutdown_status,
            reader_stopped=reader is None or not reader.is_alive(),http_stopped=http is None or not http.is_alive(),
            http_workers_idle=server is None or server._slots._value==server.config.max_http_workers,camera_clean=camera_clean,external_owner=peer_cleanup,navigation_owner=None if session is None else session.cleanup,
            nav_sdk_stopped=nav_thread is None or not nav_thread.is_alive(),external_observer_stopped=peer_cleanup_thread is None or not peer_cleanup_thread.is_alive(),
            shared_host_deadline=deadline,finished_within_shared_host_budget=time.perf_counter()<=deadline)
        write(out/'CLEANUP.json',cleanup)
    write(out/'QT_STAGES.json',stages)
    with (out/'TRACE.jsonl.gz').open('wb') as raw_stream:
        with gzip.GzipFile(filename='',mode='wb',fileobj=raw_stream,mtime=0) as stream:
            for row in rows:stream.write(json.dumps(row,allow_nan=False,separators=(',',':')).encode()+b'\n')
    independent=audit(rows);write(out/'AUDIT.json',independent)
    if backend is not None and initial is not None and runtime is not None:
        write(out/'EVAL.json',dict(source='isolated_world_evaluation_never_peer_input',initial=next(r for r in initial['robots'] if r['robot_id']==RID),
            final=next(r for r in runtime.cached['robots'] if r['robot_id']==RID)))
    qp=out/'qt/RESULT.json';qt=json.loads(qp.read_bytes()) if qp.is_file() else {}
    ros_path=out/'peer/ROS_SOURCE.jsonl';ros=[] if not ros_path.is_file() else [json.loads(line) for line in ros_path.read_text().splitlines()]
    navigation=audit_navigation_consumption(rows,ros);write(out/'NAV_AUDIT.json',navigation)
    def read_record(path):return json.loads(path.read_bytes()) if path.is_file() else {}
    goal=read_record(out/'peer/GOAL_REPORT.json');external=read_record(out/'peer/RESULT.json');gate=read_record(out/'session/PRODUCTION_GATE_STATUS.json')
    write(out/'PB_RESULT.json',dict(goal=goal,external=external,gate=gate))
    go=qt.get('stages',{}).get('go_wall');release=qt.get('stages',{}).get('release_wall')
    interval_ok=type(go) in (int,float) and type(release) in (int,float) and math.isfinite(go) and math.isfinite(release) and release-go>=args.seconds
    manual_steps=set();nav_steps=set()
    if interval_ok:
        for row in rows:
            if row.get('event') not in ('actuator_consumed','navigation_consumed') or not go<=row['consume_wall']<release:continue
            motion=row['target'].get('motion')
            if motion is None or not any(abs(motion[k])>1e-8 for k in ('vx_mps','vy_mps','wz_rps')):continue
            (nav_steps if row['event']=='navigation_consumed' else manual_steps).add(round(row['consume_sim_time']/.002))
    overlap=dict(original_host_GO=go,original_host_F12=release,interval_ok=interval_ok,manual_nonzero_steps=len(manual_steps),
        navigation_nonzero_steps=len(nav_steps),same_physical_step_both_nonzero=len(manual_steps & nav_steps),clock='same Windows host perf_counter; no Linux conversion')
    write(out/'OVERLAP.json',overlap)
    pb_identity=bool(session is not None and peer is not None and gate.get('schema')=='polar.pb.production-gate-status.v1'
        and gate.get('run_uuid')==session.run_uuid and gate.get('namespace')==session.namespace
        and external.get('schema')=='polar.pb.external-goal-result.v1' and external.get('run_uuid')==peer.run_uuid
        and external.get('session_run_uuid')==session.run_uuid and external.get('namespace')==session.namespace)
    checks=dict(actual_PB_identity=pb_identity,actual_PB_source_consumption=navigation['passed'],
        simultaneous_original_manual_and_PB=interval_ok and bool(manual_steps & nav_steps),
        actual_PB_active=gate.get('production_gate') is True and gate.get('stack_state')=='ACTIVE' and gate.get('errors')==[],
        actual_PB_estimation=all(type(gate.get(k)) is int and gate[k]>0 for k in ('map_messages','odometry_messages')),
        actual_external_goal_path=goal.get('schema')=='polar.sim.navigation-goal-scenario.v1' and goal.get('completed') is True and goal.get('lifecycle',{}).get('clean') is True,
        external_goal_not_input_or_lifecycle=external.get('sensor_published') is False and external.get('lifecycle_changed') is False,
        external_owned_cleanup=bool(peer_cleanup and peer_cleanup.get('clean')),
        nav_owned_cleanup=bool(session and session.cleanup and session.cleanup.get('clean')),
        shared_cleanup=cleanup['finished_within_shared_host_budget'] and cleanup['nav_sdk_stopped'] and cleanup['external_observer_stopped'],stages=[r['event'] for r in stages]==['qt_watch_ready','qt_plan_selected','qt_claimed_hud','qt_manual_armed'],
        actual_HTTP_image=(out/'qt/ACTUAL_QT_OFFSCREEN.png').is_file(),original_manual_inputs=qt.get('passed') is True,
        actual_batches=independent['manual_batch_count']>0,positive_physical=independent['positive_x_steps']>0,
        negative_physical=independent['negative_x_steps']>0,mouse_gimbal_physical=independent['nonzero_gimbal_steps']>0,
        exact_window_receipt_join=not independent['errors'],qt_sdk_clean=qt.get('clean') is True,
        original_Qt_job_clean=bool(qt_proof and qt_proof['clean'] and qt_proof['group_empty'] and qt_proof['reaped']),
        original_Qt_exit_zero=bool(qt_proof and qt_proof['returncode']==0),
        runtime_clean=bool(runtime and runtime.shutdown_status and runtime.shutdown_status['clean']),camera_clean=camera_clean is True,
        reader_http_clean=cleanup['reader_stopped'] and cleanup['http_stopped'] and cleanup['http_workers_idle'],errors_empty=not errors)
    return dict(passed=all(checks.values()),checks=checks,errors=errors,qt_errors=qt.get('errors',[]),physical=independent,navigation=navigation,overlap=overlap,relative_goal_completed=goal.get('completed') is True,goal_lifecycle=goal.get('lifecycle',{}),steps=None if runtime is None else runtime.steps,
        qualification='actual_offscreen_manual_infantry_real_PB_navigation_and_synthetic_source_bound_goal_hold_cancel_complete',
        limitations=['not visible desktop','no match decision tree or aiming/auto-fire/NN; PB is single-goal navigation only','not full match/long-term/performance qualification'])

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--out',type=Path);p.add_argument('--seconds',type=float,default=5.);p.add_argument('--max-wall-seconds',type=float,default=15.)
    p.add_argument('--client-root',type=Path,default=ROOT/'external/polar-rm-client-camera-order-review')
    p.add_argument('--patch-manifest',type=Path,default=ROOT/'client_patches/CLIENT_CAMERA_ORDER_PATCH_MANIFEST.json')
    p.add_argument('--client-python',type=Path,default=ROOT/'.venv-client/Scripts/python.exe')
    p.add_argument('--host-opencv-threads',type=int,choices=range(1,33));p.add_argument('--host-python-switch-interval-ms',type=float)
    p.add_argument('--environment',type=Path,required=True);p.add_argument('--stack-config',type=Path,required=True)
    p.add_argument('--run',action='store_true');args=p.parse_args(argv)
    args.environment=args.environment.absolute();args.stack_config=args.stack_config.absolute()
    if not math.isfinite(args.seconds) or not 5<=args.seconds<=30 or not math.isfinite(args.max_wall_seconds) or not args.seconds+5<=args.max_wall_seconds<=60:raise ValueError('bounded_probe_duration')
    from rm_match.deployment.launcher import check_client
    from rm_match.platform_v2.host_scheduling import PythonSwitchInterval
    switch=PythonSwitchInterval(args.host_python_switch_interval_ms)
    args.client_root=args.client_root.absolute();args.patch_manifest=args.patch_manifest.absolute();args.client_python=args.client_python.absolute()
    identity=check_client(args.client_root,patch_manifest=args.patch_manifest)
    plan=dict(client=identity,run_seconds=args.seconds,max_wall_seconds=args.max_wall_seconds,qualified=False,original_camera80ms=True,original_control150ms=True,
        scope='original Qt manual infantry alongside real PB navigation sentry; no aiming/match tree/full match',environment_sha256=digest(args.environment),stack_sha256=digest(args.stack_config),explicit_run_required=True)
    if not args.run:print(json.dumps(plan,indent=2));return 0
    if sys.platform!='win32' or args.out is None:raise RuntimeError('Windows_fresh_output_required')
    out=args.out.absolute()
    if out.exists() or out.resolve()!=out or not out.is_relative_to(ROOT/'artifacts'):raise ValueError('fresh_owned_output_required')
    out.mkdir();write(out/'COMMAND.json',dict(argv=sys.argv,plan=plan));snapshots=[]
    from rm_match.integrations.pb_wsl_navigation import SOURCE_FILES as PB_SOURCES
    from tools.qa_navigation_goal_client import SOURCE_FILES as EXTERNAL_SOURCES
    for name in sorted(set(SOURCE_FILES+PB_SOURCES+EXTERNAL_SOURCES)):
        source=ROOT/name;target=out/'source'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes());snapshots.append(dict(path=str(source),snapshot=str(target.relative_to(out)),sha256=digest(source)))
    for name in CLIENT_FILES:
        source=args.client_root/name;target=out/'client_source'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes());snapshots.append(dict(path=str(source),snapshot=str(target.relative_to(out)),sha256=digest(source)))
    (out/'CLIENT_PATCH_MANIFEST.json').write_bytes(args.patch_manifest.read_bytes());snapshots.append(dict(path=str(args.patch_manifest),snapshot='CLIENT_PATCH_MANIFEST.json',sha256=digest(args.patch_manifest)))
    for source in (args.environment,args.stack_config):
        target=out/source.name;target.write_bytes(source.read_bytes());snapshots.append(dict(path=str(source),snapshot=source.name,sha256=digest(source)))
    write(out/'SOURCE_MANIFEST.json',dict(files=snapshots));started=time.perf_counter();cv=None;record=dict(enabled=args.host_opencv_threads is not None,applied=False)
    try:
        if record['enabled']:
            import cv2 as cv
            record['original']=cv.getNumThreads();cv.setNumThreads(args.host_opencv_threads);record['applied']=True;record['effective']=cv.getNumThreads()
            if record['effective']!=args.host_opencv_threads:raise RuntimeError('cv_readback')
        with switch:result=run(out,args,identity)
    except BaseException as exc:
        result=dict(passed=False,error_type=type(exc).__name__);(out/'DRIVER_FAILURE.log').write_text(traceback.format_exc(),encoding='utf8')
    finally:
        if record['applied']:cv.setNumThreads(record['original']);record['restored']=cv.getNumThreads()
        write(out/'HOST_SCHEDULING.json',dict(opencv=record,python_switch=switch.record,scope='explicit owned current processes only; original clocks/deadlines unchanged'))
    unchanged=all(digest(row['path'])==row['sha256'] for row in snapshots)
    restored=(not record['enabled'] or record.get('restored')==record.get('original')) and (not switch.record['enabled'] or switch.record['restored'])
    result.update(source_unchanged=unchanged,host_scheduling_restored=restored,elapsed_s=time.perf_counter()-started)
    code=0 if result['passed'] and unchanged and restored else 2;result['exit_code']=code;write(out/'RESULT.json',result);print(json.dumps(dict(exit_code=code,out=str(out))));return code
if __name__=='__main__':raise SystemExit(main())
