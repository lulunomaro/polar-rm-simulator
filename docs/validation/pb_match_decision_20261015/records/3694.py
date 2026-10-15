"""Explicit local OpenCV host-thread setup; no native model or environment edits.

Call once during local setup, before starting camera/physics workers. HTTP input
cannot select this option. The result records actual API queries, not an assumed
environment effect. Query-only default does not call a setter.
"""
from __future__ import annotations
import importlib
import os

SCHEMA='polar.sim.host-opencv-threads.v1'


def configure_opencv_threads(requested_threads=None):
    """Return JSON metadata after verified host-only set/get, or raise ValueError.

    No module callback/path, environment variable, affinity, warm image, native
    request or inference is accepted. None preserves the imported cv2 default.
    This does not configure a separate Linux/C++ process.
    """
    if requested_threads is not None and (type(requested_threads) is not int or not 1<=requested_threads<=32):
        raise ValueError('host_opencv_threads_require_local_integer_1_32')
    try:cv=importlib.import_module('cv2')
    except Exception as error:raise ValueError('host_opencv_import_failed') from error
    version=getattr(cv,'__version__',None);path=getattr(cv,'__file__',None)
    if (type(version) is not str or not 1<=len(version)<=128 or any(ord(c)<32 or ord(c)>126 for c in version)
        or type(path) is not str or not path or len(path)>4096 or '\0' in path):
        raise ValueError('host_opencv_module_identity_unavailable')
    try:before=cv.getNumThreads()
    except Exception as error:raise ValueError('host_opencv_before_query_failed') from error
    if type(before) is not int or not 1<=before<=65536:raise ValueError('host_opencv_before_threads_invalid')
    if requested_threads is not None:
        try:cv.setNumThreads(requested_threads)
        except Exception as error:raise ValueError('host_opencv_set_failed') from error
        try:effective=cv.getNumThreads()
        except Exception as error:raise ValueError('host_opencv_after_query_failed') from error
        if type(effective) is not int or effective!=requested_threads:
            raise ValueError('host_opencv_threads_not_effective')
    else:effective=before
    return dict(schema=SCHEMA,process_id=os.getpid(),before_threads=before,
        requested_threads=requested_threads,effective_threads=effective,
        opencv_version=version,module_path=path,action='query_only' if requested_threads is None else 'set_num_threads',
        scope='host_camera_lenswarp_and_color_conversion',environment_changed=False,
        linux_native_changed=False,images_processed=0,inference_calls=0,
        qualification='Verified host OpenCV API setup only; no camera/native/live performance acceptance')
