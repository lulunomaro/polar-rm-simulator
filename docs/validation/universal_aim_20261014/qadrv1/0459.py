#!/usr/bin/env python3
"""Real, headless MuJoCo camera A/B profiling; never qualifies native inference.

Each variant runs in a fresh subprocess. The fixed baseline camera provider is
loaded under its package from git; both providers use the current GL renderer.
No deadlines, resolution, image values or simulator settings are relaxed.
"""
from __future__ import annotations

import argparse
import base64
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASELINE = '1fdcd249be761100076670bb863c14357e8c62ed'
FRESHNESS_S = .080


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')


def distribution(values):
    from rm_match.telemetry import percentile
    ordered = sorted(values)
    return dict(count=len(ordered), p50_ms=None if not ordered else percentile(ordered, .5)*1000,
                p95_ms=None if not ordered else percentile(ordered, .95)*1000,
                p99_ms=None if not ordered else percentile(ordered, .99)*1000,
                max_ms=None if not ordered else max(ordered)*1000,
                within_80ms_count=sum(v <= FRESHNESS_S for v in ordered),
                within_80ms_fraction=None if not ordered else sum(v <= FRESHNESS_S for v in ordered)/len(ordered))


def hardware_identity():
    result = dict(os=platform.platform(), machine=platform.machine(), cpu=platform.processor(),
                  logical_cpu_count=os.cpu_count(), python=sys.version, executable=sys.executable)
    if sys.platform == 'win32':
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
            result['cpu'] = winreg.QueryValueEx(key, 'ProcessorNameString')[0].strip()
    return result


