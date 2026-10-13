"""Real Linux stdio/STOP fixture; injected stack/transport, no ROS/DDS/NN/SIL."""
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from rm_match.integrations import pb_wsl_navigation_worker as worker
from rm_match.integrations.pb_wsl_navigation import SOURCE_FILES

ROOT=Path(__file__).resolve().parents[1]


class FakeStack:
    def __init__(self,config,out,namespace,**kwargs):
        self.namespace=namespace;self.state='CONFIGURED'
    def start(self):
        return dict(topics={k:self.namespace+'/'+v for k,v in dict(cloud='livox/lidar',
            imu='livox/imu',request='polar/pb/request',result='polar/pb/result',
            odom='odometry',clock='clock',tf_static='tf_static').items()})
    def poll_health(self):return self.state
    def stop(self,grace_s=.15):return dict(clean=True,processes=[])


class FakeTransport:
    def __init__(self,*args):pass
    def spin_once(self,timeout):pass
    def close(self):pass


class FakeGate:
    def __init__(self,*args):self.maps=0
    def poll(self,core):pass
    def close(self):return True


def fixture_spec(out):
    config=out/'config.json';config.write_bytes(b'{}\n')
    return dict(run_uuid='a'*32,namespace='/polar_sil_'+'a'*32+'/red_sentry',
        config_ref=dict(path=str(config),sha256=hashlib.sha256(config.read_bytes()).hexdigest()),
        environment_ref=dict(sha256='b'*64),diagnostics=False,relative_test_goal=False,
        source_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCE_FILES})


CHILD=r'''
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from tests.test_pb_wsl_navigation_stdio import FakeStack,FakeTransport,FakeGate
from rm_match.integrations import pb_wsl_navigation_worker as w
from rm_match.integrations.pb_wsl_navigation import SOURCE_FILES
out=Path(sys.argv[2]);mode=sys.argv[3];spec=json.loads((out/'FIXTURE_SPEC.json').read_bytes())
assert all(w.sha(w.ROOT/name)==h for name,h in spec['source_sha256'].items())
original_write=w.os.write
if mode=='short_write':
    def short(fd,view):return original_write(fd,view[:7]) if fd==1 else original_write(fd,view)
    w.os.write=short
marker=out/'fixture-source.txt'
if mode=='deleted_source':
    marker.write_bytes(b'actual fixture source, never repository source\n')
    spec['source_sha256'][str(marker)]=w.sha(marker)
class Transport(FakeTransport):
    def close(self):
        if mode=='deleted_source':marker.unlink()
        if mode=='close_error':raise RuntimeError('intentional fixture transport close failure')
w.NavigationGate=FakeGate
code=w.session_worker(spec,out,stack_factory=FakeStack,transport_factory=Transport)
assert not any(k=='rclpy' or k.startswith('rclpy.') for k in sys.modules)
(out/'CHILD_RESULT.json').write_text(json.dumps(dict(
    qualification='actual Linux stdio/cancel only; injected fake stack and transport; no ROS/DDS/NN/SIL',
    returncode=code,ros_imported=False,worker_sha256=w.sha(w.__file__),
    source_sha256={n:w.sha(w.ROOT/n) for n in SOURCE_FILES})))
raise SystemExit(code)
'''


@unittest.skipUnless(sys.platform=='linux' and os.environ.get('POLAR_TEST_WSL')=='1',
                     'explicit Linux harmless stdio fixture requires POLAR_TEST_WSL=1')
class ActualLinuxStdioTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(prefix='polar-harmless-stdio-')
        self.out=Path(self.temp.name);self.spec=fixture_spec(self.out)
        (self.out/'FIXTURE_SPEC.json').write_text(json.dumps(self.spec))
        self.script=self.out/'child.py';self.script.write_text(CHILD)
        self.child=None;self.received=[];self.buffer=bytearray();self.stderr=None

    def start(self,mode='normal'):
        self.stderr=(self.out/'stderr.log').open('wb')
        self.child=subprocess.Popen([sys.executable,'-u',str(self.script),str(ROOT),str(self.out),mode],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr,bufsize=0,start_new_session=True)
        os.set_blocking(self.child.stdout.fileno(),False)
        ready=self.read_line()
        self.assertEqual(ready['event'],'ready');self.assertEqual(ready['supervisor_pid'],self.child.pid)
        self.assertEqual(ready['run_uuid'],self.spec['run_uuid'])
        return ready

    def read_line(self,timeout=15.):
        deadline=time.monotonic()+timeout
        while b'\n' not in self.buffer:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise AssertionError('bounded child reply wait expired')
            readable,_,_=select.select([self.child.stdout],[],[],min(.02,remaining))
            if not readable:continue
            raw=os.read(self.child.stdout.fileno(),65536)
            if not raw:raise AssertionError('child EOF before complete reply')
            self.buffer.extend(raw)
            self.assertLessEqual(len(self.buffer),worker.MAX_RESPONSE)
        raw,_,rest=self.buffer.partition(b'\n');self.buffer=bytearray(rest)
        self.received.append(bytes(raw)+b'\n')
        return json.loads(raw)

    def request(self,serial=1):
        return (json.dumps(dict(schema=worker.WIRE,op='status',id=serial,run_uuid=self.spec['run_uuid'],
                packet=dict(schema='polar.sim.adapter.jsonl.v1',op='status')),separators=(',',':'))+'\n').encode()

    def finish(self,code):
        self.assertEqual(self.child.wait(timeout=5.),code)
        self.assertIsNotNone(self.child.poll())
        self.stderr.flush()
        cleanup=json.loads((self.out/'CLEANUP.json').read_bytes())
        self.assertEqual(cleanup['supervisor_pid'],self.child.pid)
        self.assertEqual(cleanup['owned_groups'],[])
        actual=json.loads((self.out/'CHILD_RESULT.json').read_bytes())
        self.assertFalse(actual['ros_imported'])
        self.assertEqual(actual['source_sha256'],self.spec['source_sha256'])
        self.assertEqual(actual['worker_sha256'],self.spec['source_sha256']['rm_match/integrations/pb_wsl_navigation_worker.py'])
        return cleanup

    def tearDown(self):
        try:
            if self.child is not None:
                if self.child.poll() is None:
                    (self.out/'STOP').write_text(json.dumps(dict(run_uuid=self.spec['run_uuid'],
                        config_sha256=self.spec['config_ref']['sha256'])))
                    try:self.child.wait(timeout=5.)
                    except subprocess.TimeoutExpired:
                        self.child.kill();self.child.wait(timeout=5.)
                for stream in (self.child.stdin,self.child.stdout):
                    if stream is not None:stream.close()
                self.assertIsNotNone(self.child.poll(),'owned fixture child must be reaped')
            if self.stderr is not None:self.stderr.close()
            destination=os.environ.get('POLAR_WSL_STDIO_ARTIFACTS')
            if destination:
                import shutil
                target=Path(destination)/self._testMethodName;target.mkdir(parents=True,exist_ok=False)
                for path in self.out.iterdir():
                    if path.is_file():shutil.copyfile(path,target/path.name)
                (target/'stdout.jsonl').write_bytes(b''.join(self.received))
                (target/'PROCESS_RESULT.json').write_text(json.dumps(dict(pid=None if self.child is None else self.child.pid,
                    returncode=None if self.child is None else self.child.returncode,owned_child_reaped=self.child is None or self.child.poll() is not None,
                    test_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    child_script_sha256=hashlib.sha256(CHILD.encode()).hexdigest(),
                    qualification='harmless real stdio with injected fake stack/transport; no ROS/DDS/NN/SIL')))
        finally:self.temp.cleanup()

    def test_empty_eof_is_normal_and_has_exact_owned_cleanup(self):
        self.start();self.child.stdin.close()
        self.assertTrue(self.finish(0)['clean'])

    def test_partial_second_header_eof_fails_without_reusing_success_reply(self):
        self.start();self.child.stdin.write(self.request())
        self.assertEqual(self.read_line()['id'],1)
        self.child.stdin.write(self.request(2)[:31]);self.child.stdin.close()
        cleanup=self.finish(2)
        self.assertFalse(cleanup['clean']);self.assertTrue(any('partial_request_at_eof' in x for x in cleanup['errors']))
        self.assertEqual(len(self.received),2)

    def test_fragmented_input_and_real_short_writes_preserve_exact_transaction(self):
        self.start('short_write');raw=self.request()
        for index in range(0,len(raw),11):self.child.stdin.write(raw[index:index+11]);time.sleep(.001)
        reply=self.read_line()
        self.assertEqual(reply,dict(schema=worker.WIRE,op='status',id=1,run_uuid=self.spec['run_uuid'],result=dict(
            stack_state='CONFIGURED',bridge_reset=False,namespace=self.spec['namespace'],goal_report={},
            odometry_messages=0,map_messages=0,errors=[],clock_domain='linux_local_receive_only')))
        self.child.stdin.close();self.assertTrue(self.finish(0)['clean'])

    def test_stop_cancels_pending_partial_input_without_waiting_for_newline(self):
        self.start();self.child.stdin.write(self.request()[:29])
        (self.out/'STOP').write_text(json.dumps(dict(run_uuid=self.spec['run_uuid'],config_sha256=self.spec['config_ref']['sha256'])))
        self.assertTrue(self.finish(0)['clean']);self.assertEqual(len(self.received),1)

    def test_deleted_fixture_source_during_close_still_writes_failed_cleanup(self):
        self.start('deleted_source');self.child.stdin.close();cleanup=self.finish(2)
        self.assertFalse(cleanup['clean']);self.assertIn('session_source_changed',cleanup['errors'])
        self.assertTrue(any('source_recheck:FileNotFoundError' in x for x in cleanup['errors']))

    def test_transport_close_exception_still_writes_failed_cleanup(self):
        self.start('close_error');self.child.stdin.close();cleanup=self.finish(2)
        self.assertFalse(cleanup['clean']);self.assertIn('transport_cleanup:RuntimeError',cleanup['errors'])

    def test_duplicate_transaction_is_sticky_failure(self):
        self.start();self.child.stdin.write(self.request());self.assertEqual(self.read_line()['id'],1)
        self.child.stdin.write(self.request());self.child.stdin.close();cleanup=self.finish(2)
        self.assertFalse(cleanup['clean']);self.assertTrue(any('request_sequence' in x for x in cleanup['errors']))


class LocalOutputDeadlineTests(unittest.TestCase):
    def test_select_wake_after_local_output_deadline_does_not_write_ready_bytes(self):
        with TemporaryDirectory() as directory:
            out=Path(directory);spec=fixture_spec(out);clock=[0.]
            def late_select(*args):clock[0]=.2;return [],[1],[]
            with patch.object(worker,'NavigationGate',FakeGate),\
                 patch.object(worker,'process_identity',return_value=dict(supervisor_pid=123,start_ticks=0,boot_id='fixture')),\
                 patch.object(worker.os,'set_blocking'),patch.object(worker.signal,'signal'),\
                 patch.object(worker.time,'monotonic',side_effect=lambda:clock[0]),\
                 patch.object(worker.select,'select',side_effect=late_select),patch.object(worker.os,'write') as write:
                code=worker.session_worker(spec,out,stack_factory=FakeStack,transport_factory=FakeTransport)
            self.assertEqual(code,2);write.assert_not_called()
            cleanup=json.loads((out/'CLEANUP.json').read_bytes())
            self.assertFalse(cleanup['clean']);self.assertTrue(any('output_blocked' in x for x in cleanup['errors']))


if __name__=='__main__':unittest.main()
