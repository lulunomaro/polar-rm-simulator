#!/usr/bin/env python3
"""Bounded Windows NVIDIA/MuJoCo + explicit WSL native live diagnostic.

Default invocation prints the fixed plan without starting a renderer or process.
No offline clock, barrier, slower physics target or substituted sensor input.
"""
from __future__ import annotations
import argparse
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PLAN = dict(schema='polar.wsl.native.live-plan.v1',
    configuration=dict(robot_count=6, timestep_s=.002, resolution=[1440,1080],
        total_fps=15, active_views=1, real_time_factor_limit=1.,
        camera_native_budget_s=.08, server_input_window_s=.15, manual_fire=False,
        native_transport='wsl_stdio_v1',
        clock='Windows time.perf_counter, wall_deadline_live'),
    scene=dict(red_sentry_xy_m=[-3.5,3.], blue_infantry_xy_m=[-1.2,3.],
        initial_velocity='zero, remaining public analytic 3v3 scene unchanged',
        truth_boundary='Initial scene is audit-only; native input is actual BGR/calibration/own capture-state'),
    setup=dict(renderer_ready_bound_s=15., native_ready_bound_s=20.,
        before_timed_run='No capture, inference, physics or clock substitution during startup'),
    measurement=dict(seconds_min=10., seconds_max=20., include_first_capture=True,
        stages=['exposure_to_raw_encode_end', 'raw_encode_end_to_adapter_enqueue',
            'adapter_enqueue_to_native_request', 'native_request_to_native_result',
            'native_result_to_actuator_consume', 'exposure_to_actuator_consume'],
        distributions=['sample_count','p50_ms','p95_ms','p99_ms','max_ms'],
        logging='In-memory small event records; first actuator receipt per source frame, all phase counters'),
    criteria=dict(minimum_physics_rtf=.98, minimum_raw_frames=30,
        minimum_native_results=10, minimum_distinct_native_actuated_frames=10,
        all_raw_encode_ages_at_most_s=.08, all_native_result_ages_at_most_s=.08,
        all_actuator_wall_and_sim_ages_at_most_s=.08,
        exact_render_native_pixel_binding=True, source_unchanged=True,
        reviewed_sdk_admission_and_window_ack=True, clean_shutdown=True),
    scope='Bounded public-static-scene live diagnostic only; not full-match, aim accuracy, GUI or hardware qualification')


def build_plan(transport):
    if transport not in ('wsl_stdio_v1','wsl_stdio_bgr_v2'):raise ValueError('Explicit reviewed transport required')
    plan=copy.deepcopy(PLAN)
    plan['configuration']['native_transport']=transport
    return plan


def distribution(values):
    values = sorted(values)
    def percentile(fraction):
        if not values:return None
        pos=(len(values)-1)*fraction;low=int(pos);high=min(low+1,len(values)-1)
        return (values[low]+(values[high]-values[low])*(pos-low))*1000
    return dict(sample_count=len(values),p50_ms=percentile(.5),p95_ms=percentile(.95),
        p99_ms=percentile(.99),max_ms=None if not values else values[-1]*1000,
        within_80ms_count=sum(0<=v<=.08 for v in values))


def expected_shutdown_rejection(error, runtime, client_error_type):
    """Only the server's exact terminal rejection after actual stop is expected."""
    return (isinstance(error,client_error_type) and getattr(error,'code',None)=='runtime_stopped'
        and getattr(runtime,'_closed',False) is True and runtime.stop_event.is_set()
        and runtime.control.stopped is True)


def image_stage_summary(events):
    """Timing fields coexist with converter/clock metadata in real telemetry."""
    samples={}
    for event in events:
        if event['event']=='native_frame_prepare':
            for stage,duration in event.get('image_stages',{}).items():
                if stage.endswith('_s') and type(duration) in (int,float):
                    samples.setdefault(stage,[]).append(duration)
    return {stage:distribution(values) for stage,values in samples.items()}


