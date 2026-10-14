"""Sealed actual renderer pixels for the explicitly enabled own-native path.

No encoded JSON camera is fabricated here. This is an accidental-pairing guard,
not a sandbox against hostile code inside the Python service.
"""
from dataclasses import dataclass
import threading
import weakref
from .contracts import exact, finite, integer, vector, string, ContractError, MAX_IMAGE_BYTES

_minted=weakref.WeakSet()
_lock=threading.Lock()
OWN=('own_qpos_at_capture','own_qvel_at_capture','own_odom_at_capture','own_odom_velocity_at_capture')


@dataclass(frozen=True,init=False,eq=False,repr=False)
class NativeCameraSnapshot:
    __slots__=('robot_id','episode','frame_id','capture_wall','capture_sim_time','consumers',
               'width','height','stride_bytes','raw_bytes','own','intrinsics','extrinsics','__weakref__')
    robot_id:str
    episode:int
    frame_id:int
    capture_wall:float
    capture_sim_time:float
    consumers:frozenset
    width:int
    height:int
    stride_bytes:int
    raw_bytes:bytes
    own:tuple
    intrinsics:tuple
    extrinsics:tuple

    def __init__(self,*args,**kwargs):raise TypeError('Use the actual raw-only renderer factory')
    def __copy__(self):return self
    def __deepcopy__(self,memo):return self
    def __repr__(self):return f'NativeCameraSnapshot(robot_id={self.robot_id!r}, frame_id={self.frame_id})'

    def metadata(self):
        """A detached INTERNAL camera description; deliberately not a JSON DTO."""
        fx,fy,cx,cy,distortion=self.intrinsics
        translation,rotation,cid=self.extrinsics
        return dict(frame_id=self.frame_id,capture_sim_time=self.capture_sim_time,
            **{k:list(v) for k,v in zip(OWN,self.own)},
            image=dict(encoding='rgb8',width=self.width,height=self.height,stride_bytes=self.stride_bytes),
            intrinsics=dict(fx=fx,fy=fy,cx=cx,cy=cy,distortion_model='brown_conrady_5',distortion=list(distortion)),
            extrinsics=dict(parent_frame='gimbal_link',translation_m=list(translation),rotation_xyzw=list(rotation),calibration_id=cid),
            provenance='simulated_raw_camera')


def is_native_snapshot(value):
    if type(value) is not NativeCameraSnapshot:return False
    with _lock:return value in _minted


def mint_native_snapshot(raw_bytes,*,robot_id,episode,frame_id,capture_wall,capture_sim_time,
                         consumers,width,height,stride_bytes,own,intrinsics,extrinsics):
    """Accept actual immutable RGB bytes and detached exposure metadata only."""
    string(robot_id,'native_camera_robot_id');integer(episode,'native_camera_episode');integer(frame_id,'native_camera_frame')
    finite(capture_wall,'native_camera_wall',0,1e12);finite(capture_sim_time,'native_camera_sim',0,1e12)
    integer(width,'width',1,4096);integer(height,'height',1,4096);integer(stride_bytes,'stride',3,12288)
    if type(raw_bytes) is not bytes or len(raw_bytes)!=width*height*3 or len(raw_bytes)>MAX_IMAGE_BYTES or stride_bytes!=width*3:
        raise ContractError('invalid_native_rgb_bytes')
    if type(consumers) is not frozenset or not consumers:raise ContractError('invalid_native_camera_consumers')
    for c in consumers:
        if (type(c) is not tuple or len(c)!=5 or c[:3]!=('adapter',robot_id,'aim')
            or any(type(v) is not str for v in c[:4])
            or type(c[3]) is not str or not c[3] or type(c[4]) is not int or c[4]<0):
            raise ContractError('invalid_native_camera_consumer')
    exact(own,OWN,'native_capture_own')
    detached_own=tuple(tuple(vector(own[k],n,k)) for k,n in zip(OWN,(5,5,3,3)))
    exact(intrinsics,('fx','fy','cx','cy','distortion_model','distortion'),'intrinsics')
    if intrinsics['distortion_model']!='brown_conrady_5' or type(intrinsics['distortion_model']) is not str:raise ContractError('unsupported_distortion')
    iv=tuple(finite(intrinsics[k],k,*bounds) for k,bounds in [('fx',(1e-6,1e7)),('fy',(1e-6,1e7)),('cx',(-1e5,1e5)),('cy',(-1e5,1e5))])
    iv=(*iv,tuple(vector(intrinsics['distortion'],5,'distortion')))
    exact(extrinsics,('parent_frame','translation_m','rotation_xyzw','calibration_id'),'extrinsics')
    if type(extrinsics['parent_frame']) is not str or extrinsics['parent_frame']!='gimbal_link':raise ContractError('unsupported_camera_parent')
    translation=tuple(vector(extrinsics['translation_m'],3,'camera_translation',-10,10))
    rotation=tuple(vector(extrinsics['rotation_xyzw'],4,'camera_rotation',-1,1))
    if abs(sum(v*v for v in rotation)-1)>1e-6:raise ContractError('camera_quaternion_not_unit')
    cid=string(extrinsics['calibration_id'],'calibration_id')
    value=object.__new__(NativeCameraSnapshot)
    fields=dict(robot_id=robot_id,episode=episode,frame_id=frame_id,capture_wall=capture_wall,capture_sim_time=capture_sim_time,
        consumers=consumers,width=width,height=height,stride_bytes=stride_bytes,raw_bytes=raw_bytes,own=detached_own,intrinsics=iv,extrinsics=(translation,rotation,cid))
    for k,v in fields.items():object.__setattr__(value,k,v)
    with _lock:_minted.add(value)
    return value
