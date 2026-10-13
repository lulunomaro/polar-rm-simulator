"""Thread-safe capability/lease state. No simulation object or physics access here."""
from __future__ import annotations
from dataclasses import dataclass, field
import copy
import math
import secrets
import threading
import time

CHANNELS = ('motion', 'gimbal', 'fire')
KINDS = {'navigation': ('motion',), 'aim': ('gimbal',)}

class Rejected(ValueError):
    def __init__(self, reason, status=409):
        super().__init__(reason)
        self.reason, self.status = reason, status

def finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Rejected('invalid_' + name, 400)
    try:value=float(value)
    except (ValueError,OverflowError):raise Rejected('invalid_' + name, 400) from None
    if not math.isfinite(value):raise Rejected('invalid_' + name, 400)
    return value

def integer(value, name):
    if type(value) is not int or not 0<=value<=2**53-1:
        raise Rejected('invalid_' + name, 400)
    return value

def exact(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise Rejected('invalid_fields', 400)

def duration(value, maximum):
    value = finite(value, 'valid_for_s')
    if not 0 < value <= maximum:
        raise Rejected('invalid_valid_for_s', 400)
    return value

@dataclass
class Session:
    sid: str
    token: str
    role: str
    expires: float
    watch_robot_id: str | None = None
    watch_epoch: int = 0
    control_profile: str = 'legacy_v2'
    windows: dict = field(default_factory=dict)
    next_window_id: int = 0
    allowed_robots: tuple | None = None
    audit_authorized: bool = False
    trusted_admin: bool = True

@dataclass
class Lease:
    epoch: int = 0
    owner: str | None = None
    expires: float = 0.
    seq: int = -1
    input: dict | None = None
    input_expires: float = 0.
    input_window_id: int | None = None
    input_window_deadline: float | None = None
    mode_signature: tuple | None = None
    mode_fault: bool = False

@dataclass
class Binding:
    epoch: int = 0
    owner: str | None = None
    adapter_id: str | None = None
    config: dict = field(default_factory=dict)
    lease_epochs: dict = field(default_factory=dict)
    activation_required: bool = False
    activation_seq: int = -1
    activation_expires: float = 0.
    activation_window_id: int | None = None
    activation_window_deadline: float | None = None

class ControlPlane:
    """A bounded session registry and separate leases per robot and actuator channel.

    Lease renewal never resurrects an expired lease. Reclaim requires a new epoch.
    Endpoints are atomic under lock; expiry/rebind removes previous inputs before
    the next authority tick. Network threads never inspect the backend.
    """
    def __init__(self, robot_ids, *, clock=time.perf_counter, max_sessions=32,
                 session_ttl=60., lease_ttl=1., command_ttl=.25, spin_capabilities=None):
        ids = tuple(robot_ids)
        if not ids or len(set(ids)) != len(ids) or any(not isinstance(r, str) or not r or len(r)>128 for r in ids):
            raise ValueError('Robot registry must contain unique nonempty IDs')
        from .spin import validate_capabilities
        self._spin_capabilities=validate_capabilities(spin_capabilities or {},ids)
        self.robot_ids = ids
        self.clock, self.max_sessions = clock, max_sessions
        self.session_ttl, self.lease_ttl, self.command_ttl = session_ttl, lease_ttl, command_ttl
        self.lock = threading.RLock()
        self.sessions = {}
        self.leases = {(r,c): Lease() for r in ids for c in CHANNELS}
        self.bindings = {(r,k): Binding() for r in ids for k in KINDS}
        self.control_window_ttl=.15
        self.stopped = False
        self.revision = 0

    def _robot(self, rid):
        if not isinstance(rid,str) or rid not in self.robot_ids:
            raise Rejected('unknown_robot',404)

    def _channels(self, channels):
        if not isinstance(channels,list) or not channels or len(channels)>3 or any(not isinstance(c,str) or c not in CHANNELS for c in channels) or len(set(channels))!=len(channels):
            raise Rejected('invalid_channels',400)
        return channels

    def _invalidate_windows(self,rid):
        # Binding changes also revoke windows: lease epochs alone are insufficient.
        for session in self.sessions.values():
            window=session.windows.pop(rid,None)
            if window is not None:
                for channel in CHANNELS:
                    lease=self.leases[rid,channel]
                    if lease.owner==session.sid and lease.input_window_id is not None:
                        lease.input=None;lease.input_expires=0.
                        lease.input_window_id=None;lease.input_window_deadline=None

    def _clear_binding(self,rid,kind):
        self._invalidate_windows(rid)
        b=self.bindings[rid,kind]
        b.epoch += 1; b.owner=None; b.adapter_id=None; b.config={}; b.lease_epochs={}
        b.activation_required=False;b.activation_seq=-1;b.activation_expires=0.;b.activation_window_id=None;b.activation_window_deadline=None
        for c in KINDS[kind]:
            lease=self.leases[rid,c]
            lease.input=None; lease.input_expires=0.
        self.revision += 1

    def _clear_lease(self,rid,channel):
        self._invalidate_windows(rid)
        lease=self.leases[rid,channel]
        lease.epoch+=1; lease.owner=None; lease.expires=0.; lease.input=None; lease.input_expires=0.; lease.seq=-1;lease.input_window_id=None;lease.input_window_deadline=None
        lease.mode_signature=None;lease.mode_fault=False
        for kind,channels in KINDS.items():
            if channel in channels and self.bindings[rid,kind].owner is not None:
                self._clear_binding(rid,kind)
        self.revision += 1

    def _expire(self):
        now=self.clock()
        expired={sid for sid,s in self.sessions.items() if now>=s.expires}
        for (rid,c), lease in self.leases.items():
            if lease.owner is not None and (lease.owner in expired or now>=lease.expires):
                self._clear_lease(rid,c)
        # Expiry is sticky: no same-epoch pulse can resurrect a used binding.
        for (rid,kind),b in self.bindings.items():
            if b.owner is not None and b.activation_required and b.activation_seq>=0 and now>=b.activation_expires:
                self._clear_binding(rid,kind)
        for sid in expired:del self.sessions[sid]

    def _session(self,token,operator=False):
        self._expire()
        if not isinstance(token,str):raise Rejected('invalid_session',401)
        s=next((s for s in self.sessions.values() if secrets.compare_digest(s.token,token)),None)
        if s is None:raise Rejected('invalid_session',401)
        if self.stopped and operator:raise Rejected('runtime_stopped')
        if operator and s.role!='operator':raise Rejected('read_only_session',403)
        return s

    def open_session(self,role,control_profile='legacy_v2',*,allowed_robots=None,audit_authorized=None,trusted_admin=True):
        """Direct calls are trusted local admin; HTTP supplies a reviewed grant.

        Neither trusted_admin nor permission fields are network-request keys.
        """
        with self.lock:
            self._expire()
            if not isinstance(role,str) or role not in ('operator','spectator'):raise Rejected('invalid_role',400)
            if type(control_profile) is not str or control_profile not in ('legacy_v2','server_window_v1'):raise Rejected('invalid_control_profile',400)
            if self.stopped:raise Rejected('runtime_stopped')
            if len(self.sessions)>=self.max_sessions:raise Rejected('session_capacity',429)
            if type(trusted_admin) is not bool:raise Rejected('invalid_trusted_admin',400)
            if allowed_robots is not None:
                if type(allowed_robots) not in (list,tuple) or len(set(allowed_robots))!=len(allowed_robots):raise Rejected('invalid_robot_scope',400)
                for rid in allowed_robots:self._robot(rid)
                allowed_robots=tuple(allowed_robots)
            if not trusted_admin and role=='operator' and not allowed_robots:raise Rejected('operator_scope_required',403)
            audit=trusted_admin if audit_authorized is None else audit_authorized
            if type(audit) is not bool or (role=='spectator' and not audit):raise Rejected('audit_authorization_required',403)
            s=Session(secrets.token_hex(12),secrets.token_urlsafe(32),role,self.clock()+self.session_ttl)
            s.allowed_robots=allowed_robots;s.audit_authorized=audit;s.trusted_admin=trusted_admin
            s.control_profile=control_profile;self.sessions[s.sid]=s
            return dict(session_id=s.sid,token=s.token,role=role,session_expires=s.expires,server_monotonic_s=self.clock(),control_profile=control_profile,control_window_version=1,control_window_ttl_s=self.control_window_ttl,
                        allowed_robots=list(self.robot_ids if s.allowed_robots is None else s.allowed_robots),audit_authorized=s.audit_authorized)

    def authorize_robot(self,session,rid):
        self._robot(rid)
        if session.allowed_robots is not None and rid not in session.allowed_robots:
            raise Rejected('robot_scope_forbidden',403)

    def visible_robot_ids(self,token):
        with self.lock:
            session=self._session(token)
            return [r for r in self.robot_ids if session.allowed_robots is None or r in session.allowed_robots]

    def keepalive(self,token):
        with self.lock:
            s=self._session(token);s.expires=self.clock()+self.session_ttl
            return dict(session_id=s.sid,session_expires=s.expires)

    def close_session(self,token):
        with self.lock:
            s=self._session(token)
            for (r,c),lease in self.leases.items():
                if lease.owner==s.sid:self._clear_lease(r,c)
            del self.sessions[s.sid]
            return {'closed':True}

    def watch(self,token,rid):
        """Read subscription only; never claim or renew an actuator lease."""
        with self.lock:
            s=self._session(token)
            if self.stopped:raise Rejected('runtime_stopped')
            if rid is not None:self.authorize_robot(s,rid)
            s.watch_epoch+=1;s.watch_robot_id=rid
            return dict(robot_id=rid,watch_epoch=s.watch_epoch)

    def watch_sample(self,token):
        with self.lock:
            s=self._session(token)
            return dict(session_id=s.sid,robot_id=s.watch_robot_id,watch_epoch=s.watch_epoch)

    def watches(self):
        with self.lock:
            self._expire()
            return [dict(session_id=s.sid,robot_id=s.watch_robot_id,watch_epoch=s.watch_epoch)
                    for s in self.sessions.values() if s.watch_robot_id is not None]

    def _owned(self,s,rid,epochs):
        self.authorize_robot(s,rid)
        if not isinstance(epochs,dict):raise Rejected('invalid_lease_epochs',400)
        self._channels(list(epochs))
        for c,epoch in epochs.items():
            integer(epoch,'lease_epoch');l=self.leases[rid,c]
            if l.owner!=s.sid or l.epoch!=epoch:raise Rejected('lease_mismatch')

    def claim(self,token,rid,channels):
        with self.lock:
            s=self._session(token,True);self.authorize_robot(s,rid);self._channels(channels)
            if any(self.leases[rid,c].owner is not None for c in channels):raise Rejected('lease_occupied')
            for c in channels:
                l=self.leases[rid,c];l.epoch+=1;l.owner=s.sid;l.expires=self.clock()+self.lease_ttl;l.seq=-1;l.input=None
            self.revision+=1
            return self._lease_reply(rid,channels)

    def _lease_reply(self,rid,channels):
        return dict(robot_id=rid,lease_epochs={c:self.leases[rid,c].epoch for c in channels},
                    lease_expires={c:self.leases[rid,c].expires for c in channels})

    def renew(self,token,rid,epochs):
        with self.lock:
            s=self._session(token,True);self._owned(s,rid,epochs)
            for c in epochs:self.leases[rid,c].expires=self.clock()+self.lease_ttl
            return self._lease_reply(rid,list(epochs))

    def release(self,token,rid,epochs):
        with self.lock:
            s=self._session(token,True);self._owned(s,rid,epochs)
            for c in epochs:self._clear_lease(rid,c)
            return {'released':True}

    def bind(self,token,rid,kind,epochs,adapter_id,config):
        with self.lock:
            s=self._session(token,True)
            if not isinstance(kind,str) or kind not in KINDS:raise Rejected('invalid_kind',400)
            if not isinstance(epochs,dict) or set(epochs)!=set(KINDS[kind]):raise Rejected('binding_requires_channels',400)
            self._owned(s,rid,epochs)
            if not isinstance(adapter_id,str) or not adapter_id or not isinstance(config,dict):raise Rejected('invalid_binding',400)
            if kind=='navigation' and self.leases[rid,'motion'].mode_fault:raise Rejected('mode_change_requires_release')
            self._clear_binding(rid,kind)
            b=self.bindings[rid,kind]
            b.owner=s.sid;b.adapter_id=adapter_id;b.config=copy.deepcopy(config);b.lease_epochs=dict(epochs)
            b.activation_required=s.control_profile=='server_window_v1'
            return dict(robot_id=rid,kind=kind,binding_epoch=b.epoch,adapter_id=adapter_id,
                        activation_required=b.activation_required,activation_version=1)

    def unbind(self,token,rid,kind,epochs):
        with self.lock:
            s=self._session(token,True)
            if not isinstance(kind,str) or kind not in KINDS:raise Rejected('invalid_kind',400)
            if not isinstance(epochs,dict) or set(epochs)!=set(KINDS[kind]):raise Rejected('binding_requires_channels',400)
            self._owned(s,rid,epochs);self._clear_binding(rid,kind)
            return dict(unbound=True,binding_epoch=self.bindings[rid,kind].epoch)

    def adapter_input(self,token,rid,kind,epochs,binding_epoch,seq,window_id,valid_for_s):
        """Continued operator authorization, never an algorithm action/fire permit."""
        with self.lock:
            s=self._session(token,True)
            self.authorize_robot(s,rid)
            if s.control_profile!='server_window_v1':raise Rejected('adapter_window_profile_required')
            if type(kind) is not str or kind not in KINDS:raise Rejected('invalid_kind',400)
            if type(epochs) is not dict or set(epochs)!=set(KINDS[kind]):raise Rejected('binding_requires_channels',400)
            self._owned(s,rid,epochs)
            integer(binding_epoch,'binding_epoch');integer(seq,'seq');integer(window_id,'window_id')
            ttl=duration(valid_for_s,self.control_window_ttl)
            # Parse may consume time. Expire before touching the sequence watermark.
            s=self._session(token,True);self._owned(s,rid,epochs);b=self.bindings[rid,kind]
            if b.owner!=s.sid or b.epoch!=binding_epoch or b.lease_epochs!=epochs:raise Rejected('binding_mismatch')
            if seq<=b.activation_seq:raise Rejected('stale_adapter_seq')
            window=s.windows.get(rid);now=self.clock()
            if window is None or window_id!=window['window_id']:raise Rejected('stale_control_window')
            self._owned(s,rid,window['lease_epochs'])
            if any(window['lease_epochs'].get(c)!=e for c,e in epochs.items()):raise Rejected('control_window_lease_mismatch')
            if now>=window['expires_wall']:raise Rejected('expired_control_window')
            if b.activation_seq>=0 and now>=b.activation_expires:
                self._clear_binding(rid,kind);raise Rejected('adapter_activation_expired')
            deadline=min(now+ttl,window['expires_wall'])
            if b.activation_window_id==window_id:deadline=min(deadline,b.activation_expires)
            b.activation_seq=seq;b.activation_expires=deadline;b.activation_window_id=window_id
            b.activation_window_deadline=window['expires_wall'];self.revision+=1
            return dict(accepted=True,robot_id=rid,kind=kind,binding_epoch=b.epoch,seq=seq,
                        window_id=window_id,activation_expires=deadline)

    def control_window(self,token,rid,epochs):
        with self.lock:
            s=self._session(token,True);self._owned(s,rid,epochs)
            if s.control_profile!='server_window_v1':raise Rejected('control_window_profile_required')
            if s.next_window_id>=2**53-1:raise Rejected('control_window_sequence_exhausted')
            s.next_window_id+=1;now=self.clock()
            window=dict(robot_id=rid,session_id=s.sid,lease_epochs=dict(epochs),window_id=s.next_window_id,issued_wall=now,expires_wall=now+self.control_window_ttl,valid_for_s=self.control_window_ttl)
            s.windows[rid]=window
            return copy.deepcopy(window)

    def control(self,token,rid,channel,epoch,seq,value,valid_for_s,window_id=None):
        with self.lock:
            s=self._session(token,True);self._owned(s,rid,{channel:epoch})
            integer(seq,'seq');ttl=duration(valid_for_s,self.command_ttl)
            l=self.leases[rid,channel]
            if seq<=l.seq:raise Rejected('stale_seq')
            kind='navigation' if channel=='motion' else 'aim'
            if self.bindings[rid,kind].owner is not None and channel!='fire':raise Rejected('channel_bound_to_adapter')
            if channel=='motion' and isinstance(value,dict) and value.get('mode')=='spin_v1':
                from .spin import parse_spin
                if s.control_profile!='server_window_v1':raise Rejected('spin_requires_strict_profile')
                value=parse_spin(value,self._spin_capabilities.get(rid))
            elif channel=='motion':
                exact(value,('vx_mps','vy_mps','wz_rps','frame'))
                if value['frame']!='base_link':raise Rejected('invalid_motion_frame',400)
                value=dict(value)
                for k,limit in [('vx_mps',3.),('vy_mps',3.),('wz_rps',4.)]:
                    value[k]=finite(value[k],k)
                    if abs(value[k])>limit:raise Rejected('motion_limit',400)
            elif channel=='gimbal':
                exact(value,('yaw_rad','pitch_rad','frame'))
                if value['frame']!='base_link':raise Rejected('invalid_gimbal_frame',400)
                value=dict(value)
                for k,lo,hi in [('yaw_rad',-3.14,3.14),('pitch_rad',-.4,.5)]:
                    value[k]=finite(value[k],k)
                    if not lo<=value[k]<=hi:raise Rejected('gimbal_limit',400)
            else:
                exact(value,('fire',))
                if type(value['fire']) is not bool:raise Rejected('invalid_fire',400)
            # Admission samples the server clock again after decoding/validation.
            s=self._session(token,True);self._owned(s,rid,{channel:epoch});now=self.clock()
            window=None
            if s.control_profile=='server_window_v1':
                integer(window_id,'window_id');window=s.windows.get(rid)
                if window is None or window_id!=window['window_id']:raise Rejected('stale_control_window')
                self._owned(s,rid,window['lease_epochs'])
                if window['lease_epochs'].get(channel)!=epoch:raise Rejected('control_window_lease_mismatch')
                if now>=window['expires_wall']:raise Rejected('expired_control_window')
            elif window_id is not None:raise Rejected('unexpected_control_window',400)
            if channel=='motion' and s.control_profile=='server_window_v1':
                from .spin import motion_signature
                signature=motion_signature(value)
                if l.mode_fault:raise Rejected('mode_change_requires_release')
                if l.mode_signature is not None and signature!=l.mode_signature:
                    l.mode_fault=True;l.input=None;l.input_expires=0.;self.revision+=1
                    raise Rejected('mode_change_requires_release')
                l.mode_signature=signature
            l.seq=seq;l.input=copy.deepcopy(value);l.input_expires=min(now+ttl,window['expires_wall']) if window else now+ttl
            l.input_window_id=window_id;l.input_window_deadline=window['expires_wall'] if window else None;self.revision+=1
            ack=dict(accepted=True,robot_id=rid,channel=channel,lease_epoch=epoch,seq=seq)
            if window:ack.update(window_id=window_id,input_expires=l.input_expires)
            return ack

    def snapshot(self,token=None):
        with self.lock:
            if token is not None:self._session(token)
            else:self._expire()
            now=self.clock()
            return dict(robot_ids=list(self.robot_ids),stopped=self.stopped,server_monotonic_s=now,revision=self.revision,
                leases={r:{c:dict(epoch=self.leases[r,c].epoch,owner=self.leases[r,c].owner,
                    expires=self.leases[r,c].expires,seq=self.leases[r,c].seq,
                    input=copy.deepcopy(self.leases[r,c].input) if now<self.leases[r,c].input_expires else None,
                    mode_signature=self.leases[r,c].mode_signature,mode_fault=self.leases[r,c].mode_fault,
                    input_expires=self.leases[r,c].input_expires,input_window_id=self.leases[r,c].input_window_id,input_window_deadline=self.leases[r,c].input_window_deadline) for c in CHANNELS} for r in self.robot_ids},
                bindings={r:{k:copy.deepcopy(vars(self.bindings[r,k])) for k in KINDS} for r in self.robot_ids})

    def snapshot_robot(self,rid):
        """Trusted authority snapshot with the same fields, copied for one robot.

        Expiry remains global and runs under the same lock as public snapshot:
        session/lease revocation, epochs and original command windows retain their
        semantics. This is an internal allocation optimization, not an endpoint
        or a fresh command authorization. Returned nested mutable values are
        detached from the live control state.
        """
        with self.lock:
            self._expire();self._robot(rid)
            now=self.clock()
            return dict(robot_ids=[rid],stopped=self.stopped,server_monotonic_s=now,revision=self.revision,
                leases={rid:{c:dict(epoch=self.leases[rid,c].epoch,owner=self.leases[rid,c].owner,
                    expires=self.leases[rid,c].expires,seq=self.leases[rid,c].seq,
                    input=copy.deepcopy(self.leases[rid,c].input) if now<self.leases[rid,c].input_expires else None,
                    mode_signature=self.leases[rid,c].mode_signature,mode_fault=self.leases[rid,c].mode_fault,
                    input_expires=self.leases[rid,c].input_expires,input_window_id=self.leases[rid,c].input_window_id,
                    input_window_deadline=self.leases[rid,c].input_window_deadline) for c in CHANNELS}},
                bindings={rid:{k:copy.deepcopy(vars(self.bindings[rid,k])) for k in KINDS}})

    def reset_episode(self):
        """Trusted authority only: retain sessions, revoke every actuator lease."""
        with self.lock:
            for r,c in self.leases:self._clear_lease(r,c)
            # Subscriptions retain their identity; old episode captures still fail.

    def stop(self):
        with self.lock:
            for r,c in self.leases:
                if self.leases[r,c].owner is not None:self._clear_lease(r,c)
            self.stopped=True