def classify(measurements,*,plan=None):
    """Late/rejected results and empty measurements never establish live pass."""
    plan=PLAN if plan is None else plan
    c=plan['criteria'];m=measurements
    checks=dict(configuration_unchanged=m.get('configuration')==plan['configuration'],
        bounded_real_wall_run=type(m.get('duration_s')) in (int,float) and 10<=m['duration_s']<=20.5,
        physics_rtf=type(m.get('physics_rtf')) in (int,float) and m['physics_rtf']>=c['minimum_physics_rtf'],
        raw_sample_count=m.get('raw_frames',0)>=c['minimum_raw_frames'],
        native_sample_count=m.get('native_results',0)>=c['minimum_native_results'],
        no_sticky_adapter_fault=m.get('adapter_error_count')==0,
        all_native_requests_completed=m.get('incomplete_native_requests')==0,
        actual_evidence_preserved=m.get('native_evidence_closed') is True,
        actual_native_actuation=m.get('distinct_native_actuated_frames',0)>=c['minimum_distinct_native_actuated_frames'],
        native_sensor_budget_80ms=m.get('native_sensor_budget_80ms') is True,
        actual_transport_matches_plan=m.get('actual_transport_matches_plan') is True,
        exact_sensor_pixel_binding=m.get('exact_sensor_pixel_binding') is True,
        source_unchanged=m.get('source_unchanged') is True,
        sdk_admission=m.get('sdk_admission') is True,
        window_acknowledged=m.get('window_acknowledged') is True,
        zero_fire=m.get('fire_true')==0,
        clean_shutdown=m.get('clean_shutdown') is True,
        runtime_error_free=not m.get('errors'))
    for key in ('raw_ages_s','native_result_ages_s','actuator_wall_ages_s','actuator_sim_ages_s'):
        values=m.get(key,[])
        checks[key]=bool(values) and all(type(v) in (int,float) and 0<=v<=.08 for v in values)
    return dict(checks=checks,live_static_chain_qualified=all(checks.values()),
        full_match_qualified=False,hardware_qualified=False,visible_qt_qualified=False,
        rejected_or_failed_criteria=[k for k,v in checks.items() if not v])


def stage_measurements(events, raw_frames, consumed_frames):
    """Join only host-clock source frame identities; never use Linux clock values."""
    enqueues={};requests={};results={};stages={k:[] for k in PLAN['measurement']['stages']}
    matched=True
    for event in events:
        kind=event['event']
        if kind=='adapter_enqueue':
            budget=event.get('sensor_budget')
            if budget:enqueues[event['observed_seq']]=event
        elif kind=='native_request':requests[event['frame_id']]=event
        elif kind=='native_result':results[event['frame_id']]=event
    for frame_id,request in requests.items():
        raw=raw_frames.get(frame_id)
        if raw is None or raw['raw_rgb_sha256']!=request['raw_rgb_sha256']:
            matched=False
        enqueue=enqueues.get(request['observed_seq'])
        if enqueue and enqueue['sensor_budget']['frame_id']!=frame_id:matched=False
        result=results.get(frame_id)
        if raw and enqueue:
            stages['raw_encode_end_to_adapter_enqueue'].append(enqueue['host_received_wall']-raw['encoded_wall'])
        if enqueue:
            stages['adapter_enqueue_to_native_request'].append(request['host_received_wall']-enqueue['host_received_wall'])
        if result:
            stages['native_request_to_native_result'].append(result['host_received_wall']-request['host_received_wall'])
        consume=consumed_frames.get(frame_id)
        if result and consume:
            stages['native_result_to_actuator_consume'].append(consume['consume_wall']-result['host_received_wall'])
    for raw in raw_frames.values():
        stages['exposure_to_raw_encode_end'].append(raw['encoded_wall']-raw['capture_wall'])
    for consume in consumed_frames.values():
        stages['exposure_to_actuator_consume'].append(consume['consume_wall']-consume['budget']['capture_wall'])
    native_ages=[]
    for frame_id,result in results.items():
        request=requests.get(frame_id);raw=raw_frames.get(frame_id)
        if request is None or raw is None or result['raw_rgb_sha256']!=request['raw_rgb_sha256']:
            matched=False
        if raw:native_ages.append(result['host_received_wall']-raw['capture_wall'])
    return dict(stages={k:distribution(v) for k,v in stages.items()},
        stage_samples_s=stages, exact_sensor_pixel_binding=matched and bool(requests),
        raw_ages_s=stages['exposure_to_raw_encode_end'],native_result_ages_s=native_ages,
        actuator_wall_ages_s=[x['consume_wall']-x['budget']['capture_wall'] for x in consumed_frames.values()],
        actuator_sim_ages_s=[x['consume_sim_time']-x['budget']['capture_sim_time'] for x in consumed_frames.values()])


