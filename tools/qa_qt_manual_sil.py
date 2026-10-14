"""Opt-in original Qt keyboard/mouse/HTTP camera/manual SDK/MuJoCo SIL."""
from __future__ import annotations
import argparse,copy,gzip,hashlib,json,math,os,secrets,sys,threading,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
RID='red_infantry'
SOURCE_FILES=('tools/qa_qt_manual_sil.py','tools/qa_qt_manual_peer.py','tools/audit_qt_manual.py',
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
    rows=[];lock=threading.Lock();errors=[];stages=[];child=reader=stderr=http=server=backend=camera=runtime=None
    qt_ready=qt_finished=qt_proof=None;camera_clean=None;budget=SharedCleanupBudget();initial=None
    def retain(row):
        with lock:
            if len(rows)>=50000:raise RuntimeError('manual_trace_capacity')
            rows.append(copy.deepcopy(row))
    try:
        backend=MuJoCoBackend(camera=True);initial=backend.display_snapshot()
        camera=CameraProvider(backend._sim,total_fps=15,max_views=1)
        def trace(row):
            if row.get('robot_id')==RID and row['event']=='actuator_consumed' and row['phase']=='integration_entry':retain(row)
        runtime=PlatformRuntime(backend,camera=camera,trace=trace,action_ttl=.15)
        credential=secrets.token_urlsafe(32)
        policy=AdmissionPolicy([dict(credential_sha256=hashlib.sha256(credential.encode()).hexdigest(),role='operator',allowed_robots=[RID],audit_authorized=False)])
        server=PlatformHTTPServer(TransportConfig(port=0,admission_policy=policy),runtime)
        http=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},name='manual-sil-http');http.start()
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
                            qt_ready=row;child.stdin.write(b'{"op":"go"}\n');child.stdin.flush()
                    elif event=='sdk_manual_batch':
                        if set(row)!={'event','robot_id','window','request','ack','entered_host_wall','returned_host_wall'} or row['robot_id']!=RID:raise RuntimeError('manual_batch_event')
                        retain(row)
                    elif event=='qt_finished':
                        if set(row)!={'event','clean','errors','exit_code'} or qt_finished is not None:raise RuntimeError('manual_finish_identity')
                        qt_finished=row;runtime.request_stop()
                    else:raise RuntimeError('unknown_manual_event')
            except BaseException as exc:
                errors.append('reader:'+type(exc).__name__);runtime.request_stop()
        reader=threading.Thread(target=collect,name='manual-sil-reader');reader.start()
        runtime.run(max_wall_seconds=args.max_wall_seconds,real_time_factor=1.)
        if qt_ready is None or qt_finished is None:raise RuntimeError('manual_run_incomplete')
    except BaseException as exc:
        errors.append(type(exc).__name__);(out/'FAILURE.log').write_text(traceback.format_exc(),encoding='utf8')
    finally:
        deadline=budget.claim()
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
            http_workers_idle=server is None or server._slots._value==server.config.max_http_workers,camera_clean=camera_clean)
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
    checks=dict(stages=[r['event'] for r in stages]==['qt_watch_ready','qt_plan_selected','qt_claimed_hud','qt_manual_armed'],
        actual_HTTP_image=(out/'qt/ACTUAL_QT_OFFSCREEN.png').is_file(),original_manual_inputs=qt.get('passed') is True,
        actual_batches=independent['manual_batch_count']>0,positive_physical=independent['positive_x_steps']>0,
        negative_physical=independent['negative_x_steps']>0,mouse_gimbal_physical=independent['nonzero_gimbal_steps']>0,
        exact_window_receipt_join=not independent['errors'],qt_sdk_clean=qt.get('clean') is True,
        original_Qt_job_clean=bool(qt_proof and qt_proof['clean'] and qt_proof['group_empty'] and qt_proof['reaped']),
        original_Qt_exit_zero=bool(qt_proof and qt_proof['returncode']==0),
        runtime_clean=bool(runtime and runtime.shutdown_status and runtime.shutdown_status['clean']),camera_clean=camera_clean is True,
        reader_http_clean=cleanup['reader_stopped'] and cleanup['http_stopped'] and cleanup['http_workers_idle'],errors_empty=not errors)
    return dict(passed=all(checks.values()),checks=checks,errors=errors,qt_errors=qt.get('errors',[]),physical=independent,steps=None if runtime is None else runtime.steps,
        qualification='actual_offscreen_original_keyboard_mouse_camera_manual_SDK_MuJoCo_only',
        limitations=['not visible desktop','no team navigation/decision/aim or NN/ROS','not full match/long-term/performance qualification'])

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--out',type=Path);p.add_argument('--seconds',type=float,default=5.);p.add_argument('--max-wall-seconds',type=float,default=15.)
    p.add_argument('--client-root',type=Path,default=ROOT/'external/polar-rm-client-robotio-batch-review')
    p.add_argument('--patch-manifest',type=Path,default=ROOT/'client_patches/CLIENT_ROBOTIO_BATCH_PATCH_MANIFEST.json')
    p.add_argument('--client-python',type=Path,default=ROOT/'.venv-client/Scripts/python.exe')
    p.add_argument('--host-opencv-threads',type=int,choices=range(1,33));p.add_argument('--host-python-switch-interval-ms',type=float)
    p.add_argument('--run',action='store_true');args=p.parse_args(argv)
    if not math.isfinite(args.seconds) or not 5<=args.seconds<=30 or not math.isfinite(args.max_wall_seconds) or not args.seconds+5<=args.max_wall_seconds<=60:raise ValueError('bounded_probe_duration')
    from rm_match.deployment.launcher import check_client
    from rm_match.platform_v2.host_scheduling import PythonSwitchInterval
    switch=PythonSwitchInterval(args.host_python_switch_interval_ms)
    args.client_root=args.client_root.absolute();args.patch_manifest=args.patch_manifest.absolute();args.client_python=args.client_python.absolute()
    identity=check_client(args.client_root,patch_manifest=args.patch_manifest)
    plan=dict(client=identity,run_seconds=args.seconds,max_wall_seconds=args.max_wall_seconds,qualified=False,original_camera80ms=True,original_control150ms=True,
        scope='original Qt keyboard/mouse/HTTP camera/manual actuator consumption; no algorithm/match',explicit_run_required=True)
    if not args.run:print(json.dumps(plan,indent=2));return 0
    if sys.platform!='win32' or args.out is None:raise RuntimeError('Windows_fresh_output_required')
    out=args.out.absolute()
    if out.exists() or out.resolve()!=out or not out.is_relative_to(ROOT/'artifacts'):raise ValueError('fresh_owned_output_required')
    out.mkdir();write(out/'COMMAND.json',dict(argv=sys.argv,plan=plan));snapshots=[]
    for name in SOURCE_FILES:
        source=ROOT/name;target=out/'source'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes());snapshots.append(dict(path=str(source),snapshot=str(target.relative_to(out)),sha256=digest(source)))
    for name in CLIENT_FILES:
        source=args.client_root/name;target=out/'client_source'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes());snapshots.append(dict(path=str(source),snapshot=str(target.relative_to(out)),sha256=digest(source)))
    (out/'CLIENT_PATCH_MANIFEST.json').write_bytes(args.patch_manifest.read_bytes());snapshots.append(dict(path=str(args.patch_manifest),snapshot='CLIENT_PATCH_MANIFEST.json',sha256=digest(args.patch_manifest)))
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
