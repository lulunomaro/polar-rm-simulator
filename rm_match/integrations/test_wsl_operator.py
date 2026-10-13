"""Host protocol units and opt-in actual WSL harmless-child cleanup evidence."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import unittest

from .wsl_operator import WslOperatorProcess, MAX_LINE

ROOT=Path(__file__).resolve().parents[2]


class HostProtocolTests(unittest.TestCase):
    def actor(self):
        actor=WslOperatorProcess.__new__(WslOperatorProcess)
        actor._stop=threading.Event(); actor._broken=threading.Event()
        actor._incoming=queue.Queue(maxsize=2); actor._outgoing=queue.Queue(maxsize=1)
        actor.evidence_out=None;actor.diagnostics=[]
        return actor

    def test_receive_uses_host_deadline_no_linux_timestamp(self):
        actor=self.actor(); before=time.perf_counter()
        with self.assertRaises(TimeoutError): actor._receive(before+.025)
        self.assertLess(time.perf_counter()-before,.3)

    def test_cancel_is_durable_before_startup(self):
        actor=self.actor(); actor.request_stop()
        with self.assertRaises(RuntimeError): actor._receive(time.perf_counter()+1)

    def test_reader_rejects_oversize_and_unsolicited_queue_flood(self):
        import io
        class Child: pass
        for raw in (b'x'*(MAX_LINE+1),b'{}\n'*3):
            actor=self.actor(); child=Child(); child.stdout=io.BytesIO(raw)
            actor._read(child)
            self.assertTrue(actor._broken.is_set()); self.assertTrue(actor._stop.is_set())
            self.assertLessEqual(actor._incoming.qsize(),2)

    def test_second_control_transaction_never_waits_or_writes(self):
        actor=self.actor(); actor._transaction=threading.Lock(); actor._transaction.acquire()
        with self.assertRaisesRegex(RuntimeError,'concurrent'): actor.control({})

    def test_expired_capture_deadline_cannot_refresh_to_new_80ms_window(self):
        actor=self.actor(); actor._transaction=threading.Lock(); actor.timeout=.08
        actor.ready={}; actor.process=object()
        with self.assertRaisesRegex(TimeoutError,'authority deadline'):
            actor.control(dict(host_deadline=time.perf_counter()-.001))
        self.assertTrue(actor._stop.is_set()); self.assertEqual(actor._outgoing.qsize(),0)

    def test_nonfinite_and_bool_host_deadline_rejected(self):
        for value in (True,float('nan'),float('inf')):
            actor=self.actor(); actor._transaction=threading.Lock(); actor.timeout=.08
            actor.ready={}; actor.process=object()
            with self.assertRaises(ValueError): actor.control(dict(host_deadline=value))

    def test_close_without_launched_process_closes_owned_errorlog(self):
        import io
        actor=self.actor(); actor.process=None; actor.stderr=io.BytesIO()
        actor.close(); actor.close(); self.assertTrue(actor.stderr.closed)

    def test_frame_rejects_world_truth_and_nested_private_objects(self):
        from .wsl_operator_worker import validate_sensor_frame
        frame=dict(schema='rmcs-mujoco-actor-frame-v1',image=dict(encoding='bgr8',width=1440,height=1080,stride_bytes=4320,bytes=4665600,sha256='0'*64,path='unused'))
        validate_sensor_frame(frame)
        for extra in (dict(robots=[]),dict(enemy_xy=[1,2]),dict(own=dict(enemy_hp=1)),dict(camera=dict(profile={})),dict(own=dict(joint_positions=[{},0,0,0,0])),dict(own=dict(hp=dict(truth=True)))):
            with self.assertRaises(ValueError): validate_sensor_frame(dict(frame,**extra))

    @unittest.skipUnless(os.name=='nt','Canonical Windows C: image boundary')
    def test_cpu_saved_bytes_prepare_events_success_and_sha_failure_no_child(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts',prefix='wsl_prep_unit_') as directory:
            out=Path(directory);path=out/'input.bgr';raw=b'\x33'*4665600;path.write_bytes(raw)
            def setup():
                actor=self.actor();actor._transaction=threading.Lock();actor.timeout=.08
                actor.ready={};actor.process=object();actor.out=out;actor.repo_root=ROOT
                actor._serial=0;actor.fov={}
                return actor
            image=dict(encoding='bgr8',width=1440,height=1080,stride_bytes=4320,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),path=str(path))
            packet=dict(episode=3,control_time_ns=123,frame=dict(schema='rmcs-mujoco-actor-frame-v1',image=image),host_deadline=time.perf_counter()+.08)
            actor=setup()
            def receive(deadline):
                sent=json.loads(actor._outgoing.get_nowait());self.assertEqual(sent['packet']['control_time_ns'],123)
                self.assertNotIn('host_deadline',sent['packet']);self.assertEqual(sent['packet']['frame']['image']['sha256'],image['sha256'])
                return dict(event='result',id=1,response=dict(status='ok',runner_identity='rmcs-sim-operator-fov-v1',clock_time_ns=123,direction_frame='world',tracking=False))
            actor._receive=receive
            actor.control(packet)
            prep=next(x for x in actor.diagnostics if x['event']=='control_prepare')
            self.assertIsNone(prep['failed_phase']);self.assertEqual(prep['original_host_deadline'],packet['host_deadline'])
            self.assertTrue({'sensor_validate_s','path_map_s','bgr_read_s','bgr_hash_s','serialize_s'}<=set(prep['stages_s']))
            actor=setup();packet['host_deadline']=time.perf_counter()+.08;packet['frame']['image']['sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'SHA'):actor.control(packet)
            prep=actor.diagnostics[-1];self.assertEqual(prep['event'],'control_prepare')
            self.assertEqual(prep['failed_phase'],'bgr_hash');self.assertEqual(prep['error_type'],'ValueError')
            self.assertEqual(actor._outgoing.qsize(),0)

    @unittest.skipUnless(os.name=='nt','Actual Windows ancestor no-reparse boundary')
    def test_owned_image_path_guard_still_rejects_actual_junction_alias(self):
        import tempfile
        from .wsl_operator import checked_host_path
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts',prefix='wsl_path_unit_') as directory:
            out=Path(directory);target=out/'target';target.mkdir();(target/'image.bgr').write_bytes(b'abc');link=out/'alias'
            result=subprocess.run(['cmd','/c','mklink','/J',str(link),str(target)],capture_output=True)
            self.assertEqual(result.returncode,0)
            try:
                with self.assertRaisesRegex(ValueError,'reparse'):checked_host_path(link/'image.bgr')
            finally:link.rmdir()


@unittest.skipUnless(os.name=='nt' and os.environ.get('POLAR_TEST_WSL')=='1','Explicit actual WSL harmless-process test')
class ActualWslSupervisorTests(unittest.TestCase):
    def setUp(self):
        import uuid
        self.out=ROOT/'artifacts'/('wsl_transport_test_'+uuid.uuid4().hex[:10]); self.out.mkdir(parents=True)
        self.child=None

    def launch(self, *, reply=True, ignore_term=False, startup_wait=False):
        script=self.out/'harmless.py'
        text='import json,sys,time,signal\n'
        if ignore_term: text+='signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
        if startup_wait: text+='time.sleep(60)\n'
        text+='for line in sys.stdin:\n    request=json.loads(line)\n'
        if reply:
            text+="    print(json.dumps(dict(status='ok',runner_identity='rmcs-sim-operator-fov-v1',clock_time_ns=request['control_time_ns'],direction_frame='world',tracking=False)),flush=True)\n"
        else: text+='    time.sleep(60)\n'
        script.write_text(text,encoding='utf8')
        linux=lambda p:'/mnt/c/'+p.as_posix()[3:]
        code=("from rm_match.integrations.wsl_operator_worker import supervise; "
            "raise SystemExit(supervise([__import__('sys').executable,"+repr(linux(script))+"],"+repr(linux(self.out/'worker'))+",{},spec_sha='harmless',startup_timeout=.6,control_timeout=.15))")
        self.child=subprocess.Popen(['wsl.exe','-d','Ubuntu','--cd',linux(ROOT),'--',linux(ROOT/'.venv-linux/bin/python'),'-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0,creationflags=subprocess.CREATE_NO_WINDOW)
        self.lines=queue.Queue()
        def reader():
            for line in self.child.stdout: self.lines.put(json.loads(line))
        self.thread=threading.Thread(target=reader,daemon=True); self.thread.start()
        return self.lines.get(timeout=15)

    def cleanup(self):
        self.child.wait(timeout=8)
        record=json.loads((self.out/'worker/CLEANUP.json').read_text())
        self.assertTrue(record['reaped']); self.assertIsNotNone(record['returncode'])
        linux_check=subprocess.run(['wsl.exe','-d','Ubuntu','--','test','!','-e',f"/proc/{record['pid']}"],capture_output=True)
        self.assertEqual(linux_check.returncode,0,'Owned Linux child remains present after cleanup')
        self.thread.join(timeout=.2)
        for stream in (self.child.stdin,self.child.stdout,self.child.stderr):
            stream.close()
        return record

    def tearDown(self):
        if self.child and self.child.poll() is None:
            (self.out/'worker/STOP').write_bytes(b'cancel')
            self.child.wait(timeout=8)

    def test_actual_zero_tick_readiness_and_host_eof_reaps_child(self):
        ready=self.launch(); self.assertEqual(ready['event'],'ready')
        self.assertEqual(ready['native_ticks'],0); self.assertEqual(ready['inference_calls'],0)
        self.assertEqual(ready['readiness']['abi'],'Linux x86_64 read(0)')
        self.child.stdin.close()
        self.assertEqual(self.cleanup()['reason'],'host_eof')

    def test_actual_stop_file_kills_sigterm_ignoring_child(self):
        self.assertEqual(self.launch(ignore_term=True)['event'],'ready')
        (self.out/'worker/STOP').write_bytes(b'cancel')
        result=self.cleanup(); self.assertTrue(result['killed']); self.assertEqual(result['returncode'],-9)

    def test_actual_control_timeout_reaps_child_no_replacement(self):
        self.assertEqual(self.launch(reply=False,ignore_term=True)['event'],'ready')
        raw=b'\x11'*4665600; path=self.out/'actual_test_bytes.bgr'; path.write_bytes(raw)
        image=dict(path='/mnt/c/'+path.as_posix()[3:],encoding='bgr8',width=1440,height=1080,stride_bytes=4320,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        request=dict(event='control',id=1,timeout_s=.1,packet=dict(control_time_ns=123000000,time_s=.123,frame=dict(schema='rmcs-mujoco-actor-frame-v1',image=image),operator_fov={}))
        self.child.stdin.write(json.dumps(request).encode()+b'\n')
        result=self.lines.get(timeout=3); self.assertEqual(result['event'],'error')
        result=self.cleanup(); self.assertEqual(result['reason'],'control_timeout'); self.assertTrue(result['killed'])

    def test_actual_startup_deadline_without_fake_native_tick(self):
        result=self.launch(startup_wait=True); self.assertEqual(result['event'],'error')
        result=self.cleanup(); self.assertEqual(result['reason'],'startup_timeout')
        self.assertFalse((self.out/'worker/STARTUP.json').exists())

    def test_actual_frozen_elf_model_initialization_zero_tick_and_reap(self):
        actor=WslOperatorProcess(ROOT/'artifacts/native-contour-v3-final-default-build/operator_source.local.json',
            self.out,dict(fov_degrees=85.,circle_radius_x_norm=.25,circle_radius_y_norm=.25))
        start=time.perf_counter()
        try:
            actor.reset({}); ready=actor.ready
            self.assertEqual(ready['native_ticks'],0); self.assertEqual(ready['inference_calls'],0)
            self.assertEqual(ready['physics_steps'],0); self.assertEqual(ready['camera_captures'],0)
            self.assertEqual(ready['readiness']['abi'],'Linux x86_64 read(0)')
            startup=time.perf_counter()-start
        finally:
            before=time.perf_counter(); actor.close(); closed=time.perf_counter()-before
            (self.out/'RESULT.json').write_text(json.dumps(dict(ready=actor.ready,cleanup=actor.cleanup,
                startup_host_s=locals().get('startup'),close_host_s=closed,
                qualification='Actual frozen ELF initialized, zero frames/native ticks/inference/physics; Windows host + WSL native, not live qualification'),indent=2)+'\n',encoding='utf8')
        self.assertLess(closed,1.5); self.assertTrue(actor.cleanup['reaped'])
        self.assertEqual(subprocess.run(['wsl.exe','-d','Ubuntu','--','test','!','-e',f"/proc/{actor.cleanup['pid']}"],capture_output=True).returncode,0)


if __name__=='__main__': unittest.main()
