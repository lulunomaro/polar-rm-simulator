"""Binary pipe privacy/deadline units and opt-in actual WSL harmless-child tests."""
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
from .wsl_operator_pipe import WslPipeOperatorProcess,CHUNK,IMAGE_BYTES

ROOT=Path(__file__).resolve().parents[2]


class PipeHostTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Windows host source attestation boundary')
    def test_v2_metadata_attests_both_actual_pipe_sources_without_mutating_v1(self):
        from unittest.mock import patch
        from ..deployment.wsl_profile import CheckedWslSpec
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts',prefix='wsl_pipe_identity_') as directory:
            repo=Path(directory);out=repo/'out';out.mkdir()
            paths=('rm_match/integrations/wsl_operator_pipe.py','rm_match/integrations/wsl_operator_pipe_worker.py',
                   'rm_match/integrations/owned_linux_group.py')
            for rel in paths:
                target=repo/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/rel).read_bytes())
            original=CheckedWslSpec({},'a'*64,{},dict(transport='wsl_stdio_v1',transport_source_sha256={}),repo/'spec.json',repo,out,{})
            def inherited_init(actor,*args,**kwargs):actor.checked=original;actor.repo_root=repo
            with patch.object(WslPipeOperatorProcess.__bases__[0],'__init__',inherited_init):
                actor=WslPipeOperatorProcess()
            self.assertEqual(original.metadata['transport'],'wsl_stdio_v1')
            self.assertEqual(original.metadata['transport_source_sha256'],{})
            self.assertEqual(actor.checked.metadata['transport'],'wsl_stdio_bgr_v2')
            for rel in paths:
                expected=hashlib.sha256((repo/rel).read_bytes()).hexdigest()
                self.assertEqual(actor.checked.metadata['transport_source_sha256'][rel],expected)
                self.assertEqual(actor.checked._identities[str(repo/rel)],expected)
            actor.checked.verify_unchanged()
            (repo/paths[1]).write_bytes(b'changed worker after validation')
            with self.assertRaisesRegex(ValueError,'wsl_input_changed_after_validation'):actor.checked.verify_unchanged()

    def actor(self):
        a=WslPipeOperatorProcess.__new__(WslPipeOperatorProcess)
        a._stop=threading.Event();a._broken=threading.Event();a._transaction=threading.Lock()
        a._incoming=queue.Queue(maxsize=2);a._outgoing=queue.Queue(maxsize=1)
        a.evidence_out=None;a.diagnostics=[];a.timeout=.08;a.ready={};a.process=object();a._serial=0;a.fov={}
        return a

    def test_expired_original_deadline_never_becomes_new_binary_window(self):
        a=self.actor()
        with self.assertRaises(TimeoutError):a.control(dict(host_deadline=time.perf_counter()-.001))
        self.assertEqual(a._outgoing.qsize(),0);self.assertTrue(a._stop.is_set())
        self.assertEqual(a.diagnostics[-1]['failed_phase'],'admission')

    def test_binary_writer_one_bounded_whole_frame_without_reencoding(self):
        a=self.actor();a._outgoing.put((b'header\n',bytes(range(256))*18225))
        class Stream:
            parts=[]
            def write(self,v):
                self.parts.append(bytes(v))
                if sum(map(len,self.parts))==IMAGE_BYTES+7:a._stop.set()
                return len(v)
        class Child:stdin=Stream()
        a._write(Child())
        self.assertEqual(len(Child.stdin.parts),1);self.assertEqual(len(Child.stdin.parts[0]),IMAGE_BYTES+7)
        self.assertEqual(b''.join(Child.stdin.parts),b'header\n'+bytes(range(256))*18225)

    def test_binary_writer_preserves_all_bytes_after_os_short_write(self):
        a=self.actor();raw=b'\x19'*IMAGE_BYTES;a._outgoing.put((b'header\n',raw))
        class Stream:
            parts=[]
            def write(self,v):
                count=min(65521,len(v));self.parts.append(bytes(v[:count]))
                if sum(map(len,self.parts))==IMAGE_BYTES+7:a._stop.set()
                return count
        class Child:stdin=Stream()
        a._write(Child());self.assertEqual(b''.join(Child.stdin.parts),b'header\n'+raw)

    def test_chunked_reader_keeps_line_and_queue_bound(self):
        a=self.actor()
        class Child:stdout=io.BytesIO(b'{}\n'*3)
        a._read(Child())
        self.assertTrue(a._broken.is_set());self.assertLessEqual(a._incoming.qsize(),2)

    @unittest.skipUnless(os.name=='nt','Windows C: canonical image boundary')
    def test_saved_bytes_header_sha_identity_and_host_only_deadline_no_child(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts',prefix='wsl_pipe_unit_') as directory:
            a=self.actor();a.out=Path(directory);a.repo_root=ROOT
            raw=b'\x19'*IMAGE_BYTES;path=a.out/'input.bgr';path.write_bytes(raw)
            sha=hashlib.sha256(raw).hexdigest();image=dict(encoding='bgr8',width=1440,height=1080,stride_bytes=4320,bytes=IMAGE_BYTES,sha256=sha,path=str(path))
            def receive(deadline):
                header,binary=a._outgoing.get_nowait();sent=json.loads(header)
                self.assertEqual(binary,raw);self.assertEqual(sent['image_bytes'],IMAGE_BYTES)
                self.assertEqual(sent['packet']['frame']['image'],image);self.assertEqual(sent['packet']['control_time_ns'],5)
                self.assertNotIn('host_deadline',sent['packet'])
                return dict(event='result',id=1,response=dict(status='ok',runner_identity='rmcs-sim-operator-fov-v1',clock_time_ns=5,direction_frame='world',tracking=False),linux_stages_s={},clock_domain='linux_local_diagnostic_only')
            a._receive=receive;deadline=time.perf_counter()+.08
            a.control(dict(episode=9,control_time_ns=5,host_deadline=deadline,frame=dict(schema='rmcs-mujoco-actor-frame-v1',image=image)))
            self.assertEqual(a.diagnostics[0]['original_host_deadline'],deadline)

    def test_private_bytes_no_file_access_exact_sha_not_json_and_no_mutable_types(self):
        from unittest.mock import patch
        a=self.actor();a.out=ROOT/'artifacts/record_only_private_bgr'
        raw=b'\x19'*IMAGE_BYTES;image=dict(encoding='bgr8',width=1440,height=1080,stride_bytes=4320,bytes=IMAGE_BYTES,sha256=hashlib.sha256(raw).hexdigest(),path=str(a.out/'sensor_input.bgr'))
        packet=dict(episode=9,control_time_ns=5,host_deadline=time.perf_counter()+.08,image_bytes=raw,
            frame=dict(schema='rmcs-mujoco-actor-frame-v1',image=image))
        def receive(deadline):
            header,binary=a._outgoing.get_nowait();sent=json.loads(header)
            self.assertIs(binary,raw);self.assertEqual(sent['image_bytes'],IMAGE_BYTES)
            self.assertNotIn('image_bytes',sent['packet']);self.assertNotIn('image_bytes',sent['packet']['frame'])
            return dict(event='result',id=1,response=dict(status='ok',runner_identity='rmcs-sim-operator-fov-v1',clock_time_ns=5,direction_frame='world',tracking=False))
        a._receive=receive
        with patch.object(Path,'open',side_effect=AssertionError('Unexpected private payload file read')),patch('rm_match.integrations.wsl_operator_pipe.checked_host_path',side_effect=AssertionError('Unexpected filesystem path stat')):
            a.control(packet)
        self.assertNotIn('bgr_read_s',a.diagnostics[0]['stages_s']);self.assertNotIn('path_check_s',a.diagnostics[0]['stages_s'])
        for wrong in (bytearray(raw),memoryview(raw),b'short'):
            b=self.actor();b.out=a.out;pkt=dict(packet,image_bytes=wrong,host_deadline=time.perf_counter()+.08)
            with self.assertRaises(ValueError):b.control(pkt)
            self.assertEqual(b._outgoing.qsize(),0)
        b=self.actor();b.out=a.out;pkt=dict(packet,host_deadline=time.perf_counter()+.08);pkt['frame']=dict(packet['frame'],image=dict(image,sha256='0'*64))
        with self.assertRaisesRegex(ValueError,'SHA'):b.control(pkt)
        self.assertEqual(b._outgoing.qsize(),0)

    def test_private_byte_record_path_cannot_label_foreign_robot_directory(self):
        a=self.actor();a.out=ROOT/'artifacts/owned_private_bgr';raw=b'\x19'*IMAGE_BYTES
        image=dict(encoding='bgr8',width=1440,height=1080,stride_bytes=4320,bytes=IMAGE_BYTES,sha256=hashlib.sha256(raw).hexdigest(),path=str(a.out.parent/'foreign/sensor_input.bgr'))
        with self.assertRaisesRegex(ValueError,'record path'):
            a.control(dict(episode=9,control_time_ns=5,image_bytes=raw,frame=dict(schema='rmcs-mujoco-actor-frame-v1',image=image)))
        self.assertEqual(a._outgoing.qsize(),0)


@unittest.skipUnless(os.name=='nt' and os.environ.get('POLAR_TEST_WSL')=='1','Explicit actual WSL harmless process evidence')
class ActualPipeTests(unittest.TestCase):
    def setUp(self):
        self.out=ROOT/'artifacts'/('wsl_pipe_test_'+uuid.uuid4().hex[:10]);self.out.mkdir();self.child=None

    def launch(self,ignore_term=False,native_write_chunk=None,native_write_delay=0,response_delay=0,native_stdout_read_delay=None):
        script=self.out/'harmless.py'
        text='import json,sys,hashlib,signal,time\nfrom pathlib import Path\n'
        if ignore_term:text+='signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
        text+="for line in sys.stdin:\n    request=json.loads(line)\n    image=request['frame']['image']; raw=Path(image['path']).read_bytes()\n"
        text+=f"    time.sleep({response_delay!r})\n"
        text+="    print(json.dumps(dict(status='ok',runner_identity='rmcs-sim-operator-fov-v1',clock_time_ns=request['control_time_ns'],direction_frame='world',tracking=False,observed_sha=hashlib.sha256(raw).hexdigest(),observed_bytes=len(raw),observed_path=image['path'],observed_stdin_bytes=len(line.encode()),observed_stdin_sha=hashlib.sha256(line.encode()).hexdigest(),exposure_timestamp_ns=request['frame'].get('exposure_timestamp_ns'))),flush=True)\n"
        script.write_text(text,encoding='utf8');linux=lambda p:'/mnt/c/'+p.as_posix()[3:]
        code=("from rm_match.integrations.wsl_operator_pipe_worker import supervise; raise SystemExit(supervise([__import__('sys').executable,"+repr(linux(script))+"],"+repr(linux(self.out/'worker'))+",{},spec_sha='harmless',startup_timeout=2.,control_timeout=.4))")
        if native_write_chunk is not None or native_stdout_read_delay is not None:
            # The supervisor's original os.write still reaches the real child;
            # only its maximum chunk/delay is constrained to exercise partial IO.
            fixture=('import os,time,subprocess,select\noriginal_popen=subprocess.Popen\nnative_stdin_fd=None\nnative_stdout_fd=None\n'
                +'def track_native_child(*args,**kwargs):\n    global native_stdin_fd,native_stdout_fd\n    child=original_popen(*args,**kwargs)\n    native_stdin_fd=child.stdin.fileno()\n    native_stdout_fd=child.stdout.fileno()\n    return child\n'
                +'subprocess.Popen=track_native_child\n')
            if native_write_chunk is not None:
                fixture+=('original_write=os.write\ndef constrained_write(fd,data):\n'
                    +'    if fd!=native_stdin_fd:return original_write(fd,data)\n'
                    +f'    time.sleep({native_write_delay!r})\n    return original_write(fd,data[:{native_write_chunk!r}])\n'
                    +'os.write=constrained_write\n')
            if native_stdout_read_delay is not None:
                # Delay ONLY after the real select observed this child's stdout
                # readable, so the worker must recheck its existing deadline.
                fixture+=('original_select=select.select\ndef delayed_readable(*args,**kwargs):\n'
                    +'    ready=original_select(*args,**kwargs)\n'
                    +f'    if native_stdout_fd in ready[0]:time.sleep({native_stdout_read_delay!r})\n'
                    +'    return ready\nselect.select=delayed_readable\n')
            code=fixture+code
        self.child=subprocess.Popen(['wsl.exe','-d','Ubuntu','--cd',linux(ROOT),'--','/usr/bin/python3','-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0,creationflags=subprocess.CREATE_NO_WINDOW)
        self.lines=queue.Queue()
        def reader():
            for line in self.child.stdout:self.lines.put(json.loads(line))
        self.thread=threading.Thread(target=reader,daemon=True);self.thread.start()
        ready=self.lines.get(timeout=15);self.assertEqual(ready['transport'],'wsl_stdio_bgr_v2');self.assertEqual(ready['native_ticks'],0);self.assertEqual(ready['tmpfs_mode'],'0o700')
        return ready

    def send(self,raw,sha=None,truncate=None,budget=.3):
        digest=sha or hashlib.sha256(raw).hexdigest();image=dict(encoding='bgr8',width=1440,height=1080,stride_bytes=4320,bytes=IMAGE_BYTES,sha256=digest,path='C:/never_read_by_linux.bgr')
        request=dict(event='control',id=1,image_bytes=IMAGE_BYTES,timeout_s=budget,packet=dict(control_time_ns=123,time_s=123/1e9,operator_fov={},frame=dict(schema='rmcs-mujoco-actor-frame-v1',image=image,exposure_timestamp_ns=100)))
        self.sent_request=request
        encoded=json.dumps(request).encode()+b'\n';payload=raw if truncate is None else raw[:truncate]
        def writer():
            try:
                for part in (encoded,payload):
                    v=memoryview(part)
                    while v:
                        count=self.child.stdin.write(v[:CHUNK]);v=v[count:]
            except (OSError,ValueError):pass
        self.writer=threading.Thread(target=writer,daemon=True);self.writer.start()

    def cleanup(self):
        self.child.wait(timeout=5);record=json.loads((self.out/'worker/CLEANUP.json').read_text())
        self.assertTrue(record['reaped']);self.assertTrue(record['tmpfs_removed'])
        for target in (f"/proc/{record['pid']}",record['tmpfs_directory']):
            self.assertEqual(subprocess.run(['wsl.exe','-d','Ubuntu','--','test','!','-e',target],capture_output=True).returncode,0)
        self.thread.join(timeout=.2)
        for stream in (self.child.stdin,self.child.stdout,self.child.stderr):stream.close()
        return record

    def tearDown(self):
        if self.child and self.child.poll() is None:
            (self.out/'worker/STOP').write_bytes(b'cancel');self.child.wait(timeout=5)

    def test_actual_binary_pixels_sha_tmpfs_and_same_exposure_then_eof_reap(self):
        self.launch();raw=bytes(range(256))*18225;self.send(raw)
        response=self.lines.get(timeout=3);self.assertEqual(response['event'],'result')
        result=response['response'];self.assertEqual(result['observed_sha'],hashlib.sha256(raw).hexdigest());self.assertEqual(result['observed_bytes'],IMAGE_BYTES)
        self.assertTrue(result['observed_path'].startswith('/dev/shm/polar-wsl-bgr-'));self.assertEqual(result['clock_time_ns'],123);self.assertEqual(result['exposure_timestamp_ns'],100)
        self.assertEqual(response['clock_domain'],'linux_local_diagnostic_only');self.assertEqual(set(response['linux_stages_s']),{'pipe_receive_s','payload_sha256_s','tmpfs_write_s','native_stdin_write_s','native_result_wait_s'})
        self.assertTrue(response['native_stdin_complete'])
        self.assertEqual(response['native_stdin_bytes_written'],result['observed_stdin_bytes'])
        self.assertEqual(response['native_stdin_expected_bytes'],result['observed_stdin_bytes'])
        self.assertEqual(response['id'],1)
        (self.out/'RESULT.json').write_text(json.dumps(dict(response=response,expected_sha256=hashlib.sha256(raw).hexdigest(),
            qualification='Actual WSL binary transfer and tmpfs read by harmless Python child; test byte pattern, no native NN/GL/live qualification'),indent=2)+'\n',encoding='utf8')
        self.child.stdin.close();self.cleanup()

    def test_actual_private_immutable_host_bytes_to_pipe_no_file_read(self):
        from unittest.mock import patch
        self.launch();a=WslPipeOperatorProcess.__new__(WslPipeOperatorProcess)
        a._stop=threading.Event();a._broken=threading.Event();a._transaction=threading.Lock()
        a._incoming=self.lines;a._outgoing=queue.Queue(maxsize=1);a.evidence_out=None;a.diagnostics=[]
        a.timeout=.08;a.ready={};a.process=self.child;a._serial=0;a.fov={};a.out=self.out
        raw=bytes(range(256))*18225;sha=hashlib.sha256(raw).hexdigest()
        image=dict(encoding='bgr8',width=1440,height=1080,stride_bytes=4320,bytes=IMAGE_BYTES,sha256=sha,path=str(self.out/'sensor_input.bgr'))
        thread=threading.Thread(target=a._write,args=(self.child,),daemon=True);thread.start()
        started=time.perf_counter();deadline=started+.08
        with patch.object(Path,'open',side_effect=AssertionError('Private bytes path must not be opened')):
            result=a.control(dict(episode=9,control_time_ns=123,host_deadline=deadline,image_bytes=raw,
                frame=dict(schema='rmcs-mujoco-actor-frame-v1',exposure_timestamp_ns=100,image=image)))
        elapsed=time.perf_counter()-started
        self.assertEqual(result['observed_sha'],sha);self.assertEqual(result['clock_time_ns'],123)
        self.assertEqual(result['exposure_timestamp_ns'],100);self.assertLess(elapsed,.08)
        self.assertFalse((self.out/'sensor_input.bgr').exists())
        (self.out/'PRIVATE_BYTES_RESULT.json').write_text(json.dumps(dict(result=result,host_elapsed_s=elapsed,
            original_host_deadline=deadline,host_events=a.diagnostics,
            qualification='Actual WSL harmless-child binary pipe, private immutable test bytes, no local image file read; no native NN/GL/live acceptance'),indent=2)+'\n',encoding='utf8')
        a._stop.set();thread.join(timeout=.2);self.child.stdin.close();self.cleanup()

    def test_actual_whole_payload_under_simulated_500hz_gil_heavy_work(self):
        stopped=threading.Event();held=[]
        def pressure():
            target=time.perf_counter()
            while not stopped.is_set():
                began=time.perf_counter();end=began+.0014;value=0
                while time.perf_counter()<end:value=(value+1)&65535
                held.append(time.perf_counter()-began);target+=.002
                if target>time.perf_counter():time.sleep(target-time.perf_counter())
        thread=threading.Thread(target=pressure,daemon=True);thread.start()
        try:self.test_actual_private_immutable_host_bytes_to_pipe_no_file_read()
        finally:stopped.set();thread.join(timeout=1)
        self.assertFalse(thread.is_alive());self.assertTrue(held)
        (self.out/'SIMULATED_GIL_LOAD.json').write_text(json.dumps(dict(target_hz=500,target_hold_s=.0014,
            holds_s=held,qualification='Synthetic CPU scheduling load, no physics/NN/GPU workload or live acceptance'),indent=2)+'\n',encoding='utf8')

    def test_actual_tmpfs_child_cwd_and_exact_original_tracking_mode(self):
        ready=self.launch()
        command=['wsl.exe','-d','Ubuntu','--','/usr/bin/python3','-c',
            'import os,sys,pathlib;pid=int(sys.argv[1]);cwd=os.readlink("/proc/%d/cwd"%pid);assert cwd==sys.argv[2];assert pathlib.Path(cwd,"tracking_mode").read_bytes()==b"multi_ekf\\n"',
            str(ready['native_pid']),ready['tmpfs_directory']]
        result=subprocess.run(command,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(ready['native_cwd'],ready['tmpfs_directory'])
        self.child.stdin.close();self.cleanup()

    def test_actual_blocked_whole_writer_unblocks_after_owned_worker_exit_and_close(self):
        ready=self.launch(ignore_term=True);a=WslPipeOperatorProcess.__new__(WslPipeOperatorProcess)
        a._stop=threading.Event();a._broken=threading.Event();a._outgoing=queue.Queue(maxsize=1)
        from types import SimpleNamespace
        a.checked=SimpleNamespace(linux_spec_sha256='harmless')
        a.evidence_out=self.out/'worker';a.diagnostics=[];a.ready=ready;a.process=self.child;a.stderr=self.child.stderr
        entered=threading.Event();finished=threading.Event();stream=self.child.stdin
        class TrackingStream:
            def write(self,v):
                entered.set()
                try:return stream.write(v)
                finally:finished.set()
        class WriterChild:stdin=TrackingStream()
        a._outgoing.put((b'not_json\n',b'\x19'*IMAGE_BYTES))
        writer=threading.Thread(target=a._write,args=(WriterChild(),),daemon=True);a._threads=[writer];writer.start()
        self.assertTrue(entered.wait(timeout=2));self.assertFalse(finished.is_set(),'Whole-frame write did not block before receiver exit')
        started=time.perf_counter();a.close();elapsed=time.perf_counter()-started
        self.assertLess(elapsed,1.3);self.assertFalse(writer.is_alive());self.assertTrue(finished.is_set())
        self.assertTrue(a.cleanup['reaped']);self.assertTrue(a.cleanup['tmpfs_removed'])
        (self.out/'BLOCKED_WRITER_RESULT.json').write_text(json.dumps(dict(close_host_s=elapsed,
            writer_joined=True,writer_initially_blocked=True,cleanup=a.cleanup,
            qualification='Actual WSL malformed-header/harmless SIGTERM-ignoring child cleanup; no GL/native NN/live acceptance'),indent=2)+'\n',encoding='utf8')

    def test_actual_hash_mismatch_is_not_given_to_child_and_tmpfs_removed(self):
        self.launch();self.send(b'\x07'*IMAGE_BYTES,sha='0'*64)
        response=self.lines.get(timeout=3);self.assertEqual(response['event'],'error');self.assertEqual(response['error_type'],'ValueError')
        self.cleanup()

    def test_actual_partial_binary_deadline_kills_ignoring_child_and_cleans_tmpfs(self):
        self.launch(ignore_term=True);self.send(b'\x07'*IMAGE_BYTES,truncate=8192,budget=.08)
        response=self.lines.get(timeout=3);self.assertEqual(response['event'],'error')
        record=self.cleanup();self.assertEqual(record['reason'],'control_timeout');self.assertTrue(record['killed'])
        error=json.loads((self.out/'worker/SUPERVISOR_ERROR.json').read_text())
        self.assertEqual(error['received_bgr_bytes'],8192)
        self.assertEqual(error['native_stdin_bytes_written'],0);self.assertFalse(error['native_stdin_complete'])

    def test_actual_short_native_writes_accumulate_exact_complete_packet_bytes(self):
        self.launch(native_write_chunk=17);raw=b'\x19'*IMAGE_BYTES;self.send(raw)
        response=self.lines.get(timeout=3);self.assertEqual(response['event'],'result')
        packet=self.sent_request['packet'];packet['frame']['image']['path']=response['response']['observed_path']
        exact=json.dumps(packet,allow_nan=False,separators=(',',':')).encode()+b'\n'
        self.assertEqual(response['native_stdin_bytes_written'],len(exact))
        self.assertEqual(response['native_stdin_expected_bytes'],len(exact))
        self.assertEqual(response['response']['observed_stdin_bytes'],len(exact))
        self.assertEqual(response['response']['observed_stdin_sha'],hashlib.sha256(exact).hexdigest())
        self.assertTrue(response['native_stdin_complete'])
        self.assertGreaterEqual(response['linux_stages_s']['native_stdin_write_s'],0)
        (self.out/'STDIN_COMPLETE_RESULT.json').write_text(json.dumps(dict(response=response,
            expected_stdin_bytes=len(exact),expected_stdin_sha=hashlib.sha256(exact).hexdigest(),
            qualification='Actual WSL constrained short os.write returns to harmless Python stdin; test pixels, no original ELF/NN/live acceptance'),indent=2)+'\n',encoding='utf8')
        self.child.stdin.close();self.cleanup()

    def test_actual_complete_bgr_but_partial_native_stdin_deadline_is_incomplete(self):
        self.launch(ignore_term=True,native_write_chunk=7,native_write_delay=.015)
        self.send(b'\x19'*IMAGE_BYTES,budget=.12)
        response=self.lines.get(timeout=3);self.assertEqual(response['event'],'error')
        self.cleanup();error=json.loads((self.out/'worker/SUPERVISOR_ERROR.json').read_text())
        self.assertEqual(error['reason'],'control_timeout');self.assertEqual(error['received_bgr_bytes'],IMAGE_BYTES)
        self.assertGreater(error['native_stdin_bytes_written'],0)
        self.assertEqual(error['native_stdin_bytes_written']%7,0)
        self.assertFalse(error['native_stdin_complete']);self.assertNotIn('native_stdin_write_s',error['linux_stages_s'])
        (self.out/'STDIN_PARTIAL_RESULT.json').write_text(json.dumps(dict(error=error,
            qualification='Actual WSL full BGR followed by constrained partial harmless-child stdin timeout; no original ELF/NN/live acceptance'),indent=2)+'\n',encoding='utf8')

    def test_actual_complete_stdin_without_response_still_fails_deadline(self):
        ready=self.launch(response_delay=.25);self.send(b'\x19'*IMAGE_BYTES,budget=.12)
        response=self.lines.get(timeout=3);self.assertEqual(response['event'],'error')
        self.cleanup();error=json.loads((self.out/'worker/SUPERVISOR_ERROR.json').read_text())
        packet=self.sent_request['packet'];packet['frame']['image']['path']=ready['tmpfs_directory']+'/sensor_input.bgr'
        exact=json.dumps(packet,allow_nan=False,separators=(',',':')).encode()+b'\n'
        self.assertEqual(error['reason'],'control_timeout');self.assertEqual(error['received_bgr_bytes'],IMAGE_BYTES)
        self.assertEqual(error['native_stdin_bytes_written'],len(exact));self.assertTrue(error['native_stdin_complete'])
        self.assertEqual(error['native_stdin_expected_bytes'],len(exact));self.assertEqual(error['request_id'],1)
        self.assertGreaterEqual(error['linux_stages_s']['native_stdin_write_s'],0)
        (self.out/'STDIN_COMPLETE_TIMEOUT_RESULT.json').write_text(json.dumps(dict(error=error,
            qualification='Actual WSL complete harmless-child stdin, delayed response fails original deadline; input delivery is not NN/live acceptance'),indent=2)+'\n',encoding='utf8')

    def test_actual_success_then_partial_header_cannot_reuse_previous_stdin_proof(self):
        self.launch();self.send(b'\x19'*IMAGE_BYTES)
        first=self.lines.get(timeout=3);self.assertEqual(first['event'],'result')
        self.assertTrue(first['native_stdin_complete']);self.assertGreater(first['native_stdin_bytes_written'],0)
        self.writer.join(timeout=1);self.assertFalse(self.writer.is_alive())
        self.child.stdin.write(b'{"event":"control","id":2')
        response=self.lines.get(timeout=3);self.assertEqual(response['event'],'error')
        self.cleanup();error=json.loads((self.out/'worker/SUPERVISOR_ERROR.json').read_text())
        self.assertEqual(error['reason'],'control_timeout');self.assertIsNone(error['request_id'])
        self.assertEqual(error['native_stdin_bytes_written'],0)
        self.assertEqual(error['native_stdin_expected_bytes'],0);self.assertFalse(error['native_stdin_complete'])
        self.assertEqual(error['received_bgr_bytes'],0)
        self.assertNotIn('native_stdin_write_s',error['linux_stages_s'])
        self.assertNotIn('native_result_wait_s',error['linux_stages_s'])
        (self.out/'NEXT_PARTIAL_HEADER_RESULT.json').write_text(json.dumps(dict(first=first,error=error,
            qualification='Actual WSL harmless two-transaction regression; previous stdin completion cannot attest a new incomplete header; no NN/live acceptance'),indent=2)+'\n',encoding='utf8')

    def test_actual_late_readable_native_result_is_rejected_after_select_deadline(self):
        self.launch(native_stdout_read_delay=.13);self.send(b'\x19'*IMAGE_BYTES,budget=.12)
        response=self.lines.get(timeout=3);self.assertEqual(response['event'],'error')
        self.cleanup();error=json.loads((self.out/'worker/SUPERVISOR_ERROR.json').read_text())
        self.assertEqual(error['reason'],'control_timeout');self.assertEqual(error['request_id'],1)
        self.assertTrue(error['native_stdin_complete'])
        self.assertGreater(error['native_stdin_bytes_written'],0)
        self.assertEqual(error['native_stdin_bytes_written'],error['native_stdin_expected_bytes'])
        self.assertGreaterEqual(error['linux_stages_s']['native_result_wait_s'],.13)
        self.assertTrue(self.lines.empty(),'Expired readable child output must not emit a result')
        (self.out/'LATE_READABLE_RESULT.json').write_text(json.dumps(dict(error=error,
            original_exposure_ns=100,original_control_ns=123,select_readable_delay_s=.13,
            qualification='Actual WSL harmless-child stdout already readable, fixture delays select return past original .12s budget; must reject late result, no original ELF/NN/GL/live acceptance'),indent=2)+'\n',encoding='utf8')

    def test_actual_readable_native_response_before_select_deadline_succeeds(self):
        self.launch(native_stdout_read_delay=.001);self.send(b'\x19'*IMAGE_BYTES,budget=.12)
        response=self.lines.get(timeout=3);self.assertEqual(response['event'],'result')
        self.assertTrue(response['native_stdin_complete'])
        self.assertEqual(response['native_stdin_bytes_written'],response['native_stdin_expected_bytes'])
        self.assertEqual(response['response']['clock_time_ns'],123)
        self.assertEqual(response['response']['exposure_timestamp_ns'],100)
        self.assertLess(response['linux_stages_s']['native_result_wait_s'],.12)
        (self.out/'ON_TIME_READABLE_RESULT.json').write_text(json.dumps(dict(response=response,
            select_readable_delay_s=.001,
            qualification='Actual WSL harmless-child readable stdout returned within original .12s test budget, unchanged clocks; no original ELF/NN/GL/live acceptance'),indent=2)+'\n',encoding='utf8')
        self.child.stdin.close();self.cleanup()

    def test_actual_cancel_mid_binary_has_bounded_owned_child_cleanup(self):
        self.launch(ignore_term=True);self.send(b'\x07'*IMAGE_BYTES,truncate=8192)
        (self.out/'worker/STOP').write_bytes(b'cancel');started=time.perf_counter();record=self.cleanup()
        self.assertEqual(record['reason'],'host_cancel');self.assertLess(time.perf_counter()-started,1.5)


if __name__=='__main__':unittest.main()
