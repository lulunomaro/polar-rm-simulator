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
    parser.add_argument('--virtual-resupply',choices=('disabled','v1-baseline'),default='disabled',
        help='Explicit scenario baseline automatic virtual ammo purchase; not full official-rule qualification')
    parser.add_argument('--native-spec',help='Explicit trusted local frozen native source specification')
    parser.add_argument('--admission-manifest',required=True,
        help='Local server-owned role/robot grants; no implicit HTTP enrollment')
    parser.add_argument('--native-out',help='Local native process output root; never a network-selected executable')
    navigation=parser.add_mutually_exclusive_group()
    navigation.add_argument('--pb-navigation-manifest',help='Explicit local PolarBear pointcloud/IMU navigation process manifest')
    navigation.add_argument('--pb-wsl-navigation-manifest',help='Opt-in trusted local Windows + WSL Humble navigation manifest; prepared before physics')
    parser.add_argument('--real-time-factor',type=float,default=1.,help='Maximum simulation/wall rate; wall leases and deadlines never scale')
    args=parser.parse_args(argv)
    if args.pb_wsl_navigation_manifest and sys.platform!='win32':parser.error('--pb-wsl-navigation-manifest requires a Windows host')
    from .admission import AdmissionPolicy
    admission=AdmissionPolicy.from_manifest(args.admission_manifest)
    if bool(args.native_spec)!=bool(args.native_out):parser.error('--native-spec and --native-out are required together')
    if args.native_spec and not args.camera:parser.error('Native source requires --camera')
    if not 0<args.real_time_factor<=1:parser.error('--real-time-factor must be within (0, 1]')
    if not 0<args.max_wall_seconds<=3600:parser.error('--max-wall-seconds must be within (0, 3600]')
    backend=camera=runtime=server=http=session=None;http_started=False;old_signals={}
    try:
        from .adapters import default_registry
        registry=default_registry(native_spec=args.native_spec,native_out=args.native_out)
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
            camera=CameraProvider(backend._sim,total_fps=args.camera_total_fps)
        runtime=PlatformRuntime(backend,camera=camera,registry=registry)
        server=PlatformHTTPServer(TransportConfig(port=args.port,admission_policy=admission),runtime)
        http=threading.Thread(target=server.serve_forever,name='sim-v2-http',daemon=True);http.start();http_started=True
        def stop(*_):
            runtime.request_stop()
            if session is not None:session.request_stop()
        for sig in (signal.SIGINT,signal.SIGTERM):
            old_signals[sig]=signal.getsignal(sig);signal.signal(sig,stop)
        print(json.dumps(dict(url=f'http://127.0.0.1:{server.server_address[1]}',
            transport='loopback_only',virtual_resupply=args.virtual_resupply,camera='real_opt_in' if args.camera else 'unavailable_no_gl',cross_machine_LAN_verified=False,real_time_factor_limit=args.real_time_factor,native_registered=bool(args.native_spec),
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
        if camera is not None:
            finish('camera_stop',camera.stop)
            def close_camera():
                if not camera.wait_closed(2.):raise RuntimeError('camera_threads_unfinished')
            finish('camera_close',close_camera)
        for sig,handler in old_signals.items():finish('signal_restore',lambda s=sig,h=handler:signal.signal(s,h))
        if errors:raise RuntimeError('Platform CLI cleanup failed: '+';'.join(errors)) from original_error

if __name__=='__main__':main()
