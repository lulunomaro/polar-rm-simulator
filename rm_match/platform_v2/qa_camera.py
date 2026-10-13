"""Bounded real MuJoCo/EGL camera qualification; loopback only, not native aim/LAN."""
import argparse
import base64
import io
import json
from pathlib import Path
import threading
import time
from PIL import Image
from .backend import MuJoCoBackend
from .camera import CameraProvider,MuJoCoCameraRenderer
from .runtime import PlatformRuntime
from .server import PlatformHTTPServer,TransportConfig
from .qa_multiclient import HTTPClient


def run(out):
    if not __debug__:raise RuntimeError('Qualification requires Python without -O')
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    identities={};checks=[];errors=[];samples={}
    class RecordedRenderer(MuJoCoCameraRenderer):
        def __init__(self,*args):
            identities['created']=threading.get_ident();super().__init__(*args)
            from OpenGL.GL import glGetString,GL_RENDERER,GL_VENDOR,GL_VERSION
            identities.update(gl_renderer=glGetString(GL_RENDERER).decode(),gl_vendor=glGetString(GL_VENDOR).decode(),gl_version=glGetString(GL_VERSION).decode())
        def render(self,cap):
            identities.setdefault('render_threads',[])
            if threading.get_ident() not in identities['render_threads']:identities['render_threads'].append(threading.get_ident())
            return super().render(cap)
        def close(self):identities['closed']=threading.get_ident();super().close()
    backend=MuJoCoBackend(camera=True);provider=CameraProvider(backend._sim,renderer_factory=RecordedRenderer,total_fps=2.)
    runtime=PlatformRuntime(backend,camera=provider);server=PlatformHTTPServer(TransportConfig(port=0),runtime)
    def authority():
        try:runtime.run(max_wall_seconds=30.)
        except Exception as exc:errors.append(type(exc).__name__+': '+str(exc))
    http=threading.Thread(target=server.serve_forever,daemon=True,name='qa-camera-http')
    physics=threading.Thread(target=authority,daemon=True,name='qa-camera-physics')
    http.start();physics.start();base=f'http://127.0.0.1:{server.server_address[1]}'
    a,b,s=[HTTPClient(base) for _ in range(3)]
    def check(name,condition,evidence=None):
        checks.append(dict(name=name,passed=bool(condition),evidence=evidence))
        if not condition:raise RuntimeError('Failed check: '+name)
    def frame(client,timeout=12):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            value=client.call('/v2/frame')
            if value.get('available'):return value
            if provider.error:raise RuntimeError('Renderer error: '+provider.error)
            time.sleep(.025)
        raise RuntimeError('Camera frame timeout')
    def slim(value):return {k:v for k,v in value.items() if k!='image'}
    try:
        sessions=[a.open('operator'),b.open('operator'),s.open('spectator')]
        check('three_independent_sessions',len({v['session_id'] for v in sessions})==3)
        ra='red_sentry';rb='blue_sentry'
        wa=a.call('/v2/watch',{'robot_id':ra});wb=b.call('/v2/watch',{'robot_id':rb});ws=s.call('/v2/watch',{'robot_id':ra})
        before=s.call('/v2/state');check('subscriptions_have_no_control_leases',all(x['owner'] is None for rows in before['control']['leases'].values() for x in rows.values()))
        fa,fb,fs=frame(a),frame(b),frame(s)
        for name,value,rid,watch in [('a',fa,ra,wa),('b',fb,rb,wb),('spectator',fs,ra,ws)]:
            check(name+'_correct_robot_episode_generation',value['robot_id']==rid and value['episode']==0 and value['watch_epoch']==watch['watch_epoch'])
            check(name+'_fresh_exposure_not_encode_restamped',0<=value['age_wall_s']<=value['max_frame_age_wall_s'] and value['capture_wall_monotonic']<=value['encode_completed_wall_monotonic'])
            check(name+'_real_full_resolution_calibration',value['source']=='simulated_raw_camera_display_jpeg' and value['full_frame'] and (value['image']['width'],value['image']['height'])==(1440,1080) and rid in value['calibration']['extrinsics']['calibration_id'])
            raw=base64.b64decode(value['image']['data_base64'],validate=True);im=Image.open(io.BytesIO(raw));im.load()
            check(name+'_jpeg_decodes_actual_dimensions',im.size==(1440,1080) and len(im.getextrema())==3 and any(high>low for low,high in im.getextrema()))
            (out/(name+'-real-camera.jpg')).write_bytes(raw);samples[name]=slim(value)
        check('two_camera_pixels_are_distinct',fa['image']['data_base64']!=fb['image']['data_base64'])
        state=s.call('/v2/state');check('single_physics_time_advanced_during_render',state['steps']>before['steps'] and state['sim_time']>before['sim_time'],dict(before=before['sim_time'],after=state['sim_time'],steps=state['steps']))
        check('one_renderer_separate_from_physics',identities['render_threads']==[identities['created']] and identities['created']!=state['authority_thread'],identities.copy())
        check('judge_display_real_fields',all(set(('max_hp','ammo','heat','heat_max'))<=r.keys() for r in state['robots']) and state['remaining_seconds']==max(0.,state['duration_seconds']-state['judge_sim_time']) and state['victory_points']=={'red':200,'blue':200})
        check('display_truth_not_algorithm_input',state['source']=='simulator_truth_display_only' and state['algorithm_input'] is False)
        rejected=s.call('/v2/claim',{'robot_id':ra,'channels':['motion']},expect=403);check('spectator_never_gets_write_rights',rejected['error']=='read_only_session')
        ae=a.call('/v2/claim',{'robot_id':ra,'channels':['motion']})['lease_epochs'];be=b.call('/v2/claim',{'robot_id':rb,'channels':['motion']})['lease_epochs']
        for seq in range(8):
            for c,rid,ep,vx in [(a,ra,ae,.2),(b,rb,be,.35)]:
                c.call('/v2/renew',dict(robot_id=rid,lease_epochs=ep))
                c.call('/v2/control',dict(robot_id=rid,channel='motion',lease_epoch=ep['motion'],seq=seq,value=dict(frame='base_link',vx_mps=vx,vy_mps=0.,wz_rps=0.),valid_for_s=.15))
            time.sleep(.04)
        active=s.call('/v2/state');check('two_motion_leases_independent',active['applied_targets'][ra]['motion']['vx_mps']==.2 and active['applied_targets'][rb]['motion']['vx_mps']==.35)
        start=time.monotonic();a.call('/v2/release',dict(robot_id=ra,lease_epochs=ae));release_elapsed=time.monotonic()-start
        time.sleep(.05);released=s.call('/v2/state');check('lease_release_unblocked_by_camera',release_elapsed<.15 and released['applied_targets'][ra]['motion'] is None,dict(http_release_wall_s=release_elapsed))
        time.sleep(.2);timed=s.call('/v2/state');check('disconnect_input_expiry_with_renderer_running',timed['applied_targets'][rb]['motion'] is None)
        switched=a.call('/v2/watch',{'robot_id':rb});pending=a.call('/v2/frame');check('switch_rejects_existing_other_robot_cache',not pending['available'] and pending['robot_id']==rb and pending['watch_epoch']==switched['watch_epoch'] and 'image' not in pending)
        new=frame(a);check('switch_receives_only_new_generation',new['robot_id']==rb and new['watch_epoch']==switched['watch_epoch'] and new['frame_seq']>fb['frame_seq'])
        check('observer_watch_unchanged_by_operator_switch',frame(s)['watch_epoch']==ws['watch_epoch'])
        a.call('/v2/watch',{'robot_id':None});empty=a.call('/v2/frame');check('unsubscribe_clears_frame',not empty['available'] and empty['robot_id'] is None and 'image' not in empty)
        b.call('/v2/close',{});check('closed_session_cannot_get_frame',b.call('/v2/frame',expect=401)['error']=='invalid_session')
        check('native_source_not_silently_enabled',next(x for x in s.call('/v2/adapters')['adapters'] if x['adapter_id']=='aim_native_rmcs_v1')['available'] is False)
        samples['camera_status']=provider.status();check('bounded_camera_resources',samples['camera_status']['pending']<=6 and samples['camera_status']['cached']<=6 and samples['camera_status']['max_renderer_threads']==1)
        runtime.request_stop();physics.join(2);stopped=s.call('/v2/frame');check('runtime_stop_rejects_cached_image',not stopped['available'] and stopped['reason']=='runtime_stopped' and 'image' not in stopped)
        check('renderer_cleanly_closes_own_context',provider.wait_closed(3) and identities['closed']==identities['created'])
        check('physics_no_error',not errors and runtime.error is None and not physics.is_alive())
        return dict(scope='same_machine_loopback_real_cameras_not_LAN_or_native_aim',passed=True,checks=checks,samples=samples,renderer=identities,
            limitations=['CPU llvmpipe low FPS only','source YAML calibration resolution association remains ASSUMED','native aim live inference not exercised','no third party models or CAD bundled'])
    finally:
        runtime.request_stop();physics.join(2);provider.wait_closed(3);server.shutdown();server.server_close();http.join(2)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True);args=p.parse_args();result=run(args.out)
    path=Path(args.out)/'qualification.json';path.write_text(json.dumps(result,indent=2));print(json.dumps(dict(passed=result['passed'],checks=len(result['checks']),report=str(path))))
if __name__=='__main__':main()
