"""Private immutable camera pixel capability; never a JSON/plugin DTO.

The producer-only factory accepts raw bytes and encodes the payload itself.
This guards accidental pair reuse/forgery, not hostile Python inside the service.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import threading
import weakref

_minted=weakref.WeakSet()
_mint_lock=threading.Lock()
MAX_PIXELS_BYTES=8*1024*1024
MAX_INTEGER=2**53-1


@dataclass(frozen=True,init=False,eq=False,repr=False)
class VerifiedCameraPixels:
    # Manual slots preserve the project's Python>=3.10 compatibility;
    # dataclass weakref_slot is only available starting with Python3.11.
    __slots__=('robot_id','episode','frame_id','capture_sim_time','encoding','width','height',
               'stride_bytes','data_base64','raw_bytes','__weakref__')
    robot_id:str
    episode:int
    frame_id:int
    capture_sim_time:float
    encoding:str
    width:int
    height:int
    stride_bytes:int
    data_base64:str
    raw_bytes:bytes

    def __init__(self,*args,**kwargs):
        raise TypeError('Camera pixels must be created by the raw-only producer factory')

    def __repr__(self):
        return f'VerifiedCameraPixels(robot_id={self.robot_id!r}, episode={self.episode}, frame_id={self.frame_id}, width={self.width}, height={self.height})'

    def __copy__(self):return self
    def __deepcopy__(self,memo):return self

    def matches(self,camera,*,robot_id,episode):
        """Same encoded object plus exact source/context metadata, without decoding."""
        if type(self) is not VerifiedCameraPixels:return False
        with _mint_lock:
            if self not in _minted:return False
        if type(robot_id) is not str or type(episode) is not int or robot_id!=self.robot_id or episode!=self.episode:return False
        if type(camera) is not dict or type(camera.get('frame_id')) is not int or camera['frame_id']!=self.frame_id:return False
        stamp=camera.get('capture_sim_time')
        if type(stamp) not in (int,float) or stamp!=self.capture_sim_time:return False
        image=camera.get('image')
        if type(image) is not dict:return False
        if type(image.get('encoding')) is not str or image['encoding']!=self.encoding:return False
        for key in ('width','height','stride_bytes'):
            if type(image.get(key)) is not int or image[key]!=getattr(self,key):return False
        return (type(image.get('data_base64')) is str and image['data_base64'] is self.data_base64
                and type(self.raw_bytes) is bytes and len(self.raw_bytes)==self.width*self.height*3
                and len(self.raw_bytes)<=MAX_PIXELS_BYTES)


def encode_camera_pixels(raw_bytes,*,robot_id,episode,frame_id,capture_sim_time,encoding,width,height,stride_bytes,
                         raw_base64_codec='stdlib_chunked'):
    """Return (encoded payload, sealed token), from one immutable raw snapshot."""
    if type(raw_bytes) is not bytes:raise ValueError('Camera raw snapshot must be immutable bytes')
    if type(robot_id) is not str or not robot_id or len(robot_id)>256:raise ValueError('Invalid camera robot identity')
    for name,value,low,high in [('episode',episode,0,MAX_INTEGER),('frame_id',frame_id,0,MAX_INTEGER),
            ('width',width,1,4096),('height',height,1,4096),('stride_bytes',stride_bytes,3,12288)]:
        if type(value) is not int or not low<=value<=high:raise ValueError('Invalid camera '+name)
    if type(capture_sim_time) not in (int,float) or not math.isfinite(capture_sim_time) or capture_sim_time<0:raise ValueError('Invalid camera exposure time')
    if type(encoding) is not str or encoding not in ('rgb8','bgr8'):raise ValueError('Invalid camera encoding')
    if stride_bytes!=width*3 or len(raw_bytes)!=width*height*3 or len(raw_bytes)>MAX_PIXELS_BYTES:raise ValueError('Invalid packed camera byte size')
    if type(raw_base64_codec) is not str or raw_base64_codec not in ('stdlib_chunked','pybase64_1_5_1'):
        raise ValueError('Unknown local raw base64 codec')
    # Import only after CameraProvider module initialization. The encoder is the
    # existing canonical bounded/yielding implementation, invoked exactly once.
    if raw_base64_codec=='stdlib_chunked':
        from .camera import encode_raw_base64
        data=encode_raw_base64(raw_bytes)
    else:
        from .base64_codec import load_raw_encoder
        data=load_raw_encoder(raw_base64_codec)(raw_bytes)
    token=object.__new__(VerifiedCameraPixels)
    values=dict(robot_id=robot_id,episode=episode,frame_id=frame_id,capture_sim_time=capture_sim_time,
        encoding=encoding,width=width,height=height,stride_bytes=stride_bytes,data_base64=data,raw_bytes=raw_bytes)
    for name,value in values.items():object.__setattr__(token,name,value)
    with _mint_lock:_minted.add(token)
    return data,token
