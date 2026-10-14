#!/usr/bin/env python3
"""Real six-car runtime profiling, fixed dt/camera/deadline configuration.

No native/GUI/full-match qualification. cProfile is diagnostic and has overhead;
compare unprofiled fresh-process runs for throughput evidence.
"""
import argparse
import cProfile
import hashlib
import json
from pathlib import Path
import pstats
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--seconds', type=float, default=10.)
    parser.add_argument('--cprofile', action='store_true')
    parser.add_argument('--no-camera', action='store_true', help='Diagnostic only; separate configuration')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    from rm_match.platform_v2.backend import MuJoCoBackend
    from rm_match.platform_v2.camera import CameraProvider
    from rm_match.platform_v2.runtime import PlatformRuntime
    from profile_camera import hardware_identity, distribution
    sources = {}
    for path in ('rm_match/platform_v2/runtime.py', 'rm_match/platform_v2/backend.py',
                 'rm_match/platform_v2/control.py', 'rm_match/platform_v2/camera.py',
                 'rm_match/match_engine.py', 'tools/profile_runtime.py'):
        raw = (ROOT/path).read_bytes()
        sources[path] = hashlib.sha256(raw).hexdigest()
        destination = out/'sources'/path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    stages = {}
    backend = MuJoCoBackend(camera=not args.no_camera)
    if len(backend.robot_ids) != 6 or abs(backend.timestep-.002) > 1e-12:
        raise ValueError('Original six-car/2ms configuration required')
    camera = None if args.no_camera else CameraProvider(backend._sim, clock=time.perf_counter,
                                                       total_fps=15, max_views=1)
    runtime = PlatformRuntime(backend, camera=camera, clock=time.perf_counter)
    def instrument(obj, name, label):
        original = getattr(obj, name)
        samples = stages.setdefault(label, [])
        def timed(*a, **kw):
            start = time.perf_counter()
            try:
                return original(*a, **kw)
            finally:
                samples.append((start, time.perf_counter()-start))
        setattr(obj, name, timed)
    for obj, name, label in [(runtime,'step_once','step_total'),
                              (runtime,'_collect','collect'), (runtime,'_schedule','schedule'),
                              (runtime,'_targets','targets'), (backend,'_step','backend_step'),
                              (backend,'display_snapshot','display_snapshot'),
                              (runtime.control,'snapshot','control_snapshot'),
                              (runtime.control,'snapshot_robot','control_snapshot_robot')]:
        instrument(obj, name, label)
    if camera:
        instrument(camera, 'capture_from_authority', 'camera_authority_capture')
        session = runtime.control.open_session('spectator')
        runtime.watch(session['token'], 'red_sentry')
    profiler = cProfile.Profile() if args.cprofile else None
    wall = time.perf_counter()
    cpu = time.process_time()
    error = None
    try:
        if profiler:
            profiler.enable()
        runtime.run(max_wall_seconds=args.seconds, real_time_factor=1.)
    except BaseException as exc:
        error = type(exc).__name__+': '+str(exc)
        raise
    finally:
        if profiler:
            profiler.disable()
            profiler.dump_stats(str(out/'runtime.prof'))
            with (out/'cprofile.txt').open('w', encoding='utf-8') as stream:
                pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats('cumulative').print_stats(60)
                pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats('tottime').print_stats(40)
        elapsed = time.perf_counter()-wall
        cpu_s = time.process_time()-cpu
        runtime.close()
        closed = True if camera is None else camera.wait_closed(5.)
        report = dict(schema='polar.sim.runtime_profile.v1', hardware=hardware_identity(),
                      source_hashes=sources, configuration=dict(seconds=args.seconds, warmup_seconds=2.,
                      robot_count=6, dt_s=.002, camera_resolution=[1440,1080],
                      total_fps=15, active_views=0 if args.no_camera else 1, native_bound=False,
                      camera_80ms_unchanged=True, input_window_s=.15, real_time_factor_limit=1.,
                      cprofile=args.cprofile), physics_steps=runtime.steps,
                      sim_progress_s=backend.sim_time, elapsed_wall_s=elapsed,
                      physics_rtf=backend.sim_time/elapsed, cpu_s=cpu_s,
                      stages={k:distribution([duration for start,duration in rows if start-wall>=2.])
                              for k,rows in stages.items()}, error=error, clean_shutdown=closed,
                      qualification='Real GL/physics diagnostic only; no native, GUI, LAN or A12 qualification')
        if camera:
            report['camera_status'] = camera.status()
            report['camera_timings'] = camera.timing_report()
        (out/'RESULT.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        (out/'stages.json').write_text(json.dumps(stages)+'\n', encoding='utf-8')
        print(json.dumps({key:report[key] for key in ('physics_steps','elapsed_wall_s','physics_rtf','clean_shutdown','error')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
