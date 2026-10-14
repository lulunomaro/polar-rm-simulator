"""Bounded loopback transport for v2. HTTP threads only use cached/state APIs."""
from __future__ import annotations
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import socket
import threading
import time
from urllib.parse import urlsplit
from .control import Rejected, exact
from .admission import AdmissionPolicy

SCHEMA='rm.sim.platform.v2'
MAX_BODY_BYTES=16384
BODY_TIMEOUT_S=1.
REJECT_DRAIN_BYTES=64*1024
REJECT_DRAIN_TIMEOUT_S=.1

@dataclass(frozen=True)
class TransportConfig:
    host: str='127.0.0.1'
    port: int=8766
    max_http_workers: int=16
    # This records a deployment proposal only, never enables a network binding.
    proposed_lan_host: str | None=None
    admission_policy: AdmissionPolicy | None=None

    def validate(self):
        if self.host!='127.0.0.1':
            raise ValueError('Only loopback is enabled; LAN security and host access need explicit deployment approval')
        if type(self.port) is not int or not 0<=self.port<=65535:raise ValueError('Invalid port')
        if type(self.max_http_workers) is not int or not 1<=self.max_http_workers<=64:raise ValueError('Invalid HTTP worker limit')
        if self.admission_policy is not None and not isinstance(self.admission_policy,AdmissionPolicy):raise ValueError('Invalid admission policy')
        if self.proposed_lan_host is not None:
            address=ipaddress.ip_address(self.proposed_lan_host)
            if not address.is_private or address.is_loopback or address.is_unspecified:
                raise ValueError('LAN proposal must name a concrete private interface address')
        return self

