#!/usr/bin/env python3
"""Pre-registered OpenCV-thread comparison on one saved real frame, offline only."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
import traceback
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.native_model_properties import parse_native_model_properties, PROPERTIES
from tools.diagnose_native_saved_compute import (select_saved_native_input,
    saved_request_identity, parse_native_phase_stderr, _saved_json, _saved_read, distribution)

SEQUENCE = ('default', 'cv1', 'cv1', 'default', 'default', 'cv1', 'cv1', 'default')
CV_KEY = 'OPENCV_FOR_THREADS_NUM'
PROFILE = 'first-frame-trace'
PIXEL_SHA = '3951a59714c439828f5e45b405d1373f03964aba342cf36d9c33e5e87ffd863e'
IDENTITY = dict(frame_id=8, exposure_timestamp_ns=476000000, control_time_ns=486000000)
EXPECTED = dict(execution_devices=['CPU'], inference_num_threads=16, num_streams=1,
    performance_mode='LATENCY', inference_precision='f32', enable_cpu_pinning=True,
    scheduling_core_type='ANY_CORE')
SOURCES = ('tools/compare_native_opencv_threads.py', 'tools/native_model_properties.py',
    'tools/diagnose_native_saved_compute.py', 'tools/validate_native_performance_profile.py',
    'rm_match/integrations/owned_linux_group.py', 'rm_match/integrations/wsl_operator_worker.py',
    'rm_match/integrations/rmcs_contract.py', 'rm_match/camera_profile.py')


def plan():
    return dict(schema='polar.native-opencv-thread-plan.v1', sequence=list(SEQUENCE),
        sole_child_environment_change={CV_KEY:dict(default=None, cv1='1')},
        expected_cv_threads=dict(default=32, cv1=1), expected_compiled_properties=EXPECTED,
        saved_identity=IDENTITY, image_sha256=PIXEL_SHA, fresh_processes=8,
        startup_timeout_s=15., offline_first_response_timeout_s=2.,
        no_warm_inference=True, live_budget_or_timestamp_changes=False,
        qualification='Linux offline first-response diagnostic only; never live/RTF qualification. No duplicate-packet throughput.')


def case_environment(base, variant):
    if variant not in ('default', 'cv1') or type(base) is not dict:
        raise ValueError('invalid_cv_variant')
    env = dict(base); env.pop(CV_KEY, None)
    if variant == 'cv1': env[CV_KEY] = '1'
    return env


def check_saved(saved):
    request = saved['request']
    if saved_request_identity(request) != IDENTITY or saved['sha256'] != PIXEL_SHA:
        raise ValueError('pre_registered_saved_input_mismatch')
    for key, expected in (('robot_id', 'red_sentry'), ('episode', 0), ('binding_epoch', 1), ('observed_seq', 9)):
        if type(request.get(key)) is not type(expected) or request[key] != expected:
            raise ValueError('saved_scope_mismatch:' + key)
    if type(saved['content']) is not bytes or len(saved['content']) != 4665600 or hashlib.sha256(saved['content']).hexdigest() != PIXEL_SHA:
        raise ValueError('saved_pixel_size_or_sha')


def check_properties(report, variant):
    if variant not in ('default', 'cv1') or not report.get('valid') or not report.get('core_properties_known'):
        raise ValueError('compiled_properties_not_known')
    row = report['record']
    for key in PROPERTIES:
        prop = row['properties'][key]; value = prop['value']; expected = EXPECTED[key]
        if prop['status'] != 'known' or type(value) is not type(expected) or value != expected:
            raise ValueError('compiled_property_changed:' + key)
    cv = row['cv_num_threads']; expected = 32 if variant == 'default' else 1
    if cv['status'] != 'known' or type(cv['value']) is not int or cv['value'] != expected:
        raise ValueError('opencv_threads_not_effective')


def make_packet(saved, image, *, profile, own_factory):
    check_saved(saved); request = saved['request']; captured = request['own_at_capture']
    own = own_factory(SimpleNamespace(own_qpos=captured['own_qpos_at_capture'],
        own_qvel=captured['own_qvel_at_capture'], odom_xyyaw=captured['own_odom_at_capture'],
        odom_vxyw=captured['own_odom_velocity_at_capture'], own_hp=0, ammo=0, own_heat=0))
    # Optional unarchived scalars are omitted, never fabricated as measurements.
    for key in ('hp', 'ammo', 'heat'): own.pop(key, None)
    frame = dict(schema='rmcs-mujoco-actor-frame-v1', episode=request['episode'],
        frame_id=request['frame_id'], exposure_timestamp_ns=IDENTITY['exposure_timestamp_ns'],
        capture_time_s=request['capture_sim_time'], own_referee_id=7, own_team='red',
        image=dict(encoding='bgr8', width=1440, height=1080, stride_bytes=4320, bytes=4665600,
            sha256=saved['sha256'], path=str(image)),
        camera=dict(fx=profile.fx, fy=profile.fy, cx=profile.cx, cy=profile.cy,
            distortion=list(profile.distortion)), own=own)
    ns = saved_request_identity(request)['control_time_ns']
    return dict(control_time_ns=ns, time_s=ns/1e9, frame=frame,
        operator_fov=dict(fov_degrees=180., circle_radius_x_norm=1., circle_radius_y_norm=1.))


def validate_response(response):
    def finite_tree(value):
        if type(value) is float and not math.isfinite(value): raise ValueError('nonfinite_native_response')
        if type(value) is dict:
            for item in value.values(): finite_tree(item)
        elif type(value) is list:
            for item in value: finite_tree(item)
    finite_tree(response)
    if (type(response) is not dict or response.get('status') != 'ok'
        or response.get('runner_identity') != 'rmcs-sim-operator-fov-v1'
        or type(response.get('clock_time_ns')) is not int or response['clock_time_ns'] != IDENTITY['control_time_ns']
        or response.get('direction_frame') != 'world' or type(response.get('tracking')) is not bool
        or response.get('detector_executed') is not True):
        raise ValueError('first_native_response_identity_or_detection')


def first_transaction(child, payload, timeout=2., *, evidence=None):
    """One bounded request, partial OS IO accounted; no second exposure submitted."""
    started = time.perf_counter(); deadline = started + timeout
    sent = 0; received = bytearray(); expected = len(payload)
    if evidence is None: evidence = {}
    evidence.update(stdin_expected_bytes=expected, stdin_written_bytes=0, received_bytes=0,
                    raw_response=b'', linux_local_request_perf=started)
    os.set_blocking(child.stdin.fileno(), False); os.set_blocking(child.stdout.fileno(), False)
    while True:
        remaining = deadline-time.perf_counter()
        if remaining <= 0: raise TimeoutError('offline_first_response_timeout')
        if child.poll() is not None: raise RuntimeError('native_exit_during_first_request')
        readable, writable, _ = select.select([child.stdout.fileno()],
            [child.stdin.fileno()] if sent < expected else [], [], min(.005, remaining))
        if time.perf_counter() >= deadline: raise TimeoutError('offline_first_response_timeout')
        if writable:
            try: count = os.write(child.stdin.fileno(), payload[sent:])
            except BlockingIOError: count = None
            if count is not None:
                if count <= 0: raise BrokenPipeError('native_stdin_write_failed')
                sent += count; evidence['stdin_written_bytes'] = sent
        if readable:
            try: chunk = os.read(child.stdout.fileno(), 65536)
            except BlockingIOError: continue
            if not chunk: raise EOFError('native_stdout_eof')
            received.extend(chunk)
            evidence.update(received_bytes=len(received), raw_response=bytes(received))
            if len(received) > 65536: raise ValueError('native_response_bound')
            if b'\n' in received:
                raw, _, tail = received.partition(b'\n')
                if tail or sent != expected: raise ValueError('unsolicited_or_extra_native_reply')
                response = _saved_json(bytes(raw))
                validate_response(response)
                ended = time.perf_counter()
                if ended >= deadline: raise TimeoutError('offline_first_response_timeout')
                return dict(response=response, response_s=ended-started,
                    linux_local_request_perf=started, linux_local_response_perf=ended,
                    stdin_expected_bytes=expected, stdin_written_bytes=sent), bytes(received)


def _write(out, name, value):
    (out/name).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def source_hashes():
    return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCES}


def summarize_cases(cases):
    summary = {}
    for variant in ('default', 'cv1'):
        valid = [c for c in cases if c['variant'] == variant and not c['errors']
                 and c.get('phases', {}).get('first_frame_complete') is True and 'first_response' in c]
        phases = {}
        for case in valid:
            for phase in case['phases']['completed_phases']:
                if not phase['startup']: phases.setdefault(phase['phase'], []).append(phase['elapsed_ns']/1e9)
        summary[variant] = dict(valid_first_cases=len(valid),
            first_response=distribution([c['first_response']['response_s'] for c in valid]),
            first_frame_phases={key:distribution(values) for key,values in phases.items()},
            qualification='Only error-free fresh first responses; four planned per arm. Inclusive nested phase durations must not be added.')
    return summary


def run(args):
    if sys.platform != 'linux': raise RuntimeError('Actual comparison requires Linux; dry plan is portable')
    import resource
    from rm_match.camera_profile import SourceCameraProfile
    from rm_match.integrations.rmcs_contract import own_state
    from rm_match.integrations.wsl_operator_worker import _stdin_wait, validate_sensor_frame
    from rm_match.integrations.owned_linux_group import LinuxOwnedProcessGroup
    from tools.validate_native_performance_profile import validate_performance_spec
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    before = source_hashes(); _write(out, 'PLAN.json', plan()); _write(out, 'SOURCE_BEFORE.json', before)
    cases = []; errors = []; tmp = None; report = {}; spec = None; saved = None
    try:
        for name in SOURCES:
            target = out/'executed_source'/name; target.parent.mkdir(parents=True, exist_ok=True)
            content = (ROOT/name).read_bytes()
            if hashlib.sha256(content).hexdigest() != before[name]: raise ValueError('source_snapshot_changed')
            target.write_bytes(content)
        spec, spec_sha = validate_performance_spec(args.native_spec, expected_profile=PROFILE)
        saved = select_saved_native_input(args.run_root); check_saved(saved)
        _write(out, 'NATIVE_SPEC.json', spec); _write(out, 'SAVED_REQUEST.json', saved['request'])
        _write(out, 'SAVED_INPUT_PROVENANCE.json', saved['provenance'])
        (out/'actual_input.bgr').write_bytes(saved['content'])
        tmp = tempfile.TemporaryDirectory(prefix='polar-cv-threads-', dir='/dev/shm')
        os.chmod(tmp.name, 0o700); workspace = Path(tmp.name)
        image = workspace/'actual_input.bgr'; image.write_bytes(saved['content'])
        if image.read_bytes() != saved['content']: raise ValueError('tmpfs_input_changed')
        base = os.environ.copy(); base.update(spec.get('environment', {})); base.pop(CV_KEY, None)
        base.update(AUTOAIM_CONFIG=spec['autoaim_config'], RMCS_HEADLESS_SHARE=spec['model_share'], ORT_DISABLE_TELEMETRY='1')
        for index, variant in enumerate(SEQUENCE):
            case = out/f'{index+1:02}_{variant}'; case.mkdir()
            cwd = workspace/f'{index+1:02}_{variant}'; cwd.mkdir(mode=0o700)
            mode = spec['runtime_mode_contents'].encode('utf-8')
            if mode != b'multi_ekf\n': raise ValueError('tracking_mode_not_original_exact_lf')
            (cwd/'tracking_mode').write_bytes(mode)
            packet = make_packet(saved, image, profile=SourceCameraProfile(), own_factory=own_state)
            validate_sensor_frame(packet['frame']); _write(case, 'PACKET.json', packet)
            payload = json.dumps(packet, allow_nan=False, separators=(',', ':')).encode()+b'\n'
            (case/'REQUEST_BYTES.jsonl').write_bytes(payload)
            env = case_environment(base, variant)
            differences = {key for key in set(base)|set(env) if base.get(key) != env.get(key)}
            if differences != ({CV_KEY} if variant == 'cv1' else set()): raise ValueError('multiple_environment_factors')
            command = [spec['binary'], spec['executor_yaml']]
            _write(case, 'COMMAND.json', dict(command=command, cwd=str(cwd), variant=variant,
                environment_difference={key:env.get(key) for key in differences},
                relevant_environment={key:env.get(key) for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS',CV_KEY)},
                cwd_mode=oct(cwd.stat().st_mode & 0o777), tracking_mode_sha256=hashlib.sha256(mode).hexdigest()))
            owner = LinuxOwnedProcessGroup(); child = None; stderr = None; row = dict(index=index+1, variant=variant, errors=[])
            io_evidence = {}
            usage_before = resource.getrusage(resource.RUSAGE_CHILDREN); started = time.perf_counter()
            try:
                stderr = (case/'native_stderr.log').open('wb')
                child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=stderr, cwd=cwd, env=env, bufsize=0, start_new_session=True)
                _write(case, 'OWNED_CHILD.json', owner.attach(child)); ready = None
                while time.perf_counter()-started < 15.:
                    if child.poll() is not None: raise RuntimeError('native_exit_before_zero_tick_readiness')
                    ready = _stdin_wait(child.pid)
                    if ready: break
                    time.sleep(.005)
                if not ready: raise TimeoutError('zero_tick_read0_not_ready')
                row['startup_s'] = time.perf_counter()-started
                row['zero_tick_readiness'] = ready
                startup_bytes = _saved_read(case/'native_stderr.log', out, 16*1024*1024)
                props = parse_native_model_properties(startup_bytes, expected_profile=PROFILE)
                row['startup_properties'] = props; _write(case, 'STARTUP_PROPERTIES.json', props)
                check_properties(props, variant)
                response, raw_response = first_transaction(child, payload, evidence=io_evidence)
                (case/'RESPONSE_BYTES.jsonl').write_bytes(raw_response)
                row['first_response'] = response; _write(case, 'FIRST_RESPONSE.json', response)
            except BaseException as exc:
                row['errors'].append(type(exc).__name__+':'+str(exc))
                (case/'exception.txt').write_text(traceback.format_exc(), encoding='utf-8')
            finally:
                try:
                    row['cleanup'] = owner.cleanup()
                except BaseException as exc:
                    row['cleanup'] = dict(clean=False, errors=[type(exc).__name__+':'+str(exc)])
                    row['errors'].append('cleanup_failed')
                for stream in (None if child is None else child.stdin, None if child is None else child.stdout, stderr):
                    if stream is not None:
                        try: stream.close()
                        except OSError as exc: row['errors'].append('stream_close:'+str(exc))
                usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
                row['lifetime_cpu'] = dict(user_s=usage_after.ru_utime-usage_before.ru_utime,
                    system_s=usage_after.ru_stime-usage_before.ru_stime,
                    max_rss_kib_cumulative=usage_after.ru_maxrss,
                    scope='RUSAGE_CHILDREN lifetime includes model startup/reap; cumulative maxRSS is not per-case peak or per-infer CPU')
                if io_evidence:
                    partial = io_evidence.pop('raw_response')
                    (case/'STDOUT_CAPTURE.bin').write_bytes(partial)
                    row['io_evidence'] = dict(io_evidence, stdout_sha256=hashlib.sha256(partial).hexdigest())
                _write(case, 'CASE_PARTIAL.json', row)
                _write(case, 'CLEANUP.json', row['cleanup'])
            try:
                raw_stderr = _saved_read(case/'native_stderr.log', out, 16*1024*1024)
                row['stderr_sha256'] = hashlib.sha256(raw_stderr).hexdigest()
                row['properties'] = parse_native_model_properties(raw_stderr, expected_profile=PROFILE)
                row['phases'] = parse_native_phase_stderr(raw_stderr.decode('utf-8'), saved['request'],
                    expected_profile=PROFILE, eof_complete=row['cleanup'].get('reaped') is True)
                _write(case, 'PHASE_REPORT.json', row['phases']); _write(case, 'PROPERTIES.json', row['properties'])
                if not row['phases'].get('first_frame_complete'): row['errors'].append('first_frame_phases_incomplete')
                check_properties(row['properties'], variant)
                if row['properties'] != row.get('startup_properties'): row['errors'].append('startup_properties_changed')
            except (ValueError, OSError, UnicodeError) as exc:
                row['errors'].append('stderr_properties_or_phases:'+str(exc))
            if row['cleanup'].get('clean') is not True: row['errors'].append('owned_group_not_clean')
            _write(case, 'RESULT.json', row); cases.append(row); _write(out, 'CASES_PARTIAL.json', cases)
            if row['errors']: errors.append(dict(case=index+1, errors=row['errors']))
            if row['cleanup'].get('clean') is not True: raise RuntimeError('stop_comparison_after_incomplete_cleanup')
            if source_hashes() != before: raise ValueError('comparison_sources_changed')
        after_spec, after_sha = validate_performance_spec(args.native_spec, expected_profile=PROFILE)
        if after_sha != spec_sha or after_spec != spec: raise ValueError('native_assets_changed')
    except BaseException as exc:
        errors.append(dict(error=type(exc).__name__+':'+str(exc)))
        (out/'exception.txt').write_text(traceback.format_exc(), encoding='utf-8')
    finally:
        tmp_path = None if tmp is None else tmp.name
        if tmp is not None:
            try: tmp.cleanup()
            except BaseException as exc: errors.append(dict(error='tmpfs_cleanup:'+str(exc)))
        after = source_hashes(); unchanged = before == after
        if not unchanged: errors.append(dict(error='comparison_sources_changed'))
        report = dict(schema='polar.native-opencv-thread-comparison.v1', plan=plan(), cases=cases,
            errors=errors, source_before=before, source_after=after, source_unchanged=unchanged,
            tmpfs_directory=tmp_path, tmpfs_removed=tmp_path is None or not Path(tmp_path).exists(),
            comparison_complete=len(cases)==8 and not errors,
            spec_sha256=None if spec is None else spec_sha,
            pixel_sha256=None if saved is None else saved['sha256'],
            summary=summarize_cases(cases),
            clock_domain='linux_local_perf_counter_diagnostic_only',
            live_qualified=False, timestamps_changed=False, model_or_threshold_changes=False)
        _write(out, 'RESULT.json', report)
        _write(out, 'EVIDENCE_MANIFEST.json', {str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in out.rglob('*') if p.is_file() and p.name != 'EVIDENCE_MANIFEST.json'})
    print(json.dumps({key:report[key] for key in ('comparison_complete','errors','source_unchanged','tmpfs_removed')}, indent=2))
    return 0 if report['comparison_complete'] and report['tmpfs_removed'] else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-spec', type=Path); parser.add_argument('--run-root', type=Path)
    parser.add_argument('--out', type=Path); parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    if not args.run:
        print(json.dumps(plan(), indent=2)); return 0
    if any(getattr(args, name) is None for name in ('native_spec','run_root','out')):
        parser.error('--native-spec, --run-root and --out required with --run')
    if args.out.exists(): parser.error('Fresh output directory required')
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
