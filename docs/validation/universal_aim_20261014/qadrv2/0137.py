"""Non-blocking opening/tactical arbitration core for a future ROS bridge.

No network/ROS import and no transport is constructed here. A caller supplies a
non-blocking submit(payload)->Future implementation. Every disabled output requires
its downstream adapter to cancel the current goal and close its velocity gate.
This contract is tested offline; it is NOT a deployed ROS2/Nav2 integration.
"""
from dataclasses import dataclass
from copy import deepcopy
import math
from .opening_strategy import OpeningRushSupervisor

BEHAVIORS={'PATROL','ENGAGE','RETREAT','HOLD','HARASS_OUTPOST','DEFEND_BASE','INTERCEPT'}


@dataclass(frozen=True)
class BridgeOutput:
    goal: dict | None
    source: str
    stop_required: bool
    generation: int


class DecisionBridgeCore:
    def __init__(self,submit,*,bounds=(-6.,6.,-4.,4.),center=(0.,0.),arrival_radius=1.35,
                 state_timeout_s=.6,decision_max_age_s=5.,max_pose_drift_m=1.,min_request_interval_s=1.):
        self.submit=submit
        self.bounds=tuple(bounds)
        if (len(self.bounds)!=4 or not all(math.isfinite(v) for v in self.bounds)
            or self.bounds[0]>=self.bounds[1] or self.bounds[2]>=self.bounds[3]):
            raise ValueError('Invalid field bounds')
        if any(not math.isfinite(v) or v<=0 for v in (state_timeout_s,decision_max_age_s,max_pose_drift_m,min_request_interval_s)):
            raise ValueError('Invalid timing/drift bound')
        if not self._in_bounds(center):raise ValueError('Opening center outside selected map')
        self.opening=OpeningRushSupervisor(center,arrival_radius)
        self.state_timeout_s=state_timeout_s
        self.decision_max_age_s=decision_max_age_s
        self.max_pose_drift_m=max_pose_drift_m
        self.min_request_interval_s=min_request_interval_s
        self.generation=0;self.regime=None;self.latest=None;self.received_at=None;self.last_sim_time=None
        self.pending=None;self.cached=None;self.last_request=-math.inf;self.events=[]
        self.last_output=BridgeOutput(None,'no_state',True,0)

    def _in_bounds(self,p):
        try:x,y=map(float,p)
        except (TypeError,ValueError):return False
        return math.isfinite(x) and math.isfinite(y) and self.bounds[0]<=x<=self.bounds[1] and self.bounds[2]<=y<=self.bounds[3]

    def _invalidate(self,reason):
        self.generation+=1;self.cached=None
        if self.pending is not None:self.pending['future'].cancel()
        self.events.append(dict(type='invalidate',reason=reason,generation=self.generation))
        self.events=self.events[-128:]

    def _stop(self,reason):
        self.last_output=BridgeOutput(None,reason,True,self.generation)
        return self.last_output

    def on_observation(self,o,*,now,payload=None):
        if not math.isfinite(now):raise ValueError('Nonfinite receipt clock')
        max_hp=getattr(o,'own_max_hp',0) or 400
        if not math.isfinite(o.own_hp) or not math.isfinite(max_hp) or max_hp<=0:
            self._invalidate('invalid_health')
            return self._stop('invalid_health')
        regime=(o.episode,o.match_phase,o.own_hp>0,bool(o.emergency_stop),bool(o.own_weak),o.own_hp/max_hp<.35)
        if regime!=self.regime:
            old=self.regime
            self._invalidate('state_regime_changed')
            self.regime=regime
            if old is None or old[0]!=o.episode:self.last_sim_time=None
        if self.last_sim_time is not None and o.sim_time<self.last_sim_time:
            self._invalidate('out_of_order_state')
            return self._stop('out_of_order_state')
        self.last_sim_time=o.sim_time
        self.latest=o;self.received_at=now
        supervisor=self.opening.decide(o)
        if not supervisor.enabled:return self._stop(supervisor.mode)
        if supervisor.intent:
            d=supervisor.intent
            self.last_output=BridgeOutput(dict(behavior=d.behavior,target_point=dict(x=d.target_point[0],y=d.target_point[1]),reason=d.reason),
                'deterministic_opening',False,self.generation)
            return self.last_output
        self._consume(now,o)
        if self.cached is not None and now-self.cached['requested_at']>self.decision_max_age_s:
            self.cached=None
        if self.pending is None and now-self.last_request>=self.min_request_interval_s:
            self.last_request=now
            try:
                future=self.submit(deepcopy(payload if payload is not None else self._payload(o)))
                if not all(hasattr(future,n) for n in ('done','result','cancel')):raise TypeError('submit must return a Future')
                self.pending=dict(future=future,generation=self.generation,episode=o.episode,
                    requested_at=now,xy=tuple(o.odom_xyyaw[:2]))
            except Exception as e:
                self.events.append(dict(type='transport_submit_failed',error=type(e).__name__))
        if self.cached is not None:
            self.last_output=BridgeOutput(self.cached['decision'],self.cached['source'],False,self.generation)
        else:
            # Arrival/transport failure does not cause a new drive toward a stale
            # tactical destination. Holding current own pose is a goal request;
            # physical stopping remains the downstream controller's job.
            self.last_output=BridgeOutput(dict(behavior='HOLD',target_point=dict(x=o.odom_xyyaw[0],y=o.odom_xyyaw[1]),
                reason='center occupation while awaiting a current tactical result'), 'occupation_hold',False,self.generation)
        return self.last_output

    def _consume(self,now,o):
        pending=self.pending
        if pending is None or not pending['future'].done():return
        self.pending=None
        reason=None
        if pending['generation']!=self.generation or pending['episode']!=o.episode:reason='invalid_generation'
        elif now-pending['requested_at']>self.decision_max_age_s:reason='expired_result'
        elif math.dist(pending['xy'],o.odom_xyyaw[:2])>self.max_pose_drift_m:reason='pose_drift'
        if reason:
            self.events.append(dict(type='decision_discarded',reason=reason));return
        try:
            result=pending['future'].result();d=result['decision'];p=d['target_point']
            if d.get('behavior') not in BEHAVIORS or not self._in_bounds((p['x'],p['y'])):
                raise ValueError('Invalid decision')
            validated=dict(behavior=d['behavior'],target_point=dict(x=float(p['x']),y=float(p['y'])),reason=str(d.get('reason',''))[:120])
            self.cached=dict(decision=validated,source=str(result.get('source','tactical'))[:64],requested_at=pending['requested_at'])
        except Exception as e:
            self.events.append(dict(type='decision_discarded',reason=type(e).__name__))

    def tick(self,*,now):
        """Call from an independent periodic timer even if state messages stop."""
        if not math.isfinite(now):raise ValueError('Nonfinite watchdog clock')
        if self.received_at is None:return self._stop('no_state')
        if now<self.received_at or now-self.received_at>self.state_timeout_s:
            if self.last_output.source!='state_timeout':self._invalidate('state_timeout')
            return self._stop('state_timeout')
        return self.last_output

    @staticmethod
    def _payload(o):
        max_hp=getattr(o,'own_max_hp',0) or 400
        return dict(episode=o.episode,t=o.sim_time,match_phase=o.match_phase,
            own=dict(id=7 if o.team=='red' else 107,pos=list(o.odom_xyyaw[:2]),hp=o.own_hp,
                hpMax=max_hp,hpPct=o.own_hp/max_hp*100),allies=[],enemies=[],recentEvents=[],engagements=[])
