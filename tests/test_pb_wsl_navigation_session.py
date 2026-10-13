"""Mock pipes/clock origins only; no WSL, DDS, navigation or native inference."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rm_match.integrations import pb_wsl_navigation as host
from rm_match.platform_v2.contracts import IDENTITY, action_for
from test_pb_navigation_bridge import observation


class Clock:
    def __init__(self):self.now = 987654000.
    def __call__(self):return self.now


class Output:
    def __init__(self, child):self.child=child;self.queue=queue.Queue();self.closed=False
    def read(self, size):
        while not self.closed:
            try:return self.queue.get(timeout=.005)
            except queue.Empty:
                if self.child.returncode is not None:return b''
        return b''
    def emit(self, value):
        raw=value if type(value) is bytes else host._encode(value,host.MAX_LINE)
        for i in range(0,len(raw),host.CHUNK):self.queue.put(raw[i:i+host.CHUNK])
    def close(self):self.closed=True


class Input:
    def __init__(self, child):self.child=child;self.pending=bytearray();self.writes=[];self.closed=False
    def write(self, value):
        if self.closed:raise BrokenPipeError()
        count=min(len(value),self.child.write_size)
        raw=bytes(value[:count]);self.writes.append(raw);self.pending.extend(raw)
        if b'\n' in self.pending:
            line,_,tail=self.pending.partition(b'\n');self.pending=bytearray(tail)
            self.child.receive(host._json(line))
        return count
    def flush(self):pass
    def close(self):self.closed=True


class Child:
    def __init__(self, session):
        self.session=session;self.returncode=None;self.write_size=31;self.requests=[];self.mutate=None
        self.cleanup_mutate=None;self.no_cleanup=False;self.no_reply=False
        self.stdout=Output(self);self.stdin=Input(self);self.pid=777
        self.identity=dict(supervisor_pid=8123,start_ticks=4567,boot_id='a'*8+'-'+('b'*4+'-')*3+'c'*12)
        self.stdout.emit(dict(schema=host.SCHEMA,event='ready',run_uuid=session.run_uuid,
            namespace=session.namespace,config_sha256=session.spec['config_ref']['sha256'],
            environment_sha256=session.spec['environment_ref']['sha256'],state='CONFIGURED',**self.identity))
    def receive(self, request):
        self.requests.append(deepcopy(request))
        if self.no_reply:return
        op=request['op']
        if op=='act':
            o=request['packet']['observation']
            result=dict(schema=host.JSONL_SCHEMA,op=op,ok=True,
                action=action_for(o,'navigation','velocity_body',dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=0.)))
        elif op=='reset':result=dict(schema=host.JSONL_SCHEMA,op=op,ok=True)
        else:result=dict(state='CONFIGURED',goal_report={'fixture_only':True})
        reply=dict(schema=host.SCHEMA,op=op,id=request['id'],run_uuid=request['run_uuid'],result=result)
        if self.mutate:self.mutate(reply)
        self.stdout.emit(reply)
    def poll(self):
        if self.returncode is None and self.session._stop.is_set():
            self.returncode=0
            if not self.no_cleanup:
                cleanup=dict(schema=host.CLEANUP_SCHEMA,run_uuid=self.session.run_uuid,
                    config_sha256=self.session.spec['config_ref']['sha256'],clean=True,owned_groups=[],errors=[],**self.identity)
                if self.cleanup_mutate:self.cleanup_mutate(cleanup)
                (self.session.out/'CLEANUP.json').write_bytes(host._encode(cleanup,host.MAX_LINE))
        return self.returncode
    def wait(self,timeout=None):
        if self.poll() is None:raise subprocess.TimeoutExpired('mock-wsl',timeout)
        return self.returncode


@unittest.skipUnless(sys.platform == 'win32', 'Windows-host path/pipe fixtures; no simulated POSIX path qualification')
class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'repo';self.root.mkdir()
        for relative in host.SOURCE_FILES:
            p=self.root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(relative.encode())
        self.config=self.root/'config.json';self.config.write_text('{}',encoding='utf8')
        self.env=self.root/'environment.json';self.env.write_text('{}',encoding='utf8')
        self.exe=self.root/'mock-wsl.exe';self.exe.write_bytes(b'NOT AN EXECUTABLE')
        self.clock=Clock();self.counter=0;self.sessions=[]
        self.addCleanup(self.stop_sessions)
    def stop_sessions(self):
        for session in self.sessions:
            try:session.close()
            except RuntimeError:pass
    def new(self):
        self.counter+=1
        ref=lambda p:dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
        s=host.WslNavigationSession(self.root,self.root/'artifacts'/('out'+str(self.counter)),ref(self.config),ref(self.env),clock=self.clock)
        self.sessions.append(s);return s
    def prepared(self):
        s=self.new();children=[]
        def start(*args,**kw):
            children.append(Child(s));return children[-1]
        with patch.object(host.sys,'platform','win32'),patch.object(host,'WSL_EXECUTABLE',self.exe),patch.object(host.subprocess,'Popen',side_effect=start) as popen:
            ready=s.prepare()
        return s,children[0],popen,ready
    def reset(self,s):return s.reset(dict(robot_id='red_sentry',episode=0,binding_epoch=1))
    def obs(self):
        o=observation();o.update(episode=0,binding_epoch=1,wall_deadline=self.clock()+.13)
        return o
    def test_fixed_command_ready_and_original_identity_foreign_clock(self):
        s,c,p,ready=self.prepared();self.reset(s);o=self.obs();old=deepcopy(o)
        reply=s.act(o)
        self.assertEqual(o,old);self.assertEqual(c.requests[-1]['packet']['observation'],old)
        self.assertEqual({k:reply['action'][k] for k in IDENTITY},{k:o[k] for k in IDENTITY})
        self.assertEqual(reply['action']['wall_deadline'],987654000.13)
        argv=p.call_args.args[0]
        self.assertEqual(argv[0],str(self.exe));self.assertLessEqual(len(argv),32)
        self.assertIn('/usr/bin/python3',argv);self.assertIn('--spec-sha256',argv)
        self.assertIs(p.call_args.kwargs['shell'],False)
        self.assertEqual(ready['state'],'CONFIGURED');self.assertNotIn('observation',s.spec)
        self.assertEqual(len(s.spec['source_sha256']),len(host.SOURCE_FILES))
        self.assertGreater(len(c.stdin.writes),1)
    def test_control_original_deadline_counts_transport_and_late_reply(self):
        s,c,_,_=self.prepared();self.reset(s);o=self.obs()
        c.mutate=lambda r:setattr(self.clock,'now',o['wall_deadline'])
        with self.assertRaises(TimeoutError):s.act(o)
        self.assertTrue(s._stop.is_set());self.assertEqual(c.requests[-1]['packet']['observation'],o)
    def test_serialization_cost_cannot_refresh_original_deadline(self):
        s,c,_,_=self.prepared();self.reset(s);o=self.obs();old_encode=host._encode
        def encode(*args,**kwargs):
            value=old_encode(*args,**kwargs)
            if args[0].get('op')=='act':self.clock.now=o['wall_deadline']+.001
            return value
        with patch.object(host,'_encode',side_effect=encode),self.assertRaises(TimeoutError):s.act(o)
        self.assertEqual(len(c.requests),1)
    def test_act_never_receives_more_than_150ms_even_future_deadline(self):
        s,c,_,_=self.prepared();self.reset(s);o=self.obs();o['wall_deadline']=self.clock()+20.
        c.mutate=lambda r:setattr(self.clock,'now',self.clock()+.151)
        with self.assertRaises(TimeoutError):s.act(o)
    def test_prepare_budget_covers_verify_and_process_start(self):
        s=self.new();original=s._verify
        def slowverify():original();self.clock.now+=10.001
        with patch.object(host.sys,'platform','win32'),patch.object(host,'WSL_EXECUTABLE',self.exe),patch.object(s,'_verify',side_effect=slowverify),patch.object(host.subprocess,'Popen') as spawn:
            with self.assertRaises(TimeoutError):s.prepare()
        spawn.assert_not_called()
    def test_ready_wait_counts_popen_time(self):
        s=self.new()
        def slowstart(*args,**kwargs):self.clock.now+=10.;return Child(s)
        with patch.object(host.sys,'platform','win32'),patch.object(host,'WSL_EXECUTABLE',self.exe),patch.object(host.subprocess,'Popen',side_effect=slowstart):
            with self.assertRaises(TimeoutError):s.prepare()
    def test_reset_is_two_seconds_including_pipe_time(self):
        s,c,_,_=self.prepared();c.mutate=lambda r:setattr(self.clock,'now',self.clock()+2.)
        with self.assertRaises(TimeoutError):self.reset(s)
    def test_reset_rechecks_prepared_source_and_config(self):
        s,c,_,_=self.prepared();self.config.write_text('{"changed_after_ready":true}')
        with self.assertRaises(ValueError):self.reset(s)
        self.assertFalse(c.requests)
    def test_stale_run_or_id_and_bool_id_fail_closed(self):
        for key,value in [('run_uuid','0'*32),('id',999),('id',True),('op','status')]:
            with self.subTest(key=key,value=value):
                s,c,_,_=self.prepared();self.reset(s);c.mutate=lambda r:r.__setitem__(key,value)
                with self.assertRaises(ValueError):s.act(self.obs())
                self.assertTrue(s._stop.is_set())
    def test_action_original_identity_type_mismatch_rejected(self):
        s,c,_,_=self.prepared();self.reset(s)
        c.mutate=lambda r:r['result']['action'].__setitem__('episode',False)
        with self.assertRaises(ValueError):s.act(self.obs())
    def test_status_is_bounded_no_action_and_detached(self):
        s,c,_,_=self.prepared();report=s.status();self.assertTrue(report['goal_report']['fixture_only'])
        c.mutate=lambda r:r['result'].__setitem__('action',{})
        with self.assertRaises(ValueError):s.status()
    def test_duplicate_nonfinite_overflow_and_oversize_json_rejected(self):
        for raw in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":Infinity}',b'{"a":1e309}'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):host._json(raw)
        with self.assertRaises(ValueError):host._encode({'v':float('nan')},host.MAX_LINE)
        s,c,_,_=self.prepared();c.stdout.emit(b'x'*(host.MAX_LINE+1))
        end=time.perf_counter()+.2
        while not s._broken.is_set() and time.perf_counter()<end:time.sleep(.001)
        self.assertTrue(s._broken.is_set())
    def test_ready_exact_namespace_and_config_drift_rejected(self):
        s=self.new()
        def start(*args,**kw):
            c=Child(s);c.stdout.queue=queue.Queue()
            c.stdout.emit(dict(schema=host.SCHEMA,event='ready',run_uuid=s.run_uuid,namespace='/wrong',
                config_sha256=s.spec['config_ref']['sha256'],environment_sha256=s.spec['environment_ref']['sha256'],
                state='CONFIGURED',**c.identity));return c
        with patch.object(host.sys,'platform','win32'),patch.object(host,'WSL_EXECUTABLE',self.exe),patch.object(host.subprocess,'Popen',side_effect=start):
            with self.assertRaises(ValueError):s.prepare()
        t=self.new();self.config.write_text('{"changed":true}')
        with patch.object(host.sys,'platform','win32'),patch.object(host.subprocess,'Popen') as spawn:
            with self.assertRaises(ValueError):t.prepare()
        spawn.assert_not_called()
    def test_source_and_spec_change_prevent_launch(self):
        for kind in ('source','spec','environment'):
            with self.subTest(kind=kind):
                s=self.new();p={'source':self.root/host.SOURCE_FILES[0],'spec':s.spec_path,'environment':self.env}[kind]
                old=p.read_bytes();p.write_bytes(old+b' ')
                with patch.object(host.sys,'platform','win32'),patch.object(host.subprocess,'Popen') as spawn:
                    with self.assertRaises(ValueError):s.prepare()
                spawn.assert_not_called();p.write_bytes(old)
    def test_symlink_alias_and_nonfresh_output_rejected(self):
        s=self.new();ref=lambda p:dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
        with self.assertRaises(ValueError):host.WslNavigationSession(self.root,s.out,ref(self.config),ref(self.env))
        # Windows developer mode is not required: model the actual reparse
        # lstat bit, even though the alias bytes/hash would equal the source.
        old=Path.lstat
        def lstat(p,*args,**kwargs):
            return SimpleNamespace(st_file_attributes=0x400,st_mode=old(p).st_mode) if p==self.config else old(p,*args,**kwargs)
        cfg=ref(self.config);env=ref(self.env)
        with patch.object(Path,'lstat',lstat),self.assertRaises(ValueError):
            host.WslNavigationSession(self.root,self.root/'artifacts'/'another',cfg,env)
    def test_concurrent_transaction_cannot_use_another_reply(self):
        s,c,_,_=self.prepared();s._transaction.acquire()
        try:
            with self.assertRaises(RuntimeError):s.status()
        finally:s._transaction.release()
        self.assertTrue(s._stop.is_set());self.assertFalse(c.requests)
    def test_durable_stop_and_cleanup_same_process_proof(self):
        s,c,_,_=self.prepared();self.reset(s);s.request_stop()
        self.assertTrue(s._stop_written.wait(.2))
        stop=host._json((s.out/'STOP').read_bytes())
        self.assertEqual(stop,dict(run_uuid=s.run_uuid,config_sha256=s.spec['config_ref']['sha256']))
        started=time.perf_counter();s.close();self.assertLess(time.perf_counter()-started,1.3)
        self.assertEqual(s.cleanup['supervisor_pid'],c.identity['supervisor_pid'])
        self.assertTrue(c.stdin.closed);self.assertTrue(c.stdout.closed)
        self.assertFalse(any(t.is_alive() for t in s._threads));s.close()
    def test_blocked_owned_writer_joins_when_worker_exits(self):
        s,c,_,_=self.prepared();self.reset(s)
        entered=threading.Event();release=threading.Event();original_poll=c.poll
        def write(_):
            entered.set();release.wait(.5);raise BrokenPipeError('owned worker exited')
        def poll():
            result=original_poll()
            if result is not None:release.set()
            return result
        c.stdin.write=write;c.poll=poll;failures=[]
        def act():
            try:s.act(self.obs())
            except RuntimeError as error:failures.append(str(error))
        actor=threading.Thread(target=act);actor.start()
        self.assertTrue(entered.wait(.2))
        started=time.perf_counter();s.close();self.assertLess(time.perf_counter()-started,1.3)
        actor.join(.2);self.assertFalse(actor.is_alive());self.assertTrue(failures)
        self.assertFalse(any(t.is_alive() for t in s._threads));self.assertTrue(s.cleanup['clean'])
    def test_cancel_never_waits_for_blocked_stop_disk_write(self):
        s,c,_,_=self.prepared();self.reset(s);o=self.obs();original_deadline=o['wall_deadline']
        entered=threading.Event();release=threading.Event();old_write=s._write_stop
        def blocked():entered.set();release.wait(3.);old_write()
        with patch.object(s,'_write_stop',side_effect=blocked):
            started=time.perf_counter();s.request_stop();self.assertLess(time.perf_counter()-started,.05)
            self.assertTrue(entered.wait(.2));started=time.perf_counter()
            try:
                with self.assertRaisesRegex(RuntimeError,'stop_writer_not_joined'):s.close()
                self.assertLess(time.perf_counter()-started,1.4)
                self.assertEqual(o['wall_deadline'],original_deadline)
            finally:release.set();s._stop_writer.join(.5)
        self.assertFalse(s._stop_writer.is_alive())
        with self.assertRaises(RuntimeError):s.close()
    def test_stop_writer_io_error_is_not_hidden_by_clean_mock_proof(self):
        s,c,_,_=self.prepared()
        with patch.object(s,'_write_stop',side_effect=OSError('blocked filesystem')):
            s.request_stop();self.assertTrue(s._stop_written.wait(.2))
            with self.assertRaisesRegex(RuntimeError,'stop_write_failed'):s.close()
    def test_stale_cleanup_identity_or_remaining_group_never_clean(self):
        for key,value in [('run_uuid','0'*32),('start_ticks',1),('boot_id','0'*36),('config_sha256','0'*64),('owned_groups',[999]),('clean',False),('errors',['still_running'])]:
            with self.subTest(key=key):
                s,c,_,_=self.prepared();c.cleanup_mutate=lambda r:r.__setitem__(key,value)
                with self.assertRaises(RuntimeError):s.close()
                self.assertIsNone(s.cleanup)
                with self.assertRaises(RuntimeError):s.close()
    def test_supervisor_exit_without_linux_proof_is_failure(self):
        s,c,_,_=self.prepared();c.no_cleanup=True
        with self.assertRaisesRegex(RuntimeError,'cleanup_unproved'):s.close()
        self.assertTrue(c.stdin.closed);self.assertTrue(c.stdout.closed)
    def test_clean_file_cannot_hide_nonzero_supervisor_exit(self):
        s,c,_,_=self.prepared();old_poll=c.poll
        def poll():
            code=old_poll()
            if code is not None:c.returncode=2
            return c.returncode
        c.poll=poll
        with self.assertRaisesRegex(RuntimeError,'exit_nonzero'):s.close()
    def test_eof_or_exited_supervisor_prevents_control(self):
        s,c,_,_=self.prepared();self.reset(s);c.returncode=9
        with self.assertRaises(RuntimeError):s.act(self.obs())
        self.assertTrue(s._stop.is_set())


class PortableWireTests(unittest.TestCase):
    def test_duplicate_and_all_nonfinite_json_forms_rejected(self):
        for raw in (b'{"v":NaN}',b'{"v":Infinity}',b'{"v":-Infinity}',b'{"v":1e309}',b'{"v":1,"v":2}'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):host._json(raw)
    def test_bounded_json_and_exact_shape(self):
        self.assertEqual(host._json(host._encode({'x':1},host.MAX_LINE)),{'x':1})
        with self.assertRaises(ValueError):host._encode({'x':'z'*host.MAX_LINE},host.MAX_LINE)
        with self.assertRaises(ValueError):host._exact({'x':1,'extra':2},('x',),'unexpected_fields')
    def test_ready_bool_pid_and_wrong_boot_are_rejected_without_host_clock_mapping(self):
        s=object.__new__(host.WslNavigationSession);s.run_uuid='1'*32;s.namespace='/polar_sil_'+s.run_uuid+'/red_sentry'
        s.spec=dict(config_ref={'sha256':'a'*64},environment_ref={'sha256':'b'*64})
        ready=dict(schema=host.SCHEMA,event='ready',run_uuid=s.run_uuid,namespace=s.namespace,
            config_sha256='a'*64,environment_sha256='b'*64,state='CONFIGURED',
            supervisor_pid=22,start_ticks=43,boot_id='a'*8+'-'+('b'*4+'-')*3+'c'*12)
        self.assertEqual(s._ready(ready),ready)
        for key,value in [('supervisor_pid',True),('start_ticks',False),('boot_id','not-boot'),('run_uuid','0'*32)]:
            bad=dict(ready);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):s._ready(bad)


if __name__=='__main__':unittest.main()
