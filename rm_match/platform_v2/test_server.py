import http.client
import json
import socket
import threading
import time
import unittest
from .runtime import PlatformRuntime
from .server import PlatformHTTPServer,TransportConfig,MAX_BODY_BYTES
from .test_runtime import FakeBackend,TestRegistry

class ServerTests(unittest.TestCase):
    def setUp(self):
        self.runtime=PlatformRuntime(FakeBackend(),registry=TestRegistry());self.runtime.step_once()
        self.server=PlatformHTTPServer(TransportConfig(port=0,max_http_workers=2),self.runtime)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.port=self.server.server_address[1]
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(2.);self.runtime.close()
    def request(self,path,body=None,token=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=2.)
        h={} if headers is None else dict(headers)
        if token:h['Authorization']='Bearer '+token
        if body is not None:h.setdefault('Content-Type','application/json')
        raw=body if isinstance(body,str) else json.dumps(body) if body is not None else None
        conn.request('POST' if body is not None else 'GET',path,raw,h)
        response=conn.getresponse();value=json.loads(response.read());status=response.status;conn.close()
        return status,value
    def operator(self):return self.request('/v2/sessions',{'role':'operator'})[1]['token']
    def test_auth_required_for_state(self):self.assertEqual(self.request('/v2/state')[0],401)
    def test_origin_blocked_for_state_and_session(self):
        self.assertEqual(self.request('/v2/sessions',{'role':'operator'},headers={'Origin':'https://example.com'})[0],403)
    def test_dns_rebinding_host_blocked(self):
        self.assertEqual(self.request('/v2/health',headers={'Host':'evil.invalid'})[0],403)
    def test_query_and_absolute_urls_refused(self):
        self.assertEqual(self.request('/v2/health?x=1')[0],400)
        self.assertEqual(self.request('http://evil.invalid/v2/health',headers={'Host':f'127.0.0.1:{self.port}'})[0],400)
    def test_malformed_duplicate_nonfinite_json_refused(self):
        for body in ['{"role":"operator","role":"spectator"}','{"role":NaN}','[]','{"role":']:
            self.assertEqual(self.request('/v2/sessions',body)[0],400)
    def test_body_size_bound(self):
        self.assertEqual(self.request('/v2/sessions','x'*(MAX_BODY_BYTES+1))[0],413)
    def test_extra_fields_and_unknown_robot_fail_closed(self):
        token=self.operator()
        self.assertEqual(self.request('/v2/claim',{'robot_id':'alpha','channels':['motion'],'takeover':True},token)[0],400)
        self.assertEqual(self.request('/v2/claim',{'robot_id':'missing','channels':['motion']},token)[0],404)
    def test_no_script_import_or_http_adapter_registration(self):
        token=self.operator()
        self.assertEqual(self.request('/v2/register',{'path':'/tmp/plugin.py'},token)[0],404)
        epochs=self.request('/v2/claim',{'robot_id':'alpha','channels':['motion']},token)[1]['lease_epochs']
        status,value=self.request('/v2/bind',dict(robot_id='alpha',kind='navigation',lease_epochs=epochs,
            adapter_id='../../arbitrary_code',config={}),token)
        self.assertEqual(status,404);self.assertEqual(value['error'],'unknown_adapter')
    def test_actual_bind_is_always_loopback_only(self):
        for host in ['0.0.0.0','192.168.1.2','::1']:
            with self.assertRaises(ValueError):TransportConfig(host=host).validate()
        config=TransportConfig(proposed_lan_host='192.168.1.2').validate()
        self.assertEqual(config.host,'127.0.0.1')
    def test_client_cannot_obtain_algorithm_gt_endpoint(self):
        self.assertEqual(self.request('/v2/observation',token=self.operator())[0],404)
    def test_session_token_not_in_spectator_status(self):
        token=self.operator();other=self.request('/v2/sessions',{'role':'spectator'})[1]['token']
        status,value=self.request('/v2/state',token=other)
        self.assertEqual(status,200);self.assertNotIn(token,json.dumps(value));self.assertNotIn(other,json.dumps(value))
    def test_http_threads_bounded_under_partial_requests(self):
        sockets=[]
        try:
            for _ in range(2):
                s=socket.create_connection(('127.0.0.1',self.port),timeout=2.);s.sendall(b'GET /v2/health HTTP/1.1\r\n');sockets.append(s)
            time.sleep(.05)
            self.assertFalse(self.server._slots.acquire(blocking=False))
            s=socket.create_connection(('127.0.0.1',self.port),timeout=2.);s.settimeout(1.)
            s.sendall(b'GET /v2/health HTTP/1.1\r\n');self.assertEqual(s.recv(1),b'');s.close()
            self.assertEqual(self.runtime.health()['steps'],1)
        finally:
            for s in sockets:s.close()

if __name__=='__main__':unittest.main()
