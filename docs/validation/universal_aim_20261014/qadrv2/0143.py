"""Owned trusted JSON adapter processes; resource lifecycle is not a sandbox."""
from __future__ import annotations
import os
import signal
import subprocess
import sys
import time
from ..integrations.owned_linux_group import LinuxOwnedProcessGroup

class OwnedJsonLaunchFailure(RuntimeError):
    def __init__(self,cause,status):
        super().__init__('Owned JSON launch failed: '+type(cause).__name__)
        self.cleanup_status=status

class _LinuxAdapterGroup(LinuxOwnedProcessGroup):
    def cleanup_until(self,deadline):
        if self.closed:raise RuntimeError('owned process cleanup is single use')
        self.closed=True;started=time.perf_counter();errors=[];reaped=[];killed=False
        child=self.child
        if child is None:return dict(clean=True,reaped=False,not_spawned=True,group_empty=True,remaining_members=[],errors=[])
        def reap():
            child.poll()
            for row in self._verified_members():
                if row['pid']==child.pid or row['ppid']!=self.pid:continue
                try:pid,status=os.waitpid(row['pid'],os.WNOHANG)
                except ChildProcessError:continue
                if pid:reaped.append(dict(pid=pid,status=status))
        def signal_group(sig):
            if self._verified_members():
                try:os.killpg(child.pid,sig)
                except ProcessLookupError:pass
        try:
            signal_group(signal.SIGTERM)
            term_end=min(deadline,started+.15)
            while time.perf_counter()<term_end:
                reap()
                if not self._verified_members():break
                time.sleep(min(.005,max(0,term_end-time.perf_counter())))
            reap()
            if self._verified_members():killed=True;signal_group(signal.SIGKILL)
            while time.perf_counter()<deadline:
                reap()
                if not self._verified_members():break
                time.sleep(min(.005,max(0,deadline-time.perf_counter())))
            reap()
        except Exception as exc:errors.append(type(exc).__name__+':'+str(exc))
        try:remaining=self._verified_members();verified=True
        except Exception as exc:remaining=[];verified=False;errors.append('owned_group_inspection:'+type(exc).__name__)
        if remaining:errors.append('owned_process_group_not_empty')
        if child.poll() is None:errors.append('owned_leader_not_reaped')
        return dict(self.identity,clean=not errors,reaped=child.returncode is not None,
            group_empty=verified and not remaining,remaining_members=remaining,errors=errors,killed=killed,
            returncode=child.returncode,reaped_descendants=reaped,cleanup_elapsed_s=time.perf_counter()-started)

class OwnedJsonProcess:
    def __init__(self,command,*,cwd,env,stop_event,linux_owner_factory=None,stderr=None):
        self.owner=None;self.child=None;self.status=None
        if stop_event.is_set():
            raise OwnedJsonLaunchFailure(RuntimeError('JSON process cancelled before launch'),
                dict(clean=True,reaped=False,not_spawned=True,group_empty=True,errors=[]))
        if sys.platform=='win32':
            from .windows_owned_job import WindowsOwnedJobProcess
            self.child=WindowsOwnedJobProcess(command,cwd=cwd,env=env,stop_event=stop_event,stderr=stderr)
            self.owner=self.child
        elif sys.platform=='linux':
            try:self.owner=(_LinuxAdapterGroup if linux_owner_factory is None else linux_owner_factory)()
            except Exception as exc:
                raise OwnedJsonLaunchFailure(exc,
                    dict(clean=True,reaped=False,not_spawned=True,group_empty=True,errors=[])) from exc
            try:
                if stop_event.is_set():raise RuntimeError('JSON process cancelled before launch')
                self.child=subprocess.Popen(command,cwd=cwd,env=env,stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,stderr=subprocess.DEVNULL if stderr is None else stderr,bufsize=0,shell=False,start_new_session=True)
                self.owner.attach(self.child)
                if stop_event.is_set():raise RuntimeError('JSON process cancelled during launch')
            except BaseException as exc:
                cleanup_deadline=time.perf_counter()+1.
                try:proof=self.owner.cleanup_until(cleanup_deadline)
                except Exception as cleanup_exc:
                    proof=dict(clean=False,reaped=False,not_spawned=self.child is None,
                        group_empty=False,errors=['launch_cleanup:'+type(cleanup_exc).__name__])
                if self.child is not None and self.owner.child is not self.child:
                    proof=dict(proof,clean=False,not_spawned=False,group_empty=False,
                        errors=list(proof.get('errors',[]))+['spawned_child_not_attached'])
                    # This exact Popen belongs to this constructor. Its group
                    # identity was not established: never signal an unknown PGID.
                    # A direct kill/wait cannot prove unknown descendants absent.
                    try:
                        if self.child.poll() is None:self.child.kill()
                        self.child.wait(timeout=max(0,cleanup_deadline-time.perf_counter()))
                        proof['reaped']=self.child.returncode is not None
                    except Exception as direct_exc:
                        proof['errors'].append('unattached_direct_child_cleanup:'+type(direct_exc).__name__)
                if self.child is not None:
                    for stream in (self.child.stdin,self.child.stdout):
                        try:
                            if stream is not None:stream.close()
                        except Exception as pipe_exc:
                            proof=dict(proof,clean=False,
                                errors=list(proof.get('errors',[]))+['launch_pipe_close:'+type(pipe_exc).__name__])
                raise OwnedJsonLaunchFailure(exc,proof) from exc
        else:raise RuntimeError('Owned JSON process lifecycle unsupported on this platform')

    def cleanup(self,deadline):
        if self.status is None:
            self.status=(self.owner.cleanup(deadline) if sys.platform=='win32' else self.owner.cleanup_until(deadline))
        return dict(self.status)

    def release_handles(self):
        if sys.platform=='win32':self.child.release_handles()
