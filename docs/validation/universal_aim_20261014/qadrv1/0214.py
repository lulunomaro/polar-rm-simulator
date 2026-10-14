"""CPU-only safety regression; run with python -m unittest this module."""
import http.client
import json
import math
import threading
import unittest
from unittest import mock
from .protocol import ControlGate, OperatorInput
from .server import BridgeState, OperatorHTTPServer, start_server


class Clock:
    def __init__(self): self.now=1000.
    def __call__(self): return self.now
    def advance(self,seconds): self.now+=seconds


class GateTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock()
        self.gate=ControlGate(wall=self.clock,monotonic=self.clock,session_id='synthetic-session')
    def message(self,**changes):
        value=dict(session_id=self.gate.session_id,epoch=self.gate.epoch,robot_id=self.gate.robot_id,
                   seq=1,sent_at_ms=self.clock()*1000,focus=True,deadman=True,vx_mps=1.,
                   vy_mps=0.,yaw_rate_rps=.3,pitch_rate_rps=.2,fire=True)
        value.update(changes)
        return value
    def test_active_command_and_timeout_neutral(self):
        self.assertTrue(self.gate.accept(self.message())['accepted'])
        self.assertTrue(self.gate.sample().fire)
        self.clock.advance(.251)
        self.assertEqual(self.gate.sample(),OperatorInput())
        self.assertEqual(self.gate.reason,'control_timeout')
    def test_clock_changes_cannot_extend_monotonic_deadline(self):
        wall=Clock();self.gate.wall=wall
        self.gate.accept(self.message())
        wall.advance(-100)
        self.clock.advance(.251)
        self.assertFalse(self.gate.sample().fire)
    def test_transit_age_reduces_lease(self):
        self.gate.accept(self.message(sent_at_ms=self.clock()*1000-200))
        self.clock.advance(.051)
        self.assertEqual(self.gate.sample(),OperatorInput())
    def test_failures_clear_previous_command(self):
        bads=[dict(seq=1),dict(session_id='another'),dict(epoch=9),dict(robot_id='blue_infantry'),
              dict(sent_at_ms=self.clock()*1000-250),dict(sent_at_ms=self.clock()*1000+51),
              dict(vx_mps=math.nan),dict(vx_mps=1.01),dict(fire=1),dict(deadman='true'),
              dict(seq=True),dict(seq=2**54),dict(yaw_rate_rps=math.inf)]
        for bad in bads:
            with self.subTest(bad=bad):
                self.setUp();self.gate.accept(self.message())
                self.assertFalse(self.gate.accept(self.message(seq=2,**{k:v for k,v in bad.items() if k!='seq'}) if 'seq' not in bad else self.message(**bad))['accepted'])
                self.assertEqual(self.gate.sample(),OperatorInput())
    def test_extreme_json_integers_reject_and_clear_fire(self):
        for key in ('sent_at_ms','vx_mps','vy_mps','yaw_rate_rps','pitch_rate_rps'):
            with self.subTest(key=key):
                self.setUp();self.gate.accept(self.message())
                self.assertTrue(self.gate.sample().fire)
                self.assertFalse(self.gate.accept(self.message(seq=2,**{key:10**1000}))['accepted'])
                self.assertEqual(self.gate.sample(),OperatorInput())
    def test_release_is_immediate_and_needs_new_sequence(self):
        self.gate.accept(self.message())
        self.assertTrue(self.gate.accept(self.message(seq=2,focus=False))['accepted'])
        self.assertEqual(self.gate.sample(),OperatorInput())
        self.assertFalse(self.gate.accept(self.message(seq=2))['accepted'])
        self.assertTrue(self.gate.accept(self.message(seq=3))['accepted'])
        self.gate.accept(self.message(seq=4,deadman=False))
        self.assertEqual(self.gate.sample(),OperatorInput())
    def test_epoch_robot_change_and_restart_never_replay(self):
        old=self.message();self.gate.accept(old)
        self.gate.new_epoch('blue_infantry')
        self.assertEqual(self.gate.sample(),OperatorInput())
        self.assertFalse(self.gate.accept(old)['accepted'])
        new=ControlGate(wall=self.clock,monotonic=self.clock)
        self.assertFalse(new.accept(old)['accepted'])
    def test_diagonal_limit(self):
        self.gate.accept(self.message(vy_mps=1.))
        self.assertAlmostEqual(math.hypot(self.gate.input.vx_mps,self.gate.input.vy_mps),1.)
    def test_server_disabled(self):
        self.gate.accept(self.message());self.gate.disable()
        self.assertFalse(self.gate.accept(self.message(seq=2))['accepted'])
        self.assertEqual(self.gate.sample(),OperatorInput())


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.state=BridgeState()
        self.server,self.thread=start_server(self.state,0)
        self.port=self.server.server_address[1]
    def tearDown(self):
        self.state.stop();self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,method,path,body=None,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=2)
        connection.request(method,path,body,headers or {})
        response=connection.getresponse();data=response.read();hdrs=dict(response.getheaders())
        connection.close()
        return response.status,data,hdrs
    def test_loopback_only_binding(self):
        with self.assertRaises(ValueError):OperatorHTTPServer(('0.0.0.0',0),self.state)
    def test_session_and_no_frame(self):
        status,data,_=self.request('GET','/session')
        self.assertEqual(status,200)
        session=json.loads(data)
        self.assertEqual(session['robot_id'],'red_infantry')
        self.assertFalse(session['hardware_transport'])
        self.assertEqual(self.request('GET','/frame.jpg')[0],503)
    def test_host_and_web_origin_rejected(self):
        self.assertEqual(self.request('GET','/session',headers={'Host':'evil.example'})[0],403)
        self.assertEqual(self.request('GET','/session',headers={'Origin':'http://evil.example'})[0],403)
    def test_control_and_stale_sequence_ack(self):
        s=self.state.gate.session()
        value=dict(session_id=s['session_id'],epoch=s['epoch'],robot_id=s['robot_id'],seq=1,
                   sent_at_ms=s['server_time_ms'],focus=True,deadman=True,vx_mps=0.,vy_mps=0.,
                   yaw_rate_rps=0.,pitch_rate_rps=0.,fire=True)
        status,data,_=self.request('POST','/control',json.dumps(value),{'Content-Type':'application/json'})
        self.assertEqual(status,200);self.assertTrue(json.loads(data)['accepted'])
        self.assertEqual(self.request('POST','/control',json.dumps(value),{'Content-Type':'application/json'})[0],409)
        self.assertFalse(self.state.gate.sample().fire)
    def test_bad_json_and_non_json_neutral(self):
        self.assertEqual(self.request('POST','/control','{}')[0],415)
        self.assertEqual(self.request('POST','/control','{"bad":NaN}',{'Content-Type':'application/json'})[0],400)
    def test_numeric_overflow_and_deep_json_clear_active_fire(self):
        session=self.state.gate.session()
        def arm(seq):
            value=dict(session_id=session['session_id'],epoch=0,robot_id='red_infantry',seq=seq,
                       sent_at_ms=self.state.gate.wall()*1000,focus=True,deadman=True,vx_mps=0.,vy_mps=0.,
                       yaw_rate_rps=0.,pitch_rate_rps=0.,fire=True)
            status,_,_=self.request('POST','/control',json.dumps(value),{'Content-Type':'application/json'})
            self.assertEqual(status,200)
            self.assertTrue(self.state.gate.sample().fire)
            return value
        for index,key in enumerate(('sent_at_ms','vx_mps','vy_mps','yaw_rate_rps','pitch_rate_rps')):
            with self.subTest(key=key):
                value=arm(index*10+1);value.update(seq=index*10+2,**{key:10**1000})
                body=json.dumps(value);self.assertLess(len(body),4096)
                status,data,_=self.request('POST','/control',body,{'Content-Type':'application/json'})
                self.assertEqual(status,409);self.assertFalse(json.loads(data)['accepted'])
                self.assertFalse(self.state.gate.sample().fire)
        arm(100)
        body='['*1500+'0'+']'*1500
        self.assertLess(len(body),4096)
        status,data,_=self.request('POST','/control',body,{'Content-Type':'application/json'})
        # JSON decoders differ in their supported nesting depth. Either a
        # parse error or the parsed non-object is rejected synchronously.
        self.assertIn(status,(400,409));self.assertFalse(json.loads(data)['accepted'])
        self.assertFalse(self.state.gate.sample().fire)
        arm(110)
        with mock.patch('rm_match.operator.server.json.loads',side_effect=RecursionError('nested JSON')):
            status,data,_=self.request('POST','/control','{}',{'Content-Type':'application/json'})
        self.assertEqual(status,400);self.assertEqual(json.loads(data)['reason'],'invalid_json')
        self.assertFalse(self.state.gate.sample().fire)
    def test_oversized_body_rejected(self):
        self.assertEqual(self.request('POST','/control','x'*4097,{'Content-Type':'application/json'})[0],413)
    def test_cached_frame_headers_and_epoch_invalidation(self):
        self.state.publish({'phase':'running'},b'synthetic-jpeg-not-camera',
                           dict(epoch=0,robot_id='red_infantry',frame_seq=1,sim_time=.2,width=320,height=240))
        status,data,headers=self.request('GET','/frame.jpg')
        self.assertEqual(status,200);self.assertEqual(headers['X-Robot-Id'],'red_infantry')
        self.assertEqual(headers['Content-Type'],'image/jpeg')
        self.assertEqual(int(headers['Content-Length']),len(data))
        self.state.gate.new_epoch()
        self.assertEqual(self.request('GET','/frame.jpg')[0],503)
    def test_reads_do_not_extend_command_lease(self):
        clock=Clock();self.state.gate=ControlGate(wall=clock,monotonic=clock)
        g=self.state.gate;s=g.session()
        value=dict(session_id=s['session_id'],epoch=0,robot_id='red_infantry',seq=1,sent_at_ms=clock()*1000,
                   focus=True,deadman=True,vx_mps=1.,vy_mps=0.,yaw_rate_rps=0.,pitch_rate_rps=0.,fire=True)
        g.accept(value);clock.advance(.251)
        self.request('GET','/session');self.request('GET','/telemetry')
        self.assertEqual(g.sample(),OperatorInput())


if __name__=='__main__':unittest.main()
