"""Read existing evidence only; no process/physics/inference is started."""
import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
LIVE = ROOT / 'docs/validation/wsl_native_live_20261013_attempt12'
inputs = {}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    raw = path.read_bytes()
    inputs[str(path.relative_to(ROOT)).replace('\\', '/')] = sha(raw)
    return raw


def js(path):
    return json.loads(read(path))


result = js(LIVE / 'RESULT.json')
events = [json.loads(line) for line in read(LIVE / 'ledger.jsonl').splitlines()]
request = next(e for e in events if e.get('event') == 'native_request')
enqueue = next(e for e in events if e.get('event') == 'adapter_enqueue' and e.get('observed_seq') == request['observed_seq'])
publish = next(e for e in events if e.get('event') == 'private_pixels_published' and e.get('frame_id') == request['frame_id'])
frame_prepare = next(e for e in events if e.get('event') == 'native_frame_prepare')
host = js(LIVE / 'native/binding_1/supervisor_1/HOST_TRACE.json')
prep = next(e for e in host if e['event'] == 'control_prepare')
error = js(LIVE / 'native/binding_1/supervisor_1/SUPERVISOR_ERROR.json')
cleanup = js(LIVE / 'native/binding_1/supervisor_1/CLEANUP.json')
native_stderr = read(LIVE / 'native/binding_1/supervisor_1/native_stderr.log')
snapshot_map = js(LIVE / 'EXECUTED_SOURCE.json')
snapshots = json.loads(gzip.decompress(read(LIVE / 'EXECUTED_SOURCE_BYTES.json.gz')))
snapshot_ok = all(sha(base64.b64decode(value, validate=True)) == snapshot_map[key] for key, value in snapshots.items())
recovery = js(ROOT / 'operator_native/runtime/RECOVERY_MANIFEST.json')
recovery_ok = all(sha(read(ROOT / 'operator_native/runtime' / f['path'])) == f['sha256'] for f in recovery['files'])
spec_path = ROOT / 'artifacts/native-contour-v3-final-default-build/operator_source.local.json'
spec = js(spec_path)
manifest_path = spec_path.parent / 'BUILD_MANIFEST.json'
manifest = js(manifest_path)
binary = spec_path.parent / 'bin/rmcs_sim_operator_fov'
identity = dict(
    spec_sha256=sha(read(spec_path)), build_sha256=sha(read(manifest_path)),
    binary_sha256=sha(read(binary)), model_sha256=sha(read(ROOT / 'models/shenzhen-0526.onnx')),
    recovered_files_checked=len(recovery['files']), recovered_file_hashes_unchanged=recovery_ok,
    executed_source_snapshots_checked=len(snapshots), executed_snapshot_hashes_match=snapshot_ok,
    contour_source_sha256=sha(read(ROOT / 'operator_native/runtime/overlays/corners_contour_v3.cpp')),
    source_identity_equal=spec['source_identity'] == result['native_identity']['source_identity'] == manifest['input_identity']['algorithm_identity'],
    current_builder_is_not_the_old_build_input=True,
    qualification='Existing ELF/spec/build/model byte identities only; no revalidation against changed current builder and no execution.'
)
identity['recorded_identities_match'] = (
    identity['spec_sha256'] == result['linux_spec_sha256'] and
    identity['build_sha256'] == result['native_identity']['build_manifest_sha256'] and
    identity['binary_sha256'] == spec['sha256']['binary'] == manifest['binary_sha256'] and
    identity['model_sha256'] == spec['model_sha256']
)
profiles = {}
for profile in ('first-frame-trace', 'request-preallocate-trace'):
    directory = ROOT / ('artifacts/native-' + profile + '-saved12-20261013')
    diagnostic = js(directory / 'RESULT.json')
    cases = []
    for path in sorted(directory.glob('*phase_report.json')):
        phase = js(path)
        response = js(path.with_name(path.name.replace('_phase_report', '_responses')))
        cases.append(dict(case=path.stem.replace('_phase_report', ''),
            completed=phase['first_frame_complete'], original_identity=phase['original_identity'],
            phases_ms={p['phase']:p['elapsed_ns']/1e6 for p in phase['completed_phases'] if not p['startup']},
            first_response_ms=response[0]['response_s']*1000,
            repeated_packet_followups_are_not_steady_inference=True))
    profiles[profile] = dict(binary_sha256=diagnostic['binary_sha256'],
        pixels_identical=diagnostic['actual_image_sha256'] == request['raw_bgr_sha256'], cases=cases,
        qualification='Independent diagnostic ELF, original recorded input, Linux offline only; never supplements failed live result.')
