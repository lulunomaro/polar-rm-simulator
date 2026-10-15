"""Bounded local QA close handshake; never conveys actuator authority."""
import json
import time
import stat
from pathlib import Path

def wait_for_driver_cleanup(path,owner_session_id,control,*,clock=time.monotonic,timeout=2.,sleep=time.sleep):
    if not 0<timeout<=2:raise ValueError('Bounded cleanup wait required')
    start=clock();reason='quiescence_unconfirmed';path=Path(path)
    while clock()-start<timeout:
        try:
            info=path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_size>4096:raise ValueError('invalid acknowledgement file')
            value=json.loads(path.read_text())
            if type(value) is not dict or set(value)!={'owner_session_id','quiesced','session_close_ack','cleanup_completed'}:raise ValueError('invalid acknowledgement')
            if type(owner_session_id) is not str or value['owner_session_id']!=owner_session_id:raise ValueError('wrong owner')
            if not all(value[k] is True for k in ('quiesced','session_close_ack','cleanup_completed')):raise ValueError('cleanup incomplete')
            remaining=timeout-(clock()-start)
            if remaining<=0:break
            acquired=control.lock.acquire(timeout=remaining)
            if not acquired:reason='control_lock_timeout';break
            try:
                present=owner_session_id in control.sessions
            finally:control.lock.release()
            checked=clock()
            if checked-start>=timeout:reason='cleanup_deadline_elapsed';break
            if present:raise ValueError('owner session remains open')
            return dict(confirmed=True,reason='driver_quiesced_and_session_closed',wall_time=checked,wait_wall_s=checked-start)
        except FileNotFoundError:pass
        except (OSError,ValueError,TypeError,RecursionError) as e:reason='invalid_cleanup_ack:'+str(e)
        remaining=timeout-(clock()-start)
        if remaining>0:sleep(min(.01,remaining))
    return dict(confirmed=False,reason=reason,wall_time=clock(),wait_wall_s=clock()-start)
