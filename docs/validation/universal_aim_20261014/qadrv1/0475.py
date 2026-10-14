#!/usr/bin/env python3
"""Explicit, bounded OFFLINE24 diagnostic using the original pinned Qt client.

Prints the plan by default. --run renders actual images, invokes the locally built
own-T2 operator, and advances physics. No firing or moving-chassis authority.
A transport pass is independent of native 3D/aim quality and live qualification.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CRITERIA = dict(profile='offline_modeled_latency_v1', captures=24, wall_limit_s=90,
    camera_native_barrier_watchdog_s=5, camera_wall_cache_ttl_s=2.5,
    max_native_age_sim_s=.08, modeled_sensor_delay_ms=10,
    modeled_compute_delay_ms=10, capture_period_ms=40,
    scene={'red_sentry_xy_m': [-3.5, 3.], 'blue_infantry_xy_m': [-1.2, 3.],
           'initial_velocity': 'all zero; public analytic 3v3 scene otherwise unchanged'},
    initialization='Renderer ready before admission, maximum 10 wall seconds; no capture, inference or physics',
    transport_required=['24 rendered exposures', '13 actual own T2 request/result pairs after original warmup',
        'original pinned Qt client admits a fresh actual camera frame', 'zero fire', 'error-free clean shutdown'],
    native_control_required=['accepted active native gimbal target consumed by physics'],
    historical_baseline_failure='Original learned corners were rejected by the unchanged PnP pitch gate. A separately identified contour-v3 build is expected to restore pose and native gimbal consumption; the actual execution decides qualification.',
    scope='Single fixed-scene OFFLINE diagnostic; not realtime, full-match, visible desktop, aim-quality or cross-PC qualification')


def classify_result(*, state, captures, counts, driver, resources_closed, driver_exit):
    cleanup = driver.get('cleanup') or {}
    clean = bool(resources_closed and driver_exit == 0 and not driver.get('errors')
        and all(cleanup.get(k) is True for k in (
            'completed', 'quiesced', 'session_close_ack', 'network_lifecycle_error_free'))
        and not cleanup.get('errors'))
    probe = driver.get('transport_before_cleanup') or {}
    display = bool(driver.get('frame_decoded') and probe.get('admitted_frame_count', 0) > 0)
    pairs = counts.get('native_request', 0) == 13 and counts.get('native_result', 0) == 13
    completed = state == 'COMPLETED' and captures == 24
    nofire = counts.get('fire_true', 0) == 0
    current = probe.get('current') or {}
    healthy = (current.get('connected') is True and current.get('uncertain') is False
        and not current.get('last_error') and not probe.get('request_errors'))
    transport = completed and pairs and display and nofire and clean and healthy
    return dict(clean_shutdown=clean, display_fresh_actual_frame=display,
        native_requests_completed=pairs, completed_24=completed, zero_fire=nofire,
        transport_final_healthy=healthy, diagnostic_transport_passed=transport,
        qualified_static_offline_chain=bool(transport and counts.get('native_gimbal_consumed', 0) > 0),
        live_default_qualified=False, full_match_qualified=False)


def cleanup_resources(*, camera, runtime, driver, server, http, errors):
    """Attempt every cleanup independently; one failure cannot hide later leaks."""
    def attempt(label, function):
        try:
            return function()
        except Exception as exc:
            errors.append(label + ': ' + type(exc).__name__ + ': ' + str(exc))
            return None
    if runtime is not None:
        attempt('runtime_close', runtime.close)
    attempt('camera_stop', camera.stop)
    if driver is not None:
        try:
            driver.wait(timeout=3.)
        except subprocess.TimeoutExpired:
            errors.append('Original client did not finish within cleanup bound')
            attempt('client_terminate', driver.terminate)
            try:
                driver.wait(timeout=2.)
            except subprocess.TimeoutExpired:
                attempt('client_kill', driver.kill)
                attempt('client_wait_after_kill', lambda: driver.wait(timeout=2.))
            except Exception as exc:
                errors.append('client_wait_after_terminate: ' + str(exc))
        except Exception as exc:
            errors.append('client_wait: ' + str(exc))
    camera_closed = attempt('camera_join', lambda: camera.wait_closed(3)) is True
    if runtime is not None and runtime.worker:
        attempt('native_stop', runtime.worker.close)
        attempt('native_join', lambda: runtime.worker.thread.join(3))
    if server is not None:
        if http is not None and http.is_alive():
            attempt('http_shutdown', server.shutdown)
        attempt('http_close', server.server_close)
    if http is not None:
        attempt('http_join', lambda: http.join(2))
    return camera_closed


def inspect_native_cleanup(runtime, children):
    """Local resource audit, independent of public state or a terminal label."""
    worker = getattr(runtime, 'worker', None)
    status = getattr(runtime, 'shutdown_status', None)
    processes = [dict(pid=p.pid, returncode=p.poll(),
        stdin_closed=p.stdin is None or p.stdin.closed,
        stdout_closed=p.stdout is None or p.stdout.closed) for p in children]
    value = dict(shutdown_status=status,
        worker_thread_alive=worker is not None and worker.thread.is_alive(),
        worker_instance_released=worker is None or worker._instance is None,
        runtime_error=getattr(runtime, 'error', None), native_processes=processes)
    value['clean'] = bool(type(status) is dict and status.get('clean') is True
        and status.get('unfinished_slots') == [] and status.get('lifecycle_errors') == []
        and not value['worker_thread_alive'] and value['worker_instance_released']
        and value['runtime_error'] is None
        and all(p['returncode'] is not None and p['stdin_closed'] and p['stdout_closed'] for p in processes))
    return value


def run(a):
    from offline_smoke.preload_contract import create_request,wait_ready
    from rm_match.deployment.profile import validate_t2_spec
    from rm_match.deployment.launcher import check_client, python_probe
    from rm_match.deployment.enrollment import provision_operator
    from rm_match.platform_v2.admission import AdmissionPolicy
    spec, specsha = validate_t2_spec(a.native_spec)
    client_identity = check_client(a.client_root)
    dependencies = dict(simulator=python_probe(sys.executable, ['mujoco', 'numpy', 'PIL', 'cv2']),
        client=python_probe(a.client_python, ['PySide6', 'numpy', 'cv2']))
    out = a.out.absolute()
    out.mkdir(parents=True, exist_ok=False)
    execution_sources = ['tools/smoke_offline_deployment.py',
        'tools/offline_smoke/offline_client_driver.py', 'tools/offline_smoke/preload_contract.py',
        'rm_match/platform_v2/offline_runtime.py', 'rm_match/platform_v2/runtime.py',
        'rm_match/platform_v2/offline_native.py', 'rm_match/platform_v2/native_adapter.py',
        'rm_match/integrations/rmcs_process.py', 'rm_match/operator/source_aim.py',
        'rm_match/platform_v2/state_projection.py']
    execution_hashes = {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in execution_sources}
    (out/'EXECUTED_SOURCE.json').write_text(json.dumps(dict(
        phase='Before renderer, Qt client and runtime creation',
        file_sha256=execution_hashes, native_spec_sha256=specsha,
        client_identity=client_identity), indent=2)+'\n')
    preload_request=create_request(out)
    credential=provision_operator(out/'admission.json')
    admission=AdmissionPolicy.from_manifest(out/'admission.json')
    (out / 'ACCEPTANCE_CRITERIA.json').write_text(json.dumps(CRITERIA, indent=2) + '\n')
    os.environ.setdefault('MUJOCO_GL', 'egl')
    os.environ['XDG_CACHE_HOME'] = str(out / 'cache')
    os.environ['MESA_SHADER_CACHE_DIR'] = str(out / 'cache/mesa')
    from rm_match.platform_v2.backend import MuJoCoBackend
    from rm_match.platform_v2.camera import CameraProvider, MuJoCoCameraRenderer
    from rm_match.platform_v2.offline_runtime import OfflineRuntime
    from rm_match.platform_v2.offline_native import OfflineNativeAdapter
    from rm_match.platform_v2.server import PlatformHTTPServer, TransportConfig
    from rm_match.match_model import SPAWNS
    import mujoco
    backend = MuJoCoBackend(camera=True)
    sim = backend._sim
    for rid, x, y in [('red_sentry', -3.5, 3.), ('blue_infantry', -1.2, 3.)]:
        sim.data.qpos[sim.qindices[rid][0]] = x - SPAWNS[rid][0]
        sim.data.qpos[sim.qindices[rid][1]] = y - SPAWNS[rid][1]
    sim.data.qvel[:] = 0
    mujoco.mj_forward(sim.model, sim.data)
    # Scene truth is recorded for audit, never appended to the algorithm DTO.
    (out / 'public_scene_initial.json').write_text(json.dumps(
        [dict(t=float(sim.time), qpos=sim.data.qpos.tolist(),
              scene_origin='explicit_public_analytic_static_test')], indent=2))
    rows, timings, errors, renderer_errors = [], [], [], []
    counts = Counter()
    native_adapters, native_children = [], []
    ready = threading.Event()
    def trace(v):
        if v['event'] == 'native_request':
            for adapter in native_adapters:
                wrapper = adapter.process
                child = getattr(wrapper, 'process', None)
                if child is not None and child not in native_children:
                    native_children.append(child)
        rows.append(v)
        counts[v['event']] += 1
        if v['event'] == 'offline_physics':
            counts['fire_true'] += bool(v['target']['fire'])
            counts['native_gimbal_consumed'] += v['target']['gimbal'] is not None
    class Render(MuJoCoCameraRenderer):
        def __init__(self, *args):
            start = time.monotonic()
            try:
                super().__init__(*args)
            except BaseException as exc:
                renderer_errors.append(str(exc))
                raise
            finally:
                timings.append(dict(stage='renderer_initialize', seconds=time.monotonic()-start))
                ready.set()
        def render(self, cap):
            start = time.monotonic()
            value = super().render(cap)
            timings.append(dict(stage='render', frame=cap.frame_seq,
                seconds=time.monotonic()-start, age_s=time.monotonic()-cap.wall_time))
            return value
    camera = CameraProvider(sim, renderer_factory=Render)
    runtime = server = http = driver = None
    camera_closed = False
    started = time.monotonic()
    try:
        camera.start()
        if not ready.wait(10) or renderer_errors:
            raise RuntimeError('Renderer initialization failed: ' + str(renderer_errors))
        def factory():
            adapter = OfflineNativeAdapter(dict(fov_degrees=180., circle_radius_x_norm=1.,
                circle_radius_y_norm=1.), spec_path=a.native_spec, out=out/'native',
                registered_spec_sha=specsha, trace=trace)
            native_adapters.append(adapter)
            return adapter
        runtime = OfflineRuntime(backend, camera=camera, native_factory=factory,
            captures=24, host_delay_s=0., trace=trace)
        server = PlatformHTTPServer(TransportConfig(port=0,admission_policy=admission), runtime)
        http = threading.Thread(target=server.serve_forever, daemon=True)
        http.start()
        url = 'http://127.0.0.1:' + str(server.server_address[1])
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen',POLAR_SIM_ADMISSION_CREDENTIAL=credential)
        env.pop('PYTHONPATH', None)
        with (out / 'client.log').open('wb') as log:
            preload_started=time.monotonic()
            driver = subprocess.Popen([str(Path(a.client_python).absolute()),
                str(ROOT/'tools/offline_smoke/offline_client_driver.py'),
                str(a.client_root.absolute()), url, str(out)], cwd=a.client_root,
                env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            preload=wait_ready(driver,out,preload_request,preload_started,timeout_s=15.)
            preload_work=dict(physics_time_s=float(sim.time),captures=camera.capture_count,
                raw_published=camera.raw_published,native_requests=counts.get('native_request',0))
            if any(preload_work.values()):
                raise RuntimeError('Camera/native/physics work occurred before startup admission')
            (out/'PRELOAD_ADMISSION.json').write_text(json.dumps({
                'startup_ready':preload,'setup_seconds':time.monotonic()-preload_started,
                'pre_run_work_counters':preload_work,
                'setup_bound_s':15.,'parent_initial_binding_watchdog_s':5.,
                'client_watch_admission_bound_s':3.5,
                'readiness_is_network_or_lease_ack':False,
                'physics_or_capture_before_readiness':False},indent=2)+'\n')
            runtime.run(max_wall_seconds=90.)
    except Exception as exc:
        errors.append(type(exc).__name__ + ': ' + str(exc))
    finally:
        camera_closed = cleanup_resources(camera=camera, runtime=runtime, driver=driver,
            server=server, http=http, errors=errors)
    driverdata = {}
    if (out/'driver.json').exists():
        try:
            driverdata = json.loads((out/'driver.json').read_text())
        except (ValueError, OSError) as exc:
            errors.append('Unreadable original-client report: ' + str(exc))
    native_cleanup = inspect_native_cleanup(runtime, native_children)
    after_source_hashes = {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in execution_sources}
    source_unchanged = after_source_hashes == execution_hashes
    if not source_unchanged:
        errors.append('Execution source changed during actual run')
    resources = (native_cleanup['clean'] and camera_closed and (http is None or not http.is_alive())
        and (runtime is None or not runtime.worker or not runtime.worker.thread.is_alive()))
    state = runtime.state if runtime is not None else 'SETUP_FAILED'
    completed = runtime.completed_captures if runtime is not None else 0
    result = dict(profile=CRITERIA['profile'], state=state,
        reason=runtime.halt_reason if runtime is not None else 'setup_failed',
        completed_captures=completed, sim_time=sim.time, wall_seconds=time.monotonic()-started,
        counts=dict(counts), camera=camera.status(), renderer_timings=timings,
        driver_exit=driver.returncode if driver is not None else None,
        driver={k: v for k, v in driverdata.items() if k != 'last_state'},
        native_binary_sha256=spec['sha256']['binary'], spec_sha256=specsha,
        client_identity=client_identity, dependencies=dependencies, errors=errors,
        native_cleanup=native_cleanup, execution_source_unchanged=source_unchanged,
        execution_source_sha256=hashlib.sha256((out/'EXECUTED_SOURCE.json').read_bytes()).hexdigest())
    result.update(classify_result(state=state, captures=completed, counts=counts,
        driver=driverdata, resources_closed=resources and not errors,
        driver_exit=result['driver_exit']))
    (out/'ledger.jsonl').write_text(''.join(json.dumps(v)+'\n' for v in rows))
    (out/'RESULT.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: result[k] for k in ('state', 'counts', 'display_fresh_actual_frame',
        'diagnostic_transport_passed', 'qualified_static_offline_chain', 'clean_shutdown')}, indent=2))
    return 0 if result['diagnostic_transport_passed'] else 2


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--native-spec', type=Path)
    p.add_argument('--client-root', type=Path)
    p.add_argument('--client-python')
    p.add_argument('--out', type=Path)
    p.add_argument('--run', action='store_true')
    a = p.parse_args(argv)
    if not a.run:
        print(json.dumps(CRITERIA, indent=2))
        return 0
    for key in ('native_spec', 'client_root', 'client_python', 'out'):
        if getattr(a, key) is None:
            p.error('--' + key.replace('_', '-') + ' is required with --run')
    a.native_spec = a.native_spec.absolute()
    a.client_root = a.client_root.absolute()
    return run(a)


if __name__ == '__main__':
    raise SystemExit(main())
