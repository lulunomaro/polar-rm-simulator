"""Source-configured lens warp with explicit, unverified sensor-size association.

No claim that this K/D calibration belongs to the user's current CS016-10UC.
The physical resolution is user/vendor context; source YAML omits calibration size.
"""
from dataclasses import dataclass
import math
import numpy as np

@dataclass(frozen=True)
class SourceCameraProfile:
    width: int = 1440
    height: int = 1080
    fx: float = 1722.231837421459
    fy: float = 1724.876404292754
    cx: float = 701.3056440882832
    cy: float = 564.5821718351237
    distortion: tuple = (-.064232403853946, -.087667493884102, 0., 0., .792381808294582)
    name: str = 'rmcs_config_KD_assumed_1440x1080_v1'
    overscan_pixels: int = 0

    def __post_init__(self):
        if self.width<=0 or self.height<=0 or self.overscan_pixels<0 or not isinstance(self.overscan_pixels,int) or not np.isfinite([self.fx,self.fy,self.cx,self.cy,*self.distortion]).all() or min(self.fx,self.fy)<=0 or len(self.distortion)!=5:
            raise ValueError('finite positive resolution/focal length and five distortion coefficients required')

    @property
    def render_width(self):
        return self.width+2*self.overscan_pixels

    @property
    def render_height(self):
        return self.height+2*self.overscan_pixels

    @property
    def K(self):
        return np.array([[self.fx,0,self.cx],[0,self.fy,self.cy],[0,0,1.]])

    @property
    def ideal_K(self):
        # MuJoCo fovy camera has square pixels and centered principal point.
        return np.array([[self.fy,0,(self.render_width-1)/2],[0,self.fy,(self.render_height-1)/2],[0,0,1.]])

    @property
    def ideal_fovy_degrees(self):
        return math.degrees(2*math.atan(self.render_height/(2*self.fy)))

    def adapter_intrinsics(self):
        return dict(fx=self.fx,fy=self.fy,cx=self.cx,cy=self.cy,distortion=np.array(self.distortion))

    def manifest(self):
        return dict(name=self.name if not self.overscan_pixels else self.name+'_overscan'+str(self.overscan_pixels)+'_v2',render_resolution=[self.render_width,self.render_height],overscan_pixels=self.overscan_pixels,resolution=[self.width,self.height],K=self.K.tolist(),
                    distortion=list(self.distortion),ideal_render_K=self.ideal_K.tolist(),
                    ideal_render_fovy_degrees=self.ideal_fovy_degrees,
                    source_repository='lulunomaro/polar-upper-computer-control',
                    source_commit='fafe897dfffd5989789871225d7ca5d551b0674f',
                    source_path='sentry-rmcs/autaim/autoaim_config.yaml',
                    source_git_blob='4e63337a47c929d977f2af45807780ce976e27f5',
                    calibration_resolution_association='ASSUMED; absent from source YAML',
                    optical_model='ideal centered MuJoCo render then source-configured Brown-Conrady lens warp',
                    exposure_us_configured=2000,exposure_blur_modeled=False,
                    gain=None,binning=None,sensor_roi=None)


def ideal_pixels(pixels, profile):
    import cv2
    criteria=(cv2.TERM_CRITERIA_COUNT|cv2.TERM_CRITERIA_EPS,30,1e-10)
    if hasattr(cv2,'undistortPointsIter'):
        return cv2.undistortPointsIter(pixels,profile.K,np.array(profile.distortion),None,profile.ideal_K,criteria)
    return cv2.undistortPoints(pixels,profile.K,np.array(profile.distortion),P=profile.ideal_K,criteria=criteria)


class SourceLensWarp:
    """Inverse-map each distorted sensor pixel into ideal rendered RGB.

    Construct once per camera profile, not each frame. No target state needed.
    Black fill marks missing ideal-render coverage; no hallucinated border pixels.
    """
    def __init__(self, profile=SourceCameraProfile()):
        import cv2
        self.profile=profile
        yy,xx=np.indices((profile.height,profile.width),dtype=np.float64)
        pixels=np.stack((xx,yy),axis=-1).reshape(-1,1,2)
        # Iterative variant avoids five-iteration inaccuracies near image edges.
        points=ideal_pixels(pixels,profile)
        mapped=points.reshape(profile.height,profile.width,2)
        self.map_x=mapped[:,:,0].astype(np.float32)
        self.map_y=mapped[:,:,1].astype(np.float32)
        valid=(self.map_x>=0)&(self.map_x<=profile.render_width-1)&(self.map_y>=0)&(self.map_y<=profile.render_height-1)
        self.outside_fraction=float(1-valid.mean())
        if profile.overscan_pixels and self.outside_fraction:
            raise ValueError('overscan insufficient for this K/D; refuse artificial sensor-border pixels')

    def apply(self, rgb):
        import cv2
        p=self.profile
        if rgb.shape!=(p.render_height,p.render_width,3) or rgb.dtype!=np.uint8:
            raise ValueError('ideal RGB must match profile native resolution and uint8 HWC')
        return cv2.remap(rgb,self.map_x,self.map_y,cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_CONSTANT,borderValue=(0,0,0))
