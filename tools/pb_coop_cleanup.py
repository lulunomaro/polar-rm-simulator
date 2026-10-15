"""Bounded cooperation between reviewed PB owners; no PID killing or retries.

Only pass resources whose close lifecycle belongs to this caller. In particular,
when Runtime owns navigation, pass external_goal ONLY, start this helper before
runtime.request_stop(), then finish against the same original host deadline.
The original owners retain their internal 1.3s budget and birth-bound Linux
proof checks. A blocked close remains visible as an unclean owned helper thread.
"""
from __future__ import annotations

import copy
import math
import threading
import time

from rm_match.integrations.pb_wsl_navigation import WslNavigationSession, CLEANUP_SCHEMA
from tools.pb_external_goal_session import ExternalGoalSession, SCHEMA as GOAL_SCHEMA

HOST_BUDGET_S = 1.5
MAX_OWNER_THREADS = 16
SCHEMA = 'polar.pb.coop-cleanup.v1'


def _stop_owner(kind, owner):
    # Exact classes below, bound original method; no arbitrary plugin hook.
    if kind == 'navigation':WslNavigationSession.request_stop(owner)
    else:ExternalGoalSession.request_stop(owner)


def _close_owner(kind, owner):
    if kind == 'navigation':WslNavigationSession.close(owner)
    else:ExternalGoalSession.close(owner)


def _identity_equal(value, expected, keys):
    return (type(value) is dict and type(expected) is dict and all(
        key in value and key in expected and type(value[key]) is type(expected[key])
        and value[key] == expected[key] for key in keys))


def _inspect_owner(kind, owner):
    """Independently summarize real host completion and original Linux proof."""
    errors=[]
    nav=kind=='navigation'
    closed=getattr(owner,'_closed' if nav else 'closed',None)
    failure=getattr(owner,'_close_failure' if nav else 'failure',None)
    stop_error=getattr(owner,'_stop_write_error' if nav else 'write_error',None)
    stop=getattr(owner,'_stop' if nav else 'stop',None)
    stop_requested=isinstance(stop,threading.Event) and stop.is_set()
    if closed is not True:errors.append('owner_not_closed')
    if failure is not None:errors.append('owner_close_failure')
    if stop_error is not None:errors.append('owner_stop_write_failure')
    if not stop_requested:errors.append('owner_stop_not_requested')
    owner_threads=getattr(owner,'_threads' if nav else 'threads',None)
    rows=[]
    if type(owner_threads) is not list or len(owner_threads)>MAX_OWNER_THREADS:
        errors.append('owner_thread_inventory_invalid')
    else:
        for thread in owner_threads:
            if not isinstance(thread,threading.Thread):
                errors.append('owner_thread_invalid');continue
            alive=thread.is_alive();rows.append(dict(name=thread.name,alive=alive))
            if alive:errors.append('owner_thread_alive')
    child=getattr(owner,'process' if nav else 'child',None)
    ready=getattr(owner,'ready',None)
    no_spawn=child is None and ready is None
    pid=returncode=None
    pipes={}
    if child is not None:
        pid=child.pid;returncode=child.poll()
        if type(pid) is not int or pid<=0:errors.append('host_launcher_identity_invalid')
        if type(returncode) is not int or returncode!=0:errors.append('host_launcher_not_reaped_zero')
        for name in ('stdin','stdout'):
            stream=getattr(child,name,None);pipes[name]=stream is None or stream.closed is True
            if not pipes[name]:errors.append('host_pipe_open')
    elif not no_spawn:errors.append('host_launcher_missing')
    stderr=getattr(owner,'stderr',None)
    stderr_closed=stderr is None or stderr.closed is True
    if not stderr_closed:errors.append('host_stderr_open')
    receipt=getattr(owner,'cleanup',None)
    proof_scope='not_spawned' if no_spawn else 'original_owner_validated_linux_cleanup'
    if not no_spawn:
        if type(receipt) is not dict:errors.append('linux_cleanup_missing')
        elif nav:
            expected=dict(schema=CLEANUP_SCHEMA,run_uuid=owner.run_uuid,config_sha256=owner.spec['config_ref']['sha256'])
            if not _identity_equal(receipt,expected,expected):errors.append('navigation_receipt_identity')
            if not _identity_equal(receipt,ready,('supervisor_pid','start_ticks','boot_id')) and ready is not None:
                errors.append('navigation_worker_birth_mismatch')
            if receipt.get('clean') is not True or receipt.get('owned_groups')!=[] or receipt.get('errors')!=[]:
                errors.append('navigation_linux_not_empty_clean')
            # A pre-ready receipt was already checked by the ORIGINAL close
            # against WORKER_STARTED.json; do not claim another file audit here.
            if ready is None:proof_scope='original_owner_validated_pre_ready_birth_marker'
        else:
            expected=dict(schema=GOAL_SCHEMA,run_uuid=owner.run_uuid,spec_sha256=owner.spec_sha)
            if not _identity_equal(receipt,expected,expected):errors.append('goal_receipt_identity')
            if ready is not None and not _identity_equal(receipt,ready,('supervisor_pid','start_ticks','boot_id')):
                errors.append('goal_worker_birth_mismatch')
            group=receipt.get('group')
            if (receipt.get('clean') is not True or receipt.get('errors')!=[] or type(group) is not dict
                or group.get('clean') is not True or group.get('reaped') is not True
                or group.get('group_empty') is not True or group.get('remaining_members')!=[]
                or type(group.get('returncode')) is not int or group['returncode']!=0):
                errors.append('goal_linux_not_empty_clean')
            if ready is not None and not _identity_equal(group,ready.get('owned_identity'),
                ('run_id','supervisor_pid','boot_id','pid','pgid','leader_start_ticks')):
                errors.append('goal_owned_group_birth_mismatch')
            if ready is None:proof_scope='original_owner_validated_pre_ready_birth_marker'
    return dict(clean=not errors,errors=errors,owner_closed=closed is True,
        owner_failure_present=failure is not None,stop_write_failure_present=stop_error is not None,
        stop_requested=stop_requested,owner_threads=rows,host_launcher_pid=pid,
        host_launcher_returncode=returncode,not_spawned=no_spawn,
        host_launcher_reaped=child is not None and type(returncode) is int,
        host_pipes_closed=pipes,host_stderr_closed=stderr_closed,
        linux_proof_scope=proof_scope,linux_cleanup=copy.deepcopy(receipt))


