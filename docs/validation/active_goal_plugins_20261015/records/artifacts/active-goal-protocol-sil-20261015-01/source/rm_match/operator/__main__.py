"""python -m rm_match.operator --port 8768 --robot red_infantry"""
import argparse
import json
import os
import sys

if sys.platform.startswith('linux') and not os.environ.get('DISPLAY'):
    os.environ.setdefault('MUJOCO_GL','egl')
    os.environ.setdefault('EGL_PLATFORM','surfaceless')
    os.environ.setdefault('MESA_SHADER_CACHE_DISABLE','true')
os.environ.setdefault('ORT_DISABLE_TELEMETRY','1')

from .protocol import ControlGate, ROBOT_IDS
from .server import BridgeState, start_server


def main():
    parser=argparse.ArgumentParser(description='Loopback-only MuJoCo human operator bridge. No hardware.')
    parser.add_argument('--port',type=int,default=8768)
    parser.add_argument('--robot',choices=ROBOT_IDS,default=None)
    parser.add_argument('--source-spec',help='Opt-in independently rebuilt stationary red_sentry native source spec')
    parser.add_argument('--source-out',default='artifacts/operator_source',help='Local source diagnostics output directory')
    parser.add_argument('--camera-fps',type=float,default=2.)
    parser.add_argument('--width',type=int,default=320)
    parser.add_argument('--height',type=int,default=240)
    parser.add_argument('--max-seconds',type=float,default=300.)
    parser.add_argument('--max-wall-seconds',type=float)
    parser.add_argument('--no-render',action='store_true',help='CPU control/referee QA only; camera endpoint returns 503')
    args=parser.parse_args()
    if not 0 < args.max_seconds <= 300:parser.error('--max-seconds must be in (0, 300]')
    if args.max_wall_seconds is not None and args.max_wall_seconds <= 0:parser.error('--max-wall-seconds must be positive')
    from .runtime import OperatorRuntime
    robot=args.robot or ('red_sentry' if args.source_spec else 'red_infantry')
    state=BridgeState(ControlGate(robot))
    options=dict(render=not args.no_render,camera_fps=args.camera_fps,width=args.width,height=args.height)
    if args.source_spec:
        if args.no_render:parser.error('--source-spec requires rendering')
        from .source_runtime import SourceOperatorRuntime
        runtime=SourceOperatorRuntime(state,source_spec=args.source_spec,source_out=args.source_out,**options)
    else:
        runtime=OperatorRuntime(state,**options)
    server,thread=start_server(state,args.port)
    print(json.dumps(dict(event='operator_bridge_ready',url=f'http://127.0.0.1:{server.server_address[1]}',
                          **state.session())),flush=True)
    try:
        runtime.run(max_seconds=args.max_seconds,max_wall_seconds=args.max_wall_seconds)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        state.stop('error',f'{type(exc).__name__}: {exc}')
        raise
    finally:
        runtime.close()
        print(json.dumps(dict(event='operator_bridge_stopped',**state.snapshot())),flush=True)
        server.shutdown();server.server_close();thread.join(timeout=3.)


if __name__=='__main__':main()
