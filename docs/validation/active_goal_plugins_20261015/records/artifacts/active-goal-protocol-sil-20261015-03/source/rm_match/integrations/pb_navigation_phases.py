"""Opt-in bounded local startup evidence; never part of the JSONL protocol."""
from __future__ import annotations
import json
import os
from pathlib import Path
import stat
import time

ENV_KEY='POLAR_PB_BRIDGE_PHASE_FILE'
MAX_RECORDS=64
MAX_RECORD_BYTES=512
PHASE_NAMES=frozenset(('module','main','ros_import_begin','ros_import_end','ros_import_failed',
    'rclpy_init_begin','rclpy_init_end','node_begin','node_end','transport_ready',
    'graph_wait_enter','graph_counts','graph_ready','graph_timeout','reset_received',
    'reset_ack','main_failed','cleanup_begin','transport_cleanup_begin',
    'transport_cleanup_end','transport_cleanup_failed','cleanup_end','diagnostic_closed'))


class PhaseRecorder:
    def __init__(self,path=None,*,repo_root=None):
        self._fd=None;self._records=0;self._graph_records=0
        if path is None:return
        root=Path(repo_root) if repo_root is not None else Path(__file__).absolute().parents[2]
        candidate=Path(path)
        if not candidate.is_absolute() or '..' in candidate.parts or not root.is_absolute():raise ValueError('pb_phase_path_scope')
        try:relative=candidate.relative_to(root/'artifacts')
        except ValueError:raise ValueError('pb_phase_path_scope') from None
        if not relative.parts or not candidate.parent.is_dir():raise ValueError('pb_phase_parent_required')
        # Check the lexical path before resolve: links must not silently redirect it.
        for item in (candidate,*candidate.parents):
            try:info=item.lstat()
            except FileNotFoundError:continue
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0):raise ValueError('pb_phase_link_rejected')
        flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0)
        if os.open in getattr(os,'supports_dir_fd',()) and hasattr(os,'O_DIRECTORY'):
            directory=os.open(candidate.anchor,os.O_RDONLY|os.O_DIRECTORY)
            try:
                for part in candidate.parts[1:-1]:
                    next_directory=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
                    os.close(directory);directory=next_directory
                self._fd=os.open(candidate.name,flags,0o600,dir_fd=directory)
            finally:os.close(directory)
        else:self._fd=os.open(candidate,flags,0o600)
        if not stat.S_ISREG(os.fstat(self._fd).st_mode):
            os.close(self._fd);self._fd=None;raise ValueError('pb_phase_regular_file_required')

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get(ENV_KEY))

    def mark(self,phase,counts=None):
        if self._fd is None:return
        if phase not in PHASE_NAMES:raise ValueError('pb_phase_name')
        if counts is not None and (phase!='graph_counts' or type(counts) is not tuple or len(counts)!=4 or any(type(n) is not int or not 0<=n<=65535 for n in counts)):raise ValueError('pb_phase_counts')
        # Graph churn is diagnostic only; leave room for ACK and cleanup evidence.
        if phase=='graph_counts':
            if self._graph_records>=32:return
            self._graph_records+=1
        if self._records>=MAX_RECORDS-1 and phase!='diagnostic_closed':return
        if self._records>=MAX_RECORDS:return
        row=dict(phase=phase,pid=os.getpid(),monotonic_ns=time.monotonic_ns(),perf_counter_ns=time.perf_counter_ns())
        if counts is not None:row['counts']=counts
        payload=(json.dumps(row,separators=(',',':'))+'\n').encode('ascii')
        if len(payload)>MAX_RECORD_BYTES:raise ValueError('pb_phase_record_bound')
        if os.write(self._fd,payload)!=len(payload):raise OSError('pb_phase_short_write')
        self._records+=1

    def close(self):
        if self._fd is None:return
        try:self.mark('diagnostic_closed')
        finally:os.close(self._fd);self._fd=None


PHASES=PhaseRecorder.from_environment()