class PBCoopCleanup:
    """One caller-owned resource deadline. begin is non-waiting; finish latches."""
    def __init__(self, *, navigation=None, external_goal=None, deadline=None):
        self.started=time.perf_counter()
        if deadline is None:deadline=self.started+HOST_BUDGET_S
        if (type(deadline) not in (float,int) or not math.isfinite(deadline)
            or deadline>self.started+HOST_BUDGET_S):
            raise ValueError('cleanup_deadline_must_not_extend_host_1_5s')
        self.deadline=deadline;self.jobs={};self.errors=[];self._result=None
        from tools.navigation_goal_session import NavigationGoalSession
        selected=(('navigation',navigation,(WslNavigationSession,)),
                  ('external_goal',external_goal,(ExternalGoalSession,NavigationGoalSession)))
        # Signal every accepted resource before starting ANY potentially blocking
        # close. Foreign objects are never invoked, while valid owners still stop.
        for kind,owner,expected_type in selected:
            if owner is None:continue
            if type(owner) not in expected_type:self.errors.append(kind+'_unreviewed_owner');continue
            job=dict(owner=owner,done=threading.Event(),thread=None,exception_type=None,completed_host_wall=None)
            self.jobs[kind]=job
            try:_stop_owner(kind,owner)
            except BaseException as exc:
                job['exception_type']=type(exc).__name__;self.errors.append(kind+'_stop_failed')
        for kind,job in self.jobs.items():
            if time.perf_counter()>=self.deadline:
                self.errors.append(kind+'_close_not_started_before_deadline');continue
            def run(kind=kind,job=job):
                try:_close_owner(kind,job['owner'])
                except BaseException as exc:job['exception_type']=type(exc).__name__
                finally:
                    job['completed_host_wall']=time.perf_counter();job['done'].set()
            thread=threading.Thread(target=run,name='pb-coop-close-'+kind,daemon=True);job['thread']=thread
            try:thread.start()
            except BaseException as exc:
                job['thread']=None;job['exception_type']=type(exc).__name__;self.errors.append(kind+'_close_thread_start_failed')

    def finish(self):
        if self._result is not None:return copy.deepcopy(self._result)
        errors=list(self.errors);owners={}
        for kind,job in self.jobs.items():
            thread=job['thread']
            if thread is not None:thread.join(max(0.,self.deadline-time.perf_counter()))
            alive=thread is not None and thread.is_alive()
            done=job['done'].is_set();completed=job['completed_host_wall']
            if not done or alive:errors.append(kind+'_close_unfinished')
            if job['exception_type'] is not None:errors.append(kind+'_close_exception')
            if completed is not None and completed>self.deadline:errors.append(kind+'_close_completed_after_deadline')
            try:proof=_inspect_owner(kind,job['owner'])
            except BaseException as exc:
                proof=dict(clean=False,errors=['owner_proof_inspection_failed'],inspection_exception_type=type(exc).__name__)
            if proof['clean'] is not True:errors.append(kind+'_owner_cleanup_unproved')
            owners[kind]=dict(proof,close_worker=dict(name=None if thread is None else thread.name,
                alive=alive,done=done,exception_type=job['exception_type'],completed_host_wall=completed))
        ended=time.perf_counter()
        if ended>self.deadline:errors.append('shared_host_cleanup_deadline_exceeded')
        self._result=dict(schema=SCHEMA,clean=not errors,errors=errors,owners=owners,
            started_host_wall=self.started,deadline_host_wall=self.deadline,finished_host_wall=ended,
            elapsed_host_s=ended-self.started,host_budget_s=HOST_BUDGET_S,
            clock='host_local_perf_counter',linux_internal_budget_s=1.3,
            no_force_kill=True,no_budget_retry=True)
        return copy.deepcopy(self._result)


def begin_pb_cleanup(*, navigation=None, external_goal=None, deadline=None):
    return PBCoopCleanup(navigation=navigation,external_goal=external_goal,deadline=deadline)


def close_pb_sessions(*, navigation=None, external_goal=None, deadline=None):
    return begin_pb_cleanup(navigation=navigation,external_goal=external_goal,deadline=deadline).finish()
