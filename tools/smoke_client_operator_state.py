#!/usr/bin/env python3
"""Bounded real HTTP/GL own-client transport smoke. No native, Qt GUI or fire.

Record static roster -> real camera -> claim -> lease HUD -> explicit arm ->
manual zero input -> explicit release -> absent own HUD. Default is criteria.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import secrets
import subprocess
import os
import threading
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
CRITERIA=dict(wall_seconds=5,robot='red_sentry',adapters_bound=0,native_inference=False,qt_gui=False,
    fire_commands=0,required=['static_roster_before_claim','actual_decoded_camera','claim_ack',
        'actual_lease_gated_own_hud','explicit_arm','release_ack','post_release_hud_absent','clean_shutdown'],
    qualification='Real local HTTP, MuJoCo GL and patched original client transport; no Qt GUI or native closed-loop claim')


def write(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')


def run(a):
    from rm_match.platform_v2.backend import MuJoCoBackend
    from rm_match.platform_v2.camera import CameraProvider
    from rm_match.platform_v2.runtime import PlatformRuntime
    from rm_match.platform_v2.server import PlatformHTTPServer,TransportConfig
    from rm_match.platform_v2.admission import AdmissionPolicy
    sys.path.insert(0,str(a.client_root.resolve()))
    from rm_client.sim_platform_transport import PlatformTransport
    from rm_client.sim_platform_client import PlatformClient,ClientError
    criteria=dict(CRITERIA,qt_offscreen_probe=bool(a.qt_python),visible_window=False)
    if a.qt_python:
        criteria['qualification']='Real local HTTP, MuJoCo GL and actual original Qt offscreen event-loop/render; no native or visible desktop claim'
        criteria.pop('qt_gui',None)
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);write(out/'CRITERIA.json',criteria)
    events=[];counts=Counter();errors=[];flags={k:False for k in CRITERIA['required']};driver_done=threading.Event()
    def event(name,**values):events.append(dict(event=name,wall=time.perf_counter(),**values))
    def trace(value):
        counts[value['event']]+=1
        if value['event']=='physics_apply':
            counts['fire_outputs_true']+=sum(bool(t['fire']) for t in value['targets'].values())
            target=value['targets']['red_sentry']
            counts['manual_motion_applied']+=target['motion'] is not None
            counts['manual_gimbal_applied']+=target['gimbal'] is not None
    backend=MuJoCoBackend(camera=True);camera=CameraProvider(backend._sim,total_fps=15,max_views=1)
    runtime=PlatformRuntime(backend,camera=camera,trace=trace);runtime.step_once()
    credential=secrets.token_urlsafe(32)
    policy=AdmissionPolicy([dict(credential_sha256=hashlib.sha256(credential.encode()).hexdigest(),
        role='operator',allowed_robots=['red_sentry'],audit_authorized=False)])
    server=PlatformHTTPServer(TransportConfig(port=0,admission_policy=policy),runtime)
    http=threading.Thread(target=server.serve_forever,name='operator-smoke-http',daemon=True);http.start()
    url='http://127.0.0.1:'+str(server.server_address[1])
    t=PlatformTransport(url,role='operator',admission_credential=credential)
    t.start()
    qt=None
    if a.qt_python:
        env=dict(os.environ,QT_QPA_PLATFORM='offscreen',POLAR_SIM_ADMISSION_CREDENTIAL=credential)
        env.pop('PYTHONPATH',None)
        qt_stdout=(out/'qt.stdout.log').open('wb');qt_stderr=(out/'qt.stderr.log').open('wb')
        qt=subprocess.Popen([str(a.qt_python.resolve()),str(ROOT/'tools/qt_client_operator_probe.py'),
            '--client-root',str(a.client_root.resolve()),'--endpoint',url,'--out',str(out/'qt')],
            cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=qt_stdout,stderr=qt_stderr)
    def driver():
        watched=False;claimed=False;armed=False;release_requested=False;armed_at=None;end=time.perf_counter()+5.
        try:
            while time.perf_counter()<end:
                with t._lock:
                    raw=t.raw_state;data=t.snapshot()[0]
                    if not watched and t.robot_ids:
                        write(out/'STATIC_STATE.json',raw);flags['static_roster_before_claim']=all(set(r)=={'robot_id','team','role'} for r in raw['robots'])
                        t.watch('red_sentry');watched=True;event('watch_requested')
                    if watched and not claimed and t.selection_ready():
                        flags['actual_decoded_camera']=t.video is not None
                        operator_frame=t.client.frame();write(out/'OPERATOR_FRAME.json',operator_frame)
                        flags['operator_frame_has_no_exposure_pose']=not any(k.startswith('own_') for k in operator_frame)
                        endpoint_values=dict(robots=t.client.robots(),capabilities=t.client._request('/v2/capabilities'),adapters=t.client.adapters())
                        write(out/'OPERATOR_ENDPOINTS.json',endpoint_values)
                        flags['operator_roster_is_admission_scoped']=t.robot_ids==('red_sentry',)
                        try:t.client.watch('blue_sentry')
                        except ClientError:flags['cross_team_watch_rejected']=True
                        try:PlatformClient(url,admission_credential=credential).open('spectator')
                        except ClientError:flags['operator_credential_cannot_get_audit_spectator']=True
                        try:PlatformClient(url).open('operator')
                        except ClientError:flags['anonymous_operator_denied']=True
                        t.request_claim();claimed=True;event('claim_requested')
                    if claimed and t.owned_robot=='red_sentry':flags['claim_ack']=True
                    if not armed and not release_requested and t.operator_hud_ready():
                        write(out/'LEASED_STATE.json',raw);write(out/'LEASED_HUD.json',data)
                        flags['actual_lease_gated_own_hud']=data is not None and data.get('own') is not None
                        armed=t.activate();flags['explicit_arm']=armed;armed_at=time.perf_counter();event('armed',armed=armed)
                    if armed and not release_requested:
                        t.heartbeat(True);t.submit_input(vx_mps=0.,vy_mps=0.,fire=False)
                        if time.perf_counter()-armed_at>=.20:
                            import cv2
                            if t.video is not None:cv2.imwrite(str(out/'ACTUAL_CAMERA.png'),t.video)
                            t.neutral('Explicit smoke release');release_requested=True;event('release_requested')
                            write(out/'IMMEDIATE_RELEASE_HUD.json',t.snapshot()[0])
                            flags['immediate_release_hud_cache_cleared']=all(set(r)=={'robot_id','team','role'} for r in t.snapshot()[0]['robots'])
                    if release_requested and raw is not None:
                        leases=raw['control']['leases']['red_sentry']
                        if all(leases[c]['owner'] is None for c in ('motion','gimbal','fire')):
                            write(out/'RELEASED_STATE.json',raw);write(out/'RELEASED_HUD.json',data)
                            flags['release_ack']=True;flags['post_release_hud_absent']=data is not None and data.get('own') is None
                            event('released_state_observed');driver_done.set();return
                time.sleep(.01)
        except BaseException as exc:
            errors.append('driver: '+repr(exc));(out/'driver.error.log').write_text(traceback.format_exc(),encoding='utf-8')
        finally:driver_done.set()
    worker=threading.Thread(target=driver,name='operator-smoke-driver',daemon=True);worker.start()
    try:runtime.run(max_wall_seconds=5,real_time_factor=1.)
    except BaseException as exc:
        errors.append('runtime: '+repr(exc));(out/'runtime.error.log').write_text(traceback.format_exc(),encoding='utf-8')
    finally:
        worker.join(2.);t.stop();camera_closed=camera.wait_closed(5.)
        server.shutdown();server.server_close();http.join(2.)
        flags['clean_shutdown']=camera_closed and not worker.is_alive() and not http.is_alive() and not t._threads
    result=dict(schema='polar.sim.own_client_operator_state.smoke.v1',criteria=criteria,checks=flags,
        counts=dict(counts),errors=errors,physics_steps=runtime.steps,camera=camera.status(),
        client_head='0cedf99b70b1beec99865b9980af6789e6c53d99',
        transport_sha256=hashlib.sha256((a.client_root/'rm_client/sim_platform_transport.py').read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
        qualification=criteria['qualification'])
    diagnostics=t.diagnostics()
    flags['credential_absent_from_diagnostics']=credential not in json.dumps(diagnostics)
    if qt:
        try:
            qt.wait(timeout=3.)
            qt_result=json.loads((out/'qt/RESULT.json').read_text())
            flags['actual_qt_offscreen_display']=qt.returncode==0 and qt_result.get('passed') is True
            result['qt']=qt_result
        except BaseException as exc:
            if qt.poll() is None:qt.kill();qt.wait()
            errors.append('actual Qt probe: '+repr(exc));flags['actual_qt_offscreen_display']=False
        finally:qt_stdout.close();qt_stderr.close()
    counts['manual_control_http_requests']=sum(e.get('event')=='request_started' and e.get('path')=='/v2/control' for e in diagnostics['sdk']['events'])
    result['counts']=dict(counts)
    result['passed']=all(flags.values()) and not errors and counts.get('fire_outputs_true',0)==0 and counts['manual_motion_applied']>0 and counts['manual_gimbal_applied']>0
    write(out/'events.json',events);write(out/'client_diagnostics.json',diagnostics);write(out/'RESULT.json',result)
    print(json.dumps(result,indent=2));return 0 if result['passed'] else 2


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client-root',type=Path,default=ROOT/'external/polar-rm-client-state-review')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--qt-python',type=Path,help='Run actual original Qt offscreen event-loop probe alongside HTTP/GL')
    args=parser.parse_args()
    if not args.run:print(json.dumps(CRITERIA,indent=2));return 0
    return run(args)


if __name__=='__main__':raise SystemExit(main())
