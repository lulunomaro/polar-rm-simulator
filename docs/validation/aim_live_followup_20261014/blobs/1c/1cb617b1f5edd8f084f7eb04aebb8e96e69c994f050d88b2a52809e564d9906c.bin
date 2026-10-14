"""Explicit local scheduling scopes; never change simulation deadlines or timers."""
import math
import os
import sys
import threading


def switch_interval_ms(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not .1 <= value <= 10:
        raise ValueError('Host Python switch interval must be finite within 0.1..10 ms')
    return float(value)


def affinity_mask(value):
    if type(value) is not int or not 0 < value < 2**64:
        raise ValueError('Authority affinity mask must be a positive 64-bit integer')
    return value


def parse_affinity_mask(value):
    return affinity_mask(int(value, 0))


class PythonSwitchInterval:
    """Set once before local preparation and restore after all owned cleanup."""
    def __init__(self, requested_ms=None):
        self.requested = None if requested_ms is None else switch_interval_ms(requested_ms)
        self.record = dict(schema='polar.host.python-switch-interval.v1', enabled=self.requested is not None,
            requested_ms=self.requested, original_ms=None, effective_ms=None, restored_ms=None,
            applied=False, restored=False, scope='Current owned CPython process only')
        self._original = None

    def __enter__(self):
        if self.requested is None:
            return self.record
        self._original = sys.getswitchinterval()
        self.record['original_ms'] = self._original * 1000
        # Mark restoration necessary before calling a potentially failing setter.
        try:
            sys.setswitchinterval(self.requested / 1000)
            self.record['applied'] = True
            effective = sys.getswitchinterval()
            self.record['effective_ms'] = effective * 1000
            if not math.isfinite(effective) or abs(effective - self.requested / 1000) > 1.01e-6:
                raise RuntimeError('CPython switch interval readback mismatch')
        except BaseException:
            self.close()
            raise
        return self.record

    def close(self):
        if self._original is None or self.record['restored']:
            return
        sys.setswitchinterval(self._original)
        restored = sys.getswitchinterval()
        self.record['restored_ms'] = restored * 1000
        if abs(restored - self._original) > 1.01e-6:
            raise RuntimeError('CPython switch interval restoration readback mismatch')
        self.record['restored'] = True

    def __exit__(self, *_):
        self.close()


class _WindowsAffinityAPI:
    """Lazy WinAPI binding. Pseudohandle always names the calling thread."""
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        class GroupAffinity(ctypes.Structure):
            _fields_ = [('Mask', ctypes.c_size_t), ('Group', wintypes.WORD), ('Reserved', wintypes.WORD * 3)]
        self.structure = GroupAffinity
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.current = api.GetCurrentThread
        self.current.argtypes = []; self.current.restype = wintypes.HANDLE
        self.get = api.GetThreadGroupAffinity
        self.get.argtypes = [wintypes.HANDLE, ctypes.POINTER(GroupAffinity)]; self.get.restype = wintypes.BOOL
        self.set = api.SetThreadGroupAffinity
        self.set.argtypes = [wintypes.HANDLE, ctypes.POINTER(GroupAffinity), ctypes.POINTER(GroupAffinity)]
        self.set.restype = wintypes.BOOL
        self.active = api.GetActiveProcessorCount
        self.active.argtypes = [wintypes.WORD]; self.active.restype = wintypes.DWORD

    def read(self):
        result = self.structure()
        if not self.get(self.current(), self.ctypes.byref(result)):
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        return int(result.Group), int(result.Mask)

    def replace(self, group, mask):
        if mask >= 2**(self.ctypes.sizeof(self.ctypes.c_size_t)*8):
            raise ValueError('Authority mask exceeds this host pointer width')
        requested = self.structure(); requested.Group = group; requested.Mask = mask
        previous = self.structure()
        if not self.set(self.current(), self.ctypes.byref(requested), self.ctypes.byref(previous)):
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        return int(previous.Group), int(previous.Mask)

    def processor_count(self, group):
        count = int(self.active(group))
        if not count:
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        return count


class AuthorityThreadAffinity:
    """Bind only the calling authority thread for runtime.run, then restore it."""
    def __init__(self, requested_mask=None):
        self.requested = None if requested_mask is None else affinity_mask(requested_mask)
        self.record = dict(schema='polar.host.authority-affinity.v1', enabled=self.requested is not None,
            requested_mask=self.requested, process_id=os.getpid(), thread_id=None, cpu_group=None,
            processor_count=None, original_mask=None, effective_mask=None, restored_mask=None,
            restored_group=None, applied=False, restored=False,
            scope='Current authority thread during runtime.run only; no priority, power or OS timer changes')
        self._api = None; self._previous = None; self._thread = None

    def __enter__(self):
        if self.requested is None:
            return self.record
        if sys.platform != 'win32':
            raise RuntimeError('Explicit authority affinity currently requires Windows')
        self._thread = threading.get_ident()
        self.record['thread_id'] = threading.get_native_id()
        self._api = _WindowsAffinityAPI()
        group, original = self._api.read()
        count = self._api.processor_count(group)
        self.record.update(cpu_group=group, original_mask=original, processor_count=count)
        if self.requested >> count:
            raise ValueError('Authority mask selects unavailable CPUs in the current processor group')
        # The API returns the actual pre-set affinity, which is the restoration target.
        self._previous = self._api.replace(group, self.requested)
        self.record['applied'] = True
        try:
            effective_group, effective = self._api.read()
            self.record['effective_mask'] = effective
            if self._previous != (group, original) or (effective_group, effective) != (group, self.requested):
                raise RuntimeError('Authority thread affinity readback mismatch')
        except BaseException:
            self.close()
            raise
        return self.record

    def close(self):
        if self._previous is None or self.record['restored']:
            return
        if threading.get_ident() != self._thread:
            raise RuntimeError('Authority affinity must be restored by its owning thread')
        self._api.replace(*self._previous)
        group, mask = self._api.read()
        self.record.update(restored_group=group, restored_mask=mask)
        if (group, mask) != self._previous:
            raise RuntimeError('Authority affinity restoration readback mismatch')
        self.record['restored'] = True

    def __exit__(self, *_):
        self.close()


def scheduling_qualified(record):
    """An explicit setting is qualified only after application AND restoration."""
    return all(not row['enabled'] or (row['applied'] and row['restored']) for row in record.values())
