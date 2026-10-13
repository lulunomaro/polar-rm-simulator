#!/usr/bin/env python3
"""Explicit five-wall-second local, no-fire native/HTTP/camera smoke.

Default prints acceptance criteria only. --run starts actual local simulation and
native inference; it never installs anything, relaxes deadlines or claims a match.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CRITERIA = dict(wall_seconds=5, real_time_factor=1, camera_total_fps=15,
    robot='red_sentry', claimed_channels=['gimbal'], fire_commands='none',
    required=['real_physics_steps', 'real_camera_frame', 'HTTP_session_and_native_binding',
              'native_request_and_result', 'native_gimbal_consumed_before_original_deadline',
              'all_fire_outputs_false', 'clean_shutdown'],
    optional_qt_required_if_requested=['zero_exit','Qt_event_loop','catalog','watch','decoded_frame'],
    unchanged_gates=['150ms_server_window', '80ms_native_camera_age', 'existing_action_ttl'],
    qualification='Bounded smoke only; no full match, aim accuracy or visible desktop claim')


def classify_result(*, steps, camera, counts, driver, errors, resources_closed, driver_exit, qt_requested):
    native = all(counts.get(k, 0) > 0 for k in ('native_request', 'native_result', 'red_native_gimbal_consumed'))
    qt_data = driver.get('qt_offscreen')
    qt_ok = not qt_requested or (driver.get('qt_exit_code') == 0 and isinstance(qt_data, dict)
        and all(qt_data.get(k) is True for k in ('qt_event_loop', 'catalog', 'watched', 'frame_decoded')))
    closed = (resources_closed and driver_exit == 0 and driver.get('session_closed') is True
              and not driver.get('close_error') and (not qt_requested or driver.get('qt_exit_code') == 0))
    passed = (native and not errors and closed and steps > 0 and camera.get('rendered', 0) > 0
              and counts.get('fire_outputs_true', 0) == 0 and qt_ok)
    return dict(clean_shutdown=closed, native_closed_loop_observed=native,
                qt_requested=qt_requested, qt_offscreen_passed=qt_ok if qt_requested else None,
                result=('passed_bounded_smoke' if qt_requested else 'passed_bounded_native_only_smoke')
                    if passed else 'incomplete_or_failed_bounded_smoke')


def run(a):
    from rm_match.deployment.profile import own_registry, validate_t2_spec
    from rm_match.platform_v2.backend import MuJoCoBackend
    from rm_match.platform_v2.camera import CameraProvider, MuJoCoCameraRenderer
    from rm_match.platform_v2.runtime import PlatformRuntime
    from rm_match.platform_v2.server import PlatformHTTPServer, TransportConfig
    from rm_match.platform_v2.client import PlatformClient
    from rm_match.deployment.enrollment import provision_operator
    from rm_match.platform_v2.admission import AdmissionPolicy
    out = a.out.absolute(); out.mkdir(parents=True, exist_ok=False)
    credential=provision_operator(out/'admission.json')
    admission=AdmissionPolicy.from_manifest(out/'admission.json')
    (out / 'ACCEPTANCE_CRITERIA.json').write_text(json.dumps(CRITERIA, indent=2) + '\n')
    spec, spec_sha = validate_t2_spec(a.native_spec)
    counts = Counter(); events = []; errors = []; driver_data = {}
    lock = threading.Lock()
    def trace(event):
        with lock:
            name = event['event']; counts[name] += 1
            if name == 'physics_apply':
                targets = event['targets']
                counts['fire_outputs_true'] += sum(bool(v['fire']) for v in targets.values())
                counts['red_native_gimbal_consumed'] += targets['red_sentry']['gimbal'] is not None
            elif name == 'adapter_result':
                counts['adapter_result_late'] += event['completed_wall'] >= event['wall_deadline']
                counts['adapter_result_error'] += event['error'] is not None
            if name not in ('physics_apply', 'integration_boundary', 'actuator_consumed') and len(events) < 1000:
                events.append(event)
    registry = own_registry(a.native_spec, out / 'native', native_trace=trace)
    backend = MuJoCoBackend(camera=True)
    render_timings = []
    class TimedRenderer:
        def __init__(self, model, camera_profile):
            started = time.monotonic()
            self.delegate = MuJoCoCameraRenderer(model, camera_profile)
            render_timings.append(dict(stage='renderer_init', duration_s=time.monotonic()-started))
        def render(self, cap):
            started = time.monotonic()
            pixels = self.delegate.render(cap)
            render_timings.append(dict(stage='render', frame=cap.frame_seq, duration_s=time.monotonic()-started,
                                       capture_age_at_start_s=started-cap.wall_time,
                                       capture_age_at_finish_s=time.monotonic()-cap.wall_time))
            return pixels
        def close(self):
            self.delegate.close()
    class TimedCamera(CameraProvider):
        def _encode(self, cap, pixels):
            started = time.monotonic()
            result = super()._encode(cap, pixels)
            render_timings.append(dict(stage='encode', frame=cap.frame_seq, duration_s=time.monotonic()-started,
                                       capture_age_at_finish_s=time.monotonic()-cap.wall_time))
            return result
    camera = TimedCamera(backend._sim, total_fps=15, renderer_factory=TimedRenderer)
    runtime = PlatformRuntime(backend, camera=camera, registry=registry, trace=trace)
    runtime.step_once()  # Initial episode exists before an HTTP binding can be admitted.
    server = PlatformHTTPServer(TransportConfig(port=0,admission_policy=admission), runtime)
    http = threading.Thread(target=server.serve_forever, daemon=True); http.start()
    url = 'http://127.0.0.1:' + str(server.server_address[1])
    stop_path = out / 'driver.stop'
    driver_result = out / 'driver_result.json'
    driver_code = r'''import json,os,sys,time
from pathlib import Path
from rm_match.platform_v2.client import PlatformClient
url,stop_path,result_path=sys.argv[1:]
c=PlatformClient(url,control_profile='server_window_v1',admission_credential=os.environ.get('POLAR_SIM_ADMISSION_CREDENTIAL')); r={'activation_pulses':0,'max_activation_gap_s':0.0}; previous=None
try:
 c.open('operator'); c.watch('red_sentry'); c.claim('red_sentry',['gimbal'])
 b=c.bind('red_sentry','aim','aim_native_rmcs_v1',{}); r['native_binding']=b['adapter_id']
 end=time.monotonic()+7; renew_at=0
 while not Path(stop_path).exists() and time.monotonic()<end:
  now=time.monotonic()
  if now>=renew_at: c.keepalive(); c.renew('red_sentry',['gimbal']); renew_at=now+.25
  w=c.control_window('red_sentry',['gimbal']); c.adapter_input('red_sentry','aim',b['binding_epoch'],window_id=w['window_id'],valid_for_s=.15)
  now=time.monotonic()
  if previous is not None:r['max_activation_gap_s']=max(r['max_activation_gap_s'],now-previous)
  previous=now;r['activation_pulses']+=1;time.sleep(.02)
except Exception as e:r['error']=type(e).__name__+': '+str(e)
finally:
 try:c.close();r['session_closed']=True
 except Exception as e:r['close_error']=str(e)
 Path(result_path).write_text(json.dumps(r))
'''
    driver = subprocess.Popen([sys.executable, '-c', driver_code, url, str(stop_path), str(driver_result)],
                              cwd=ROOT, env=dict(os.environ,POLAR_SIM_ADMISSION_CREDENTIAL=credential),
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    qt = None
    if a.client_python and a.client_root:
        # Original client's transport + Qt event loop, without constructing a
        # visible window or claiming a vehicle. This is explicitly offscreen.
        code = '''import json,sys,time
from PySide6.QtWidgets import QApplication
from rm_client.sim_platform_transport import PlatformTransport
app=QApplication(['sim-smoke-offscreen']); t=PlatformTransport(sys.argv[1],role='operator')
t.start(); end=time.monotonic()+6.0; watched=False; seen=False; catalog=False
while time.monotonic()<end:
 app.processEvents()
 if t.robot_ids and not watched: t.watch('red_sentry'); watched=True
 seen=seen or t.video is not None; catalog=catalog or t.catalog.get('ready',False)
 time.sleep(.02)
r=dict(qt_event_loop=True,pinned_client_transport=True,watched=watched,frame_decoded=seen,catalog=catalog,visible_window=False,role='operator')
t.stop(); print(json.dumps(r),flush=True)
'''
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen',POLAR_SIM_ADMISSION_CREDENTIAL=credential); env.pop('PYTHONPATH', None)
        qt = subprocess.Popen([str(a.client_python.absolute()), '-c', code, url],
            cwd=a.client_root.absolute(), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        runtime.run(max_wall_seconds=5, real_time_factor=1.)
    except Exception as exc:
        errors.append('runtime: ' + type(exc).__name__ + ': ' + str(exc))
    finally:
        stop_path.write_text('stop\n')
        try:
            _, driver_stderr = driver.communicate(timeout=2.)
        except subprocess.TimeoutExpired:
            driver.kill(); _, driver_stderr = driver.communicate(timeout=2.)
        (out / 'driver.stderr.log').write_bytes(driver_stderr)
        if driver_result.exists():
            driver_data.update(json.loads(driver_result.read_text()))
        if driver_data.get('error') and 'runtime_stopped' not in driver_data['error']:
            errors.append('operator_client: ' + driver_data['error'])
        runtime.close()
        for slot in runtime.slots.values():
            slot.thread.join(3.)
        camera_closed = camera.wait_closed(3.)
        server.shutdown(); server.server_close(); http.join(2.)
    if qt:
        try:
            stdout, stderr = qt.communicate(timeout=3.)
            driver_data['qt_exit_code'] = qt.returncode
            driver_data['qt_offscreen'] = json.loads(stdout.strip().splitlines()[-1]) if stdout.strip() else None
            (out / 'qt.stderr.log').write_text(stderr)
        except Exception as exc:
            qt.kill(); qt.wait(timeout=2.)
            errors.append('qt_offscreen: ' + str(exc))
    camera_status = camera.status()
    acceptance = classify_result(steps=runtime.steps, camera=camera_status, counts=counts,
        driver=driver_data, errors=errors, resources_closed=camera_closed and all(
            not s.thread.is_alive() for s in runtime.slots.values()), driver_exit=driver.returncode, qt_requested=qt is not None)
    result = dict(schema='polar.sim.deployment.smoke.v1', spec_sha256=spec_sha,
        binary_sha256=spec['sha256']['binary'], criteria=CRITERIA, counts=dict(counts),
        physics_steps=runtime.steps, camera=camera_status, camera_capture_count=camera.capture_count,
        renderer_timings=render_timings, driver=driver_data,
        errors=errors, driver_exit_code=driver.returncode, **acceptance,
        final_algorithm_status={str(k): v for k, v in runtime.status.items()})
    (out / 'events.json').write_text(json.dumps(events, indent=2) + '\n')
    (out / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['result'] in ('passed_bounded_smoke', 'passed_bounded_native_only_smoke') else 2


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--native-spec', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--client-python', type=Path)
    p.add_argument('--client-root', type=Path)
    p.add_argument('--run', action='store_true')
    a = p.parse_args()
    if bool(a.client_python) != bool(a.client_root):
        p.error('--client-python and --client-root must be provided together')
    if not a.run:
        print(json.dumps(CRITERIA, indent=2)); return 0
    cache = a.out.absolute() / 'cache'
    os.environ['XDG_CACHE_HOME'] = str(cache)
    os.environ['MESA_SHADER_CACHE_DIR'] = str(cache / 'mesa')
    return run(a)


if __name__ == '__main__':
    raise SystemExit(main())