cap = enqueue['sensor_budget']['capture_wall']
host_stages = dict(
    exposure_to_private_publish_ms=(publish['wall_time']-cap)*1000,
    private_publish_to_enqueue_ms=(enqueue['wall_time']-publish['wall_time'])*1000,
    enqueue_to_adapter_native_request_ms=(request['wall_time']-enqueue['wall_time'])*1000,
    adapter_request_to_bridge_request_ms=(next(e for e in host if e['event']=='native_request')['host_perf_counter']-request['wall_time'])*1000,
    exposure_to_bridge_request_ms=(next(e for e in host if e['event']=='native_request')['host_perf_counter']-cap)*1000,
    remaining_host_budget_ms=prep['remaining_host_budget_s']*1000,
    image_prepare_detail_ms={k:v*1000 for k,v in frame_prepare['image_stages'].items() if k.endswith('_s')},
    bridge_prepare_detail_ms={k:v*1000 for k,v in prep['stages_s'].items()})
report = dict(
    schema='polar.native-attempt12-readonly-review.v1',
    scope='Read-only archived raw evidence plus current source; no WSL/ROS/GL/native/build/test execution.',
    identity=identity,
    actual_live=dict(native_results=result['measurements']['native_results'],
        distinct_native_actuated_frames=result['measurements']['distinct_native_actuated_frames'],
        adapter_error_count=result['measurements']['adapter_error_count'],
        incomplete_native_requests=result['measurements']['incomplete_native_requests'],
        frame_id=request['frame_id'], exposure_ns=410000000, control_ns=422000000,
        bgr_sha256=request['raw_bgr_sha256'], host_stages=host_stages,
        linux_local_stages_ms={k:v*1000 for k,v in error['linux_stages_s'].items()},
        complete_stdin_bytes=error['native_stdin_bytes_written'], expected_stdin_bytes=error['native_stdin_expected_bytes'],
        stdin_complete=error['native_stdin_complete'], native_stderr_bytes=len(native_stderr), cleanup=cleanup,
        wait_semantics='41.232ms is native full-response wait after stdin delivery, not measured NN-only time.',
        clock_guard='Host differences use Windows perf_counter only. Linux durations are independently reported; never subtract Linux absolute times from Windows.'),
    offline_diagnostic_profiles=profiles,
    observed_exclusions=[
        'LATENCY performance hint is already in common_model.hpp and CPU is explicitly configured.',
        'Tensor plus request allocation totals about 0.040-0.090ms in the three fresh trace cases; preallocation is not a credible fix.',
        'All 15 duplicate-packet responses do not imply 15 model inferences. Only first actual exposure is counted.',
        'Zero stdout return/zero native actuation remains failed. Archive/audit/cleanup success cannot qualify the live chain.'
    ],
    missing_metrics=[
        'Actual live ELF phase begin/end; native_stderr is empty, so timeout phase is unknown.',
        'Effective OpenVINO inference thread count/streams/CPU topology/affinity. OMP_NUM_THREADS=1 is not an observed compiled-model property.',
        'Owned ELF scheduler runnable delay and per-first-tick CPU, separated from model-startup lifetime CPU.',
        'Host writer queue/write timing and receiver scheduling; Linux pipe_receive includes delivery and supervisor wake, not pure bus throughput.',
        'Valid native reply-to-adapter-to-actuator margin; no response exists in this run.'
    ],
    next_experiment=dict(
        priority='One explicit diagnostic live first-frame run after source identity setup, not another original-profile blind repetition.',
        implementation='Use independent first-frame-trace profile with existing bounded begin/end stderr and strict diagnostic-only harness admission. Dump effective compiled-model properties once at zero-tick startup; preserve model, input size, precision, gates and raw timestamps. No warm inference.',
        window='One exclusive 10s same-six-car Windows GL + WSL run, original 80ms exposure budget/150ms SDK window. Distinct new diagnostic spec/ELF; never register it as the old 4d357 production identity.',
        outcomes='A last infer begin without end targets CPU scheduling/model compute; a later phase locates post/tracker/output cost; completed first_tick without host result targets bridge/scheduling. Store failures and reap.'),
    minimal_optimization_candidate=dict(
        change='Reuse a privately sealed native BGR preparation receipt for the second host SHA check, only for exact reviewed immutable bytes/envelope identity.',
        measured_target_ms=prep['stages_s']['bgr_hash_s']*1000,
        retained='First synchronous preparation SHA, Linux full-payload SHA, actual BGR archive/postclose RGB audit, strict public fallback, all original gate deadlines.',
        required_counterexamples='Wrong byte object, mutable bytes, forged digest, changed envelope/size/scope or reused receipt must still reject; subclass/public path must still hash.',
        qualification='Possible ~2.660ms host budget saving only. It cannot by itself establish compute root cause or reliable live closure.'),
    input_sha256=inputs,
    analysis_script_sha256=sha(Path(__file__).read_bytes())
)
(OUT/'REVIEW.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
print(json.dumps(dict(identity=identity, host_stages=host_stages,
    actual_native_results=report['actual_live']['native_results'],
    actual_native_consumed=report['actual_live']['distinct_native_actuated_frames'],
    report_sha256=sha((OUT/'REVIEW.json').read_bytes())),indent=2))
