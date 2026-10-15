"""Offline execution of the original repository's rule fallback.

Own odometry/referee feedback and optional RGB colour detections are the entire
input. Estimated enemy positions come from pixels, not MuJoCo or referee truth.
The detector and standoff controller remain provisional, not the user's auto-aim.
"""
import math
import numpy as np
from .upstream_rule import rule_decide, FIELD_PROFILE, SOURCE_COMMIT
from .arena import arena_metadata


def visible_contacts(o):
    if not o.rgb.size or o.odom_xyyaw is None:
        return []
    rgb=o.rgb.astype(np.float32)
    channel=2 if o.team=='red' else 0
    other=0 if channel==2 else 2
    mask=(rgb[:,:,channel]>70)&(rgb[:,:,channel]>1.8*rgb[:,:,other])&(rgb[:,:,channel]>1.8*rgb[:,:,1])
    ys,xs=np.nonzero(mask)
    if len(xs)<4:
        return []
    peak=int(np.argmax(np.bincount(xs,minlength=mask.shape[1])))
    keep=np.abs(xs-peak)<25
    xs=xs[keep]
    h,w=mask.shape
    f=h/(2*math.tan(math.radians(o.fovy_degrees)/2))
    distance=float(np.clip(f*.135/max(float(xs.max()-xs.min()+1),2),.5,10.))
    ex=(float(xs.mean())-(w-1)/2)/f
    bearing=o.odom_xyyaw[2]+o.own_qpos[3]-math.atan(ex)
    x,y=o.odom_xyyaw[:2]
    return [dict(id=-1,type='anonymous_rgb_contact',alive=True,objective=False,
        dist=distance,pos=[x+distance*math.cos(bearing),y+distance*math.sin(bearing)],
        provenance='pixel_colour_nominal_armor_width_estimate',observed_at=o.sim_time)]


class OriginalRuleAdapter:
    label='original_rule_decide_offline_rmul_profile'

    def __init__(self):
        self.memory={}
        self.calls=0
        self.last_record=None

    def decide(self,o):
        metadata=arena_metadata()['coordinates']
        own_supply=metadata[o.team+'_supply_center'][:2]
        st=dict(t=o.sim_time,phase=o.match_phase,
            own=dict(id=7 if o.team=='red' else 107,type='sentry',pos=list(o.odom_xyyaw[:2]),
                hp=o.own_hp,hpMax=o.own_max_hp or 400,hpPct=o.own_hp/max(o.own_max_hp or 400,1)*100),
            allies=[],enemies=visible_contacts(o),bases=dict(own=list(own_supply)),
            recentEvents=[],engagements=[])
        decision=rule_decide(st,self.memory)
        self.calls+=1
        self.last_record=dict(input=st,decision=decision,source=self.label,source_commit=SOURCE_COMMIT,
            field_profile=FIELD_PROFILE,llm_called=False)
        return decision
