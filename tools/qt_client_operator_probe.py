#!/usr/bin/env python3
"""Actual original Qt window/renderer/event loop, offscreen and never shown.

The local admitted operator watches real HTTP camera pixels before claiming.
Credential is read only from POLAR_SIM_ADMISSION_CREDENTIAL, never argv/logs.
PNG is a real Qt QPainter/QImage render, not a visible desktop screenshot.
"""
import argparse
import json
from pathlib import Path
import sys
import time
import traceback


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client-root',type=Path,required=True)
    parser.add_argument('--endpoint',required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(args.client_root.resolve()))
    from PySide6 import __version__ as qt_version
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QColor,QImage,QPainter
    from PySide6.QtWidgets import QApplication
    from rm_client.sim_platform_runtime import PlatformRuntime
    from rm_client.ui.sim_platform_window import PlatformWindow
    app=QApplication(['POLAR-operator-camera-offscreen'])
    runtime=PlatformRuntime(args.endpoint,role='operator');window=PlatformWindow(runtime)
    window.resize(1360,900)
    transport=runtime.transport
    result=dict(schema='polar.sim.own_client.actual_qt_probe.v1',qt_version=qt_version,
        qpa_platform=app.platformName(),visible_window=False,qt_event_loop=False,actual_frame_display=False,
        physics_or_native_in_this_process=False,synthetic_camera=False,
        screenshot_kind='Original Qt renderer with actual HTTP camera pixels into QImage; not a visible desktop screenshot')
    started=time.perf_counter();polls=[0];selected=[False]
    def finish():
        result['visible_window']=window.isVisible()
        result['elapsed_s']=time.perf_counter()-started;result['qt_timer_events']=polls[0]
        window.close();runtime._tmp.cleanup();app.quit()
    def poll():
        polls[0]+=1;result['qt_event_loop']=True
        try:
            if not selected[0] and transport.robot_ids:
                runtime.select_robot(window,'red_sentry');selected[0]=True
            if selected[0] and transport.selection_ready():
                window.consume_backend_video_frame();runtime.apply_state(window.state)
                if window.normal_video_frame_ready():
                    image=QImage(1360,900,QImage.Format.Format_RGBA8888);image.fill(QColor('#050609'))
                    painter=QPainter(image)
                    try:
                        window.draw_video(painter,1360,900)
                        window.paint_overlay(None,painter=painter,logical_size=(1360,900),hud_background_ready=True,capture_module_list=True)
                    finally:painter.end()
                    saved=image.save(str(args.out/'ACTUAL_QT_OFFSCREEN.png'))
                    result.update(actual_frame_display=bool(saved),frame_sequence=transport.video_sequence,
                        decoded_camera_shape=list(transport.video.shape),native_size=list(transport.video_native_size),
                        operator_own_hud_unavailable_before_claim=transport.snapshot()[0]['own'] is None,
                        no_claim_implicit=transport.owned_robot is None,roster=list(transport.robot_ids),
                        screenshot='ACTUAL_QT_OFFSCREEN.png')
                    finish();return
            if time.perf_counter()-started>4.5:
                result['error']='Actual admitted HTTP camera did not reach Qt display before bounded deadline'
                finish();return
        except BaseException as exc:
            result['error']=repr(exc);(args.out/'error.log').write_text(traceback.format_exc(),encoding='utf-8');finish();return
        QTimer.singleShot(10,poll)
    QTimer.singleShot(0,poll)
    result['qt_exit_code']=app.exec()
    result['passed']=bool(result['qt_event_loop'] and result['actual_frame_display'] and not result['visible_window']
                          and result.get('no_claim_implicit') and result.get('operator_own_hud_unavailable_before_claim')
                          and result['qt_exit_code']==0 and not result.get('error'))
    (args.out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2));return 0 if result['passed'] else 2


if __name__=='__main__':raise SystemExit(main())
