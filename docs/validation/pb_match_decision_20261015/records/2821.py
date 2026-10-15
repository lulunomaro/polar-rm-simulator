import json,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from .offline_lifecycle import wait_for_driver_cleanup
class Tests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'ack.json';self.now=0.;self.control=SimpleNamespace(lock=threading.RLock(),sessions={})
 def tearDown(self):self.tmp.cleanup()
 def clock(self):return self.now
 def sleep(self,n):self.now+=n
 def call(self):return wait_for_driver_cleanup(self.path,'owner',self.control,clock=self.clock,sleep=self.sleep,timeout=.1)
 def ack(self,**kw):self.path.write_text(json.dumps(dict(owner_session_id='owner',quiesced=True,session_close_ack=True,cleanup_completed=True,**kw)))
 def test_quiesced_closed_ack_required(self):self.ack();self.assertTrue(self.call()['confirmed'])
 def test_missing_ack_is_unconfirmed_at_bound(self):r=self.call();self.assertFalse(r['confirmed']);self.assertGreaterEqual(r['wait_wall_s'],.1)
 def test_wrong_bool_owner_extra_fields_rejected(self):
  good=dict(owner_session_id='owner',quiesced=True,session_close_ack=True,cleanup_completed=True)
  for change in ({'quiesced':1},{'owner_session_id':'other'},{'extra':True},{'cleanup_completed':False}):
   self.now=0.;self.path.write_text(json.dumps(dict(good,**change)));self.assertFalse(self.call()['confirmed'])
 def test_open_session_cannot_confirm(self):self.control.sessions['owner']=object();self.ack();self.assertFalse(self.call()['confirmed'])
 def test_oversize_invalid_json_bounded(self):
  for data in ('x'*5000,'invalid'):
   self.now=0.;self.path.write_text(data);self.assertFalse(self.call()['confirmed'])
 def test_deadline_rechecked_after_lock_acquire(self):
  self.ack();outer=self
  class Jump:
   def acquire(self,timeout):outer.now+=.101;return True
   def release(self):pass
  self.control.lock=Jump();self.assertFalse(self.call()['confirmed'])
 def test_contended_lock_has_bounded_acquire(self):
  self.ack();entered=threading.Event();release=threading.Event()
  def hold():
   with self.control.lock:entered.set();release.wait(1.)
  thread=threading.Thread(target=hold);thread.start();self.assertTrue(entered.wait(.3));started=time.monotonic()
  try:
   result=wait_for_driver_cleanup(self.path,'owner',self.control,timeout=.025)
   self.assertFalse(result['confirmed']);self.assertEqual(result['reason'],'control_lock_timeout');self.assertLess(time.monotonic()-started,.2)
  finally:release.set();thread.join(1)
if __name__=='__main__':unittest.main()
