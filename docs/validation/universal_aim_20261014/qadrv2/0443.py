"""Bounded observation hooks for a smoke harness; never modify transport policy.

No source patch, timeout, clock, payload, generation, or authority override. The
pinned client's original methods execute once and their result/error is preserved.
"""
from collections import deque
import copy
import threading
import time


class TransportProbe:
    def __init__(self, transport, *, clock=time.monotonic, capacity=128):
        self.transport = transport
        self.clock = clock
        self.lock = threading.Lock()
        self.transitions = deque(maxlen=capacity)
        self.frame_calls = deque(maxlen=capacity)
        self.request_errors = deque(maxlen=capacity)
        self.admitted_frame_count = 0
        self.last_transition = None
        self._install_frame = transport.install_frame
        self._request = transport.client._request
        transport.install_frame = self.install_frame
        transport.client._request = self.request

    def install_frame(self, data, **kwargs):
        item = {key: data.get(key) for key in (
            'available', 'reason', 'robot_id', 'episode', 'watch_epoch',
            'frame_seq', 'capture_sim_time', 'age_wall_s', 'max_frame_age_wall_s')}
        item['received_wall'] = self.clock()
        try:
            result = self._install_frame(data, **kwargs)
            item['installed'] = result
            if result:
                with self.lock:
                    self.admitted_frame_count += 1
            return result
        except Exception as exc:
            item['error_type'] = type(exc).__name__
            item['error'] = str(exc)[:512]
            raise
        finally:
            with self.lock:
                self.frame_calls.append(item)

    def request(self, path, *args, **kwargs):
        start = self.clock()
        try:
            return self._request(path, *args, **kwargs)
        except Exception as exc:
            cause = exc.__cause__
            item = dict(path=path, started_wall=start,
                        elapsed_wall_s=self.clock() - start,
                        error_type=type(exc).__name__, error=str(exc)[:512],
                        cause_type=type(cause).__name__ if cause else None,
                        cause=str(cause)[:512] if cause else None)
            with self.lock:
                self.request_errors.append(item)
            raise

    def sample(self):
        t = self.transport
        with t._lock:
            value = dict(last_error=t.last_error, frame_error=t.frame_error,
                         connected=t._connected, uncertain=t.client.uncertain,
                         watch_robot=t.watch_robot, watch_epoch=t.watch_epoch,
                         video_sequence=t.video_sequence,
                         video_available=t.video is not None,
                         raw_state_available=t.raw_state is not None,
                         telemetry_available=t.telemetry is not None,
                         catalog_ready=t.catalog.get('ready') is True,
                         selection_pending=t.selection_pending)
        with self.lock:
            if value != self.last_transition:
                self.transitions.append(dict(wall_monotonic=self.clock(), **value))
                self.last_transition = value
        return value

    def watch_ready(self, robot):
        value = self.sample()
        return (value['connected'] and not value['uncertain']
                and value['watch_robot'] == robot
                and type(value['watch_epoch']) is int
                and value['watch_epoch'] >= 0
                and not value['selection_pending']
                and value['raw_state_available'] and value['telemetry_available']
                and value['catalog_ready'])

    def snapshot(self):
        """Call before stop(), which intentionally clears display identity."""
        current = self.sample()
        with self.lock:
            result = copy.deepcopy(dict(
                current=current, admitted_frame_count=self.admitted_frame_count,
                transitions=list(self.transitions), frame_calls=list(self.frame_calls),
                request_errors=list(self.request_errors)))
        result['diagnostics'] = self.transport.diagnostics()
        return result
