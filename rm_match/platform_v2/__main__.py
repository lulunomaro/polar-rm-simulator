"""Start the v2 loopback-only experimental simulation server."""
import argparse
import json
import signal
import threading
from .backend import MuJoCoBackend
from .runtime import PlatformRuntime
from .server import PlatformHTTPServer,TransportConfig

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--max-wall-seconds',type=float,default=300.)
    parser.add_argument('--camera',action='store_true',help='Opt in to actual role_v23 calibrated cameras')
    parser.add_argument('--camera-total-fps',type=float,default=2.)
    parser.add_argument('--virtual-resupply',choices=('disabled','v1-baseline'),default='disabled',
        help='Explicit scenario baseline automatic virtual ammo purchase; not full official-rule qualification')
    parser.add_argument('--native-spec',help='Explicit trusted local frozen native source specification')
    parser.add_argument('--native-out',help='Local native process output root; never a network-selected executable')
    parser.add_argument('--real-time-factor',type=float,default=1.,help='Maximum simulation/wall rate; wall leases and deadlines never scale')
    args=parser.parse_args()
    if bool(args.native_spec)!=bool(args.native_out):parser.error('--native-spec and --native-out are required together')
    if args.native_spec and not args.camera:parser.error('Native source requires --camera')
    if not 0<args.real_time_factor<=1:parser.error('--real-time-factor must be within (0, 1]')
    if not 0<args.max_wall_seconds<=3600:parser.error('--max-wall-seconds must be within (0, 3600]')
    backend=MuJoCoBackend(camera=args.camera,virtual_resupply=args.virtual_resupply);camera=None
    if args.camera:
        from .camera import CameraProvider
        camera=CameraProvider(backend._sim,total_fps=args.camera_total_fps)
    from .adapters import default_registry
    registry=default_registry(native_spec=args.native_spec,native_out=args.native_out)
    runtime=PlatformRuntime(backend,camera=camera,registry=registry)
    server=PlatformHTTPServer(TransportConfig(port=args.port),runtime)
    http=threading.Thread(target=server.serve_forever,name='sim-v2-http',daemon=True);http.start()
    def stop(*_):runtime.request_stop()
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    print(json.dumps(dict(url=f'http://127.0.0.1:{server.server_address[1]}',
        transport='loopback_only',virtual_resupply=args.virtual_resupply,camera='real_opt_in' if args.camera else 'unavailable_no_gl',cross_machine_LAN_verified=False,real_time_factor_limit=args.real_time_factor,native_registered=bool(args.native_spec))),flush=True)
    try:runtime.run(max_wall_seconds=args.max_wall_seconds,real_time_factor=args.real_time_factor)
    finally:
        server.shutdown();server.server_close();http.join(2.)
        if camera is not None:camera.wait_closed(2.)

if __name__=='__main__':main()
