"""Opt-in moving-target test fixture, never an algorithm or observation source.

The trusted scene controller owns only the target's motion lease. It sends new
manual packets through the original ControlPlane windows; it never writes qpos,
ctrl, timestamps or native outputs. Pose samples are audit-only after the run.
"""
from __future__ import annotations
import math
from rm_match.platform_v2.control import Rejected


def target_velocity(value):
    if type(value) not in (int,float) or not .03<=abs(value)<=.15 or not math.isfinite(value):
        raise ValueError('moving target velocity must be finite with magnitude 0.03..0.15 m/s')
    return float(value)


class ScriptedTargetMotion:
    def __init__(self,control,backend,robot_id,vy_mps):
        self.vy_mps=target_velocity(vy_mps)
        if robot_id not in backend.robot_ids or robot_id not in control.robot_ids:
            raise ValueError('moving target must be a declared scene robot')
        self.control=control;self.backend=backend;self.robot_id=robot_id
        self.command=dict(frame='base_link',vx_mps=0.,vy_mps=self.vy_mps,wz_rps=0.)
        self._token=None;self._sid=None;self._epochs=None;self._episode=None;self._seq=-1
        self._last_pulse=None;self._last_renew=None;self.samples=[];self.dropped_samples=0
        self.windows={}
        self.bad_consumptions=0;self.active_consumptions=0;self.closed=False

    def before_step(self):
        if self.closed or self.control.stopped:return
        now=self.control.clock();episode=self.backend.episode
        if self._token is None:
            session=self.control.open_session('operator','server_window_v1',
                allowed_robots=(self.robot_id,),audit_authorized=False,trusted_admin=True)
            self._token=session['token'];self._sid=session['session_id'];self._episode=episode
            self._epochs=self.control.claim(self._token,self.robot_id,['motion'])['lease_epochs']
            self._last_renew=now
        if episode!=self._episode:raise ValueError('moving target fixture cannot cross an episode reset')
        try:
            if now-self._last_renew>=.25:
                self.control.renew(self._token,self.robot_id,self._epochs);self._last_renew=now
            if self._last_pulse is None or now-self._last_pulse>=.04:
                window=self.control.control_window(self._token,self.robot_id,self._epochs)
                self._seq+=1
                ack=self.control.control(self._token,self.robot_id,'motion',self._epochs['motion'],self._seq,
                    dict(self.command),.15,window['window_id'])
                self.windows[window['window_id']]=dict(issued_wall=window['issued_wall'],expires_wall=window['expires_wall'],
                    input_expires=ack['input_expires'],seq=self._seq,epoch=self._epochs['motion'])
                self._last_pulse=now
        except Rejected as exc:
            # Stop racing the first API may occur at the normal teardown edge.
            # Other failures, including lost epochs, never auto-claim or retry.
            if exc.reason=='runtime_stopped' and self.control.stopped:return
            raise
        pose=self.backend.own_pose(self.robot_id);sim=self.backend._sim
        xy=sim.data.xpos[sim.body_ids[self.robot_id]][:2]
        sample=dict(episode=episode,sim_time=self.backend.sim_time,wall_time=self.control.clock(),
            xy_m=[float(v) for v in xy],speed_mps=math.hypot(pose['vx'],pose['vy']),
            consumed=False,original_manual_authorized=False)
        if len(self.samples)<12000:self.samples.append(sample)
        else:self.dropped_samples+=1

    def consumed(self,row):
        if (row.get('event')!='actuator_consumed' or row.get('robot_id')!=self.robot_id
            or row.get('phase')!='integration_entry'):return
        if not self.samples or row['consume_sim_time']!=self.samples[-1]['sim_time']:
            self.bad_consumptions+=1;return
        sample=self.samples[-1];sample['consumed']=True
        target=row['target'];motion=target['motion']
        if motion is None:return
        lease=row['manual_inputs']['motion'];now=row['consume_wall']
        window=self.windows.get(lease['input_window_id'])
        valid=(motion==self.command and target['fire'] is False and target['gimbal'] is None
            and row['episode']==sample['episode'] and window is not None
            and lease['owner']==self._sid and lease['epoch']==self._epochs['motion']
            and lease['seq']==self._seq==window['seq'] and lease['epoch']==window['epoch']
            and lease['input_expires']==window['input_expires']
            and lease['input_window_deadline']==window['expires_wall']
            and window['expires_wall']<=window['issued_wall']+.15
            and window['issued_wall']<=now<min(lease['expires'],lease['input_expires'],lease['input_window_deadline']))
        sample['original_manual_authorized']=valid
        sample['manual_receipt']={k:lease[k] for k in ('epoch','seq','expires','input_expires','input_window_id','input_window_deadline')}
        sample['consume_wall']=now
        if valid:self.active_consumptions+=1
        else:self.bad_consumptions+=1

    def close(self):
        if self.closed:return
        if self._token is not None:self.control.close_session(self._token)
        self._token=None;self.closed=True

    def report(self,raw_frames,consumed_frames):
        """Exact original capture sim-time join; truth stays in this audit plane."""
        by_time={sample['sim_time']:sample for sample in self.samples}
        moving=[]
        for fid,raw in raw_frames.items():
            sample=by_time.get(raw['capture_sim_time']);receipt=consumed_frames.get(fid)
            if (sample is not None and sample['consumed'] and sample['original_manual_authorized']
                and sample['speed_mps']>=.02 and receipt is not None
                and receipt.get('episode')==sample['episode']
                and receipt.get('budget',{}).get('episode')==sample['episode']
                and receipt.get('budget',{}).get('frame_id')==fid
                and receipt['budget']['capture_sim_time']==raw['capture_sim_time']):moving.append(fid)
        displacement=math.dist(self.samples[0]['xy_m'],self.samples[-1]['xy_m']) if self.samples else 0.
        complete=(len(by_time)==len(self.samples) and bool(self.samples) and not self.dropped_samples
            and self.bad_consumptions==0 and self.closed)
        proven=complete and displacement>=.15 and self.active_consumptions>=100 and len(moving)>=10
        return dict(robot_id=self.robot_id,vy_mps=self.vy_mps,sample_count=len(self.samples),
            dropped_samples=self.dropped_samples,bad_consumptions=self.bad_consumptions,
            active_consumptions=self.active_consumptions,displacement_m=displacement,
            original_window_count=len(self.windows),
            distinct_moving_actuated_frames=len(moving),moving_actuated_frame_ids=moving,
            original_manual_authority_and_motion_proven=bool(proven),closed=self.closed,
            native_target_association_verified=False,moving_target_tracking_qualified=False,
            scope='Scripted manual target motion and audit only; temporal overlap does not identify the native tracked target; no target-tracking, navigation/decision, accuracy, shooting or moving-shooter qualification')
