"""Exact RGB8 to native BGR8 preparation, without serializing large copies."""
from __future__ import annotations
import hashlib
from pathlib import Path
import time
import numpy as np
try:
    import cv2 as _opencv
except ImportError:
    _opencv = None


def prepare_native_image(rgb, path, *, trace_rgb=False, return_bytes=False, write_artifact=True):
    """Return original image envelope, optional RGB SHA and host-local timings.

    Channel swap only. There is no normalization, annotation, resizing or truth
    input. Hash and file write consume the same contiguous BGR memory directly.
    """
    if type(return_bytes) is not bool or type(write_artifact) is not bool or (not write_artifact and not return_bytes):
        raise ValueError('No-file native preparation requires private immutable bytes')
    if not isinstance(rgb,np.ndarray) or rgb.dtype!=np.uint8 or rgb.ndim!=3 or rgb.shape[2]!=3 or not rgb.shape[0] or not rgb.shape[1]:
        raise ValueError('Native image requires nonempty RGB8 HxWx3')
    started=time.perf_counter()
    if _opencv is not None:
        bgr=_opencv.cvtColor(rgb,_opencv.COLOR_RGB2BGR)
        converter='opencv_cvtColor_exact_channel_swap'
    else:
        bgr=np.empty(rgb.shape,dtype=np.uint8)
        bgr[:,:,0]=rgb[:,:,2];bgr[:,:,1]=rgb[:,:,1];bgr[:,:,2]=rgb[:,:,0]
        converter='numpy_exact_channel_assignment'
    converted=time.perf_counter()
    immutable=bgr.tobytes() if return_bytes else None
    snapshotted=time.perf_counter()
    buffer=memoryview(immutable) if return_bytes else memoryview(bgr).cast('B')
    digest=hashlib.sha256(buffer).hexdigest();hashed=time.perf_counter()
    path=Path(path)
    if write_artifact:
        with path.open('wb') as stream:
            written=stream.write(buffer)
        if written!=buffer.nbytes:raise OSError('Incomplete native BGR file write')
    saved=time.perf_counter();rgb_sha=None
    if trace_rgb:
        rgb_sha=hashlib.sha256(memoryview(np.ascontiguousarray(rgb)).cast('B')).hexdigest()
    completed=time.perf_counter()
    image=dict(encoding='bgr8',width=rgb.shape[1],height=rgb.shape[0],stride_bytes=rgb.shape[1]*3,
        bytes=buffer.nbytes,sha256=digest,path=str(path.absolute()))
    stages=dict(converter=converter,clock_domain='host_perf_counter',rgb_to_bgr_s=converted-started,
        immutable_bgr_snapshot_s=snapshotted-converted,bgr_sha256_s=hashed-snapshotted,bgr_file_write_s=saved-hashed,
        rgb_trace_sha256_s=completed-saved,total_s=completed-started)
    return (image,rgb_sha,stages,immutable) if return_bytes else (image,rgb_sha,stages)
