"""Actual offscreen QWidget selector + Qt client SDK; protocol fixture only.

No PlatformWindow/QOpenGLWidget, camera, F2 arming, ROS or algorithm is loaded.
The original client's catalog/options/plan code selects an already registered
ID. The explicit test button grants motion only through the actual client SDK.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time


def emit(event, **values):
    raw=json.dumps(dict(event=event,**values),allow_nan=False,separators=(',',':')).encode()+b'\n'
    if len(raw)>16384:raise RuntimeError('bounded_fixture_event_oversized')
    sys.stdout.buffer.write(raw);sys.stdout.buffer.flush()


def operation(buffer):
    """Owned Windows stdin only; bounded nonblocking local go/stop controls."""
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    peek=kernel.PeekNamedPipe
    peek.argtypes=[wintypes.HANDLE,wintypes.LPVOID,wintypes.DWORD,wintypes.LPVOID,
                  ctypes.POINTER(wintypes.DWORD),wintypes.LPVOID]
    peek.restype=wintypes.BOOL
    available=wintypes.DWORD()
    if not peek(msvcrt.get_osfhandle(sys.stdin.fileno()),None,0,None,ctypes.byref(available),None):
        raise EOFError('owned_fixture_stdin_closed')
    if available.value:
        buffer.extend(os.read(sys.stdin.fileno(),min(available.value,1025)))
        if len(buffer)>1024:raise ValueError('fixture_control_oversized')
    if b'\n' not in buffer:return None
    raw,_,tail=bytes(buffer).partition(b'\n')
    if tail:raise ValueError('fixture_one_control_line_required')
    buffer.clear()
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:raise ValueError('fixture_duplicate_control')
            result[k]=v
        return result
    def nonfinite(_):raise ValueError('fixture_nonfinite_control')
    value=json.loads(raw,object_pairs_hook=pairs,parse_constant=nonfinite)
    if type(value) is not dict or set(value)!={'op'} or type(value['op']) is not str or value['op'] not in ('go','stop'):
        raise ValueError('fixture_exact_control_required')
    return value['op']


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--client-root',type=Path,required=True);p.add_argument('--url',required=True)
    p.add_argument('--adapter-id',required=True);p.add_argument('--duration',type=float,required=True)
    a=p.parse_args(argv)
    if not 3<=a.duration<=4:raise ValueError('bounded_fixture_duration')
    if os.environ.get('QT_QPA_PLATFORM')!='offscreen':raise RuntimeError('explicit_offscreen_required')
    sys.path.insert(0,str(a.client_root))
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtWidgets import QApplication,QWidget,QComboBox,QPushButton,QVBoxLayout
    from rm_client.sim_platform_client import PlatformClient
    from rm_client.sim_platform_adapters import parse_catalog,options,make_plan,MANUAL
    client=None;claimed=False;errors=[];code=2;binding=None;plan=None;selected=[];buffer=bytearray()
    app=QApplication([]);widget=QWidget();selector=QComboBox(widget);button=QPushButton('Explicit test SDK motion claim/bind',widget)
    layout=QVBoxLayout(widget);layout.addWidget(selector);layout.addWidget(button)
    try:
        credential=os.environ.pop('POLAR_SIM_ADMISSION_CREDENTIAL',None)
        client=PlatformClient(a.url,control_profile='server_window_v1',timeout=.25,admission_credential=credential)
        client.open('operator')
        catalog=parse_catalog(client.adapters());allowed=options(catalog,'red_infantry','navigation')
        if a.adapter_id not in allowed:raise RuntimeError('pipeline_not_selectable_in_actual_catalog')
        selector.addItems(allowed)
        def choose(_):
            nonlocal plan
            plan=make_plan(catalog,'red_infantry',{'navigation':selector.currentText(),'aim':MANUAL},{})
            selected.append(selector.currentText())
        selector.activated.connect(choose)
        selector.setCurrentIndex(selector.findText(a.adapter_id))
        selector.activated.emit(selector.currentIndex())
        if plan!={'navigation':{'adapter_id':a.adapter_id,'config':{}}}:raise RuntimeError('typed_empty_plan_required')
        def authorize():
            nonlocal claimed,binding
            try:
                client.claim('red_infantry',['motion']);claimed=True
                binding=client.bind('red_infantry','navigation',plan['navigation']['adapter_id'],plan['navigation']['config'])
            except Exception as exc:errors.append(type(exc).__name__)
        button.clicked.connect(authorize);button.click()
        if errors or binding is None:raise RuntimeError('explicit_test_sdk_bind_failed')
        safe_binding={k:binding[k] for k in ('robot_id','kind','adapter_id','binding_epoch','activation_required','activation_version')}
        emit('qt_ready',robot_id='red_infantry',selected=selected,plan=plan,binding=safe_binding,
             actual_widgets=['QWidget','QComboBox','QPushButton'],camera=False,visible_gui=False,f2=False)
        deadline=time.perf_counter()+15.
        while True:
            op=operation(buffer)
            if op=='go':break
            if op=='stop':raise RuntimeError('fixture_cancelled_before_physics')
            if time.perf_counter()>=deadline:raise TimeoutError('fixture_go_wait_expired')
            time.sleep(.005)
        end=time.perf_counter()+a.duration-.75
        timer=QTimer();timer.setTimerType(Qt.TimerType.PreciseTimer)
        def tick():
            try:
                op=operation(buffer)
                if op=='go':raise ValueError('fixture_go_once')
                if op=='stop' or time.perf_counter()>=end:timer.stop();app.quit();return
                client.renew('red_infantry',['motion'])
                window=client.control_window('red_infantry',['motion'])
                activation=client.adapter_input('red_infantry','navigation',binding['binding_epoch'],window_id=window['window_id'],valid_for_s=.15)
                safe_window={k:window[k] for k in ('robot_id','session_id','lease_epochs','window_id','issued_wall','expires_wall','valid_for_s')}
                safe_activation={k:activation[k] for k in ('robot_id','kind','binding_epoch','seq','window_id','activation_expires','accepted')}
                emit('sdk_activation',robot_id='red_infantry',window=safe_window,activation=safe_activation)
            except Exception as exc:
                errors.append(type(exc).__name__);timer.stop();app.quit()
        timer.timeout.connect(tick);timer.start(25)
        app.exec();code=0 if not errors else 2
    except Exception as exc:errors.append(type(exc).__name__)
    finally:
        try:
            if client is not None:
                if claimed:client.release('red_infantry',['motion'])
                client.close()
        except Exception as exc:errors.append('sdk_cleanup:'+type(exc).__name__);code=2
        widget.close();app.processEvents()
        emit('qt_finished',clean=not errors and code==0,errors=errors,exit_code=code)
    return code


if __name__=='__main__':raise SystemExit(main())
