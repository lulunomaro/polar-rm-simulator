"""Read one existing failed actual request; no benchmark or process launch."""
from pathlib import Path
import hashlib
import json
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
INPUT=ROOT/'artifacts/wsl-native-live-20261014-prepared-bgr-attempt3'
BUILD=ROOT/'artifacts/native-original-nav-checkpoint-build-20261013'
SOURCE=('rm_match/integrations/wsl_operator.py', 'rm_match/integrations/wsl_operator_pipe.py',
        'rm_match/integrations/wsl_operator_pipe_worker.py', 'rm_match/platform_v2/native_adapter.py',
        'rm_match/platform_v2/wsl_native_adapter.py', 'rm_match/platform_v2/native_image.py',
        'tools/smoke_wsl_native_live.py')


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def load(path):return json.loads(path.read_bytes())


def main():
    began=time.perf_counter()
    supervisor=next(INPUT.glob('native/binding_*/wsl_pipe_supervisor_*'))
    files=[INPUT/n for n in ('RESULT.json','EXECUTED_SOURCE.json','FRAME_BINDINGS.json',
        'ledger.jsonl','POST_CLOSE_PIXEL_AUDIT.json','STARTUP_ADMISSION.json','RAW_CODEC_IDENTITY.json')]
    files.extend(x for x in supervisor.iterdir() if x.is_file())
    image=next(INPUT.glob('native/binding_*/actual_frames/sensor_8.bgr'))
    image_manifest=image.with_suffix('.json');files.extend((image,image_manifest))
    files.extend(INPUT.glob('native/host_spec_*.json'))
    before={str(p.relative_to(INPUT)):sha(p) for p in files}
    source_before={n:sha(ROOT/n) for n in SOURCE}
    executed=load(INPUT/'EXECUTED_SOURCE.json')
    phases=load(supervisor/'HOST_TRACE.json');error=load(supervisor/'SUPERVISOR_ERROR.json')
    startup=load(supervisor/'STARTUP.json');cleanup=load(supervisor/'CLEANUP.json')
    child=load(supervisor/'OWNED_CHILD.json');worker=load(supervisor/'WORKER_STARTUP.json')
    events=[json.loads(x) for x in (INPUT/'ledger.jsonl').read_text().splitlines()]
    request=next(x for x in events if x['event']=='native_request')
    frame=request['frame_id'];seq=request['observed_seq']
    pub=next(x for x in events if x['event']=='private_pixels_published' and x['frame_id']==frame)
    encoded=next(x for x in events if x['event']=='public_base64_complete' and x['frame_id']==frame)
    enqueue=next(x for x in events if x['event']=='adapter_enqueue' and x['observed_seq']==seq)
    prepare=next(x for x in events if x['event']=='native_frame_prepare' and x['frame_id']==frame)
    result=next(x for x in events if x['event']=='adapter_result' and x['observed_seq']==seq)
    bridge=next(x for x in phases if x['event']=='control_prepare')
    bridge_request=next(x for x in phases if x['event']=='native_request')
    cap=enqueue['sensor_budget']['capture_wall'];deadline=request['wall_deadline']
    image_data=image.read_bytes();manifest=load(image_manifest)
    post=load(INPUT/'POST_CLOSE_PIXEL_AUDIT.json')
    build_manifest=load(BUILD/'BUILD_MANIFEST.json')
    main_path=BUILD/'generated/main.cpp'
    main_sha=sha(main_path)
    main_pinned=build_manifest['input_identity']['generated_sha256']['generated/main.cpp']
    linux=error['linux_stages_s']
    identity_fields=('run_id','supervisor_pid','boot_id','pid','pgid','leader_start_ticks')
    report=dict(schema='polar.prepared-bgr.first-request-readonly.v1',
        scope='Saved first actual control request, no microbenchmark/WSL/ROS/NN/GL',
        input=str(INPUT),input_sha256=before,source_sha256=source_before,
        selected_sources_match_actual_snapshot=all(executed[n]==h for n,h in source_before.items()),
        original_identity={k:request[k] for k in ('robot_id','episode','binding_epoch','observed_seq','frame_id','capture_sim_time','observation_sim_time','wall_deadline')},
        exposure_timestamp_ns_from_source_round=round(request['capture_sim_time']*1e9),
        exposure_integer_scope='Derived by the exact pinned native_adapter frame construction; full stdin JSON bytes were not archived.',
        actual_control_time_ns=bridge_request['control_time_ns'],
        host_timeline=dict(capture=cap,private_publication=pub['wall_time'],public_complete=encoded['wall_time'],
            adapter_enqueue=enqueue['wall_time'],adapter_started=result['started_wall'],native_frame_prepare=prepare['wall_time'],
            adapter_native_request=request['wall_time'],bridge_prepare=bridge['host_perf_counter'],
            bridge_native_request=bridge_request['host_perf_counter'],original_deadline=deadline,
            adapter_completed=result['completed_wall'],runtime_collect=result['wall_time']),
        host_durations_ms=dict(original_capture_budget=(deadline-cap)*1000,
            capture_to_private=(pub['wall_time']-cap)*1000,
            private_to_enqueue=(enqueue['wall_time']-pub['wall_time'])*1000,
            enqueue_to_adapter_native_request=(request['wall_time']-enqueue['wall_time'])*1000,
            capture_to_bridge_request=(bridge_request['host_perf_counter']-cap)*1000,
            bridge_prepare_remaining_recorded=bridge['remaining_host_budget_s']*1000,
            bridge_request_remaining=(deadline-bridge_request['host_perf_counter'])*1000,
            adapter_completed_after_original_deadline=(result['completed_wall']-deadline)*1000),
        image_prepare_stages=prepare['image_stages'],host_bridge_prepare=bridge,
        linux_stages_s=linux,linux_stage_sum_ms=sum(linux.values())*1000,
        linux_error=error,host_exception_diagnostic=result['exception_diagnostic'],
        bgr_identity=dict(bytes=len(image_data),actual_sha256=hashlib.sha256(image_data).hexdigest(),
            manifest=manifest,request_sha256=request['raw_bgr_sha256'],bridge_sha256=bridge_request['image_sha256'],
            Linux_received_bytes=error['received_bgr_bytes'],native_stdin_bytes_written=error['native_stdin_bytes_written'],
            native_stdin_expected_bytes=error['native_stdin_expected_bytes'],native_stdin_complete=error['native_stdin_complete']),
        original_postclose_pixel_audit=post,
        stdout_bytes_or_partial_buffer_recorded=any(k in error for k in ('native_stdout_bytes','native_buffer_bytes','stdout_read_bytes')),
        native_read_tick_infer_serialize_flush_phase_recorded=False,
        cold_first_request=True,startup_zero_counters={k:startup[k] for k in ('native_ticks','inference_calls','camera_captures','physics_steps')},
        native_main_sha256=main_sha,native_main_matches_build_manifest=main_sha==main_pinned,
        build_manifest_sha256=sha(BUILD/'BUILD_MANIFEST.json'),
        native_binary_declared_sha256=build_manifest['binary_sha256'],
        same_owned_child_identity=all(child[k]==cleanup[k] for k in identity_fields),
        worker_identity_namespace_note='WORKER_STARTUP run_id is a bootstrap identity distinct from LinuxOwnedProcessGroup child run_id; correlate supervisor PID, boot/spec then exact child run_id across OWNED_CHILD/STARTUP/CLEANUP.',
        worker_child_supervisor_matches=worker['supervisor_pid']==child['supervisor_pid'] and worker['boot_id']==child['boot_id'] and worker['spec_sha256']==child['spec_sha256'],
        cleanup=cleanup,classification=load(INPUT/'RESULT.json')['classification'],
        cross_clock_subtraction=False,native_lifetime_cpu_used_as_inference_time=False,
        benchmark_started=False,ROS_started=False,WSL_started=False,NN_started=False,GL_started=False)
    expected=request['raw_bgr_sha256']
    report['bgr_sha_bindings_equal']=all(x==expected for x in (report['bgr_identity']['actual_sha256'],manifest['sha256'],bridge_request['image_sha256']))
    raw=OUT/'raw';raw.mkdir(exist_ok=False)
    for p in files:
        rel=p.relative_to(INPUT);target=raw/rel;target.parent.mkdir(parents=True,exist_ok=True)
        data=p.read_bytes()
        if hashlib.sha256(data).hexdigest()!=before[str(rel)]:raise RuntimeError('input_changed:'+str(rel))
        target.write_bytes(data)
    for n in SOURCE:
        target=OUT/'source'/n;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/n).read_bytes())
    for p in (BUILD/'BUILD_MANIFEST.json', main_path):
        target=OUT/'native_build'/p.relative_to(BUILD);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(p.read_bytes())
    report['input_unchanged']=before=={str(p.relative_to(INPUT)):sha(p) for p in files}
    report['source_unchanged']=source_before=={n:sha(ROOT/n) for n in SOURCE}
    report['raw_copies_byteidentical']=before=={str(p.relative_to(INPUT)):sha(raw/p.relative_to(INPUT)) for p in files}
    if not all(report[k] for k in ('input_unchanged','source_unchanged','raw_copies_byteidentical','bgr_sha_bindings_equal','native_main_matches_build_manifest')):raise RuntimeError('audit_identity_failure')
    (OUT/'AUDIT.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf8')
    process=dict(exit_code=0,elapsed_s=time.perf_counter()-began,python=sys.version,
        script_sha256=sha(Path(__file__)),input_unchanged=report['input_unchanged'],source_unchanged=report['source_unchanged'],
        raw_copies_byteidentical=report['raw_copies_byteidentical'],scope=report['scope'],benchmark_started=False,NN_started=False,WSL_started=False,GL_started=False)
    (OUT/'PROCESS_RESULT.json').write_text(json.dumps(process,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(host_timeline=report['host_timeline'],host_durations_ms=report['host_durations_ms'],linux_stages_s=linux,
        linux_stage_sum_ms=report['linux_stage_sum_ms'],bgr_sha_bindings_equal=report['bgr_sha_bindings_equal'],source_unchanged=report['source_unchanged'],
        native_main_matches_build_manifest=report['native_main_matches_build_manifest'],same_owned_child_identity=report['same_owned_child_identity'],process=process),indent=2))


if __name__=='__main__':main()
