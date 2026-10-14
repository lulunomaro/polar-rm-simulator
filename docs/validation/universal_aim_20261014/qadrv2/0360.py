"""Actual loopback sockets; no renderer, native process or simulator."""
import http.client
import json
import socket
import threading
import time
import unittest
from unittest.mock import patch

from rm_match.operator import server as transport
from rm_match.operator.protocol import OperatorInput


class RejectionTests(unittest.TestCase):
    def setUp(self):
        self.state=transport.BridgeState();self.server,self.thread=transport.start_server(self.state,0)
        self.port=self.server.server_address[1]
    def tearDown(self):
        self.state.stop();self.server.shutdown();self.server.server_close();self.thread.join(2.)
        self.assertFalse(self.thread.is_alive())
    def headers(self,size,host=None):
        return ('POST /control HTTP/1.0\r\nHost: '+(host or '127.0.0.1:'+str(self.port))+
            '\r\nContent-Type: application/json\r\nContent-Length: '+str(size)+'\r\n\r\n').encode()
    def arm(self):
        g=self.state.gate;s=g.session()
        v=dict(session_id=s['session_id'],epoch=s['epoch'],robot_id=s['robot_id'],seq=1,
            sent_at_ms=g.wall()*1000,focus=True,deadman=True,vx_mps=0.,vy_mps=0.,
            yaw_rate_rps=0.,pitch_rate_rps=0.,fire=True)
        self.assertTrue(g.accept(v)['accepted']);self.assertTrue(g.sample().fire)
    def test_split_oversized_body_delivers_complete_413_and_neutralizes_first(self):
        self.arm()
        # The vulnerable handler closed during this header/body gap. No retries
        # or tolerated socket errors: each response must be complete HTTP JSON.
        for i in range(8):
            with self.subTest(trial=i),socket.create_connection(('127.0.0.1',self.port),timeout=1.) as raw:
                raw.sendall(self.headers(4097));time.sleep(.02);raw.sendall(b'x'*4097)
                response=http.client.HTTPResponse(raw);response.begin();body=response.read()
                self.assertEqual(response.status,413);self.assertEqual(json.loads(body)['reason'],'invalid_body_length')
                self.assertEqual(int(response.getheader('Content-Length')),len(body))
                self.assertEqual(response.getheader('Connection'),'close')
                self.assertEqual(self.state.gate.sample(),OperatorInput())
    def test_authorization_rejection_does_not_parse_delayed_body(self):
        with socket.create_connection(('127.0.0.1',self.port),timeout=1.) as raw:
            raw.sendall(self.headers(4097,host='evil.example'));time.sleep(.02);raw.sendall(b'x'*4097)
            response=http.client.HTTPResponse(raw);response.begin()
            self.assertEqual(response.status,403);self.assertEqual(json.loads(response.read())['error'],'invalid_host')
    def test_exact_4096_byte_json_reaches_gate_instead_of_size_rejection(self):
        connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=1.)
        try:
            connection.request('POST','/control','{}'+' '*4094,{'Content-Type':'application/json'})
            response=connection.getresponse();self.assertEqual(response.status,409)
            self.assertFalse(json.loads(response.read())['accepted'])
        finally:connection.close()
    def test_huge_declared_body_returns_413_without_waiting_for_payload(self):
        finished=threading.Event();old=transport.OperatorHandler.finish
        def finish(handler):
            try:old(handler)
            finally:finished.set()
        with patch.object(transport.OperatorHandler,'finish',finish),socket.create_connection(('127.0.0.1',self.port),timeout=1.) as raw:
            started=time.perf_counter();raw.sendall(self.headers(10**12));response=http.client.HTTPResponse(raw);response.begin()
            self.assertEqual(response.status,413);self.assertFalse(json.loads(response.read())['accepted'])
            self.assertTrue(finished.wait(.4));self.assertLess(time.perf_counter()-started,.5)
    def test_discard_cap_does_not_attempt_to_read_all_claimed_bytes(self):
        # Constant is a disposal cap, never an expanded accepted JSON limit.
        self.assertEqual(transport.MAX_BODY_BYTES,4096)
        with socket.create_connection(('127.0.0.1',self.port),timeout=1.) as raw:
            raw.sendall(self.headers(transport.REJECT_DRAIN_BYTES+100));response=http.client.HTTPResponse(raw);response.begin()
            self.assertEqual(response.status,413);response.read()
            raw.sendall(b'x'*transport.REJECT_DRAIN_BYTES)
            # EOF follows the cap even though 100 declared bytes never arrive.
            self.assertEqual(raw.recv(1),b'')
    def test_slow_valid_body_has_total_deadline_and_cannot_hold_active_fire(self):
        self.arm();finished=threading.Event();old=transport.OperatorHandler.finish
        def finish(handler):
            try:old(handler)
            finally:finished.set()
        with patch.object(transport,'BODY_TIMEOUT_S',.1),patch.object(transport.OperatorHandler,'finish',finish),socket.create_connection(('127.0.0.1',self.port),timeout=1.) as raw:
            started=time.perf_counter();raw.sendall(self.headers(100));raw.sendall(b'{');time.sleep(.03);raw.sendall(b' ')
            time.sleep(.03);raw.sendall(b' ')
            response=http.client.HTTPResponse(raw);response.begin();self.assertEqual(response.status,400)
            self.assertEqual(json.loads(response.read())['reason'],'invalid_json')
            self.assertTrue(finished.wait(.4));self.assertLess(time.perf_counter()-started,.5)
            self.assertEqual(self.state.gate.sample(),OperatorInput())
    def test_nonreading_continuous_sender_cannot_keep_rejection_worker_alive(self):
        self.arm();finished=threading.Event();stop=threading.Event();old=transport.OperatorHandler.finish
        def finish(handler):
            try:old(handler)
            finally:finished.set()
        with patch.object(transport.OperatorHandler,'finish',finish),socket.create_connection(('127.0.0.1',self.port),timeout=.3) as raw:
            def send():
                while not stop.is_set():
                    try:raw.sendall(b'x'*1024)
                    except OSError:return  # Attack ends when the bounded server closes.
                    stop.wait(.003)
            started=time.perf_counter();raw.sendall(self.headers(10**12))
            sender=threading.Thread(target=send,name='bounded-http-attack-fixture');sender.start()
            try:
                # Deliberately never read HTTP. A disposal loop cannot wait for
                # either the enormous declared body or the sender's eventual EOF.
                self.assertTrue(finished.wait(.4));self.assertLess(time.perf_counter()-started,.5)
                self.assertEqual(self.state.gate.sample(),OperatorInput())
            finally:
                stop.set()
                try:raw.shutdown(socket.SHUT_RDWR)
                except OSError:pass  # The attacking peer may already be disconnected.
                sender.join(.4)
            self.assertFalse(sender.is_alive())


if __name__=='__main__':unittest.main()
