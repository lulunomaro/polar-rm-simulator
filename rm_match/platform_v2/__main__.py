"""Start the v2 loopback-only experimental simulation server."""
import argparse
import json
import signal
import sys
import threading
from pathlib import Path
from .backend import MuJoCoBackend
from .runtime import PlatformRuntime
from .server import PlatformHTTPServer,TransportConfig

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--max-wall-seconds',type=float,default=300.)
    parser.add_argument('--camera',action='store_true',help='Opt in to actual role_v23 calibrated cameras')
    parser.add_argument('--camera-total-fps',type=float,default=2.)
    parser.add_argument('--host-opencv-threads',type=int,help='Explicit local host camera OpenCV thread option, 1..32')
    parser.add_argument('--virtual-resupply',choices=('disabled','v1-baseline'),default='disabled',
        help='Explicit scenario baseline automatic virtual ammo purchase; not full official-rule qualification')
    native=parser.add_mutually_exclusive_group()
    native.add_argument('--native-spec',help='Explicit trusted local frozen native source specification')
    native.add_argument('--wsl-native-spec',help='Explicit trusted Linux native spec for a locally prepared Windows WSL peer')
    parser.add_argument('--wsl-native-distribution',default='Ubuntu')
    parser.add_argument('--wsl-native-transport',choices=('wsl_stdio_v1','wsl_stdio_bgr_v2','wsl_async_bgr_v3'),default='wsl_stdio_v1')
    parser.add_argument('--private-native-pixels',action='store_true',help='Explicit sealed own-native pixels before public base64 encoding')
    parser.add_argument('--admission-manifest',required=True,
        help='Local server-owned role/robot grants; no implicit HTTP enrollment')
    parser.add_argument('--native-out',help='Local native process output root; never a network-selected executable')
    parser.add_argument('--aim-plugins-json',help='Trusted local manifest of negotiated camera/gimbal aim plugins')
    parser.add_argument('--prepare-aim-plugins',action='store_true',
        help='Explicit Windows WSL aim resource initialization before physics; binding reset still uses 2 seconds')
    navigation=parser.add_mutually_exclusive_group()
    navigation.add_argument('--pb-navigation-manifest',help='Explicit local PolarBear pointcloud/IMU navigation process manifest')
    navigation.add_argument('--pb-wsl-navigation-manifest',help='Opt-in trusted local Windows + WSL Humble navigation manifest; prepared before physics')
    parser.add_argument('--real-time-factor',type=float,default=1.,help='Maximum simulation/wall rate; wall leases and deadlines never scale')
    args=parser.parse_args(argv)
    if args.pb_wsl_navigation_manifest and sys.platform!='win32':parser.error('--pb-wsl-navigation-manifest requires a Windows host')
    from .admission import AdmissionPolicy
    admission=AdmissionPolicy.from_manifest(args.admission_manifest)
    if bool(args.native_spec or args.wsl_native_spec)!=bool(args.native_out):parser.error('A native spec and --native-out are required together')
    if (args.native_spec or args.wsl_native_spec) and not args.camera:parser.error('Native source requires --camera')
    if args.wsl_native_spec and sys.platform!='win32':parser.error('--wsl-native-spec requires a Windows host')
    if args.private_native_pixels and not args.wsl_native_spec:parser.error('--private-native-pixels requires --wsl-native-spec')
    if args.aim_plugins_json and not args.camera:parser.error('Aim plugins require --camera')
    if args.prepare_aim_plugins and not args.aim_plugins_json:parser.error('--prepare-aim-plugins requires --aim-plugins-json')
    if args.prepare_aim_plugins and sys.platform!='win32':parser.error('--prepare-aim-plugins currently requires a Windows host')
    if args.host_opencv_threads is not None and not 1<=args.host_opencv_threads<=32:parser.error('--host-opencv-threads must be within 1..32')
    if not 0<args.real_time_factor<=1:parser.error('--real-time-factor must be within (0, 1]')
    if not 0<args.max_wall_seconds<=3600:parser.error('--max-wall-seconds must be within (0, 3600]')
    backend=camera=runtime=server=http=session=aim_resources=wsl_native_registry=None;http_started=False;old_signals={}
    try:
        host_opencv=None
        if args.host_opencv_threads is not None:
            from .host_opencv import configure_opencv_threads
            host_opencv=configure_opencv_threads(args.host_opencv_threads)
        from .adapters import default_registry
        if args.wsl_native_spec:
            from ..deployment.wsl_registry import own_wsl_registry
            repo_root=Path(__file__).resolve().parents[2]
            registry=wsl_native_registry=own_wsl_registry(args.wsl_native_spec,args.native_out,repo_root=repo_root,
                distribution=args.wsl_native_distribution,transport=args.wsl_native_transport)
            # Actual model loading and stdin readiness, zero captured frames and
            # zero NN calls, precede the physics clock. Binding still resets.
            registry.prepare_native()
        else:registry=default_registry(native_spec=args.native_spec,native_out=args.native_out)
        if args.aim_plugins_json:
            from ..deployment.aim_plugin import register_aim_plugins
            if args.prepare_aim_plugins:
                from ..deployment.wsl_jsonl import PreparedWslAimPlugins
                repo_root=Path(__file__).resolve().parents[2]
                aim_resources=PreparedWslAimPlugins(args.aim_plugins_json,repo_root=repo_root,
                    shared_root=repo_root/'artifacts/aim-wsl')
            register_aim_plugins(registry,args.aim_plugins_json,wsl_prepared=aim_resources)
        if args.pb_wsl_navigation_manifest:
            from ..integrations.pb_wsl_navigation_registry import register_pb_wsl_navigation
            from ..integrations.pb_wsl_navigation import WslNavigationSession
            def own_session(*values,**settings):
                nonlocal session
                session=WslNavigationSession(*values,**settings)
                return session
            session=register_pb_wsl_navigation(registry,args.pb_wsl_navigation_manifest,
                repo_root=Path(__file__).resolve().parents[2],session_factory=own_session)
        elif args.pb_navigation_manifest:
            from ..integrations.pb_navigation_adapter import register_pb_navigation
            register_pb_navigation(registry,args.pb_navigation_manifest)
        navigation_config=None
        if args.pb_navigation_manifest or args.pb_wsl_navigation_manifest:
            from ..navigation_sensors import NavigationSensorConfig
            navigation_config=NavigationSensorConfig()
        backend=MuJoCoBackend(camera=args.camera,virtual_resupply=args.virtual_resupply,navigation_sensors=navigation_config)
        if args.camera:
            from .camera import CameraProvider
            camera=CameraProvider(backend._sim,total_fps=args.camera_total_fps,enable_native_pixels=args.private_native_pixels)
        runtime=PlatformRuntime(backend,camera=camera,registry=registry,enable_native_pixels=args.private_native_pixels)
        server=PlatformHTTPServer(TransportConfig(port=args.port,admission_policy=admission),runtime)
        http=threading.Thread(target=server.serve_forever,name='sim-v2-http',daemon=True);http.start();http_started=True
        def stop(*_):
            runtime.request_stop()
            if session is not None:session.request_stop()
        for sig in (signal.SIGINT,signal.SIGTERM):
            old_signals[sig]=signal.getsignal(sig);signal.signal(sig,stop)
        print(json.dumps(dict(url=f'http://127.0.0.1:{server.server_address[1]}',
            transport='loopback_only',virtual_resupply=args.virtual_resupply,camera='real_opt_in' if args.camera else 'unavailable_no_gl',cross_machine_LAN_verified=False,real_time_factor_limit=args.real_time_factor,native_registered=bool(args.native_spec),
            aim_plugins_registered=bool(args.aim_plugins_json),
            wsl_native_registered=bool(args.wsl_native_spec),
            wsl_native_transport=None if not args.wsl_native_spec else args.wsl_native_transport,
            prepared_aim_plugin_count=0 if aim_resources is None else len(aim_resources.instances),
            host_opencv=host_opencv,
            navigation_sensor_profile=None if navigation_config is None else navigation_config.identity(),
            pb_navigation_registered=bool(args.pb_navigation_manifest),
            pb_wsl_navigation_registered=bool(args.pb_wsl_navigation_manifest),
            pb_wsl_navigation_namespace=None if session is None else session.namespace,
            pb_wsl_navigation_domain=None if session is None else 84)),flush=True)
        runtime.run(max_wall_seconds=args.max_wall_seconds,real_time_factor=args.real_time_factor)
    finally:
        original_error=sys.exc_info()[1];errors=[]
        def finish(label,callback):
            try:callback()
            except BaseException as error:errors.append(label+':'+type(error).__name__+':'+str(error))
        if runtime is not None:finish('runtime_stop',runtime.request_stop)
        if session is not None:finish('session_stop',session.request_stop)
        if server is not None:
            # shutdown() waits for serve_forever(); calling it when thread.start
            # failed would deadlock instead of releasing the prepared session.
            if http_started or (http is not None and http.is_alive()):finish('http_shutdown',server.shutdown)
            finish('http_close',server.server_close)
        if http_started:
            finish('http_join',lambda:http.join(2.))
            if http.is_alive():errors.append('http_thread_unfinished')
        if runtime is not None:
            finish('runtime_close',runtime.close)
            if not getattr(runtime,'shutdown_status',{'clean':True}).get('clean',False):errors.append('runtime_shutdown_incomplete')
        elif backend is not None:finish('backend_close',backend.close)
        if session is not None:finish('session_close',session.close)
        if aim_resources is not None:finish('aim_unclaimed_close',aim_resources.close_unclaimed)
        if wsl_native_registry is not None:finish('wsl_native_unclaimed_close',wsl_native_registry.close)
        if camera is not None:
            finish('camera_stop',camera.stop)
            def close_camera():
                if not camera.wait_closed(2.):raise RuntimeError('camera_threads_unfinished')
            finish('camera_close',close_camera)
        for sig,handler in old_signals.items():finish('signal_restore',lambda s=sig,h=handler:signal.signal(s,h))
        if errors:raise RuntimeError('Platform CLI cleanup failed: '+';'.join(errors)) from original_error

if __name__=='__main__':main()
