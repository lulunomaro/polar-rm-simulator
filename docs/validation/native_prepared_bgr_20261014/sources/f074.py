"""Small loopback HTTP transport; cached reads never wait for a renderer."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import copy
import ipaddress
import json
import socket
import threading
import time
from urllib.parse import urlsplit

from .protocol import SCHEMA, ControlGate

MAX_BODY_BYTES = 4096
BODY_TIMEOUT_S = 2.
REJECT_DRAIN_BYTES = 64 * 1024
REJECT_DRAIN_TIMEOUT_S = .1


class BridgeState:
    def __init__(self, gate=None):
        self.gate = gate or ControlGate()
        self.lock = threading.Lock()
        self.telemetry = None
        self.frame = None
        self.frame_meta = {}
        self.runtime_state = 'starting'
        self.error = None

    def publish(self, telemetry, frame=None, frame_meta=None):
        with self.lock:
            self.telemetry = telemetry
            if frame is not None:
                self.frame = bytes(frame)
                self.frame_meta = dict(frame_meta or {})
            self.runtime_state = telemetry.get('phase', 'running')

    def snapshot(self):
        # Lock in the same gate -> state order as physics publication. Never
        # relabel a cached physical sample with a different operator identity.
        with self.gate.lock:
            control = self.gate.status()
            with self.lock:
                result = copy.deepcopy(self.telemetry or {})
                result.update(runtime_state=self.runtime_state, error=self.error)
            identity = {key:control[key] for key in ('session_id','epoch','robot_id')}
            if any(result.get(key) != value for key,value in identity.items()):
                return dict(schema=SCHEMA, **identity,
                            server_time_ms=control['server_time_ms'],
                            runtime_state='not_ready', error='telemetry_identity_not_ready',
                            telemetry_available=False, own=None, own_damage=None, robots=[],
                            operator_modes=None, autoaim=None, control=control)
            result.update(schema=SCHEMA, server_time_ms=control['server_time_ms'],
                          telemetry_available=True, control=control)
            # Gate state is current; measurements remain the timestamped cached
            # physical sample. Do not pretend old torque was already zeroed.
            modes = result.get('operator_modes')
            if isinstance(modes, dict):
                modes['measurement_sim_time'] = result.get('sim_time')
                if control['state'] != 'active':
                    modes['effective'].update(spin_enabled=False, direction_resolved=None,
                                              spin_speed_dps=0., target_yaw_rate_rps=0.,spin_origin=None)
                    modes['effective_seq'] = None
                    modes['reason'] = control['reason']
                drive=modes.get('drive')
                if isinstance(drive,dict):
                    # The lease/revision is current, while velocity and actuator
                    # measurements are historical until the next physics tick.
                    drive['measurement_sim_time']=result.get('sim_time')
                    pending=drive.get('input_revision') != control.get('safety_revision')
                    if control['state'] != 'active' or pending:
                        reason=control['reason'] if control['state'] != 'active' else 'new_input_pending'
                        drive.update(active=False,mode='free',input_kind='legacy_chassis',
                            reference_yaw_rad=0.,world_velocity_target_mps=[0.,0.],reason=reason)
                        modes['effective']['chassis_follow']='free'
                        modes['effective_seq']=None
                        modes['reason']=reason
            aim=result.get('autoaim')
            if isinstance(aim,dict):
                current_aim=control.get('control',{}).get('aim_request',{})
                aim.update(requested=bool(current_aim.get('enabled')),held=bool(current_aim.get('hold')))
                if all(k in current_aim for k in ('fov_degrees','circle_radius_x_norm','circle_radius_y_norm')):
                    aim['fov']={k:current_aim[k] for k in ('fov_degrees','circle_radius_x_norm','circle_radius_y_norm')}
                if control['state']!='active' or ('input_revision' in aim and aim['input_revision']!=control.get('safety_revision')):
                    aim.update(active=False,selected=False,in_fov=None,fov_applied=False,authority='manual',
                               reason=control['reason'] if control['state']!='active' else 'new_input_pending')
            result['applied_command_sim_time'] = result.get('sim_time')
            return result

    def session(self):
        with self.gate.lock:
            result = self.gate.session()
            with self.lock:
                result.update(runtime_state=self.runtime_state, error=self.error)
                if self.runtime_state in ('finished','stopped','error'):
                    result['state'] = self.runtime_state
            return result

    def select_robot(self, message):
        # Same gate -> state lock order as publication/snapshot. No HTTP thread
        # can touch MuJoCo, reset the judge, or await inference/rendering here.
        with self.gate.lock:
            result = self.gate.select_robot(message)
            if result['accepted']:
                with self.lock:
                    self.telemetry = None
                    self.frame = None
                    self.frame_meta = {}
            return result

    def stop(self, reason='stopped', error=None):
        self.gate.disable(reason)
        with self.lock:
            self.runtime_state = reason
            self.error = error


class OperatorHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address, state):
        host, port = address
        if host != '127.0.0.1':
            raise ValueError('Operator transport must bind exactly 127.0.0.1')
        self.state = state
        super().__init__(address, OperatorHandler)


class OperatorHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'
    server_version = 'MuJoCoOperator/1'

    def log_message(self, *_):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(BODY_TIMEOUT_S)
        self._body_bytes_read = 0
        self._discard_body_on_close = False

    def _read_body(self, size):
        """One total deadline, rather than a fresh idle timeout per byte."""
        deadline = time.perf_counter() + BODY_TIMEOUT_S
        raw = bytearray()
        while len(raw) < size:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:raise TimeoutError('Request body deadline expired')
            self.connection.settimeout(remaining)
            chunk = self.rfile.read1(size-len(raw))
            if not chunk:raise ValueError('Incomplete request')
            self._body_bytes_read += len(chunk)
            raw.extend(chunk)
        if time.perf_counter() >= deadline:raise TimeoutError('Request body deadline expired')
        return bytes(raw)

    def finish(self):
        try:
            if self._discard_body_on_close:
                # Closing with unread TCP data can reset Winsock and discard
                # the 413 already sent. Send FIN first, then discard only bounded
                # data/time; the rejected body is never parsed or authorized.
                self.wfile.flush()
                try:self.connection.shutdown(socket.SHUT_WR)
                except OSError:pass
                try:
                    declared = int(self.headers.get('Content-Length','-1'))
                except ValueError:declared = -1
                remaining = (REJECT_DRAIN_BYTES if declared < 0 else
                    min(REJECT_DRAIN_BYTES,max(0,declared-self._body_bytes_read)))
                deadline = time.perf_counter() + REJECT_DRAIN_TIMEOUT_S
                while remaining > 0:
                    timeout = deadline - time.perf_counter()
                    if timeout <= 0:break
                    self.connection.settimeout(timeout)
                    try:chunk = self.rfile.read1(min(4096,remaining))
                    except OSError:break
                    if not chunk:break
                    remaining -= len(chunk)
        except OSError:
            pass  # Peer aborts never authorize a control message.
        finally:
            super().finish()

    def _safe_request(self):
        try:
            if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                self._json(403, {'error':'loopback_only'})
                return False
        except ValueError:
            self._json(403, {'error':'loopback_only'})
            return False
        port = self.server.server_address[1]
        if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
            self._json(403, {'error':'invalid_host'})
            return False
        # Native clients send no Origin. Refuse web-origin access rather than
        # opening a local robot-control API to arbitrary websites or DNS rebinding.
        if self.headers.get('Origin') is not None:
            self._json(403, {'error':'browser_origin_forbidden'})
            return False
        return True

    def _reply(self, code, content, content_type, headers=None):
        self.close_connection = True
        if code >= 400 and (self.command in ('POST','PUT','PATCH')
                or self.headers.get('Content-Length') is not None or self.headers.get('Transfer-Encoding')):
            self._discard_body_on_close = True
        self.send_response(code)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(content)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Connection','close')
        for key,value in (headers or {}).items():
            self.send_header(key,str(value))
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, code, value):
        self._reply(code, json.dumps(value, allow_nan=False, separators=(',',':')).encode(),
                    'application/json; charset=utf-8')

    def do_GET(self):
        if not self._safe_request():
            return
        state = self.server.state
        path = urlsplit(self.path).path
        if path == '/session':
            self._json(200,state.session())
        elif path == '/telemetry':
            self._json(200,state.snapshot())
        elif path == '/frame.jpg':
            with state.lock:
                frame,meta = state.frame,dict(state.frame_meta)
            session=state.gate.status()
            if frame is None or meta.get('epoch') != session['epoch'] or meta.get('robot_id') != session['robot_id']:
                self._json(503,{'error':'frame_not_ready', 'schema':SCHEMA})
                return
            self._reply(200,frame,'image/jpeg',{
                'X-Sim-Session-Id':session['session_id'], 'X-Sim-Epoch':session['epoch'],
                'X-Frame-Seq':meta['frame_seq'], 'X-Sim-Time':meta['sim_time'],
                'X-Robot-Id':meta['robot_id'], 'X-Camera-Name':meta['robot_id']+'__aim',
                'X-Frame-Width':meta['width'], 'X-Frame-Height':meta['height'],
                'X-Camera-Overlays':'false',
                **({'X-Native-Frame-Width':meta['native_width'],'X-Native-Frame-Height':meta['native_height'],
                    'X-Source-Camera':'true'} if meta.get('source_camera') else {}),
                **({'X-Source-Capture-Seq':meta['source_frame_seq']} if meta.get('source_frame_seq') is not None else {})})
        else:
            self._json(404,{'error':'not_found'})

    def do_POST(self):
        if not self._safe_request():
            return
        path = urlsplit(self.path).path
        if path not in ('/control','/select_robot'):
            self._json(404,{'error':'not_found'})
            return
        gate = self.server.state.gate
        def invalid(code, reason):
            gate.neutral(reason)
            self._json(code, {'schema':SCHEMA,'accepted':False,'reason':reason})
        if self.headers.get('Content-Type','').split(';',1)[0].strip() != 'application/json':
            invalid(415,'json_required')
            return
        if self.headers.get('Transfer-Encoding'):
            invalid(400,'transfer_encoding_forbidden')
            return
        try:
            size = int(self.headers.get('Content-Length','-1'))
        except ValueError:
            size = -1
        if not 0 < size <= MAX_BODY_BYTES:
            invalid(413,'invalid_body_length')
            return
        try:
            raw = self._read_body(size)
            message = json.loads(raw,parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (ValueError,UnicodeError,OSError,RecursionError,OverflowError):
            invalid(400,'invalid_json')
            return
        result = (self.server.state.select_robot(message) if path == '/select_robot'
                  else gate.accept(message))
        self._json(200 if result['accepted'] else 409,result)

    def do_OPTIONS(self):
        self._json(403,{'error':'browser_origin_forbidden'})


def start_server(state, port=8768):
    server = OperatorHTTPServer(('127.0.0.1',port),state)
    thread = threading.Thread(target=server.serve_forever,name='operator-http',daemon=True)
    thread.start()
    return server,thread
