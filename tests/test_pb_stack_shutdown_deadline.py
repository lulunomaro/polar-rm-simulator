"""Concurrent teardown must share the existing owner's resource deadline."""
import threading
import time
import unittest
from tools.pb_navigation_stack import PBNavigationStack

class ShutdownDeadlineTests(unittest.TestCase):
    def stack(self):
        stack=PBNavigationStack.__new__(PBNavigationStack)
        stack._stop_lock=threading.Lock();stack._stop_complete=threading.Event()
        stack.cleanup=None
        return stack

    def test_busy_owner_is_not_given_a_new_five_second_wait(self):
        stack=self.stack();stack._stop_lock.acquire();stack._stop_deadline=time.perf_counter()+.04
        started=time.perf_counter()
        try:result=stack.stop(grace_s=.15)
        finally:stack._stop_lock.release()
        self.assertLess(time.perf_counter()-started,.25)
        self.assertFalse(result['clean']);self.assertEqual(result['errors'],['shutdown_in_progress'])

    def test_completed_owned_teardown_snapshot_is_independent(self):
        stack=self.stack();stack.cleanup={'clean':True,'errors':[]};stack._stop_complete.set()
        result=stack.stop(grace_s=.15);result['errors'].append('outside_mutation')
        self.assertEqual(stack.cleanup['errors'],[])

if __name__=='__main__':unittest.main()
