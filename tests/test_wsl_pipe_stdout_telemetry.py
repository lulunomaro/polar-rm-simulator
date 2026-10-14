"""Pure supervisor logic fixtures; no WSL, ELF, ROS, inference or GL launch."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rm_match.integrations import wsl_operator_pipe_worker as worker


class ObservationTests(unittest.TestCase):
    def test_reset_is_per_transaction_and_empty_is_not_no_child_write_proof(self):
        value=worker._NativeStdoutObservation()
        value.observed_readable(5.001,5.)
        value.observed_read(b'abc',5.002,5.)
        before=value.snapshot(bytearray(b'abc'))
        self.assertEqual(before['native_stdout_read_bytes'],3)
        self.assertEqual(before['native_stdout_readable_count'],1)
        self.assertAlmostEqual(before['native_stdout_first_readable_after_stdin_s'],.001)
        self.assertAlmostEqual(before['native_stdout_first_read_after_stdin_s'],.002)
        value.reset();after=value.snapshot(bytearray())
        self.assertEqual(after['native_stdout_read_bytes'],0)
        self.assertEqual(after['native_stdout_readable_count'],0)
        self.assertIsNone(after['native_stdout_first_read_after_stdin_s'])
        self.assertNotIn('native_did_not_write',after)

    def test_prefix_hash_is_bounded_and_raw_response_is_absent(self):
        buffer=bytearray(b'x'*(worker.STDOUT_PREFIX_LIMIT+123))
        value=worker._NativeStdoutObservation().snapshot(buffer)
        self.assertEqual(value['native_stdout_buffer_retained_bytes'],len(buffer))
        self.assertEqual(value['native_stdout_prefix_bytes'],worker.STDOUT_PREFIX_LIMIT)
        self.assertEqual(value['native_stdout_prefix_sha256'],hashlib.sha256(buffer[:worker.STDOUT_PREFIX_LIMIT]).hexdigest())
        self.assertIs(value['native_stdout_prefix_truncated'],True)
        self.assertTrue(all(type(v) in (int,float,str,bool,type(None)) for v in value.values()))

    def test_observation_before_stdin_completion_does_not_invent_elapsed(self):
        value=worker._NativeStdoutObservation()
        value.observed_readable(5.,None);value.observed_read(b'a',5.,None)
        value.observed_readable(5.,6.);value.observed_read(b'b',5.,6.)
        row=value.snapshot(b'ab')
        self.assertIsNone(row['native_stdout_first_readable_after_stdin_s'])
        self.assertIsNone(row['native_stdout_first_read_after_stdin_s'])
        self.assertEqual(row['native_stdout_read_bytes'],2)


class PayloadReadvTests(unittest.TestCase):
    def test_partial_read_writes_only_unreceived_owned_bytes(self):
        payload=bytearray(b'abc'+b'\x00'*5)
        def readv(fd,buffers):
            self.assertEqual(fd,0)
            self.assertEqual(len(buffers),2)
            buffers[0][:2]=b'de';return 2
        with patch.object(worker.os,'readv',side_effect=readv,create=True):
            self.assertEqual(worker._read_payload_into(0,payload,3),2)
        self.assertEqual(payload,b'abcde\x00\x00\x00')

    def test_boundary_keeps_one_byte_extra_guard_and_eof(self):
        payload=bytearray(4)
        def overflow(fd,buffers):
            self.assertEqual([len(v) for v in buffers],[4,1])
            buffers[0][:]=b'full';buffers[1][:]=b'!';return 5
        with patch.object(worker.os,'readv',side_effect=overflow,create=True):
            self.assertEqual(worker._read_payload_into(0,payload,0),5)
        with patch.object(worker.os,'readv',return_value=0,create=True):
            self.assertEqual(worker._read_payload_into(0,payload,1),0)
        self.assertEqual(payload,b'full')

    def test_invalid_syscall_count_and_exhausted_buffer_are_rejected(self):
        for value in (True,-1,7,None):
            with self.subTest(value=value),patch.object(worker.os,'readv',return_value=value,create=True):
                with self.assertRaises(OSError):worker._read_payload_into(0,bytearray(4),0)
        with self.assertRaises(ValueError):worker._read_payload_into(0,bytearray(4),4)


class FakePipe:
    def __init__(self,fd):self.fd=fd;self.closed=False
    def fileno(self):return self.fd
    def close(self):self.closed=True


class FakeChild:
    def __init__(self):self.pid=123;self.stdin=FakePipe(10);self.stdout=FakePipe(11)
    def poll(self):return None


class FakeOwner:
    def attach(self,child):
        return dict(run_id='fixture',supervisor_pid=1,boot_id='fixture',pid=child.pid,pgid=child.pid,leader_start_ticks=1)
    def cleanup(self):return dict(clean=True,reaped=True,group_empty=True,remaining_members=[],errors=[],returncode=0)


class SupervisorTests(unittest.TestCase):
    def fixture(self,mode,requests=1):
        """Real bounded image-size packet, mocked child FDs and Linux clock."""
        clock=[0.];captured={};emitted=[];native_reads=[];actions=[];native_writes=[]
        fov=dict(fov_degrees=180.,circle_radius_x_norm=1.,circle_radius_y_norm=1.)
        raw=b'\x01'*worker.MAX_IMAGE
        image=dict(encoding='bgr8',width=1440,height=1080,stride_bytes=4320,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        for request_id in range(1,requests+1):
            packet=dict(control_time_ns=request_id,time_s=request_id/1e9,frame=dict(image=image),operator_fov=fov)
            header=(json.dumps(dict(event='control',id=request_id,image_bytes=len(raw),timeout_s=.08,packet=packet))+'\n').encode()
            combined=header+raw
            actions.extend(('read',0,combined[i:i+worker.CHUNK],.00001) for i in range(0,len(combined),worker.CHUNK))
            if mode=='extra_payload':
                kind,fd,data,delta=actions[-1]
                actions[-1]=(kind,fd,data+b'!',delta)
            elif mode=='payload_eof':
                actions=actions[:2]+[('read',0,b'',.00001)]
            elif mode=='payload_late':
                kind,fd,data,delta=actions[1]
                actions[1]=('late',fd,data,.09)
            elif mode=='bad_sha':
                # Change real received bytes while retaining the declared SHA.
                kind,fd,data,delta=actions[1]
                actions[1]=(kind,fd,b'\x02'+data[1:],delta)
            actions.append(('write',10,b'',.00001))
            if mode=='cancel_wait':actions.append(('cancel',11,b'',.006))
            elif mode=='partial':
                actions.append(('read',11,b'{"status":',.001))
                actions.append(('late',11,b'"ok"}\n',.09))
            elif mode=='late':actions.append(('late',11,b'{"status":"ok"}\n',.09))
            elif mode=='parse_late':actions.append(('read',11,b'{"status":"ok"}\n',.001))
            else:
                actions.append(('read',11,b'{"status":',.001))
                actions.append(('read',11,b'"ok"}\n',.001))
        actions.append(('read',0,b'',.001))
        current=[None]
        def select_ready(*args):
            current[0]=actions.pop(0);kind,fd,data,delta=current[0];clock[0]+=delta
            if kind=='cancel':
                (Path(out)/'STOP').write_bytes(b'cancel\n')
                return [],[],[]
            return ([],[fd],[]) if kind=='write' else ([fd],[],[])
        def read_fd(fd,size):
            kind,expected,data,delta=current[0]
            self.assertEqual(fd,expected);self.assertNotEqual(kind,'late')
            self.assertLessEqual(len(data),size)
            if fd==11:native_reads.append(data)
            return data
        def write_fd(fd,data):
            self.assertEqual(fd,10);native_writes.append(bytes(data));return len(data)
        def readv_fd(fd,buffers):
            kind,expected,data,delta=current[0]
            self.assertEqual(fd,expected);self.assertEqual(fd,0)
            self.assertNotEqual(kind,'late')
            self.assertLessEqual(len(data),sum(len(v) for v in buffers))
            offset=0
            for view in buffers:
                count=min(len(view),len(data)-offset)
                view[:count]=data[offset:offset+count];offset+=count
            return len(data)
        def record(out,name,value):captured[name]=copy.deepcopy(value)
        original_json_loads=json.loads
        def loads(value,*args,**kwargs):
            parsed=original_json_loads(value,*args,**kwargs)
            if mode=='parse_late' and type(parsed) is dict and parsed.get('status')=='ok':clock[0]+=.09
            return parsed
        real_temp=tempfile.TemporaryDirectory
        resource_fixture=SimpleNamespace(RUSAGE_CHILDREN=-1,getrusage=lambda _:SimpleNamespace(ru_utime=0.,ru_stime=0.,ru_maxrss=0))
        with real_temp() as out:
            with patch.object(worker.tempfile,'TemporaryDirectory',side_effect=lambda **kwargs:real_temp()), \
                 patch.object(worker.signal,'signal'),patch.dict(sys.modules,resource=resource_fixture), \
                 patch.object(worker,'LinuxOwnedProcessGroup',FakeOwner), \
                 patch.object(worker.subprocess,'Popen',return_value=FakeChild()), \
                 patch.object(worker,'_stdin_wait',return_value={'fixture_readiness':True}), \
                 patch.object(worker.os,'set_blocking'),patch.object(worker.os,'read',side_effect=read_fd), \
                 patch.object(worker.os,'readv',side_effect=readv_fd,create=True), \
                 patch.object(worker.os,'write',side_effect=write_fd), \
                 patch.object(worker.select,'select',side_effect=select_ready), \
                 patch.object(worker.time,'monotonic',side_effect=lambda:clock[0]), \
                 patch.object(worker,'validate_sensor_frame'),patch.object(worker,'_record',side_effect=record), \
                 patch.object(worker,'_emit',side_effect=lambda value:emitted.append(copy.deepcopy(value))), \
                 patch.object(worker.json,'loads',side_effect=loads):
                result=worker.supervise(['fixture-never-launched'],Path(out),fov,spec_sha='fixture')
        self.last_native_writes=native_writes
        return result,captured,emitted,native_reads

    def test_image_boundary_overflow_is_rejected_before_native_stdin(self):
        result,records,emitted,reads=self.fixture('extra_payload')
        self.assertEqual(result,2)
        self.assertIn('extra bytes',records['SUPERVISOR_ERROR.json']['error'])
        self.assertEqual(self.last_native_writes,[])
        self.assertFalse(any(x['event']=='result' for x in emitted))
        self.assertIs(records['CLEANUP.json']['clean'],True)

    def test_partial_image_eof_reaps_without_forwarding(self):
        result,records,emitted,reads=self.fixture('payload_eof')
        self.assertEqual(result,0)
        self.assertEqual(records['CLEANUP.json']['reason'],'host_eof')
        self.assertIs(records['CLEANUP.json']['clean'],True)
        self.assertEqual(self.last_native_writes,[])
        self.assertFalse(any(x['event']=='result' for x in emitted))

    def test_cancel_preserves_original_inflight_io_without_fabricating_completion(self):
        result,records,emitted,reads=self.fixture('cancel_wait')
        row=records['FINAL_IO.json']
        self.assertEqual(row['reason'],'host_cancel')
        self.assertTrue(row['host_transaction_inflight'])
        self.assertTrue(row['native_stdin_complete'])
        self.assertEqual(row['received_bgr_bytes'],worker.MAX_IMAGE)
        self.assertEqual(row['native_stdin_bytes_written'],row['native_stdin_expected_bytes'])
        self.assertEqual(row['native_stdout_read_bytes'],0)
        self.assertFalse(any(x['event']=='result' for x in emitted))
        self.assertTrue(records['CLEANUP.json']['clean'])

    def test_expired_payload_readability_is_not_read_or_forwarded(self):
        result,records,emitted,reads=self.fixture('payload_late')
        self.assertEqual(result,2)
        row=records['SUPERVISOR_ERROR.json']
        self.assertEqual(row['reason'],'control_timeout')
        self.assertLess(row['received_bgr_bytes'],worker.MAX_IMAGE)
        self.assertEqual(self.last_native_writes,[])
        self.assertFalse(any(x['event']=='result' for x in emitted))

    def test_received_bytes_still_require_full_exact_sha(self):
        result,records,emitted,reads=self.fixture('bad_sha')
        self.assertEqual(result,2)
        self.assertEqual(records['SUPERVISOR_ERROR.json']['error'],'inline BGR SHA mismatch')
        self.assertEqual(self.last_native_writes,[])
        self.assertFalse(any(x['event']=='result' for x in emitted))

    def test_partial_stdout_error_retains_length_hash_and_no_late_read(self):
        result,records,emitted,reads=self.fixture('partial')
        self.assertEqual(result,2)
        row=records['SUPERVISOR_ERROR.json']
        self.assertTrue(row['native_stdin_complete'])
        self.assertEqual(row['native_stdout_read_bytes'],len(b'{"status":'))
        self.assertEqual(row['native_stdout_buffer_retained_bytes'],len(b'{"status":'))
        self.assertEqual(row['native_stdout_prefix_sha256'],hashlib.sha256(b'{"status":').hexdigest())
        self.assertEqual(row['native_stdout_readable_count'],2)
        self.assertEqual(reads,[b'{"status":'])
        self.assertFalse(any(x['event']=='result' for x in emitted))

    def test_stdout_readable_after_deadline_is_observed_not_read_or_accepted(self):
        result,records,emitted,reads=self.fixture('late')
        self.assertEqual(result,2)
        row=records['SUPERVISOR_ERROR.json']
        self.assertEqual(row['native_stdout_read_bytes'],0)
        self.assertEqual(row['native_stdout_readable_count'],1)
        self.assertGreater(row['native_stdout_first_readable_after_stdin_s'],.08)
        self.assertIsNone(row['native_stdout_first_read_after_stdin_s'])
        self.assertEqual(reads,[])
        self.assertFalse(any(x['event']=='result' for x in emitted))

    def test_parser_crossing_deadline_never_emits_result_and_retains_line(self):
        result,records,emitted,reads=self.fixture('parse_late')
        self.assertEqual(result,2)
        row=records['SUPERVISOR_ERROR.json']
        self.assertEqual(row['native_stdout_read_bytes'],len(b'{"status":"ok"}\n'))
        self.assertEqual(row['native_stdout_buffer_retained_bytes'],len(b'{"status":"ok"}\n'))
        self.assertFalse(any(x['event']=='result' for x in emitted))

    def test_success_metadata_resets_for_second_transaction(self):
        result,records,emitted,reads=self.fixture('success',requests=2)
        self.assertEqual(result,0)
        replies=[x for x in emitted if x['event']=='result']
        self.assertEqual([x['id'] for x in replies],[1,2])
        for row in replies:
            self.assertEqual(row['native_stdout_read_bytes'],len(b'{"status":"ok"}\n'))
            self.assertEqual(row['native_stdout_readable_count'],2)
            self.assertEqual(row['native_stdout_buffer_retained_bytes'],0)
            self.assertGreaterEqual(row['native_stdout_first_read_after_stdin_s'],0.)
        self.assertNotIn('SUPERVISOR_ERROR.json',records)


if __name__=='__main__':unittest.main()
