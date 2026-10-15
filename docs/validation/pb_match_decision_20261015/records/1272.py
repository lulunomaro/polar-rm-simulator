"""Bounded monotonic duration distributions, independent of simulation clocks."""
from collections import deque
import math
import threading


def percentile(sorted_values, fraction):
    if not sorted_values:
        return None
    index = (len(sorted_values)-1)*fraction
    low = math.floor(index);high = math.ceil(index)
    return sorted_values[low]+(sorted_values[high]-sorted_values[low])*(index-low)


class TimingLedger:
    """Keep the latest N samples per known stage; totals cover the whole run.

    Percentiles explicitly describe the retained window, not all-time samples.
    No pixels, poses, model objects, tokens or world truth are stored here.
    """
    def __init__(self, stages, capacity=4096):
        if type(capacity) is not int or not 1 <= capacity <= 100000:
            raise ValueError('invalid_timing_capacity')
        self.capacity = capacity;self.lock = threading.Lock()
        self.samples = {s: deque(maxlen=capacity) for s in stages}
        self.totals = {s: dict(count=0,total_s=0.,max_s=None) for s in stages}

    def record(self, stage, duration_s):
        if type(duration_s) not in (float,int) or not math.isfinite(duration_s) or duration_s < 0:
            raise ValueError('invalid_duration')
        with self.lock:
            self.samples[stage].append(float(duration_s))
            total = self.totals[stage];total['count'] += 1;total['total_s'] += duration_s
            total['max_s'] = max(total['max_s'] or 0.,duration_s)

    def snapshot(self):
        with self.lock:
            result = {}
            for stage, samples in self.samples.items():
                values = sorted(samples);total = self.totals[stage]
                result[stage] = dict(sample_count=total['count'],retained_count=len(values),
                    percentile_scope='latest_retained_samples',capacity=self.capacity,
                    mean_s=total['total_s']/total['count'] if total['count'] else None,
                    max_s=total['max_s'],p50_s=percentile(values,.5),
                    p95_s=percentile(values,.95),p99_s=percentile(values,.99))
            return result