def fault_and_evidence_measurements(events, counts, *, writer_required):
    errors=sum(x['event']=='adapter_result' and bool(x.get('error')) for x in events)
    incomplete=counts.get('native_request',0)-counts.get('native_result',0)
    statuses=[x.get('status') for x in events if x['event']=='native_evidence_closed']
    evidence_clean=(not writer_required and not statuses) or (bool(statuses) and all(
        type(s) is dict and s.get('clean') is True and s.get('written')==s.get('submitted')
        and type(s.get('written')) is int and s.get('failed')==0 and s.get('worker_alive') is False
        for s in statuses))
    return dict(adapter_error_count=errors,incomplete_native_requests=incomplete,
        native_evidence_closed=bool(evidence_clean),native_evidence_shutdown_statuses=statuses,
        native_evidence_writer_required=writer_required)


def run(a):
    if sys.platform!='win32':raise RuntimeError('Actual Windows host required for NVIDIA live diagnostic')
    from rm_match.deployment.launcher import check_client
    from rm_match.deployment.enrollment import provision_operator
    from rm_match.deployment.wsl_profile import own_wsl_registry
    from rm_match.platform_v2.admission import AdmissionPolicy
    from rm_match.platform_v2.backend import MuJoCoBackend
    from rm_match.platform_v2.camera import CameraProvider,MuJoCoCameraRenderer
    from rm_match.platform_v2.runtime import PlatformRuntime
    from rm_match.platform_v2.server import PlatformHTTPServer,TransportConfig
    from rm_match.match_model import SPAWNS
    import mujoco
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    plan=build_plan(a.native_transport)
    def write(name,value):
        (out/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    sources={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT/'rm_match').rglob('*.py')}
    sources[Path(__file__).relative_to(ROOT).as_posix()]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    write('EXECUTED_SOURCE.json',sources);write('PLAN.json',plan)
    identity=check_client(a.client_root)
    write('CLIENT_IDENTITY.json',identity)
    sys.path.insert(0,str(a.client_root.resolve()))
    from rm_client.sim_platform_client import PlatformClient,ClientError
    credential=provision_operator(out/'admission.json')
    backend=MuJoCoBackend(camera=True);sim=backend._sim
    if len(backend.robot_ids)!=6 or backend.timestep!=.002:raise RuntimeError('Six-car dt2ms required')
    for rid,x,y in [('red_sentry',-3.5,3.),('blue_infantry',-1.2,3.)]:
        sim.data.qpos[sim.qindices[rid][0]]=x-SPAWNS[rid][0]
        sim.data.qpos[sim.qindices[rid][1]]=y-SPAWNS[rid][1]
    sim.data.qvel[:]=0;mujoco.mj_forward(sim.model,sim.data)
    write('PUBLIC_INITIAL_SCENE.json',dict(origin='Explicit public static test only; never native DTO',qpos=sim.data.qpos.tolist()))
    events=[];raw={};consumed={};counts=Counter();errors=[];ready=threading.Event();renderer_errors=[]
    def trace(row):
        event=row['event'];counts[event]+=1
        now=time.perf_counter()
        if event=='physics_apply':
            counts['fire_true']+=sum(bool(t['fire']) for t in row['targets'].values())
            return
        if event=='integration_boundary':return
        if row.get('robot_id','red_sentry')!='red_sentry':return
        if event=='actuator_consumed':
            target=row['target'];budget=row.get('budget')
            if target.get('gimbal') is None or budget is None:return
            counts['native_actuator_receipts']+=1
            wall_age=row['consume_wall']-budget['capture_wall']
            sim_age=row['consume_sim_time']-budget['capture_sim_time']
            if not (0<=wall_age<=.08 and 0<=sim_age<=.08):counts['stale_actuator_receipts']+=1
            frame_id=budget['frame_id']
            if frame_id not in consumed:
                value=dict(row,host_received_wall=now,
                    actual_qpos=sim.data.qpos[sim.qindices['red_sentry']].tolist(),
                    actual_actuator_ctrl=sim.data.ctrl[sim.aindices['red_sentry']].tolist())
                consumed[frame_id]=value;events.append(value)
            return
        events.append(dict(row,host_received_wall=now))
    class Render(MuJoCoCameraRenderer):
        def __init__(self,*args):
            try:
                super().__init__(*args)
                if 'NVIDIA' not in str(self.identity):raise RuntimeError('Actual NVIDIA GL required')
            except BaseException as exc:
                renderer_errors.append(type(exc).__name__+':'+str(exc));raise
            finally:ready.set()
    class Camera(CameraProvider):
        def _encode(self,cap,rgb):
            value=super()._encode(cap,rgb)
            raw[cap.frame_seq]=dict(frame_id=cap.frame_seq,capture_wall=cap.wall_time,
                capture_sim_time=cap.sim_time,encoded_wall=value['encoded_wall'],
                raw_rgb_sha256=hashlib.sha256(rgb.tobytes()).hexdigest(),shape=list(rgb.shape))
            return value
    camera=Camera(sim,clock=time.perf_counter,total_fps=15,max_views=1,renderer_factory=Render)
    registry=own_wsl_registry(a.linux_native_spec,out/'native',repo_root=ROOT,
        distribution=a.distribution,native_trace=trace,transport=a.native_transport)
    runtime=PlatformRuntime(backend,camera=camera,registry=registry,clock=time.perf_counter,trace=trace)
    server=PlatformHTTPServer(TransportConfig(port=0,admission_policy=AdmissionPolicy.from_manifest(out/'admission.json')),runtime)
    http=threading.Thread(target=server.serve_forever,daemon=True)
    client=None;physics=None;native=None;native_process=None;sdk_events=[];timing={};sdk_admitted=False;window_acked=False
    setup=time.perf_counter()
    try:
        camera.start()
        if not ready.wait(15.) or renderer_errors:raise RuntimeError('Renderer readiness failed: '+str(renderer_errors))
        native=registry.prepare_native(dict(fov_degrees=180.,circle_radius_x_norm=1.,circle_radius_y_norm=1.))
        native_process=native.process
        if camera.capture_count or camera.raw_published or sim.time or counts['native_request']:
            raise RuntimeError('Capture/inference/physics before live readiness')
        write('STARTUP_ADMISSION.json',dict(setup_s=time.perf_counter()-setup,
            captures=0,native_requests=0,physics_time_s=0,renderer=camera.renderer_identity))
        http.start()
        client=PlatformClient('http://127.0.0.1:'+str(server.server_address[1]),
            timeout=.25,control_profile='server_window_v1',admission_credential=credential)
        client.open('operator');client.watch('red_sentry');client.claim('red_sentry',['gimbal'])
        bound=client.bind('red_sentry','aim','aim_native_rmcs_v1',
            dict(fov_degrees=180.,circle_radius_x_norm=1.,circle_radius_y_norm=1.))
        sdk_admitted=True
        def activate():
            nonlocal window_acked
            window=client.control_window('red_sentry',['gimbal'])
            ack=client.adapter_input('red_sentry','aim',bound['binding_epoch'],window_id=window['window_id'],valid_for_s=.15)
            window_acked=True;sdk_events.append(dict(event='activation_ack',host_wall=time.perf_counter(),
                window_id=window['window_id'],activation_expires=ack['activation_expires']))
        activate()
        def authority():
            timing['start']=time.perf_counter()
            timing['cpu_start']=time.process_time()
            try:runtime.run(max_wall_seconds=a.seconds,real_time_factor=1.)
            except BaseException as exc:errors.append(type(exc).__name__+':'+str(exc))
            finally:
                timing['end']=time.perf_counter()
                timing['cpu_end']=time.process_time()
        physics=threading.Thread(target=authority,name='live-physics-authority',daemon=True);physics.start()
        start=time.perf_counter();renew=start;sample=start
        while physics.is_alive() and time.perf_counter()-start<a.seconds:
            activate()
            now=time.perf_counter()
            if now-renew>=.25:client.renew('red_sentry',['gimbal']);renew=now
            if now-sample>=.2:
                state=client.state();sample=now
                sdk_events.append(dict(event='operator_status',host_wall=now,
                    algorithm_status=state.get('algorithm_status'),runtime_state=state.get('runtime_state')))
            time.sleep(.04)
        client.release('red_sentry',['gimbal']);client.close();client=None
    except BaseException as exc:
        if expected_shutdown_rejection(exc,runtime,ClientError):
            sdk_events.append(dict(event='expected_runtime_stopped',phase='terminal_sdk_request',
                host_wall=time.perf_counter(),remote_session_close_ack=False))
        else:errors.append(type(exc).__name__+':'+str(exc))
    finally:
        def cleanup(label,function):
            try:return function()
            except BaseException as exc:errors.append(label+': '+type(exc).__name__+':'+str(exc));return None
        cleanup('runtime_stop',runtime.request_stop)
        if physics is not None:cleanup('physics_join',lambda:physics.join(4.))
        else:cleanup('runtime_close_before_first_job',runtime.close)
        # The registry retains a prewarmed adapter until the first slot claims it.
        # Runtime closes claimed slots; the registry closes an unclaimed preload.
        cleanup('registry_close',registry.close)
        if client is not None:
            try:client.close()
            except BaseException as exc:
                if expected_shutdown_rejection(exc,runtime,ClientError):
                    sdk_events.append(dict(event='expected_runtime_stopped',phase='terminal_sdk_close',
                        host_wall=time.perf_counter(),remote_session_close_ack=False))
                else:errors.append('SDK_close: '+type(exc).__name__+':'+str(exc))
        cleanup('camera_stop',camera.stop)
        camera_closed=cleanup('camera_join',lambda:camera.wait_closed(4.)) is True
        if http.is_alive():cleanup('HTTP_shutdown',server.shutdown)
        cleanup('HTTP_close',server.server_close)
        if http.is_alive():cleanup('HTTP_join',lambda:http.join(2.))
    # Persist actual execution before any derived report/percentile calculation.
    # Report errors must never erase the native/physics/SDK source evidence.
    write('FRAME_BINDINGS.json',raw);write('SDK_EVENTS.json',sdk_events)
    (out/'ledger.jsonl').write_text(''.join(json.dumps(x,allow_nan=False)+'\n' for x in events),encoding='utf-8')
    write('RUNTIME_OBSERVATION.json',dict(counts=dict(counts),camera=camera.status(),
        camera_closed=camera_closed,physics_thread_alive=physics is not None and physics.is_alive(),
        shutdown_status=getattr(runtime,'shutdown_status',None),runtime_error=runtime.error,
        sim_time=sim.time,timing=timing,errors=errors))
    elapsed=timing.get('end',time.perf_counter())-timing.get('start',time.perf_counter())
    clean=(camera_closed and not http.is_alive() and (physics is None or not physics.is_alive())
        and getattr(runtime,'shutdown_status',{}).get('clean') is True)
    source_unchanged=all((ROOT/p).is_file() and hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in sources.items())
    if counts['stale_actuator_receipts']:errors.append('Stale actuator consumption')
    budgets=[x['sensor_budget'] for x in events if x['event']=='adapter_enqueue' and x.get('sensor_budget')]
    native_budget_ok=bool(budgets) and all(0< b['wall_deadline']-b['capture_wall']<=.08+1e-9
        and 0< b['sim_deadline']-b['capture_sim_time']<=.08+1e-9 for b in budgets)
    transport_evidence={}
    evidence_out=getattr(native_process,'evidence_out',None)
    if evidence_out is not None:
        for name in ('STARTUP.json','CLEANUP.json','HOST_TRACE.json','SUPERVISOR_ERROR.json'):
            path=Path(evidence_out)/name
            if path.is_file():transport_evidence[name]=json.loads(path.read_text(encoding='utf-8'))
    actual_transport=(transport_evidence.get('STARTUP.json') or {}).get('transport')
    measured=dict(configuration=plan['configuration'],duration_s=elapsed,
        physics_rtf=sim.time/elapsed if elapsed>0 else 0,raw_frames=len(raw),
        native_results=counts['native_result'],distinct_native_actuated_frames=len(consumed),
        source_unchanged=source_unchanged,sdk_admission=sdk_admitted,window_acknowledged=window_acked,
        native_sensor_budget_80ms=native_budget_ok,
        actual_transport_matches_plan=actual_transport==a.native_transport,
        fire_true=counts['fire_true'],clean_shutdown=clean,errors=errors,
        **fault_and_evidence_measurements(events,counts,
            writer_required=getattr(native,'_evidence_required',False)),
        **stage_measurements(events,raw,consumed))
    rejects=Counter()
    for event in events:
        if event['event']=='adapter_result':
            if event.get('error'):rejects['adapter_error:'+event['error']]+=1
            if event['host_received_wall']>=event['wall_deadline']:rejects['adapter_result_after_deadline']+=1
        elif event['event']=='adapter_sample_rejected':
            rejects['adapter_sample:'+str(event.get('reason','expired'))]+=1
    rejects['raw_encode_over_80ms']=sum(x>.08 for x in measured['raw_ages_s'])
    rejects['native_result_over_80ms']=sum(x>.08 for x in measured['native_result_ages_s'])
    rejects['stale_actuator_receipts']=counts['stale_actuator_receipts']
    rejects['camera_dropped']=camera.dropped
    report=dict(schema='polar.wsl.native.live-result.v1',measurements=measured,
        host_process_cpu=dict(seconds=None if 'cpu_start' not in timing or 'cpu_end' not in timing else timing['cpu_end']-timing['cpu_start'],
            clock='process_time',scope='All Windows process threads during runtime.run including cleanup; excludes setup and WSL native child'),
        classification=classify(measured,plan=plan),counts=dict(counts),rejects=dict(rejects),camera=camera.status(),
        camera_timings=camera.timing_report(),shutdown_status=getattr(runtime,'shutdown_status',None),
        client_identity=identity,linux_spec_sha256=hashlib.sha256(a.linux_native_spec.read_bytes()).hexdigest(),
        environment={k:os.environ.get(k) for k in ('MUJOCO_GL','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')},
        native_process_diagnostic=getattr(native_process,'diagnostics',None),
        native_transport_evidence=transport_evidence,
        image_preparation=image_stage_summary(events),
        native_identity=None if native_process is None else native_process.checked.metadata,
        native_spec=None if native_process is None else native_process.checked.linux_spec,
        scope=PLAN['scope'])
    write('RESULT.json',report)
    print(json.dumps(report['classification'],indent=2))
    return 0 if report['classification']['live_static_chain_qualified'] else 2


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--linux-native-spec','--native-spec',dest='linux_native_spec',type=Path)
    p.add_argument('--distribution',default='Ubuntu')
    p.add_argument('--native-transport',choices=('wsl_stdio_v1','wsl_stdio_bgr_v2'),default='wsl_stdio_v1')
    p.add_argument('--client-root',type=Path)
    p.add_argument('--out',type=Path)
    p.add_argument('--seconds',type=float,default=10.)
    p.add_argument('--run',action='store_true')
    a=p.parse_args(argv)
    if not 10<=a.seconds<=20:p.error('Actual run must be bounded to 10..20 wall seconds')
    if not a.run:
        print(json.dumps(build_plan(a.native_transport),indent=2));return 0
    for key in ('linux_native_spec','client_root','out'):
        if getattr(a,key) is None:p.error('--'+key.replace('_','-')+' is required with --run')
        setattr(a,key,getattr(a,key).resolve())
    if a.out.exists():p.error('Fresh output directory required; preserved evidence is never overwritten')
    try:return run(a)
    except BaseException as exc:
        # Errors before resource construction still leave an honest bounded
        # setup record. Resource-owning code above attempts every cleanup.
        a.out.mkdir(parents=True,exist_ok=True)
        (a.out/'REPORT_EXCEPTION.txt').write_text(traceback.format_exc(),encoding='utf-8')
        admitted=(a.out/'STARTUP_ADMISSION.json').exists()
        value=dict(schema='polar.wsl.native.live-failure.v2',
            state='AFTER_STARTUP_FAILURE' if admitted else 'SETUP_FAILED',
            startup_admitted=admitted,runtime_evidence_available=(a.out/'RUNTIME_OBSERVATION.json').exists(),
            errors=[type(exc).__name__+':'+str(exc)],live_static_chain_qualified=False,
            cleanup_qualified=False,plan=build_plan(a.native_transport))
        (a.out/'RESULT.json').write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(value,indent=2));return 2


if __name__=='__main__':
    raise SystemExit(main())
