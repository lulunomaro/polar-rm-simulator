"""Host stop has no blocking file IO; claimed cleanup must bind original group."""
import hashlib
import json
from pathlib import Path
import queue
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from tools.pb_external_goal_session import ExternalGoalSession,SCHEMA,strict_json

class Process:
    stdout=None
    def poll(self):return 0
    def wait(self,timeout):return 0

class ExternalOwnerTests(unittest.TestCase):
    def test_repeated_identity_key_and_nonfinite_ready_json_rejected(self):
        for raw in (b'{"run_uuid":"current","run_uuid":"foreign"}',b'{"pid":NaN}',b'{"elapsed":1e999}'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):strict_json(raw)
    def make(self,root):
        out=Path(root)/'artifacts/peer';out.mkdir(parents=True)
        spec=out/'EXTERNAL_SPEC.json';spec.write_text(json.dumps(dict(run_uuid='a'*32)))
        session=ExternalGoalSession(root,out,spec,hashlib.sha256(spec.read_bytes()).hexdigest())
        return session,out
    def test_stop_event_does_not_wait_for_disk_writer(self):
        with TemporaryDirectory() as root,patch('tools.pb_external_goal_session.sys.platform','win32'):
            with patch.object(ExternalGoalSession,'_stop_file',lambda s:s.stop.wait()):session,out=self.make(root)
            session.request_stop();session.close()
            self.assertTrue(session.stop.is_set());self.assertFalse(any(t.is_alive() for t in session.threads))
    def test_wrong_record_cannot_relabel_foreign_group_as_owned_clean(self):
        with TemporaryDirectory() as root,patch('tools.pb_external_goal_session.sys.platform','win32'):
            session,out=self.make(root);session.child=Process()
            token=dict(supervisor_pid=33,start_ticks=44,boot_id='boot')
            owned=dict(run_id='b'*32,supervisor_pid=33,boot_id='boot',pid=55,pgid=55,leader_start_ticks=66)
            session.ready=dict(**token,owned_identity=owned)
            foreign=dict(owned,pid=99,reaped=True,group_empty=True,remaining_members=[],returncode=0,clean=True)
            value=dict(schema=SCHEMA,run_uuid='a'*32,spec_sha256=session.spec_sha,**token,clean=True,errors=[],group=foreign)
            (out/'SUPERVISOR_CLEANUP.json').write_text(json.dumps(value))
            with self.assertRaisesRegex(RuntimeError,'group_identity'):session.close()
            self.assertIsNone(session.cleanup);self.assertTrue(session.closed)

if __name__=='__main__':unittest.main()
