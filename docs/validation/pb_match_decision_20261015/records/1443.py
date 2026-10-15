"""Offline colour-pixel baseline. NOT the user's learned detector/controller.

Uses rendered enemy-colour pixels, nominal fixture width for approximate range,
own joint feedback and configured muzzle speed. No world/enemy pose inputs.
"""
import math
import numpy as np
from .contracts import Command

class MatchPixelAim:
    def __init__(self):self.reset(-1)
    def reset(self,episode):
        self.episode=episode;self.previous=None;self.last_time=None;self.status='search';self.range_estimate=None
    def act(self,o):
        if o.episode!=self.episode:self.reset(o.episode)
        yaw,pitch=float(o.own_qpos[3]),float(o.own_qpos[4])
        if not o.rgb.size:return Command(gimbal_yaw=yaw,gimbal_pitch=pitch)
        rgb=o.rgb.astype(float);channel=2 if o.team=='red' else 0;other=0 if channel==2 else 2
        mask=(rgb[:,:,channel]>70)&(rgb[:,:,channel]>1.8*rgb[:,:,other])&(rgb[:,:,channel]>1.8*rgb[:,:,1])
        ys,xs=np.nonzero(mask)
        fire=False
        if len(xs)>=4:
            # Select one vertical pixel cluster, avoiding a global multi-robot centroid.
            histogram=np.bincount(xs,minlength=mask.shape[1]);peak=int(np.argmax(histogram))
            selected=np.abs(xs-peak)<25;xs=xs[selected];ys=ys[selected]
            h,w=mask.shape;f=h/(2*math.tan(math.radians(o.fovy_degrees)/2))
            ex=(float(xs.mean())-(w-1)/2)/f;ey=((h-1)/2-float(ys.mean()))/f
            distance=float(np.clip(f*.135/max(float(xs.max()-xs.min()+1),2),.5,10.))
            self.range_estimate=distance
            speed=12. if o.role=='hero' else 22.5
            bearing=float(o.own_qpos[2])+yaw-math.atan(ex)
            rate=0. if self.previous is None else (bearing-self.previous)/max(o.sim_time-self.last_time,1e-5)
            rate=float(np.clip(rate,-1.5,1.5))
            self.previous=bearing;self.last_time=o.sim_time
            desired=bearing-float(o.own_qpos[2])+rate*distance/speed
            yaw=float(np.clip(desired,-math.pi,math.pi))
            # Pinhole parallax + no-drag low-arc approximation + provisional plant FF.
            correction=math.atan(4.905*distance/(speed*speed))+.06/distance+.024
            pitch=float(np.clip(pitch+math.atan(ey)+correction,-.4,.5))
            fire=abs(ex)<.10 and abs(ey)<.30 and o.ammo>0 and o.own_hp>0
            self.status='pixel_track'
        else:
            self.previous=None;self.last_time=None;self.range_estimate=None
            yaw=math.pi*math.sin(o.sim_time*.6);pitch=-.03;self.status='search'
        return Command(gimbal_yaw=yaw,gimbal_pitch=pitch,fire=bool(fire))