def child(a):
    from rm_match.platform_v2.backend import MuJoCoBackend
    from rm_match.platform_v2.camera import CameraProvider, MuJoCoCameraRenderer
    from rm_match.platform_v2.runtime import PlatformRuntime
    import mujoco
    import numpy
    import PIL

    out = a.out.resolve()
    rows = OrderedDict(); stage_rows = []; runtime = None; provider = None
    integrity = {}; errors = []; renderer_identity = {}; step_times = []
    started = None; elapsed = None; sim_start = None; sim_end = None; closed = False
    cpu_start = None; cpu_end = None
    current_source = (ROOT / 'rm_match/platform_v2/camera.py').read_bytes()
    (out / 'current_camera.py').write_bytes(current_source)
    source = out.parent / 'baseline_camera.py'
    baseline_source = source.read_bytes()
    provider_class = CameraProvider
    if a.variant == 'baseline':
        name = 'rm_match.platform_v2._baseline_camera'
        spec = importlib.util.spec_from_file_location(name, source)
        module = importlib.util.module_from_spec(spec); sys.modules[name] = module
        spec.loader.exec_module(module)
        provider_class = module.CameraProvider

    class Pending(OrderedDict):
        def __setitem__(self, key, cap):
            rows[cap.frame_seq] = dict(frame_seq=cap.frame_seq, robot_id=cap.robot_id,
                capture_wall=cap.wall_time, capture_sim_time=cap.sim_time,
                raw_published_wall=None, display_published_wall=None)
            super().__setitem__(key, cap)

    class Cache(dict):
        def __init__(self, raw, display):
            super().__init__(); self.raw = raw; self.display = display
        def __setitem__(self, key, value):
            now = time.perf_counter(); row = rows[value['capture'].frame_seq]
            if self.raw:
                row['raw_published_wall'] = now
                if 'camera' not in integrity:
                    integrity['camera'] = value['camera']
                    integrity['frame_seq'] = value['capture'].frame_seq
                    integrity['rgb'] = integrity['candidate_rgb']
                    integrity['render_frame_seq'] = value['capture'].frame_seq
            if self.display:
                row['display_published_wall'] = now
            super().__setitem__(key, value)

    class Render:
        def __init__(self, model, profile):
            t = time.perf_counter(); self.delegate = MuJoCoCameraRenderer(model, profile)
            renderer_identity.update(self.delegate.identity)
            self.identity = self.delegate.identity
            self.last_timings = {}
            stage_rows.append(dict(stage='renderer_init', duration_s=time.perf_counter()-t))
        def render(self, cap):
            t = time.perf_counter(); rgb = self.delegate.render(cap); finished = time.perf_counter()
            self.last_timings = dict(self.delegate.last_timings)
            stage_rows.append(dict(stage='render_total', frame_seq=cap.frame_seq,
                duration_s=finished-t, queue_wait_s=t-cap.wall_time, **self.delegate.last_timings))
            return rgb
        def close(self):
            self.delegate.close()

    class TimedCamera(provider_class):
        def _encode(self, cap, rgb):
            t = time.perf_counter(); result = super()._encode(cap, rgb)
            # Retain a reference only; hash after shutdown, outside the run.
            if 'camera' not in integrity: integrity['candidate_rgb'] = rgb
            stage_rows.append(dict(stage='raw_and_jpeg_encode' if a.variant == 'baseline' else 'raw_encode',
                                   frame_seq=cap.frame_seq, duration_s=time.perf_counter()-t))
            return result
        def _encode_display(self, cap, rgb):
            t = time.perf_counter(); result = super()._encode_display(cap, rgb)
            stage_rows.append(dict(stage='jpeg_encode', frame_seq=cap.frame_seq, duration_s=time.perf_counter()-t))
            return result

    class TimedRuntime(PlatformRuntime):
        def step_once(self):
            t = time.perf_counter(); result = super().step_once()
            step_times.append(dict(wall=t, duration_s=time.perf_counter()-t, sim_time=self.backend.sim_time))
            return result

    result = dict(schema='polar.sim.camera_profile.variant.v1', variant=a.variant,
                  baseline_commit=BASELINE, baseline_camera_sha256=sha(baseline_source),
                  current_camera_sha256=sha(current_source), renderer_source='current_camera.py for both variants',
                  runtime_sha256=sha((ROOT / 'rm_match/platform_v2/runtime.py').read_bytes()),
                  hardware=hardware_identity(), versions=dict(mujoco=mujoco.__version__, numpy=numpy.__version__, pillow=PIL.__version__),
                  configuration=dict(wall_seconds=a.seconds, warmup_seconds=a.warmup, total_fps=15,
                                     resolution=[1440,1080], robot_count=6, view_count=1, watched_robot='red_sentry',
                                     target_rtf=1, native_camera_freshness_s=FRESHNESS_S,
                                     provider_cache_ttl_s=2.5, gui=False, adapters_bound=0, fire_commands=0),
                  measurement_clock=dict(name='perf_counter',resolution_s=time.get_clock_info('perf_counter').resolution,
                                         implementation=time.get_clock_info('perf_counter').implementation),
                  qualification='Actual GL camera and physics measurement only; no native closed-loop claim')
    write_json(out / 'PARTIAL.json', result)
    try:
        backend = MuJoCoBackend(camera=True)
        if len(backend.robot_ids) != 6: raise RuntimeError('Expected six-robot original scene')
        provider = TimedCamera(backend._sim, clock=time.perf_counter, total_fps=15, max_views=1, renderer_factory=Render)
        if (provider.profile.width, provider.profile.height) != (1440,1080):
            raise RuntimeError('Expected original 1440x1080 sensor resolution')
        provider.pending = Pending()
        provider.cache = Cache(raw=True, display=a.variant == 'baseline')
        if a.variant == 'current': provider.display_cache = Cache(raw=False, display=True)
        runtime = TimedRuntime(backend, camera=provider, clock=time.perf_counter)
        session = runtime.control.open_session('spectator')
        runtime.watch(session['token'], 'red_sentry')
        started = time.perf_counter(); cpu_start = time.process_time(); sim_start = backend.sim_time
        runtime.run(max_wall_seconds=a.seconds, real_time_factor=1.)
        elapsed = time.perf_counter()-started
        cpu_end = time.process_time()
        sim_end = backend.sim_time
    except BaseException as exc:
        errors.append(type(exc).__name__ + ': ' + str(exc))
        (out / 'error.log').write_text(traceback.format_exc(), encoding='utf-8')
    finally:
        if started is not None:
            elapsed = elapsed or time.perf_counter()-started
            cpu_end = cpu_end or time.process_time()
        if runtime is not None:
            try:
                sim_end = runtime.backend.sim_time
                runtime.close()
            except BaseException as exc: errors.append('shutdown: ' + repr(exc))
        if provider is not None:
            provider.stop(); closed = provider.wait_closed(5.)
    measurement = []
    for row in rows.values():
        row['elapsed_capture_s'] = None if started is None else row['capture_wall']-started
        row['phase'] = 'measurement' if started is not None and row['elapsed_capture_s'] >= a.warmup else 'warmup'
        for kind in ('raw', 'display'):
            pub = row[kind+'_published_wall']
            row['capture_to_'+kind+'_s'] = None if pub is None else pub-row['capture_wall']
        if row['phase'] == 'measurement': measurement.append(row)
    for kind in ('raw', 'display'):
        values = [r['capture_to_'+kind+'_s'] for r in measurement if r['capture_to_'+kind+'_s'] is not None]
        summary = distribution(values)
        summary['published_fps'] = len(values)/max(.001, (elapsed or a.seconds)-a.warmup)
        summary['captured_frame_count'] = len(measurement)
        summary['captured_within_80ms_fraction'] = None if not measurement else summary['within_80ms_count']/len(measurement)
        summary['freshness_scope'] = 'capture-to-publication wall latency; native inference, consumer queue and sim-age gate unmeasured'
        result['capture_to_'+kind] = summary
    if 'camera' in integrity and 'rgb' in integrity:
        camera = integrity['camera']; image = camera['image']
        pixels = base64.b64decode(image['data_base64'], validate=True)
        render_pixels = integrity['rgb'].tobytes()
        permitted = {'available','reason','frame_id','capture_sim_time','own_qpos_at_capture','own_qvel_at_capture',
                     'own_odom_at_capture','own_odom_velocity_at_capture','image','intrinsics','extrinsics','provenance'}
        audit = dict(frame_seq=integrity['frame_seq'], renderer_frame_seq=integrity['render_frame_seq'],
                     rgb_sha256=sha(render_pixels), decoded_raw_sha256=sha(pixels), byte_count=len(pixels),
                     pixel_bytes_equal=pixels == render_pixels, dto_keys=sorted(camera),
                     camera_keys_match_sensor_allowlist=set(camera) == permitted,
                     image_keys_match_allowlist=set(image) == {'encoding','width','height','stride_bytes','data_base64'},
                     provenance=camera['provenance'], hash_computed_after_run=True)
        audit['passed'] = (audit['frame_seq'] == audit['renderer_frame_seq'] and audit['pixel_bytes_equal']
                           and audit['camera_keys_match_sensor_allowlist'] and audit['image_keys_match_allowlist']
                           and audit['byte_count'] == 1440*1080*3 and audit['provenance'] == 'simulated_raw_camera')
        result['raw_pixel_audit'] = audit
    else:
        result['raw_pixel_audit'] = dict(passed=False, reason='no renderer and raw sample pair available')
    sim_progress = None if sim_end is None or sim_start is None else sim_end-sim_start
    cpu_s = None if cpu_start is None else cpu_end-cpu_start
    result.update(errors=errors, clean_shutdown=closed, renderer_identity=renderer_identity,
                  physics_steps=runtime.steps if runtime is not None else 0,
                  elapsed_wall_s=elapsed, simulation_progress_s=sim_progress,
                  physics_rtf=None if not elapsed or sim_progress is None else sim_progress/elapsed,
                  process_cpu_s=cpu_s, process_cpu_average_cores=None if not elapsed or cpu_s is None else cpu_s/elapsed,
                  process_cpu_machine_fraction=None if not elapsed or cpu_s is None else cpu_s/elapsed/(os.cpu_count() or 1),
                  physics_step_latency=distribution([r['duration_s'] for r in step_times if started is not None and r['wall']-started >= a.warmup]),
                  provider_status=provider.status() if provider is not None else None,
                  provider_timings=provider.timing_report() if provider is not None and hasattr(provider,'timing_report') else None)
    result['completed_camera_physics_profile'] = (not errors and closed and result['physics_steps'] > 0
        and result['capture_to_raw']['count'] > 0 and result['capture_to_display']['count'] > 0
        and result['raw_pixel_audit']['passed'] and provider.error is None and getattr(provider,'display_error',None) is None)
    write_json(out / 'frames.json', list(rows.values()))
    write_json(out / 'stages.json', stage_rows)
    write_json(out / 'physics_steps.json', step_times)
    write_json(out / 'RESULT.json', result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['completed_camera_physics_profile'] else 2


def compare(a):
    out = (a.out or ROOT / 'artifacts' / ('camera_profile_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8])).resolve()
    out.mkdir(parents=True, exist_ok=False)
    tool_source = Path(__file__).resolve().read_bytes()
    (out / 'profile_camera.py').write_bytes(tool_source)
    baseline_source = subprocess.check_output(['git','show',BASELINE+':rm_match/platform_v2/camera.py'], cwd=ROOT)
    (out / 'baseline_camera.py').write_bytes(baseline_source)
    results = {}
    for variant in a.order.split(','):
        directory = out / variant; directory.mkdir()
        command = [sys.executable, str(Path(__file__).resolve()), '--child', '--variant', variant,
                   '--seconds', str(a.seconds), '--warmup', str(a.warmup), '--out', str(directory)]
        with (directory / 'stdout.log').open('wb') as stdout, (directory / 'stderr.log').open('wb') as stderr:
            process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL)
            try: exit_code = process.wait(timeout=a.seconds+45)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(); exit_code = -1
        path = directory / 'RESULT.json'
        results[variant] = json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(errors=['No final result; inspect PARTIAL.json and logs'])
        results[variant]['process_exit_code'] = exit_code
        write_json(out / 'PARTIAL_COMPARISON.json', results)
    comparison = dict(schema='polar.sim.camera_profile.comparison.v1', created_utc=datetime.now(timezone.utc).isoformat(),
        profiler_sha256=sha(tool_source),
        baseline_commit=BASELINE, baseline_camera_sha256=sha(baseline_source), run_order=a.order.split(','),
        results=results, evidence_directory=str(out),
        qualification='Same host, fresh processes, real MuJoCo GL renderer and PlatformRuntime. No native adapter or GUI qualification.')
    same_hardware = results['baseline'].get('hardware') == results['current'].get('hardware')
    same_renderer = results['baseline'].get('renderer_identity') == results['current'].get('renderer_identity')
    same_config = results['baseline'].get('configuration') == results['current'].get('configuration')
    same_current_source = results['baseline'].get('current_camera_sha256') == results['current'].get('current_camera_sha256')
    comparison.update(same_hardware=same_hardware, same_renderer=same_renderer, same_configuration=same_config,
                      same_current_source=same_current_source)
    comparison['completed_camera_physics_comparison'] = (all(results[v].get('completed_camera_physics_profile') for v in results)
        and same_hardware and same_renderer and same_config and same_current_source)
    write_json(out / 'COMPARISON.json', comparison)
    print(json.dumps(dict(evidence_directory=str(out), completed=comparison['completed_camera_physics_comparison'],
        results={k:{field:v.get(field) for field in ('capture_to_raw','capture_to_display','physics_rtf','clean_shutdown','errors')} for k,v in results.items()}), indent=2))
    return 0 if comparison['completed_camera_physics_comparison'] else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=10.)
    parser.add_argument('--warmup', type=float, default=2., help='Included within total duration; excluded from steady-state distributions')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--order', choices=['baseline,current','current,baseline'], default='baseline,current')
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--variant', choices=['baseline','current'], help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 5 <= args.seconds <= 15: parser.error('--seconds must be between 5 and 15')
    if not 0 <= args.warmup <= 3 or args.warmup >= args.seconds: parser.error('--warmup must be within 0..3 and less than --seconds')
    if args.child and (args.out is None or args.variant is None): parser.error('internal child arguments missing')
    return child(args) if args.child else compare(args)


if __name__ == '__main__':
    raise SystemExit(main())

