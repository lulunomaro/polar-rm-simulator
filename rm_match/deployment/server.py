"""Own-RMCS server. No baseline, automatic binding, arming, or fire fallback."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import signal
import sys
import threading
from .profile import PROFILE, LIMITATIONS, own_registry, validate_t2_spec


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument('--native-spec', type=Path, required=True)
    p.add_argument('--native-out', type=Path, required=True)
    p.add_argument('--native-robot-scope', type=Path,help='Explicit local stationary robot identity scope')
    p.add_argument('--adapters-json', type=Path)
    p.add_argument('--aim-plugins-json', type=Path,help='Reviewed local calibrated-camera aim interface registrations')
    p.add_argument('--admission-manifest', type=Path, required=True,
                   help='Local server-owned role/robot grants; contains credential hashes only')
    p.add_argument('--port', type=int, default=8766)
    p.add_argument('--camera-total-fps', type=float, default=15.)
    p.add_argument('--max-wall-seconds', type=float, default=300.)
    p.add_argument('--real-time-factor', type=float, default=1.)
    a = p.parse_args(argv)
    if sys.platform != 'linux':
        p.error('Own RMCS native profile supports Linux only; Windows is unvalidated')
    if not 1024 <= a.port <= 65535 or not 0 < a.max_wall_seconds <= 3600:
        p.error('Nonprivileged loopback port and bounded wall duration required')
    if not 0 < a.camera_total_fps <= 15 or not 0 < a.real_time_factor <= 1:
        p.error('Camera FPS must be (0,15], real-time factor (0,1]')
    spec, spec_sha = validate_t2_spec(a.native_spec)
    from ..platform_v2.admission import AdmissionPolicy
    admission = AdmissionPolicy.from_manifest(a.admission_manifest)
    admission_sha = admission.manifest_sha256
    registry = own_registry(a.native_spec, a.native_out, adapters_json=a.adapters_json,aim_plugins_json=a.aim_plugins_json,native_robot_scope=a.native_robot_scope)
    from ..platform_v2.backend import MuJoCoBackend
    from ..platform_v2.camera import CameraProvider
    from ..platform_v2.runtime import PlatformRuntime
    from ..platform_v2.server import PlatformHTTPServer, TransportConfig
    backend = MuJoCoBackend(camera=True)
    camera = server = runtime = http = None
    try:
        camera = CameraProvider(backend._sim, total_fps=a.camera_total_fps)
        runtime = PlatformRuntime(backend, camera=camera, registry=registry)
        # Publish a first authoritative state before announcing readiness.
        runtime.step_once()
        admission.verify_manifest_unchanged(a.admission_manifest)
        server = PlatformHTTPServer(TransportConfig(port=a.port, admission_policy=admission), runtime)
        http = threading.Thread(target=server.serve_forever, name='own-rmcs-http', daemon=True)
        http.start()
        def stop(*_):
            runtime.request_stop()
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        admission.verify_manifest_unchanged(a.admission_manifest)
        print(json.dumps(dict(event='ready', profile=PROFILE,
            url=f'http://127.0.0.1:{a.port}', transport='loopback_only',
            native_registered=True, spec_sha256=spec_sha,
            admission_policy_sha256=admission_sha,
            source_identity=spec['source_identity'],
            adapter_ids=[v['adapter_id'] for v in registry.descriptors()],
            automatic_binding=False, fire_authority='manual_only',
            native_robot_scope=registry.get('aim_native_rmcs_v1').descriptor['native_robot_scope'],
            limitations=([x for x in LIMITATIONS if x!='stationary_red_sentry_only']+['stationary_locally_declared_robots_only']) if a.native_robot_scope else list(LIMITATIONS))), flush=True)
        runtime.run(max_wall_seconds=a.max_wall_seconds, real_time_factor=a.real_time_factor)
        if runtime.error:
            raise RuntimeError('Runtime stopped with error: ' + str(runtime.error))
    finally:
        if server:
            if http and http.is_alive():
                server.shutdown()
            server.server_close()
        if http:
            http.join(2.)
        if runtime:
            runtime.close()
        else:
            backend.close()
        if camera:
            camera.stop(); camera.wait_closed(2.)


if __name__ == '__main__':
    main()