class PlatformHTTPServer(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=False
    request_queue_size=16

    def __init__(self,config,runtime):
        config.validate()
        if config.admission_policy is not None:config.admission_policy.validate_robots(runtime.control.robot_ids)
        self.runtime=runtime;self.config=config
        self._slots=threading.BoundedSemaphore(config.max_http_workers)
        super().__init__((config.host,config.port),PlatformHandler)

    def process_request(self,request,client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:super().process_request(request,client_address)
        except BaseException:
            self._slots.release();raise

    def process_request_thread(self,request,client_address):
        try:super().process_request_thread(request,client_address)
        finally:self._slots.release()

class PlatformHandler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.0'
    server_version='MuJoCoPlatform/2'
    def log_message(self,*_):pass
    def setup(self):
        super().setup();self.connection.settimeout(BODY_TIMEOUT_S)
        self._body_bytes_read=0;self._discard_body_on_close=False

    def _read_body(self,length):
        deadline=time.perf_counter()+BODY_TIMEOUT_S;raw=bytearray()
        try:
            while len(raw)<length:
                remaining=deadline-time.perf_counter()
                if remaining<=0:raise TimeoutError('Request body deadline expired')
                self.connection.settimeout(remaining)
                chunk=self.rfile.read1(length-len(raw))
                if not chunk:raise ValueError('truncated body')
                self._body_bytes_read+=len(chunk);raw.extend(chunk)
            if time.perf_counter()>=deadline:raise TimeoutError('Request body deadline expired')
            return bytes(raw)
        finally:self.connection.settimeout(BODY_TIMEOUT_S)

    def finish(self):
        try:
            if self._discard_body_on_close:
                # FIN preserves the rejection before unread receive data can
                # cause a Winsock reset. Discarding is bounded and never parsed.
                self.wfile.flush()
                try:self.connection.shutdown(socket.SHUT_WR)
                except OSError:pass
                try:declared=int(self.headers.get('Content-Length','-1'))
                except ValueError:declared=-1
                remaining=(REJECT_DRAIN_BYTES if declared<0 else
                    min(REJECT_DRAIN_BYTES,max(0,declared-self._body_bytes_read)))
                deadline=time.perf_counter()+REJECT_DRAIN_TIMEOUT_S
                while remaining>0:
                    timeout=deadline-time.perf_counter()
                    if timeout<=0:break
                    self.connection.settimeout(timeout)
                    try:chunk=self.rfile.read1(min(4096,remaining))
                    except OSError:break
                    if not chunk:break
                    remaining-=len(chunk)
        except OSError:pass
        finally:super().finish()

    def _json(self,code,value):
        self.close_connection=True
        if code>=400 and (self.command=='POST' or self.headers.get('Content-Length') is not None or self.headers.get('Transfer-Encoding')):
            self._discard_body_on_close=True
        body=json.dumps(value,allow_nan=False,separators=(',',':')).encode()
        self.send_response(code)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Connection','close')
        try:self.end_headers();self.wfile.write(body);self.wfile.flush()
        except OSError:pass

    def _safe(self):
        if not ipaddress.ip_address(self.client_address[0]).is_loopback:raise Rejected('loopback_only',403)
        port=self.server.server_address[1]
        if self.headers.get_all('Host') not in ([f'127.0.0.1:{port}'],[f'localhost:{port}']):raise Rejected('invalid_host',403)
        if self.headers.get('Origin') is not None:raise Rejected('browser_origin_forbidden',403)
        if self.headers.get('Transfer-Encoding') is not None:raise Rejected('transfer_encoding_forbidden',400)
        url=urlsplit(self.path)
        if url.scheme or url.netloc or url.query or url.fragment:raise Rejected('invalid_path',400)
        return url.path

    def _token(self):
        values=self.headers.get_all('Authorization') or []
        if len(values)!=1 or not values[0].startswith('Bearer '):raise Rejected('invalid_session',401)
        return values[0][7:]

    def _body(self):
        if self.headers.get('Content-Type')!='application/json':raise Rejected('content_type_required',400)
        lengths=self.headers.get_all('Content-Length') or []
        if len(lengths)!=1 or not lengths[0].isdigit():raise Rejected('invalid_length',400)
        length=int(lengths[0])
        if length>MAX_BODY_BYTES:raise Rejected('body_too_large',413)
        def pairs(values):
            d={}
            for k,v in values:
                if k in d:raise ValueError('duplicate key')
                d[k]=v
            return d
        def invalid(_):raise ValueError('nonfinite JSON')
        try:
            raw=self._read_body(length)
            value=json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)
            if not isinstance(value,dict):raise ValueError('object required')
            return value
        except (OSError,ValueError,UnicodeError,RecursionError):raise Rejected('invalid_json',400)

    def do_GET(self):
        try:
            path=self._safe();runtime=self.server.runtime
            if path=='/v2/health':result=runtime.health()
            else:
                token=self._token()
                runtime.control.snapshot(token)
                if path=='/v2/state':result=runtime.snapshot(token)
                elif path=='/v2/frame':result=runtime.frame(token)
                elif path=='/v2/robots':result={'robot_ids':runtime.control.visible_robot_ids(token)}
                elif path=='/v2/adapters':result=runtime.adapter_catalog(token)
                elif path=='/v2/plugins':result=runtime.plugin_catalog(token)
                elif path=='/v2/capabilities':result=runtime.capabilities(token)
                else:raise Rejected('not_found',404)
            self._json(200,dict(schema=SCHEMA,**result))
        except Rejected as e:self._json(e.status,{'accepted':False,'error':e.reason})
        except (ValueError,TypeError,KeyError,RecursionError):self._json(400,{'accepted':False,'error':'invalid_request'})

    def do_POST(self):
        try:
            path=self._safe();v=self._body();runtime=self.server.runtime;p=runtime.control
            if path=='/v2/sessions':
                keys=('role',)+tuple(k for k in ('control_profile','credential') if k in v)
                exact(v,keys)
                policy=self.server.config.admission_policy
                if policy is None:raise Rejected('admission_policy_required',401)
                grant=policy.authenticate(v['role'],v.get('credential'))
                result=p.open_session(grant.role,v.get('control_profile','legacy_v2'),
                    allowed_robots=grant.allowed_robots if grant.role=='operator' else None,
                    audit_authorized=grant.audit_authorized,trusted_admin=False)
            else:
                token=self._token()
                if path=='/v2/keepalive':exact(v,());result=p.keepalive(token)
                elif path=='/v2/close':exact(v,());result=p.close_session(token)
                elif path=='/v2/watch':exact(v,('robot_id',));result=runtime.watch(token,v['robot_id'])
                elif path=='/v2/claim':
                    exact(v,('robot_id','channels'));result=p.claim(token,v['robot_id'],v['channels'])
                elif path=='/v2/renew':
                    exact(v,('robot_id','lease_epochs'));result=p.renew(token,v['robot_id'],v['lease_epochs'])
                elif path=='/v2/release':
                    exact(v,('robot_id','lease_epochs'));result=p.release(token,v['robot_id'],v['lease_epochs'])
                elif path=='/v2/adapter_input':
                    exact(v,('robot_id','kind','lease_epochs','binding_epoch','seq','window_id','valid_for_s'))
                    result=p.adapter_input(token,v['robot_id'],v['kind'],v['lease_epochs'],v['binding_epoch'],v['seq'],v['window_id'],v['valid_for_s'])
                elif path=='/v2/control_window':
                    exact(v,('robot_id','lease_epochs'));result=p.control_window(token,v['robot_id'],v['lease_epochs'])
                elif path=='/v2/control_batch':
                    exact(v,('robot_id','lease_epochs','window_id','valid_for_s','adapter_inputs','controls'))
                    result=p.control_batch(token,v['robot_id'],v['lease_epochs'],v['window_id'],v['valid_for_s'],v['adapter_inputs'],v['controls'])
                elif path=='/v2/control':
                    keys=('robot_id','channel','lease_epoch','seq','value','valid_for_s')
                    exact(v,keys+('window_id',) if 'window_id' in v else keys)
                    if 'window_id' in v and type(v['window_id']) is not int:raise Rejected('invalid_window_id',400)
                    result=p.control(token,v['robot_id'],v['channel'],v['lease_epoch'],v['seq'],v['value'],v['valid_for_s'],v.get('window_id'))
                elif path=='/v2/bind':
                    exact(v,('robot_id','kind','lease_epochs','adapter_id','config'))
                    result=runtime.bind(token,**v)
                elif path=='/v2/unbind':
                    exact(v,('robot_id','kind','lease_epochs'));result=p.unbind(token,v['robot_id'],v['kind'],v['lease_epochs'])
                else:raise Rejected('not_found',404)
            self._json(200,dict(schema=SCHEMA,**result))
        except Rejected as e:self._json(e.status,{'accepted':False,'error':e.reason})
        except (ValueError,TypeError,KeyError,RecursionError):self._json(400,{'accepted':False,'error':'invalid_request'})
