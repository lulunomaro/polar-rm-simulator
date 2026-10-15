"""Source-bound asynchronous goals. No sensor feedback or actuator authority.

A lifecycle receipt retains the original goal intent even when a later scan
renews authorization. Backend operations never block; their executor belongs
to the caller. Opaque foreign deadlines are not compared with the local clock.
"""
from __future__ import annotations
import copy
import math
import re
import secrets
import time
from ..platform_v2.contracts import ContractError, IDENTITY, exact, identity
from ..platform_v2.decision_contracts import validate_decision_intent_shape

SCHEMA='polar.sim.navigation-goal-lifecycle.v1'
BACKEND_SCHEMA='polar.sim.navigation-goal-backend-status.v1'
TERMINAL={'succeeded','canceled','stopped','rejected','aborted'}
STATES=TERMINAL|{'sending','active','canceling','fault'}

def source(value):return {key:copy.deepcopy(value[key]) for key in IDENTITY}
def same_source(a,b):return all(type(a[k]) is type(b[k]) and a[k]==b[k] for k in IDENTITY)


class NavigationGoalLifecycle:
    def __init__(self,backend,*,clock=time.perf_counter,deadline_mode='host',
                 send_timeout_s=1.,cancel_timeout_s=1.3,history_capacity=64,token_factory=None):
        if deadline_mode not in ('host','opaque'):raise ValueError('goal_deadline_mode')
        for value,cap in ((send_timeout_s,1.),(cancel_timeout_s,1.3)):
            if type(value) not in (float,int) or not math.isfinite(value) or not 0<value<=cap:raise ValueError('goal_resource_budget')
        if type(history_capacity) is not int or not 1<=history_capacity<=256:raise ValueError('goal_history_capacity')
        self.backend=backend;self.clock=clock;self.deadline_mode=deadline_mode
        self.send_timeout_s=send_timeout_s;self.cancel_timeout_s=cancel_timeout_s;self.history_capacity=history_capacity
        self.token_factory=token_factory or (lambda:secrets.token_hex(16))
        self.context=None;self.records=[];self.operations={};self.current=None;self.pending=None
        self.latest=None;self.last_seq=-1;self.fault=None;self.stopped=False;self.sticky_target=None
        self.sent_at={};self.cancel_at={}

    def _now(self):
        value=self.clock()
        if type(value) not in (float,int) or not math.isfinite(value):raise ContractError('goal_local_clock')
        return value

    def reset(self,context):
        if self.context is not None or self.stopped:raise ContractError('goal_reset_once')
        exact(context,('robot_id','episode','binding_epoch'),'goal_context')
        identity(dict(context,observed_seq=0,sim_time=0.,wall_deadline=0.))
        self.context=copy.deepcopy(context);return self.snapshot()

    def _expire(self,intent):
        return self.deadline_mode=='host' and self._now()>=intent['wall_deadline']

    def _cancel(self,record,reason,intent=None):
        if record['terminal'] and record['stop_confirmed']:return
        if record['cancel_requested']:return
        record['cancel_requested']=True;record['stop_reason']=reason
        record['stop_intent']=copy.deepcopy(intent);self.cancel_at[record['operation_id']]=self._now()
        try:self.backend.cancel(self.operations[record['operation_id']])
        except BaseException:self.fault=self.fault or 'backend_cancel_failed'

    def _fault(self,code):
        self.fault=self.fault or code;self.pending=None;self.sticky_target=None
        if self.current is not None:self._cancel(self.current,'fault')

    def submit(self,intent,*,expected_source=None):
        if self.context is None or self.stopped or self.fault:raise ContractError('goal_lifecycle_unavailable')
        checked=validate_decision_intent_shape(intent);original=source(checked)
        if any(type(original[k]) is not type(v) or original[k]!=v for k,v in self.context.items()):raise ContractError('goal_context_mismatch')
        if expected_source is not None:
            identity(expected_source)
            if not same_source(original,expected_source):raise ContractError('goal_expected_source_mismatch')
        if checked['observed_seq']<=self.last_seq:raise ContractError('goal_intent_replayed')
        if self._expire(checked):raise ContractError('goal_original_intent_expired')
        self.last_seq=checked['observed_seq'];self.latest=original
        behavior=checked['command']['behavior']
        if behavior in ('hold','cancel'):
            self.pending=None;self.sticky_target=None
            if self.current is not None:self._cancel(self.current,behavior,checked)
        else:
            goal=checked['command']['goal']
            if self.current is not None and self.current['goal']==goal and not self.current['cancel_requested']:
                self.current['latest_authorization']=original
            elif self.current is None and self.sticky_target==goal:
                # Historical terminal remains tied to its own original intent.
                if self.records:self.records[-1]['latest_authorization']=original
            else:
                self.pending=checked
                if self.current is not None:self._cancel(self.current,'replaced',checked)
        return self.poll()

    def _start_pending(self):
        if self.pending is None or self.current is not None or self.stopped or self.fault:return
        intent=self.pending
        if self._expire(intent):self.pending=None;return
        if len(self.records)>=self.history_capacity:self._fault('goal_history_capacity_exhausted');return
        token=self.token_factory()
        if type(token) is not str or not re.fullmatch('[0-9a-f]{32}',token) or token in self.operations:
            self._fault('goal_operation_identity_invalid');return
        goal=copy.deepcopy(intent['command']['goal']);original=source(intent)
        record=dict(operation_id=token,origin_intent=copy.deepcopy(intent),latest_authorization=original,
            goal=goal,state='sending',goal_uuids=dict(planner=None,navigation=None),
            cancel_requested=False,cancel_acknowledged=False,terminal=False,stop_confirmed=False,error_code=None,
            stop_intent=None,stop_reason=None)
        self.pending=None;self.records.append(record);self.current=record;self.sticky_target=copy.deepcopy(goal)
        self.sent_at[token]=self._now()
        try:self.operations[token]=self.backend.start(copy.deepcopy(goal),copy.deepcopy(original),operation_id=token)
        except BaseException:
            # Start may be uncertain; do not manufacture a rejected goal proof.
            record['state']='fault';record['error_code']='backend_start_failed';self.fault='backend_start_failed'

    def _checked_backend(self,value,record):
        exact(value,('schema','operation_id','source','state','goal_uuids','terminal','cancel_acknowledged','stop_confirmed','error_code'),'goal_backend_status')
        if (type(value['schema']) is not str or type(value['operation_id']) is not str
            or value['schema']!=BACKEND_SCHEMA or value['operation_id']!=record['operation_id']):raise ContractError('goal_backend_operation_mismatch')
        exact(value['source'],IDENTITY,'goal_backend_source');identity(value['source'])
        if not same_source(value['source'],source(record['origin_intent'])):raise ContractError('goal_backend_source_mismatch')
        if type(value['state']) is not str or value['state'] not in STATES:raise ContractError('goal_backend_state')
        for k in ('terminal','cancel_acknowledged','stop_confirmed'):
            if type(value[k]) is not bool:raise ContractError('goal_backend_boolean')
        exact(value['goal_uuids'],('planner','navigation'),'goal_backend_uuids')
        for k,uuid in value['goal_uuids'].items():
            if uuid is not None and (type(uuid) is not str or not re.fullmatch('[0-9a-f]{32}',uuid)):raise ContractError('goal_backend_uuid')
            prior=record['goal_uuids'][k]
            if prior is not None and uuid!=prior:raise ContractError('goal_backend_uuid_changed')
        if value['state']=='fault':
            if value['terminal'] and not value['stop_confirmed']:raise ContractError('goal_backend_fault_stop_unproved')
        elif value['terminal'] != (value['state'] in TERMINAL):raise ContractError('goal_backend_terminal_unproved')
        if record['terminal'] and (not value['terminal'] or value['state']!=record['state']):raise ContractError('goal_backend_terminal_reversed')
        if record['stop_confirmed'] and not value['stop_confirmed']:raise ContractError('goal_backend_stop_reversed')
        if value['stop_confirmed'] and not value['terminal']:raise ContractError('goal_backend_stop_not_terminal')
        if value['state']=='succeeded' and value['goal_uuids']['navigation'] is None:raise ContractError('goal_backend_success_without_navigation')
        if value['cancel_acknowledged'] and (not record['cancel_requested'] or not any(value['goal_uuids'].values())):raise ContractError('goal_backend_cancel_ack_unrequested')
        if value['state']=='canceled' and not (record['cancel_requested'] and value['cancel_acknowledged'] and value['stop_confirmed']):raise ContractError('goal_backend_cancel_not_confirmed')
        if value['state']=='stopped' and not (record['cancel_requested'] and value['stop_confirmed']):raise ContractError('goal_backend_stop_unrequested')
        error=value['error_code']
        if error is not None and (type(error) is not str or not re.fullmatch('[a-z][a-z0-9_]{0,63}',error)):raise ContractError('goal_backend_error_code')
        if record['cancel_acknowledged'] and not value['cancel_acknowledged']:raise ContractError('goal_backend_cancel_ack_reversed')
        return copy.deepcopy(value)

    def poll(self):
        if self.context is None:raise ContractError('goal_context_required')
        record=self.current
        if record is not None and record['operation_id'] in self.operations:
            if self.deadline_mode=='host' and self._now()>=record['latest_authorization']['wall_deadline']:
                self.sticky_target=None;self._cancel(record,'authorization_expired')
            try:
                value=self._checked_backend(self.backend.poll(self.operations[record['operation_id']]),record)
                for k in ('state','goal_uuids','terminal','cancel_acknowledged','stop_confirmed','error_code'):record[k]=value[k]
            except BaseException:self._fault('backend_status_invalid')
            if record['state']=='fault':self._fault('backend_fault')
            now=self._now();token=record['operation_id']
            if record['state']=='sending' and now-self.sent_at[token]>=self.send_timeout_s:self._fault('goal_send_timeout')
            if record['cancel_requested'] and not (record['terminal'] and record['stop_confirmed']) and now-self.cancel_at[token]>=self.cancel_timeout_s:
                self._fault('goal_cancel_timeout')
            if record['terminal'] and record['stop_confirmed']:self.current=None
        if self.pending is not None and self._expire(self.pending):self.pending=None
        self._start_pending()
        return self.snapshot()

    def request_stop(self):
        self.stopped=True;self.pending=None;self.sticky_target=None
        if self.current is not None and self.current['operation_id'] in self.operations:self._cancel(self.current,'shutdown')
        return self.snapshot()

    def snapshot(self):
        state='fault' if self.fault else ('stopped' if self.stopped and self.current is None else
            ('pending' if self.pending is not None and self.current is None else
             ('idle' if self.current is None else ('canceling' if self.current['cancel_requested'] else self.current['state']))))
        clean=self.current is None and self.pending is None and self.fault is None
        return copy.deepcopy(dict(schema=SCHEMA,current_source=self.latest,state=state,
            active=None if self.current is None else self.current['operation_id'],pending_intent=self.pending,
            fault=self.fault,stop_requested=self.stopped,clean=clean,goals=self.records,
            deadline_mode=self.deadline_mode,actuator_authority='none',localization_feedback='unavailable'))
