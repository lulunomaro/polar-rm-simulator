"""Exact RGB8 to native BGR8 preparation, without serializing large copies."""
from __future__ import annotations
import hashlib
from pathlib import Path
import time
import math
import threading
import weakref
import numpy as np
try:
    import cv2 as _opencv
except ImportError:
    _opencv = None

_prepared=weakref.WeakKeyDictionary()
_prepared_lock=threading.Lock()
_IMAGE_FIELDS=('encoding','width','height','stride_bytes','bytes','sha256','path')


class PreparedNativeBGR:
    """Opaque pairing receipt for one actual conversion, never a JSON DTO."""
    __slots__=('__weakref__',)
    def __init__(self,*args,**kwargs):raise TypeError('Use actual native snapshot preparation')
    def __copy__(self):return self
    def __deepcopy__(self,memo):return self


def prepare_native_snapshot(pixels,path,*,control_time_ns,host_deadline):
    """Hash actual immutable BGR once and retain its exact source pairing.

    This receipt guards accidental pairing in the trusted Python service. It
    does not replace validation of transport metadata, deadlines or Linux SHA.
    """
    from .native_camera_snapshot import is_native_snapshot
    if not is_native_snapshot(pixels):raise ValueError('Unsealed native preparation source')
    if type(control_time_ns) is not int or control_time_ns<0:raise ValueError('Invalid prepared control clock')
    exposure_ns=round(pixels.capture_sim_time*1e9)
    if not exposure_ns<=control_time_ns<=exposure_ns+80000000:raise ValueError('Prepared exposure/control mismatch')
    if (type(host_deadline) not in (int,float) or not math.isfinite(host_deadline)
        or not pixels.capture_wall<host_deadline<=pixels.capture_wall+.08):raise ValueError('Prepared original deadline mismatch')
    rgb=np.frombuffer(pixels.raw_bytes,dtype=np.uint8).reshape(pixels.height,pixels.width,3)
    image,rgb_sha,stages,raw=prepare_native_image(rgb,path,return_bytes=True,write_artifact=False)
    token=object.__new__(PreparedNativeBGR)
    image_values=tuple(image[k] for k in _IMAGE_FIELDS)
    source=(pixels.episode,pixels.frame_id,exposure_ns,pixels.capture_sim_time,control_time_ns,host_deadline)
    calibration=(*pixels.intrinsics[:4],pixels.intrinsics[4])
    own=(tuple(np.asarray(pixels.own[0]).tolist()),tuple(np.asarray(pixels.own[1]).tolist()),
        pixels.own[2],pixels.own[3])
    with _prepared_lock:_prepared[token]=(raw,image_values,source,calibration,own)
    return image,rgb_sha,stages,raw,token


def prepared_native_bgr_matches(token,raw,packet):
    """Only the same immutable byte object and original typed packet can reuse SHA."""
    if type(token) is not PreparedNativeBGR or type(raw) is not bytes or type(packet) is not dict:return False
    with _prepared_lock:
        record=_prepared.get(token)
    if record is None:return False
    saved_raw,image_values,source,calibration,own=record
    if raw is not saved_raw:return False
    frame=packet.get('frame')
    if type(frame) is not dict:return False
    if (type(frame.get('schema')) is not str or frame['schema']!='rmcs-mujoco-actor-frame-v1'
        or type(frame.get('episode')) is not int or frame['episode']!=source[0]):return False
    image=frame.get('image')
    if type(image) is not dict or set(image)!=set(_IMAGE_FIELDS):return False
    for k,expected in zip(_IMAGE_FIELDS,image_values):
        if type(image[k]) is not type(expected) or image[k]!=expected:return False
    actual=(packet.get('episode'),frame.get('frame_id'),frame.get('exposure_timestamp_ns'),
        frame.get('capture_time_s'),packet.get('control_time_ns'),packet.get('host_deadline'))
    if any(type(a) is not type(b) or a!=b for a,b in zip(actual,source)):return False
    state=frame.get('own')
    if type(state) is not dict:return False
    for k,expected in zip(('joint_positions','joint_velocities','base_odom_xyyaw','base_odom_vxyw'),own):
        value=state.get(k)
        if type(value) is not list or len(value)!=len(expected):return False
        if any(type(a) is not type(b) or a!=b for a,b in zip(value,expected)):return False
    camera=frame.get('camera')
    if type(camera) is not dict or set(camera)!=set(('fx','fy','cx','cy','distortion')):return False
    for k,expected in zip(('fx','fy','cx','cy'),calibration[:4]):
        if type(camera[k]) is not type(expected) or camera[k]!=expected:return False
    d=camera['distortion'];expected=calibration[4]
    if type(d) is not list or len(d)!=len(expected):return False
    return all(type(a) is type(b) and a==b for a,b in zip(d,expected))


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
