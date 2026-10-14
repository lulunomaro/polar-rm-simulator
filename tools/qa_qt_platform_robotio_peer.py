"""Original PlatformWindow + real admitted HTTP camera, offscreen protocol probe.

No synthetic state, image, clock or focus predicate. The parent continuously
advances physics/camera before any ready event. GO marks a measurement interval
after actual Jello selection, two F2 events, own HUD and real binding. This is
offscreen Qt internal show, not visible desktop or successful Qt GL rendering.
Only explicitly supplied CLI arguments execute this peer; no default launch.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
PINNED_BASE = '0cedf99b70b1beec99865b9980af6789e6c53d99'
MANIFEST = ROOT / 'client_patches/CLIENT_ROBOTIO_PATCH_MANIFEST.json'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--client-root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    parser.add_argument('--url', required=True)
    parser.add_argument('--robot-id', default='red_infantry')
    parser.add_argument('--adapter-id', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--max-wall-seconds', '--duration', dest='max_wall_seconds', type=float, default=15.)
    parser.add_argument('--run-seconds', type=float, default=3.)
    parser.add_argument('--host-opencv-threads', type=int, choices=range(1,33))
    parser.add_argument('--host-python-switch-interval-ms', type=float)
    args = parser.parse_args(argv)
    if (not math.isfinite(args.max_wall_seconds) or not 8 <= args.max_wall_seconds <= 20
        or not math.isfinite(args.run_seconds) or not 1 <= args.run_seconds <= 4
        or args.run_seconds + 3 >= args.max_wall_seconds):
        raise ValueError('bounded_actual_window_probe_budget')
    if args.host_python_switch_interval_ms is not None and (
        not math.isfinite(args.host_python_switch_interval_ms)
        or not .1 <= args.host_python_switch_interval_ms <= 10):
        raise ValueError('bounded_host_python_switch_interval')
    if (args.client_root.is_symlink() or args.manifest.is_symlink()
        or not args.client_root.is_dir() or not args.manifest.is_file()):
        raise ValueError('plain_local_client_and_manifest_required')
    if os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
        raise RuntimeError('explicit_offscreen_environment_required')
    args.out.mkdir(parents=True, exist_ok=False)
    # Libraries/original Qt diagnostics cannot pollute the bounded protocol.
    sys.stdout.flush()
    protocol=os.fdopen(os.dup(sys.stdout.fileno()),'wb',buffering=0)
    os.dup2(sys.stderr.fileno(),sys.stdout.fileno())
    sys.path.insert(0, str(ROOT))
    from tools.apply_client_patch import inspect_client
    from tools.qa_qt_robotio_peer import operation
    from rm_match.platform_v2.host_scheduling import PythonSwitchInterval
    switch_scope=PythonSwitchInterval(args.host_python_switch_interval_ms)
    cv2_module=None;opencv_original=None
    scheduling=dict(python_switch_interval=switch_scope.record,opencv=dict(
        enabled=args.host_opencv_threads is not None,requested_threads=args.host_opencv_threads,
        original_threads=None,effective_threads=None,restored_threads=None,applied=False,restored=False))

    started = time.perf_counter();cancel = threading.Event();lock = threading.RLock()
    errors = [];events = [];total_events = 0;dropped = 0;stdout_rows = 0
    app = window = runtime = transport = None
    snapshots = {};images = {};wrapped = {};threads = [];buffer = bytearray()
    manual_batch_channels=set()
    original_neutral=None
    state = dict(phase='watch',watch_selected=False,first_f2=False,second_f2=False,
                 plan_selected=False,ready=False,go_wall=None,release_wall=None,
                 release_ack=False,close_ack=False,activation_count=0,finished=False,
                 last_wait_wall=None,control_batch_submit_count=0,control_batch_ack_count=0)
    result = dict(schema='polar.sim.qt-platform-robotio-peer.v1',robot_id=args.robot_id,
        adapter_id=args.adapter_id,qualification='offscreen_original_window_HTTP_camera_F2_SDK_protocol_only',
        clock='unmodified_original_client_clock; probe metadata host_perf_counter',
        fake_camera=False,fake_HUD=False,fake_focus=False,visible_desktop=False,
        physical_ROS_NN_in_this_process=False,guard_evidence={},host_scheduling=scheduling)

    def remember(event, **fields):
        nonlocal total_events,dropped
        with lock:
            total_events += 1
            if len(events) < 256:
                events.append(dict(event=event,host_perf_counter=time.perf_counter(),**fields))
            else:dropped += 1

    def error(where, exc):
        with lock:
            if len(errors) < 32:errors.append(where+':'+type(exc).__name__)
        remember('error',phase=where,exception_type=type(exc).__name__)
        with (args.out/'errors.log').open('a',encoding='utf8') as log:
            log.write(where+'\n'+''.join(traceback.format_exception(type(exc),exc,exc.__traceback__))+'\n')

    def emit(event, **fields):
        nonlocal stdout_rows
        with lock:
            raw=json.dumps(dict(event=event,**fields),allow_nan=False,separators=(',',':')).encode()+b'\n'
            if len(raw)>16384 or stdout_rows>=(1024 if event=='qt_finished' else 1023):
                raise RuntimeError('bounded_peer_protocol_limit')
            protocol.write(raw);protocol.flush();stdout_rows+=1

    def guards():
        handle=window.windowHandle() if window is not None else None
        return dict(qt_internal_shown=bool(window and window.isVisible()),
            qt_active=bool(window and window.isActiveWindow()),
            qt_exposed=bool(handle and handle.isExposed()),
            combat_input=bool(window and window.combat_control_input_allowed()),
            selection_ready=bool(transport and transport.selection_ready()),
            own_hud_ready=bool(transport and transport.operator_hud_ready()),
            runtime_armed=bool(runtime and runtime.armed),
            transport_focus=bool(transport and transport._focus))

    def local_claim_view():
        with transport._lock:
            return dict(owned_robot=transport.owned_robot,lease_epochs=dict(transport.owned_epochs),
                claim_pending=transport.claim_pending,claim_job_pending=transport._claim_job is not None,
                control_generation=transport._control_generation,plan_generation=transport._plan_generation,
                watch_generation=transport._watch_generation,
                runtime_note=str(runtime.note)[:256],transport_note=str(transport.note)[:256])

    def state_lease_view(value):
        control=value.get('control',{})
        leases=control.get('leases',{}).get(args.robot_id,{})
        return dict(episode=value.get('episode'),sim_time=value.get('sim_time'),
            sample_sim_time=value.get('sample_sim_time'),control_revision=control.get('revision'),
            server_monotonic_s=control.get('server_monotonic_s'),
            leases={channel:{k:lease[k] for k in ('owner','epoch','occupied','expires') if k in lease}
                for channel,lease in leases.items() if channel in ('motion','gimbal','fire')})

    def snapshot(label):
        with transport._lock:
            data,video,*_=transport.snapshot()
            snapshots[label]=dict(state=copy.deepcopy(transport.raw_state),
                own_display=copy.deepcopy(data),frame_sequence=transport.video_sequence,
                video_source_sequence=transport.video_source_sequence,
                video_shape=None if video is None else list(video.shape),guard=guards())

    def capture_render(label):
        from PySide6.QtGui import QColor,QImage,QPainter
        render_started=time.perf_counter()
        with transport._lock:
            window.consume_backend_video_frame();runtime.apply_state(window.state)
            if not window.normal_video_frame_ready():raise RuntimeError('actual_HTTP_pixels_not_in_original_renderer')
            if (window._last_backend_video_at!=transport.video_at
                or (window.frame_image.height(),window.frame_image.width())!=tuple(transport.video.shape[:2])):
                raise RuntimeError('original_renderer_does_not_match_current_HTTP_frame')
            source=dict(frame_sequence=transport.video_sequence,
                video_source_sequence=transport.video_source_sequence,
                capture_sim_time=transport.video_sim_time,watch_epoch=transport.watch_epoch,
                video_shape=list(transport.video.shape),backend_frame_at=window._last_backend_video_at,
                backend_clock='original_client_local_monotonic')
        image=QImage(1360,900,QImage.Format.Format_RGBA8888);image.fill(QColor('#050609'))
        painter=QPainter(image)
        try:
            window.draw_video(painter,1360,900)
            window.paint_overlay(None,painter=painter,logical_size=(1360,900),
                hud_background_ready=True,capture_module_list=True)
        finally:painter.end()
        images[label]=image
        result.setdefault('display_frames',{})[label]=source
        remember('original_QPainter_camera_render',phase=label,source=source,
            elapsed_host_s=time.perf_counter()-render_started,
            screenshot_kind='real_HTTP_camera_original_draw_video_QImage_not_visible_desktop')

    def key(key_value):
        from PySide6.QtCore import QEvent,Qt
        from PySide6.QtGui import QKeyEvent
        for kind in (QEvent.Type.KeyPress,QEvent.Type.KeyRelease):
            app.sendEvent(window,QKeyEvent(kind,key_value,Qt.KeyboardModifier.NoModifier))

    def release(reason):
        if state['release_wall'] is not None:return
        from PySide6.QtCore import Qt
        state['phase']='release';state['release_wall']=time.perf_counter()
        remember('actual_F12_release',reason=reason,guards=guards())
        key(Qt.Key.Key_F12)  # Original backend/disarm/reset-inputs path.

    def hook_client():
        nonlocal original_neutral
        client=transport.client
        original_neutral=transport.neutral
        cost_code=transport._handoff.cost.__func__.__code__
        supports_batched='batched' in cost_code.co_varnames[:cost_code.co_argcount+cost_code.co_kwonlyargcount]
        def neutral(reason='Input released'):
            # Bounded code locations and scheduling scalars, no stack source
            # reads or sleeps. Original arguments and estimator are unchanged.
            frames=[];frame=sys._getframe(1);scheduling_call=None
            for _ in range(4):
                if frame is None:break
                frames.append(dict(file=frame.f_code.co_filename[-256:],
                    function=frame.f_code.co_name[:64],line=frame.f_lineno))
                if frame.f_code.co_name=='_strict_control_tick':
                    # Only these non-input scheduling scalars from the actual
                    # callsite; never emit the rest of its locals or intent.
                    values=frame.f_locals
                    plan=values.get('plan');controls=values.get('controls');maintenance=values.get('maintenance')
                    if type(plan) is dict and type(controls) is int:
                        scheduling_call=dict(kinds=len(plan),controls=controls,
                            maintenance=None if type(maintenance) is not list else
                            [item for item in maintenance if item in ('renew','keepalive')])
                        if supports_batched and type(values.get('batched')) is bool:
                            scheduling_call['batched']=values['batched']
                frame=frame.f_back
            try:
                with transport._lock:
                    h=transport._handoff
                    scalar=lambda value:value if type(value) in (int,float) and math.isfinite(value) else None
                    handoff=dict(clock_domain='original_client_local_monotonic',
                        observed_local_clock=transport.clock(),costs=dict(h.costs),phase=h.phase,
                        deadline=scalar(h.deadline),started=scalar(h.started),
                        last_issue=scalar(h.last_issue),last_batch=scalar(h.last_batch),
                        handoff_reason=h.handoff_reason,actual_scheduling_call=scheduling_call)
                    if scheduling_call is not None and scheduling_call['maintenance'] is not None:
                        handoff['predicted_cost_s']=h.cost(**scheduling_call)
                remember('original_neutral_entry',reason=str(reason)[:256],
                    thread=threading.current_thread().name,location=frames,local=local_claim_view(),handoff=handoff)
            except BaseException as exc:error('neutral_evidence',exc)
            return original_neutral(reason)
        transport.neutral=neutral
        for name in ('control_window','adapter_input','_request'):
            wrapped[name]=getattr(client,name)
        if hasattr(client,'control_batch'):wrapped['control_batch']=client.control_batch
        last_window={}
        def control_window(*pos,**kw):
            value=wrapped['control_window'](*pos,**kw)
            try:
                safe={k:copy.deepcopy(value[k]) for k in ('robot_id','session_id','lease_epochs',
                    'window_id','issued_wall','expires_wall','valid_for_s')}
                with lock:last_window.clear();last_window[safe['window_id']]=safe
                remember('actual_control_window_ack',window_id=safe['window_id'])
            except BaseException as exc:error('control_window_evidence',exc)
            return value
        def adapter_input(*pos,**kw):
            value=wrapped['adapter_input'](*pos,**kw)
            try:
                safe={k:value[k] for k in ('robot_id','kind','binding_epoch','seq',
                    'window_id','activation_expires','accepted')}
                with lock:
                    actual=copy.deepcopy(last_window.get(safe['window_id']))
                    if actual is None:raise RuntimeError('activation_without_recorded_original_window')
                    state['activation_count']+=1
                emit('sdk_activation',robot_id=args.robot_id,window=actual,activation=safe)
                remember('actual_adapter_activation_ack',window_id=safe['window_id'],seq=safe['seq'])
            except BaseException as exc:error('activation_evidence',exc)
            return value
        def control_batch(*pos,**kw):
            # One original RPC. Evidence never issues a replacement pulse,
            # window, control or renew, nor changes its deadline or values.
            with lock:
                state['control_batch_submit_count']+=1
                submission=state['control_batch_submit_count']
            entered=time.perf_counter()
            remember('actual_control_batch_submit',submission=submission)
            value=wrapped['control_batch'](*pos,**kw)
            returned=time.perf_counter()
            try:
                if (type(value) is not dict or set(value)!={'schema','accepted','robot_id','lease_epochs',
                    'window_id','batch_version','adapter_inputs','controls'}
                    or value['schema']!='rm.sim.platform.v2' or value['accepted'] is not True
                    or type(value['robot_id']) is not str or value['robot_id']!=args.robot_id
                    or type(value['batch_version']) is not int or value['batch_version']!=1
                    or type(value['window_id']) is not int or value['window_id']<=0
                    or type(value['lease_epochs']) is not dict
                    or type(value['adapter_inputs']) is not list or type(value['controls']) is not list
                    or len(value['adapter_inputs'])>3 or len(value['controls'])>3):
                    raise RuntimeError('original_batch_ACK_shape_or_identity_mismatch')
                with lock:actual=copy.deepcopy(last_window.get(value['window_id']))
                if actual is None or actual['robot_id']!=value['robot_id']:
                    raise RuntimeError('batch_without_recorded_original_window')
                epochs=value['lease_epochs']
                if (set(epochs)!=set(actual['lease_epochs']) or any(
                    type(epoch) is not int or epoch<=0 or epoch!=actual['lease_epochs'][channel]
                    for channel,epoch in epochs.items())):
                    raise RuntimeError('batch_original_window_lease_epoch_mismatch')
                activation_keys={'accepted','robot_id','kind','binding_epoch','seq','window_id','activation_expires'}
                control_keys={'accepted','robot_id','channel','lease_epoch','seq','window_id','input_expires'}
                activations=[];controls=[];kinds=set();channels=set()
                for item in value['adapter_inputs']:
                    if (type(item) is not dict or set(item)!=activation_keys or item['accepted'] is not True
                        or type(item['robot_id']) is not str or item['robot_id']!=value['robot_id']
                        or type(item['kind']) is not str or item['kind'] not in ('navigation','aim')
                        or item['kind'] in kinds or any(type(item[k]) is not int or item[k]<=0
                            for k in ('binding_epoch','window_id'))
                        or type(item['seq']) is not int or item['seq']<0
                        or item['window_id']!=value['window_id']
                        or type(item['activation_expires']) not in (int,float)
                        or not math.isfinite(item['activation_expires'])
                        or not actual['issued_wall']<item['activation_expires']<=actual['expires_wall']):
                        raise RuntimeError('original_batch_activation_ACK_not_typed')
                    kinds.add(item['kind']);activations.append(copy.deepcopy(item))
                for item in value['controls']:
                    if (type(item) is not dict or set(item)!=control_keys or item['accepted'] is not True
                        or type(item['robot_id']) is not str or item['robot_id']!=value['robot_id']
                        or type(item['channel']) is not str or item['channel'] not in ('motion','gimbal','fire')
                        or item['channel'] in channels or any(type(item[k]) is not int or item[k]<=0
                            for k in ('lease_epoch','window_id'))
                        or type(item['seq']) is not int or item['seq']<0
                        or item['window_id']!=value['window_id']
                        or item['lease_epoch']!=epochs.get(item['channel'])
                        or type(item['input_expires']) not in (int,float)
                        or not math.isfinite(item['input_expires'])
                        or not actual['issued_wall']<item['input_expires']<=actual['expires_wall']):
                        raise RuntimeError('original_batch_manual_ACK_not_typed')
                    channels.add(item['channel']);controls.append(copy.deepcopy(item))
                with lock:
                    state['control_batch_ack_count']+=1
                    manual_batch_channels.update(channels)
                    state['activation_count']+=len(activations)
                remember('actual_control_batch_ack',submission=submission,window_id=value['window_id'],
                    elapsed_host_s=returned-entered,adapter_kinds=sorted(kinds),manual_ACKs=controls)
                for activation in activations:
                    emit('sdk_activation',robot_id=args.robot_id,window=actual,activation=activation)
                    remember('actual_adapter_activation_ack',window_id=activation['window_id'],
                        seq=activation['seq'],source='original_control_batch_ACK')
            except BaseException as exc:error('control_batch_evidence',exc)
            return value

        def request(path,*pos,**kw):
            # Include pre-F2 in-flight requests, whose responses can arrive
            # after the real claim ACK. Keep the original source/revision.
            traced=path=='/v2/claim' or (path=='/v2/state' and not state['second_f2'])
            if traced:remember('actual_HTTP_entry',path=path,thread=threading.current_thread().name,
                local=local_claim_view())
            value=wrapped['_request'](path,*pos,**kw)
            if traced:
                metadata=(state_lease_view(value) if path=='/v2/state'
                    else {k:copy.deepcopy(value[k]) for k in ('robot_id','lease_epochs') if k in value})
                remember('actual_HTTP_return',path=path,thread=threading.current_thread().name,
                    original_response=metadata,local=local_claim_view())
            if path=='/v2/release':
                with lock:state['release_ack']=value.get('released') is True
                remember('actual_release_ack',released=state['release_ack'])
            elif path=='/v2/close':
                with lock:state['close_ack']=value.get('closed') is True
                remember('actual_close_ack',closed=state['close_ack'])
            return value
        client.control_window=control_window;client.adapter_input=adapter_input;client._request=request
        if 'control_batch' in wrapped:client.control_batch=control_batch

    def quit_loop():
        state['finished']=True
        if app is not None:app.quit()

    def poll():
        try:
            now=time.perf_counter()
            if state['last_wait_wall'] is None or now-state['last_wait_wall']>=.5:
                state['last_wait_wall']=now
                remember('window_wait_observation',phase=state['phase'],guards=guards(),local=local_claim_view())
            op=operation(buffer)
            if op=='go':
                if not state['ready'] or state['go_wall'] is not None:
                    raise RuntimeError('go_requires_actual_armed_bound_once')
                state['go_wall']=now;remember('parent_go_measurement_only',guards=guards())
            if op=='stop':
                if state['go_wall'] is None or now-state['go_wall']<args.run_seconds:
                    raise RuntimeError('parent_stop_before_original_run_completed')
                release('parent_stop')
            if cancel.is_set():raise RuntimeError('peer_signal_cancelled')
            if now-started>=args.max_wall_seconds-1.5 and state['release_wall'] is None:
                raise TimeoutError('peer_original_wall_budget')
            if errors and state['release_wall'] is None:release('recorded_failure')
            if state['release_wall'] is not None:
                if state['release_ack']:
                    snapshot('released')
                    if transport.operator_hud_ready():raise RuntimeError('own_HUD_authority_survived_release')
                    quit_loop();return
                if now-state['release_wall']>=1.:
                    raise TimeoutError('actual_release_ack_not_observed')
                return
            # After ready, preclaim wait predicates must never swallow an
            # actual authority/focus/HUD loss or the measurement end.
            if state['ready']:
                actual=guards();local=local_claim_view()
                with transport._lock:
                    binding=transport._bindings.get('navigation')
                    binding_valid=(type(binding) is dict and binding.get('adapter_id')==args.adapter_id
                        and binding.get('binding_epoch')==state['ready_binding_epoch'])
                required=('qt_internal_shown','qt_active','combat_input','selection_ready',
                    'own_hud_ready','runtime_armed','transport_focus')
                if (not all(actual[k] is True for k in required)
                    or local['owned_robot']!=args.robot_id
                    or local['lease_epochs']!=state['ready_lease_epochs'] or not binding_valid):
                    remember('ready_guard_revoked',guards=actual,local=local,binding_valid=binding_valid)
                    raise RuntimeError('original_ready_authority_or_focus_guard_revoked')
                if state['go_wall'] is not None and now-state['go_wall']>=args.run_seconds:
                    release('original_measurement_completed')
                return
            if not state['watch_selected']:
                if args.robot_id not in transport.robot_ids:return
                runtime.select_robot(window,args.robot_id);state['watch_selected']=True
                remember('original_select_robot',robot_id=args.robot_id)
                return
            if not transport.selection_ready():return
            if not state['plan_selected']:
                from PySide6.QtCore import QPointF,QRectF
                setting=window.registry.get('RobotProfile').get_setting('V2 Navigation')
                runtime.sync_adapters(window)
                if args.adapter_id not in setting.options:
                    if not transport.catalog.get('ready'):return
                    raise RuntimeError('actual_catalog_pipeline_not_selectable')
                snapshot('preclaim')
                if transport.owned_robot is not None or transport.operator_hud_ready():
                    raise RuntimeError('implicit_claim_before_first_F2')
                capture_render('preclaim')
                emit('qt_watch_ready',robot_id=args.robot_id,guards=guards(),
                    frame_sequence=transport.video_sequence,watch_epoch=transport.watch_epoch)
                window.dispatch('jello_mode_select',(setting,args.adapter_id),QPointF(),1,QRectF(0,0,100,20))
                wanted={'navigation':{'adapter_id':args.adapter_id,'config':{}}}
                if transport.plan!=wanted:raise RuntimeError('original_Jello_empty_pipeline_plan_not_selected')
                state['plan_selected']=True
                emit('qt_plan_selected',robot_id=args.robot_id,selected=setting.value,
                    plan=copy.deepcopy(transport.plan),guards=guards(),selection_route='original_Jello_dispatch')
                return
            actual=guards()
            if not actual['qt_active'] or not actual['combat_input']:
                # Never override the predicate or manufacture a focus event.
                return
            from PySide6.QtCore import Qt
            if not state['first_f2']:
                key(Qt.Key.Key_F2);state['first_f2']=True
                remember('first_actual_F2',guards=guards(),local=local_claim_view())
                return
            local=local_claim_view()
            if (not state['second_f2'] and local['owned_robot']!=args.robot_id
                and not local['claim_pending'] and not local['claim_job_pending']):
                remember('first_F2_claim_not_pending_or_owned',guards=guards(),local=local)
                raise RuntimeError('original_first_F2_claim_refused_or_revoked')
            if transport.owned_robot!=args.robot_id or not transport.operator_hud_ready():return
            if not state['second_f2']:
                snapshot('claimed_hud')
                emit('qt_claimed_hud',robot_id=args.robot_id,guards=guards(),
                    lease_epochs=copy.deepcopy(transport.owned_epochs),f2_count=1)
                key(Qt.Key.Key_F2);state['second_f2']=True
                remember('second_actual_F2',guards=guards(),local=local_claim_view())
                if not runtime.armed:raise RuntimeError('original_second_F2_did_not_arm')
                return
            if not runtime.armed or not transport._focus:
                raise RuntimeError('original_heartbeat_focus_or_sensor_guard_revoked')
            with transport._lock:binding=copy.deepcopy(transport._bindings.get('navigation'))
            if not state['ready']:
                if binding is None:return
                if binding.get('adapter_id')!=args.adapter_id:raise RuntimeError('actual_binding_identity_mismatch')
                # Keep the original window timer/paint path. No extra armed
                # screenshot or state copy on the measured control path.
                state['ready_binding_epoch']=binding.get('binding_epoch')
                state['ready_lease_epochs']=dict(transport.owned_epochs)
                state['ready']=True
                result['guard_evidence']=guards()
                emit('qt_armed_bound',robot_id=args.robot_id,guards=guards(),binding=binding,
                    f2_count=2,frame_sequence=transport.video_sequence,
                    visible_desktop=False,qt_internal_shown=window.isVisible())
                return
        except BaseException as exc:
            error('event_loop',exc)
            try:release('actual_failure')
            except BaseException as close_exc:error('release',close_exc)
            quit_loop()

    old_signals={}
    try:
        result['client_check']=inspect_client(args.client_root,args.manifest)
        if (result['client_check']['status']!='verified_patched'
            or result['client_check']['base_commit']!=PINNED_BASE):
            raise RuntimeError('reviewed_pinned_combined_patch_not_applied')
        result['manifest_sha256']=hashlib.sha256(args.manifest.read_bytes()).hexdigest()
        result['peer_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        switch_scope.__enter__()
        if args.host_opencv_threads is not None:
            import cv2 as cv2_module
            opencv_original=cv2_module.getNumThreads()
            scheduling['opencv']['original_threads']=opencv_original
            cv2_module.setNumThreads(args.host_opencv_threads)
            scheduling['opencv']['applied']=True
            effective=cv2_module.getNumThreads()
            scheduling['opencv']['effective_threads']=effective
            if effective!=args.host_opencv_threads:raise RuntimeError('host_opencv_readback_mismatch')
        sys.path.insert(0,str(args.client_root.resolve()))
        from PySide6 import __version__ as qt_version
        from PySide6.QtCore import QTimer,Qt
        from PySide6.QtWidgets import QApplication
        from rm_client.sim_platform_runtime import PlatformRuntime
        from rm_client.ui.sim_platform_window import PlatformWindow
        app=QApplication(['POLAR-original-platform-window-offscreen'])
        app.setQuitOnLastWindowClosed(False)
        result.update(qt_version=qt_version,qpa_platform=app.platformName())
        if app.platformName()!='offscreen':raise RuntimeError('actual_QPA_platform_not_offscreen')
        for sig in (signal.SIGTERM,signal.SIGINT):
            old_signals[sig]=signal.getsignal(sig);signal.signal(sig,lambda *_:cancel.set())
        runtime=PlatformRuntime(args.url,role='operator');transport=runtime.transport
        hook_client()
        window=PlatformWindow(runtime);window.resize(1360,900)
        window.show();window.activateWindow();window.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        # The window's OWN timer invokes original heartbeat/on_tick/control.tick.
        # This observer neither calls control_tick nor manually renews/windows.
        timer=QTimer();timer.setTimerType(Qt.TimerType.PreciseTimer)
        timer.timeout.connect(poll);timer.start(20)
        result['qt_exit_code']=app.exec();timer.stop()
    except BaseException as exc:error('setup_or_loop',exc)
    finally:
        if transport is not None:
            threads=list(transport._threads)
            result['preclose_guards']=guards()
        try:
            if window is not None:window.close()
            elif runtime is not None:runtime.stop()
        except BaseException as exc:error('original_window_close',exc)
        if transport is not None:
            result['threads_alive']=[thread.name for thread in threads if thread.is_alive()]
            result['diagnostics']=transport.diagnostics()
            for name,function in wrapped.items():setattr(transport.client,name,function)
            result['sdk_hooks_restored']=all(getattr(transport.client,name)==function for name,function in wrapped.items())
            if original_neutral is not None:transport.neutral=original_neutral
            result['neutral_hook_restored']=original_neutral is None or transport.neutral==original_neutral
        try:
            if runtime is not None:runtime._tmp.cleanup()
        except BaseException as exc:error('temporary_config_cleanup',exc)
        for sig,handler in old_signals.items():signal.signal(sig,handler)
        if 'preclaim' in images:
            try:
                result['actual_frame_display']=images['preclaim'].save(str(args.out/'ACTUAL_QT_OFFSCREEN.png'))
                result['screenshot_phase']='preclaim_frame'
            except BaseException as exc:error('actual_camera_evidence_save',exc)
        try:
            if opencv_original is not None:
                cv2_module.setNumThreads(opencv_original)
                scheduling['opencv']['restored_threads']=cv2_module.getNumThreads()
                scheduling['opencv']['restored']=scheduling['opencv']['restored_threads']==opencv_original
                if not scheduling['opencv']['restored']:raise RuntimeError('host_opencv_restore_mismatch')
        except BaseException as exc:error('host_opencv_restore',exc)
        try:switch_scope.close()
        except BaseException as exc:error('host_python_switch_restore',exc)
        result['host_scheduling_qualified']=all(not row['enabled'] or
            (row['applied'] and row['restored']) for row in scheduling.values())
        result.update(stages=state,errors=errors,elapsed_s=time.perf_counter()-started,
            control_batch_submit_count=state['control_batch_submit_count'],
            control_batch_ack_count=state['control_batch_ack_count'],
            manual_batch_ack_channels=sorted(manual_batch_channels),
            stdout_rows=stdout_rows,diagnostic_total=total_events,diagnostic_dropped=dropped)
        # Protocol rejection is distinct from actual resources being reaped.
        result['resource_errors']=[item for item in errors if item.startswith(
            ('original_window_close:','temporary_config_cleanup:',
             'host_opencv_restore:','host_python_switch_restore:'))]
        result['clean']=bool(not result.get('threads_alive') and state['release_ack']
            and state['close_ack'] and not result['resource_errors'])
        guard=result['guard_evidence']
        result['passed']=bool(result['clean'] and result['host_scheduling_qualified'] and not errors and state['ready'] and state['go_wall'] is not None
            and state['first_f2'] and state['second_f2'] and state['activation_count']>0
            and result.get('actual_frame_display') and all(guard.get(k) is True for k in
                ('qt_internal_shown','qt_active','combat_input','selection_ready','own_hud_ready','runtime_armed','transport_focus')))
        result['exit_code']=0 if result['passed'] else 2
        for name,value in (('STAGES.json',events),('STATE_SNAPSHOTS.json',snapshots),('RESULT.json',result)):
            (args.out/name).write_text(json.dumps(value,allow_nan=False,indent=2)+'\n',encoding='utf8')
        emit('qt_finished',clean=result['clean'],errors=list(errors),exit_code=result['exit_code'])
        protocol.close()
    return result['exit_code']


if __name__=='__main__':raise SystemExit(main())
