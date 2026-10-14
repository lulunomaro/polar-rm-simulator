"""Linux peer tree ownership including nested sessions and adopted children.

Only this dedicated supervisor's unique spawned peer and its descendants are
owned. Birth checks precede each individual signal; no arbitrary PGID is killed.
This cannot sandbox a plugin which deliberately transfers work to other services.
"""
from __future__ import annotations
import os
from pathlib import Path
import signal
import time
from .json_owned_process import _LinuxAdapterGroup
from ..integrations.owned_linux_group import _stat

class WslJsonPeerTree(_LinuxAdapterGroup):
    def __init__(self):
        if not hasattr(os,'pidfd_open') or not hasattr(signal,'pidfd_send_signal'):
            raise RuntimeError('Linux pidfd ownership required')
        super().__init__();self.births={}
        # The dedicated worker must not already own unrelated direct children.
        if any((r:=_stat(int(p.name))) is not None and r['ppid']==self.pid
               for p in Path('/proc').iterdir() if p.name.isdigit()):
            raise RuntimeError('WSL peer supervisor already has child processes')
    def attach(self,child):
        value=super().attach(child)
        if value['leader_start_ticks'] is None:raise RuntimeError('peer birth identity unavailable')
        return value
    def _verified_members(self):
        if Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=self.boot_id:
            raise RuntimeError('Linux boot identity changed')
        if self.child is None:return []
        all_rows={}
        for path in Path('/proc').iterdir():
            if path.name.isdigit():
                row=_stat(int(path.name))
                if row is not None:all_rows[row['pid']]=row
        selected={}
        for row in all_rows.values():
            cursor=row;seen=set()
            while True:
                if cursor['pid']==self.child.pid or cursor['ppid']==self.pid:
                    selected[row['pid']]=row;break
                if cursor['pid'] in seen or cursor['ppid'] not in all_rows:break
                seen.add(cursor['pid']);cursor=all_rows[cursor['ppid']]
        for pid,row in selected.items():
            if pid==self.child.pid and row['ppid']!=self.pid:raise RuntimeError('peer leader parent changed')
            birth=self.births.get(pid)
            if birth is not None and birth!=row['start_ticks']:raise RuntimeError('owned descendant PID birth changed')
            if pid==self.child.pid and self.identity['leader_start_ticks'] is not None and row['start_ticks']!=self.identity['leader_start_ticks']:
                raise RuntimeError('peer leader PID birth changed')
            self.births[pid]=row['start_ticks']
        # A previously observed live child cannot silently escape the lineage.
        for pid,birth in self.births.items():
            row=all_rows.get(pid)
            if row is not None and (row['start_ticks']!=birth or pid not in selected):
                raise RuntimeError('owned descendant lineage changed')
        return list(selected.values())
    def _signal_row(self,row,sig):
        try:fd=os.pidfd_open(row['pid'],0)
        except ProcessLookupError:return False
        try:
            current=_stat(row['pid'])
            if current is None:return False
            if current['start_ticks']!=row['start_ticks']:raise RuntimeError('owned birth changed before signal')
            # The fd refers to this process even if the numeric PID is reused
            # after the final inspection. Never fall back to a numeric kill.
            try:signal.pidfd_send_signal(fd,sig,None,0)
            except ProcessLookupError:return False
            return True
        finally:os.close(fd)
    def cleanup_until(self,deadline):
        if self.closed:raise RuntimeError('owned cleanup single use')
        self.closed=True;started=time.perf_counter();errors=[];reaped=[];sent=set();killed=False
        if self.child is None:return dict(clean=True,reaped=False,not_spawned=True,group_empty=True,errors=[])
        def reap():
            self.child.poll()
            for row in self._verified_members():
                if row['pid']==self.child.pid or row['ppid']!=self.pid:continue
                try:pid,status=os.waitpid(row['pid'],os.WNOHANG)
                except ChildProcessError:continue
                if pid:reaped.append(dict(pid=pid,start_ticks=row['start_ticks'],status=status))
        def signal_owned(sig):
            # Children may create a new SID; signal only exact verified births.
            for row in self._verified_members():
                key=(row['pid'],row['start_ticks'],sig)
                if key in sent:continue
                if self._signal_row(row,sig):sent.add(key)
        try:
            term_end=min(deadline,started+1.17)
            while time.perf_counter()<term_end:
                signal_owned(signal.SIGTERM);reap()
                if not self._verified_members():break
                time.sleep(min(.005,max(0,term_end-time.perf_counter())))
            reap()
            while self._verified_members() and time.perf_counter()<deadline:
                killed=True;signal_owned(signal.SIGKILL);reap()
                time.sleep(min(.005,max(0,deadline-time.perf_counter())))
            reap()
        except Exception as exc:errors.append(type(exc).__name__)
        try:remaining=self._verified_members();verified=True
        except Exception as exc:remaining=[];verified=False;errors.append('owned_tree_inspection:'+type(exc).__name__)
        if remaining:errors.append('owned_tree_not_empty')
        if self.child.poll() is None:errors.append('owned_leader_not_reaped')
        return dict(self.identity,clean=not errors,reaped=self.child.returncode is not None,
            group_empty=verified and not remaining,remaining_members=remaining,errors=errors,
            owned_scope='birth_bound_descendants_including_nested_sessions',
            observed_births=dict(self.births),reaped_descendants=reaped,killed=killed,
            cleanup_elapsed_s=time.perf_counter()-started)
