"""Opt-in, bounded scalar phase timing; never an authority or deadline clock.

Call sites with no probe must branch before sampling or constructing metadata.
Records retain only fixed scalar fields. Snapshots detach those records under
the probe lock; callers should serialize a snapshot after their owned work has
stopped. Thread CPU differences are meaningful only within the same thread.
"""
from __future__ import annotations

import math
import threading
import time

SCHEMA = 'polar.sim.numeric-phase-probe.v1'
MAX_CAPACITY = 1048576
SOURCE_FIELDS = ('robot_id', 'episode', 'binding_epoch', 'observed_seq', 'sim_time', 'wall_deadline')
ROW_FIELDS = ('phase', 'wall_ns', 'thread_cpu_ns', 'thread_id', 'request_id', *SOURCE_FIELDS,
              'frame_id', 'pixel_sha256', 'original_deadline', 'bytes_count', 'queue_depth', 'detail')


def _integer(value, name, *, optional=True):
    if value is None and optional:
        return
    if type(value) is not int or not 0 <= value <= (1 << 63) - 1:
        raise ValueError('phase_probe_' + name)


def _number(value, name):
    if not (type(value) is int and 0 <= value <= (1 << 63) - 1
            or type(value) is float and math.isfinite(value) and value >= 0):
        raise ValueError('phase_probe_' + name)


class NumericPhaseProbe:
    """Keep the first ``capacity`` scalar samples and count every overflow.

    ``source`` is either None or the exact six original identity fields. The
    original values and numeric types are retained, including wall_deadline.
    ``sample`` may be an earlier ``sample()`` from the same producer callback,
    associated with an original source only after that callback validates it.
    It is not a clock conversion and must never replace control authority.
    """

    def __init__(self, capacity=8192):
        if type(capacity) is not int or not 1 <= capacity <= MAX_CAPACITY:
            raise ValueError('phase_probe_capacity')
        self.capacity = capacity
        self._rows = []
        self._dropped = 0
        self._lock = threading.Lock()

    @staticmethod
    def sample():
        return time.perf_counter_ns(), time.thread_time_ns(), threading.get_ident()

    def mark(self, phase, *, source=None, request_id=None, frame_id=None, pixel_sha256=None,
             original_deadline=None, bytes_count=None, queue_depth=None, detail=None, sample=None):
        if type(phase) is not str or not 1 <= len(phase) <= 96:
            raise ValueError('phase_probe_phase')
        if source is None:
            identity = (None,) * len(SOURCE_FIELDS)
        else:
            if type(source) is not dict or set(source) != set(SOURCE_FIELDS):
                raise ValueError('phase_probe_source')
            if type(source['robot_id']) is not str or not 1 <= len(source['robot_id']) <= 128:
                raise ValueError('phase_probe_robot_id')
            for key in ('episode', 'binding_epoch', 'observed_seq'):
                _integer(source[key], key, optional=False)
            for key in ('sim_time', 'wall_deadline'):
                _number(source[key], key)
            identity = tuple(source[key] for key in SOURCE_FIELDS)
        for key, value in (('request_id', request_id), ('frame_id', frame_id),
                           ('bytes_count', bytes_count), ('queue_depth', queue_depth)):
            _integer(value, key)
        if pixel_sha256 is not None and (type(pixel_sha256) is not str or len(pixel_sha256) != 64
                or any(c not in '0123456789abcdef' for c in pixel_sha256)):
            raise ValueError('phase_probe_pixel_sha256')
        if original_deadline is not None:
            _number(original_deadline, 'original_deadline')
        if detail is not None and not (type(detail) is str and len(detail) <= 96
                or type(detail) is int and -(1 << 63) <= detail < (1 << 63)):
            raise ValueError('phase_probe_detail')
        stamp = self.sample() if sample is None else sample
        if type(stamp) is not tuple or len(stamp) != 3:
            raise ValueError('phase_probe_sample')
        for key, value in zip(('wall_ns', 'thread_cpu_ns', 'thread_id'), stamp):
            _integer(value, key, optional=False)
        if sample is not None and stamp[2] != threading.get_ident():
            raise ValueError('phase_probe_sample_thread')
        row = (phase, *stamp, request_id, *identity, frame_id, pixel_sha256,
               original_deadline, bytes_count, queue_depth, detail)
        with self._lock:
            if len(self._rows) == self.capacity:
                self._dropped += 1
            else:
                self._rows.append(row)

    def snapshot(self):
        with self._lock:
            rows = list(self._rows)
            dropped = self._dropped
        return dict(schema=SCHEMA, capacity=self.capacity, retained=len(rows), dropped=dropped,
            attempted=len(rows) + dropped, complete=dropped == 0,
            clocks=dict(wall='time.perf_counter_ns', thread_cpu='time.thread_time_ns',
                        thread_id='threading.get_ident', domain='process_local'),
            rows=[dict(zip(ROW_FIELDS, row)) for row in rows])
