"""Bounded cleanup of a directly spawned Linux session, never arbitrary PID kill.

This is a trusted process lifecycle helper, not a sandbox for escaping children.
Only the single attached Popen and descendants in its original session are owned.
"""
from __future__ import annotations
import ctypes
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid


def _stat(pid):
    try:
        fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
        return dict(pid=pid,state=fields[0],ppid=int(fields[1]),pgid=int(fields[2]),
                    sid=int(fields[3]),start_ticks=int(fields[19]))
    except FileNotFoundError:return None


class LinuxOwnedProcessGroup:
    def __init__(self):
        if not Path('/proc/self/stat').is_file() or os.name!='posix':
            raise RuntimeError('Linux process ownership required')
        # Before spawning: orphan descendants become waitable by this owner.
        libc=ctypes.CDLL(None,use_errno=True)
        if libc.prctl(36,1,0,0,0)!=0:raise OSError(ctypes.get_errno(),'subreaper setup failed')
        self.pid=os.getpid();self.boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        self.run_id=uuid.uuid4().hex;self.child=None;self.identity=None;self.closed=False

    def attach(self,child):
        # Harmless IO tests wrap subprocess.Popen, but return its real class.
        # The process's parent/session identity below is the ownership boundary.
        if self.child is not None or type(child).__module__!='subprocess' or type(child).__name__!='Popen':
            raise RuntimeError('only one directly spawned Popen may be owned')
        if child.pid<=1 or child.pid in (self.pid,os.getpgrp()):raise RuntimeError('unsafe owned process group')
        row=_stat(child.pid)
        self.child=child
        self.identity=dict(run_id=self.run_id,supervisor_pid=self.pid,boot_id=self.boot_id,
                           pid=child.pid,pgid=child.pid,leader_start_ticks=row['start_ticks'] if row else None)
        if row is not None and (row['ppid']!=self.pid or row['pgid']!=child.pid or row['sid']!=child.pid):
            raise RuntimeError('child is not our directly spawned Linux session')
        return dict(self.identity)

    def _members(self):
        if self.child is None:return []
        rows=[]
        for path in Path('/proc').iterdir():
            if not path.name.isdigit():continue
            row=_stat(int(path.name))
            if row is not None and row['pgid']==self.child.pid:rows.append(row)
        return rows

    def _verified_members(self):
        if Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=self.boot_id:
            raise RuntimeError('Linux boot identity changed')
        rows=self._members();by_pid={row['pid']:row for row in rows}
        for row in rows:
            if row['sid']!=self.child.pid:raise RuntimeError('foreign session reused process group')
            if row['pid']==self.child.pid:
                expected=self.identity['leader_start_ticks']
                if row['ppid']!=self.pid or (expected is not None and row['start_ticks']!=expected):
                    raise RuntimeError('owned leader identity changed')
            else:
                cursor=row;seen=set()
                while cursor['ppid']!=self.pid:
                    if cursor['pid'] in seen or cursor['ppid'] not in by_pid:
                        raise RuntimeError('foreign process in owned group')
                    seen.add(cursor['pid']);cursor=by_pid[cursor['ppid']]
        return rows

    def cleanup(self):
        if self.closed:raise RuntimeError('owned process cleanup is single use')
        self.closed=True;started=time.monotonic();deadline=started+1.;errors=[];killed=False;reaped=[]
        child=self.child
        if child is None:return dict(clean=True,reaped=True,group_empty=True,remaining_members=[],errors=[])
        def reap():
            # Popen owns its leader wait status; waitpid only this owned group.
            child.poll()
            for row in self._verified_members():
                if row['pid']==child.pid or row['ppid']!=self.pid:continue
                try:pid,status=os.waitpid(row['pid'],os.WNOHANG)
                except ChildProcessError:continue
                if pid:reaped.append(dict(pid=pid,status=status))
        def signal_group(sig):
            rows=self._verified_members()
            if rows:
                try:os.killpg(child.pid,sig)
                except ProcessLookupError:pass
        try:
            signal_group(signal.SIGTERM)
            term_end=started+.5
            while time.monotonic()<term_end:
                reap()
                if not self._verified_members():break
                time.sleep(min(.005,max(0.,term_end-time.monotonic())))
            reap()
            if self._verified_members():killed=True;signal_group(signal.SIGKILL)
            while time.monotonic()<deadline:
                reap()
                if not self._verified_members():break
                time.sleep(min(.005,max(0.,deadline-time.monotonic())))
            reap()
        except Exception as exc:errors.append(type(exc).__name__+':'+str(exc))
        group_verified=True
        try:remaining=self._members()
        except Exception as exc:
            remaining=[];group_verified=False;errors.append('process_group_inspection_failed:'+type(exc).__name__)
        if remaining:errors.append('owned_process_group_not_empty')
        if child.poll() is None:errors.append('owned_leader_not_reaped')
        return dict(self.identity,clean=not errors,reaped=child.returncode is not None,
                    group_empty=group_verified and not remaining,remaining_members=remaining,errors=errors,killed=killed,
                    returncode=child.returncode,reaped_descendants=reaped,cleanup_elapsed_s=time.monotonic()-started)
