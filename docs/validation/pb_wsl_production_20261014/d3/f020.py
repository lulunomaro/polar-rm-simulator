"""Real loopback transport boundaries; fake authority, no physics/ROS runtime."""
import http.client
import json
import socket
import threading
import time
import unittest
from types import SimpleNamespace

from rm_match.platform_v2.server import (PlatformHTTPServer,TransportConfig,MAX_BODY_BYTES,
    BODY_TIMEOUT_S,REJECT_DRAIN_TIMEOUT_S)


class Control:
    robot_ids=['red_sentry']
    def __init__(self):self.calls=[];self.original_window_deadline=77.
    def renew(self,*args):self.calls.append(args);return {'accepted':True}


class RejectionTests(unittest.TestCase):
    def setUp(self):
        self.control=Control();runtime=SimpleNamespace(control=self.control,health=lambda:{'steps':0})
        self.server=PlatformHTTPServer(TransportConfig(port=0,max_http_workers=2),runtime)
        self.thread=threading.Thread(target=lambda:self.server.serve_forever(poll_interval=.01));self.thread.start()
        self.port=self.server.server_address[1]
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(2.)
        self.assertFalse(self.thread.is_alive())
        deadline=time.perf_counter()+1.5
        while time.perf_counter()<deadline:
            acquired=[]
            for _ in range(2):
                if self.server._slots.acquire(blocking=False):acquired.append(True)
            for _ in acquired:self.server._slots.release()
            if len(acquired)==2:return
            time.sleep(.005)
        self.fail('HTTP workers did not release their bounded slots')
    def headers(self,conn,length,extra=None):
        conn.putrequest('POST','/v2/renew');conn.putheader('Content-Type','application/json')
        conn.putheader('Content-Length',str(length));conn.putheader('Authorization','Bearer fixture')
        for k,v in (extra or {}).items():conn.putheader(k,v)
        conn.endheaders()
    def connection(self):return http.client.HTTPConnection('127.0.0.1',self.port,timeout=2.)
    def response(self,conn):
        response=conn.getresponse();body=json.loads(response.read())
        self.assertEqual(response.getheader('Connection'),'close')
        return response.status,body

    def test_oversized_immediate_and_delayed_unread_bytes_deliver_exact_413(self):
        for delay in (0.,.015,.05):
            for sample in range(3):
                with self.subTest(delay=delay,sample=sample):
                    conn=self.connection()
                    try:
                        self.headers(conn,MAX_BODY_BYTES+1)
                        if delay:time.sleep(delay)
                        conn.send(b'x'*(MAX_BODY_BYTES+1))
                        self.assertEqual(self.response(conn),(413,{'accepted':False,'error':'body_too_large'}))
                    finally:conn.close()
        self.assertEqual(self.control.calls,[]);self.assertEqual(self.control.original_window_deadline,77.)

    def test_earlier_origin_rejection_with_unread_body_also_finishes_without_authority(self):
        conn=self.connection()
        try:
            self.headers(conn,MAX_BODY_BYTES+1,{'Origin':'https://untrusted.invalid'})
            time.sleep(.02);conn.send(b'x'*(MAX_BODY_BYTES+1))
            self.assertEqual(self.response(conn),(403,{'accepted':False,'error':'browser_origin_forbidden'}))
        finally:conn.close()
        self.assertEqual(self.control.calls,[])

    def test_declared_huge_body_stall_has_bounded_rejection_drain_and_releases_worker(self):
        conn=self.connection();started=time.perf_counter()
        try:
            self.headers(conn,10**9);conn.send(b'x'*8192)
            self.assertEqual(self.response(conn),(413,{'accepted':False,'error':'body_too_large'}))
            self.assertLess(time.perf_counter()-started,.5)
            time.sleep(REJECT_DRAIN_TIMEOUT_S+.05)
            acquired=[]
            for _ in range(2):
                if self.server._slots.acquire(blocking=False):acquired.append(True)
            for _ in acquired:self.server._slots.release()
            self.assertEqual(len(acquired),2)
        finally:conn.close()
        self.assertEqual(self.control.calls,[])

    def test_accepted_size_limit_preserved_with_fragmented_complete_valid_body(self):
        raw=json.dumps({'robot_id':'red_sentry','lease_epochs':{'motion':1}}).encode()
        raw+=b' '*(MAX_BODY_BYTES-len(raw));conn=self.connection()
        try:
            self.headers(conn,len(raw));conn.send(raw[:33]);time.sleep(.02);conn.send(raw[33:])
            status,body=self.response(conn)
            self.assertEqual(status,200);self.assertTrue(body['accepted'])
        finally:conn.close()
        self.assertEqual(len(self.control.calls),1);self.assertEqual(MAX_BODY_BYTES,16384)

    def test_slow_drip_hits_one_total_second_and_never_renews_authority(self):
        raw=json.dumps({'robot_id':'red_sentry','lease_epochs':{'motion':1}}).encode();conn=self.connection()
        self.headers(conn,len(raw));sock=conn.sock;conn.send(raw[:1]);stop=threading.Event()
        def drip():
            try:
                for i in range(1,5):
                    if stop.wait(.3):return
                    sock.sendall(raw[i:i+1])
                if not stop.wait(.3):sock.sendall(raw[5:])
            except OSError:pass  # peer may close after its already-sent error
        writer=threading.Thread(target=drip);started=time.perf_counter();writer.start()
        try:
            self.assertEqual(self.response(conn),(400,{'accepted':False,'error':'invalid_json'}))
            elapsed=time.perf_counter()-started
            self.assertGreaterEqual(elapsed,BODY_TIMEOUT_S-.2)
            self.assertLess(elapsed,BODY_TIMEOUT_S+.4)
        finally:stop.set();writer.join(1.);conn.close()
        self.assertFalse(writer.is_alive());self.assertEqual(self.control.calls,[])
        self.assertEqual(self.control.original_window_deadline,77.)

    def test_truncated_body_returns_json_failure_without_dispatch(self):
        conn=self.connection()
        try:
            self.headers(conn,10);conn.send(b'{');conn.sock.shutdown(socket.SHUT_WR)
            self.assertEqual(self.response(conn),(400,{'accepted':False,'error':'invalid_json'}))
        finally:conn.close()
        self.assertEqual(self.control.calls,[])


if __name__=='__main__':unittest.main()
