"""Exact integer schedules; processing opportunities consume the newest captured frame.

2000 Hz physics evenly represents 80 Hz capture and 100 Hz control. The 36 Hz
historical detector-throughput profile is realized by a rational phase accumulator
at policy ticks, giving 20/30 ms service intervals, not invented extra actor ticks.
"""
from dataclasses import dataclass

@dataclass
class SensorSchedule:
    physics_hz: int = 2000
    capture_hz: int = 80
    control_hz: int = 100
    detector_hz: int = 36

    def __post_init__(self):
        if self.physics_hz % self.capture_hz or self.physics_hz % self.control_hz:
            raise ValueError('Capture and control must exactly divide physics rate')
        if not 0 < self.detector_hz <= min(self.capture_hz, self.control_hz):
            raise ValueError('Invalid processing rate')
        self._previous_bucket = -1

    def capture(self, step):
        return step % (self.physics_hz // self.capture_hz) == 0

    def control(self, step):
        return step % (self.physics_hz // self.control_hz) == 0

    def process(self, step):
        if not self.control(step):
            return False
        bucket = step * self.detector_hz // self.physics_hz
        if bucket == self._previous_bucket:
            return False
        self._previous_bucket = bucket
        return True
