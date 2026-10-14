"""Host coordinator tests with explicit simulated receipts; no WSL/ROS/physics."""
import copy
import io
import threading
import time
import unittest
from unittest.mock import patch

from tools import pb_coop_cleanup as module
from tools.pb_coop_cleanup import begin_pb_cleanup,close_pb_sessions
from rm_match.integrations.pb_wsl_navigation import WslNavigationSession,CLEANUP_SCHEMA
from tools.pb_external_goal_session import ExternalGoalSession,SCHEMA as GOAL_SCHEMA

BOOT='01234567-89ab-cdef-0123-456789abcdef'

class Child:
    pid=123
    def __init__(self):self.stdin=io.BytesIO();self.stdout=io.BytesIO();self.code=None
    def poll(self):return self.code

def make(kind,spawned=True):
    nav=kind=='navigation';owner=(WslNavigationSession if nav else ExternalGoalSession).__new__(WslNavigationSession if nav else ExternalGoalSession)
    owner.run_uuid='a'*32;owner.spec=dict(config_ref=dict(sha256='c'*64));owner.spec_sha='d'*64
    birth=dict(supervisor_pid=33,start_ticks=44,boot_id=BOOT)
    owned=dict(run_id='b'*32,supervisor_pid=33,boot_id=BOOT,pid=55,pgid=55,leader_start_ticks=66)
    owner.ready=dict(birth,**({} if nav else dict(owned_identity=owned))) if spawned else None
    owner.stderr=io.BytesIO();owner.cleanup=None
    if nav:
        owner.process=Child() if spawned else None;owner._stop=threading.Event();owner._closed=False;owner._threads=[]
        owner._close_failure=None;owner._stop_write_error=None
    else:
        owner.child=Child() if spawned else None;owner.stop=threading.Event();owner.closed=False;owner.threads=[]
        owner.failure=None;owner.write_error=None
    return owner

def finish_owner(kind,owner):
    nav=kind=='navigation';child=owner.process if nav else owner.child
    if child is not None:
        child.code=0;child.stdin.close();child.stdout.close()
        birth={k:owner.ready[k] for k in ('supervisor_pid','start_ticks','boot_id')}
        if nav:owner.cleanup=dict(schema=CLEANUP_SCHEMA,run_uuid=owner.run_uuid,config_sha256='c'*64,**birth,clean=True,owned_groups=[],errors=[])
        else:
            group=dict(owner.ready['owned_identity'],clean=True,reaped=True,group_empty=True,remaining_members=[],returncode=0)
            owner.cleanup=dict(schema=GOAL_SCHEMA,run_uuid=owner.run_uuid,spec_sha256='d'*64,**birth,clean=True,errors=[],group=group)
    owner.stderr.close()
    if nav:owner._closed=True
    else:owner.closed=True

