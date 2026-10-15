"""Clearly labeled baseline: RGB red-blob aim + ideal-own-odometry goal control.
No enemy truth input. Not the user's detection/tracking or RL policy.
"""
import math
import numpy as np
from .contracts import Command

class PixelBaseline:
    def __init__(self, goal=(0.,-1.8), enable_fire=True):
        self.goal=goal; self.enable_fire=enable_fire; self.last_bearing=None; self.last_time=None
    def reset(self, episode): self.last_bearing=None; self.last_time=None
    def act(self, o):
        q,v=o.own_qpos,o.own_qvel
        force=np.clip(35*(np.array(self.goal)-np.array([q[0],q[1]-1.8]))-15*np.array(v[:2]),-60,60)
        rgb=o.rgb.astype(float)
        mask=(rgb[:,:,0]>80)&(rgb[:,:,0]>rgb[:,:,1]*2)&(rgb[:,:,0]>rgb[:,:,2]*2)
        yy,xx=np.nonzero(mask)
        yaw,pitch=q[3],q[4]; fire=False
        if len(xx)>=3:
            h,w=mask.shape; focal=h/(2*math.tan(math.radians(o.fovy_degrees)/2))
            ex=(xx.mean()-(w-1)/2)/focal
            ey=((h-1)/2-yy.mean())/focal
            bearing=yaw-math.atan(ex)
            rate=0. if self.last_time is None else (bearing-self.last_bearing)/max(o.sim_time-self.last_time,1e-6)
            self.last_bearing,self.last_time=bearing,o.sim_time
            yaw=bearing+float(np.clip(rate,-1,1))*.26
            pitch+=math.atan(ey)
            # Fixed TEST compensation, not calibrated range estimation/ballistics.
            pitch+=.094
            fire=self.enable_fire and abs(ex)<.06 and abs(ey)<.10
        return Command(float(force[0]),float(force[1]),0.,float(yaw),float(pitch),bool(fire))
