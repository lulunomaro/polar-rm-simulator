"""Canonical camera codec/source hook for reviewed native or ROS wrappers.

No detector, target-to-angle solver, fake TF or wall-clock authorization.
Keep source_context through the algorithm's actual processing of these pixels.
Bare latest Target/Twist or serial packets cannot be rebound to a new request.
"""
from __future__ import annotations
import copy
import json
from dataclasses import dataclass
from ..platform_v2.contracts import ContractError,IDENTITY,OBS_SCHEMA,validate_observation,exact

SOURCE_SCHEMA='polar.sim.aim-source-context.v1'

@dataclass(frozen=True)
class CameraSensorBundle:
    pixels:bytes
    encoding:str
    width:int
    height:int
    stride_bytes:int
    capture_stamp_ns:int
    _source_context_json:bytes
    _camera_json:bytes

    @property
    def source_context(self):return json.loads(self._source_context_json)
    @property
    def camera(self):return json.loads(self._camera_json)

def camera_sensor_bundle(observation):
    return prepare_aim_input(observation)[1]

def prepare_aim_input(observation):
    """One strict decode builds the detached DTO and its matching byte bundle."""
    decoded={};o=validate_observation(observation,image_bytes=decoded)
    if o['schema']!=OBS_SCHEMA:raise ContractError('aim_requires_public_camera_observation_v2')
    camera=o['sensors']['camera']
    if not camera['available']:raise ContractError('aim_camera_unavailable')
    image=camera['image'];stamp=round(camera['capture_sim_time']*1_000_000_000)
    context=dict(schema=SOURCE_SCHEMA,**{k:o[k] for k in IDENTITY},
        frame_id=camera['frame_id'],capture_sim_time=camera['capture_sim_time'],
        capture_stamp_ns=stamp,calibration_id=camera['extrinsics']['calibration_id'])
    # The frozen bundle holds only immutable bytes/scalars. Accessors return
    # fresh detached metadata; caller edits cannot alter the pending source.
    metadata={k:v for k,v in camera.items() if k!='image'}
    bundle=CameraSensorBundle(decoded['raw'],image['encoding'],
        image['width'],image['height'],image['stride_bytes'],stamp,
        json.dumps(context,allow_nan=False,separators=(',',':')).encode(),
        json.dumps(metadata,allow_nan=False,separators=(',',':')).encode())
    return o,bundle

def validate_source_echo(value,bundle):
    """Exact captured request, not a nearest-time/latest-message association."""
    if type(bundle) is not CameraSensorBundle:raise ContractError('invalid_aim_sensor_bundle')
    wanted=bundle.source_context;exact(value,wanted,'aim_source_context');value=copy.deepcopy(value)
    if any(type(value[k]) is not type(v) or value[k]!=v for k,v in wanted.items()):
        raise ContractError('aim_source_context_mismatch')
    return copy.deepcopy(value)

def ros_camera_messages(bundle):
    """Actual optional message objects; import failure is explicit, no stub.

    Caller owns namespace/QoS/generation. TF is static optical calibration only;
    no world/odom pose, ideal IMU or target position is generated here.
    """
    if type(bundle) is not CameraSensorBundle:raise ContractError('invalid_aim_sensor_bundle')
    try:
        from sensor_msgs.msg import Image,CameraInfo
        from geometry_msgs.msg import TransformStamped
    except (ImportError,OSError):raise ContractError('ros2_camera_message_types_unavailable') from None
    camera=bundle.camera;intr=camera['intrinsics'];ext=camera['extrinsics']
    image=Image();image.header.frame_id='camera_optical'
    image.header.stamp.sec=bundle.capture_stamp_ns//1_000_000_000
    image.header.stamp.nanosec=bundle.capture_stamp_ns%1_000_000_000
    image.encoding=bundle.encoding;image.width=bundle.width;image.height=bundle.height
    image.step=bundle.stride_bytes;image.is_bigendian=0;image.data=bundle.pixels
    info=CameraInfo();info.header=copy.deepcopy(image.header);info.width=bundle.width;info.height=bundle.height
    info.distortion_model='plumb_bob';info.d=list(intr['distortion'])
    info.k=[intr['fx'],0.,intr['cx'],0.,intr['fy'],intr['cy'],0.,0.,1.]
    info.r=[1.,0.,0.,0.,1.,0.,0.,0.,1.]
    info.p=[intr['fx'],0.,intr['cx'],0.,0.,intr['fy'],intr['cy'],0.,0.,0.,1.,0.]
    transform=TransformStamped();transform.header.frame_id=ext['parent_frame'];transform.child_frame_id='camera_optical'
    for key,value in zip(('x','y','z'),ext['translation_m']):setattr(transform.transform.translation,key,value)
    for key,value in zip(('x','y','z','w'),ext['rotation_xyzw']):setattr(transform.transform.rotation,key,value)
    return image,info,transform