class CleanupTests(unittest.TestCase):
    def test_all_stop_before_any_close_and_concurrent_shared_deadline(self):
        nav=make('navigation');goal=make('external_goal');barrier=threading.Barrier(2);called=[]
        def close(kind,owner):
            self.assertTrue(nav._stop.is_set());self.assertTrue(goal.stop.is_set());called.append(kind)
            barrier.wait(.3);finish_owner(kind,owner)
        with patch.object(module,'_close_owner',side_effect=close):proof=close_pb_sessions(navigation=nav,external_goal=goal)
        self.assertTrue(proof['clean'],proof);self.assertCountEqual(called,['navigation','external_goal'])
        for row in proof['owners'].values():
            self.assertTrue(row['host_launcher_reaped']);self.assertFalse(row['close_worker']['alive']);self.assertTrue(row['close_worker']['done'])
    def test_runtime_owned_navigation_not_passed_not_stopped_by_goal_helper(self):
        nav=make('navigation');goal=make('external_goal')
        with patch.object(module,'_close_owner',side_effect=finish_owner):proof=close_pb_sessions(external_goal=goal)
        self.assertTrue(proof['clean']);self.assertEqual(set(proof['owners']),{'external_goal'})
        self.assertFalse(nav._stop.is_set());self.assertIsNone(nav.process.code)
        nav.stderr.close();nav.process.stdin.close();nav.process.stdout.close()
    def test_foreign_and_subclass_hooks_never_called_but_valid_owner_still_closed(self):
        class Foreign:
            def request_stop(self):raise AssertionError('foreign called')
            def close(self):raise AssertionError('foreign called')
        class Subclass(WslNavigationSession):pass
        for foreign in (Foreign(),Subclass.__new__(Subclass)):
            with self.subTest(kind=type(foreign).__name__):
                goal=make('external_goal')
                with patch.object(module,'_close_owner',side_effect=finish_owner):proof=close_pb_sessions(navigation=foreign,external_goal=goal)
                self.assertFalse(proof['clean']);self.assertIn('navigation_unreviewed_owner',proof['errors']);self.assertTrue(goal.closed)
    def test_cleanup_already_assigned_cannot_hide_close_exception_or_failure(self):
        for exception in (True,False):
            with self.subTest(exception=exception):
                goal=make('external_goal')
                def close(kind,owner):
                    finish_owner(kind,owner);owner.failure='simulated_host_wait_failure'
                    if exception:raise RuntimeError('simulated')
                with patch.object(module,'_close_owner',side_effect=close):proof=close_pb_sessions(external_goal=goal)
                self.assertFalse(proof['clean']);self.assertTrue(proof['owners']['external_goal']['linux_cleanup']['clean'])
                self.assertTrue(proof['owners']['external_goal']['owner_failure_present'])
    def test_wrong_group_run_or_birth_empty_receipt_and_bool_exit_cannot_prove_clean(self):
        mutations=[lambda o:o.cleanup['group'].update(pid=99),lambda o:o.cleanup.update(run_uuid='e'*32),
            lambda o:o.cleanup.update(start_ticks=True),lambda o:o.cleanup['group'].update(returncode=False),
            lambda o:o.cleanup['group'].update(remaining_members=[55]),lambda o:setattr(o,'cleanup',None)]
        for mutation in mutations:
            with self.subTest(case=mutations.index(mutation)):
                goal=make('external_goal')
                def close(kind,owner):finish_owner(kind,owner);mutation(owner)
                with patch.object(module,'_close_owner',side_effect=close):proof=close_pb_sessions(external_goal=goal)
                self.assertFalse(proof['clean'])
    def test_alive_owner_io_thread_and_stop_writer_failure_still_unclean(self):
        release=threading.Event();worker=threading.Thread(target=release.wait,name='simulated-io',daemon=True);worker.start()
        try:
            nav=make('navigation');nav._threads=[worker]
            def close(kind,owner):finish_owner(kind,owner);owner._stop_write_error='simulated'
            with patch.object(module,'_close_owner',side_effect=close):proof=close_pb_sessions(navigation=nav)
            self.assertFalse(proof['clean']);self.assertEqual(proof['owners']['navigation']['owner_threads'],[dict(name='simulated-io',alive=True)])
        finally:release.set();worker.join(.3)
        self.assertFalse(worker.is_alive())
    def test_stalled_close_returns_unclean_at_original_deadline_and_never_upgrades(self):
        goal=make('external_goal');entered=threading.Event();release=threading.Event()
        def close(kind,owner):
            # Deliberately misleading partial receipt while owner is blocked.
            finish_owner(kind,owner);entered.set();release.wait(.5)
        deadline=time.perf_counter()+.03
        with patch.object(module,'_close_owner',side_effect=close):
            job=begin_pb_cleanup(external_goal=goal,deadline=deadline)
            try:
                self.assertTrue(entered.wait(.2));proof=job.finish()
                self.assertFalse(proof['clean']);self.assertTrue(proof['owners']['external_goal']['close_worker']['alive'])
                self.assertLess(time.perf_counter()-deadline,.2)
            finally:release.set();job.jobs['external_goal']['thread'].join(.3)
        self.assertEqual(job.finish(),proof);self.assertFalse(job.jobs['external_goal']['thread'].is_alive())
    def test_caller_delay_after_complete_cleanup_does_not_reset_resource_budget(self):
        goal=make('external_goal')
        with patch.object(module,'_close_owner',side_effect=finish_owner):
            job=begin_pb_cleanup(external_goal=goal,deadline=time.perf_counter()+.03)
            self.assertTrue(job.jobs['external_goal']['done'].wait(.2));time.sleep(.04);proof=job.finish()
        self.assertFalse(proof['clean']);self.assertIn('shared_host_cleanup_deadline_exceeded',proof['errors'])
    def test_expired_deadline_stops_without_launching_fresh_close_budget(self):
        goal=make('external_goal',spawned=False)
        with patch.object(module,'_close_owner',side_effect=AssertionError('should not start')) as close:
            proof=close_pb_sessions(external_goal=goal,deadline=time.perf_counter()-1.)
        self.assertFalse(proof['clean']);self.assertTrue(goal.stop.is_set());close.assert_not_called();goal.stderr.close()
    def test_no_spawn_is_not_misrepresented_as_linux_reaped(self):
        goal=make('external_goal',spawned=False)
        with patch.object(module,'_close_owner',side_effect=finish_owner):proof=close_pb_sessions(external_goal=goal)
        self.assertTrue(proof['clean']);row=proof['owners']['external_goal']
        self.assertTrue(row['not_spawned']);self.assertFalse(row['host_launcher_reaped']);self.assertEqual(row['linux_proof_scope'],'not_spawned')
    def test_invalid_or_extended_deadline_rejected_without_stop_hook(self):
        for deadline in (True,float('nan'),float('inf'),time.perf_counter()+2.):
            with self.subTest(deadline=deadline):
                goal=make('external_goal',spawned=False)
                with self.assertRaises(ValueError):begin_pb_cleanup(external_goal=goal,deadline=deadline)
                self.assertFalse(goal.stop.is_set());goal.stderr.close()

if __name__=='__main__':unittest.main()
