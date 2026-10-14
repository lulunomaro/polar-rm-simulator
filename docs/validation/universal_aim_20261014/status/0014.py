"""Synthetic aim-status identity, worker, authority and cleanup tests; no NN."""
import copy
import time
import unittest
from rm_match.platform_v2.aim_contracts import (AIM_PLUGIN_CONTRACT, AIM_STATUS_SCHEMA,
    aim_status_for, validate_aim_status)
from rm_match.platform_v2.adapters import BaseAdapter, Registry, descriptor
from rm_match.platform_v2.contracts import IDENTITY, ContractError, action_for
from rm_match.platform_v2.runtime import AdapterSlot, PlatformRuntime
from rm_match.platform_v2.state_projection import project_state
from rm_match.platform_v2.test_contracts import sample
from rm_match.platform_v2.test_control import Clock
from rm_match.platform_v2.test_runtime import FakeBackend


class _StatusAdapter(BaseAdapter):
    def __init__(self, config): pass
    def act(self, o): return aim_status_for(o, 'no_target')


def registry(reviewed=True):
    r = Registry()
    extra = {'aim_plugin_contract': AIM_PLUGIN_CONTRACT} if reviewed else {}
    r.register(descriptor('test_status', 'aim', 'Synthetic no-target fixture', ['camera'], **extra), _StatusAdapter)
    return r


class AimStatusContractsTests(unittest.TestCase):
    def test_status_is_detached_and_has_no_command_or_detection_claim(self):
        o = sample(True)
        for state in ('no_target', 'pending_result'):
            v = aim_status_for(o, state)
            self.assertEqual(v['schema'], AIM_STATUS_SCHEMA)
            self.assertEqual({k:v[k] for k in IDENTITY}, {k:o[k] for k in IDENTITY})
            self.assertNotIn('command', v)
            self.assertNotIn('tracking', v)
            self.assertEqual(validate_aim_status(v, o), v)

    def test_unknown_state_command_identity_and_equal_wrong_types_rejected(self):
        o = sample(True)
        changes = [('status', 'tracking'), ('kind', 'navigation'), ('schema', 'other'),
            ('command', {}), ('robot_id', 'other'), ('episode', True),
            ('binding_epoch', 1.), ('observed_seq', True), ('sim_time', 1), ('wall_deadline', 10)]
        for key, value in changes:
            with self.subTest(key=key):
                v = aim_status_for(o, 'no_target'); v[key] = value
                with self.assertRaises(ContractError): validate_aim_status(v, o)

    def test_worker_only_accepts_status_for_negotiated_aim_contract(self):
        for reviewed in (True, False):
            with self.subTest(reviewed=reviewed):
                clock = Clock(); o = sample(True); o['wall_deadline'] = clock()+.08
                slot = AdapterSlot(registry(reviewed), clock)
                try:
                    slot.submit(dict(kind='aim', observation=o,
                        binding=dict(adapter_id='test_status', config={}, epoch=o['binding_epoch'])))
                    limit = time.perf_counter()+1.; result = None
                    while result is None and time.perf_counter()<limit:
                        result = slot.poll()
                        if result is None: time.sleep(.001)
                    self.assertIsNotNone(result)
                    self.assertEqual(result['error'], None if reviewed else 'ContractError')
                    if reviewed: self.assertNotIn('command', result['value'])
                finally:
                    slot.close(); slot.thread.join(1.)
                    self.assertFalse(slot.thread.is_alive())


class AimStatusHarvestTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock(); self.backend = FakeBackend(); self.backend.episode = 1
        self.backend.sim_time = 1.; self.r = PlatformRuntime(self.backend, registry=registry(), clock=self.clock)
        p = self.r.control; self.token = p.open_session('operator')['token']
        self.leases = p.claim(self.token, 'alpha', ['gimbal', 'fire'])['lease_epochs']
        self.r.bind(self.token, 'alpha', 'aim', {'gimbal': self.leases['gimbal']}, 'test_status', {})
        self.snapshot = p.snapshot(); self.binding = copy.deepcopy(self.snapshot['bindings']['alpha']['aim']); self.r._episode = 1
        self.o = sample(True); self.o.update(robot_id='alpha', binding_epoch=self.binding['epoch'],
            observed_seq=2, wall_deadline=self.clock()+.08)
        self.key = ('alpha', 'aim')
        old = copy.deepcopy(self.o); old['observed_seq'] = 1
        self.r.outputs[self.key] = action_for(old, 'aim', 'gimbal_target', dict(frame='base_link',
            yaw_rad=.2, pitch_rad=.1, active=True, confidence=None, fire_permission=False))
        self.r.output_budgets[self.key] = None; self.r.output_authorizations[self.key] = {'fixture': True}

    def tearDown(self):
        self.r.slots.clear(); self.r.close()

    def deliver(self, value, *, completed=None, budget=None, observation=None):
        result = dict(job=dict(kind='aim', observation=observation or self.o,
            binding=copy.deepcopy(self.binding), sensor_budget=budget), value=value,
            error=None, completed=self.clock() if completed is None else completed)
        class Poll:
            def poll(self):
                nonlocal result
                v=result; result=None; return v
        self.r.slots[self.key] = Poll()
        self.r._collect(self.snapshot, self.backend.sim_time)

    def test_no_target_clears_old_action_and_all_receipts_without_fault(self):
        self.deliver(aim_status_for(self.o, 'no_target'))
        for values in (self.r.outputs, self.r.output_budgets, self.r.output_authorizations):
            self.assertNotIn(self.key, values)
        self.assertNotIn(self.key, self.r._private_outputs)
        self.assertEqual(self.r.status[self.key], 'waiting_for_aim:no_target')
        self.assertNotIn(self.key, self.r._fault_epochs)
        self.assertIsNone(self.r._targets(self.snapshot, 1.)['alpha']['gimbal'])
        self.assertFalse(self.r._targets(self.snapshot, 1.)['alpha']['fire'])

    def test_late_status_cannot_keep_old_action_or_become_success(self):
        self.clock.advance(.09); self.deliver(aim_status_for(self.o, 'no_target'))
        self.assertNotIn(self.key, self.r.outputs)
        self.assertEqual(self.r.status[self.key], 'late_result')

    def test_old_binding_status_cannot_clear_new_generation_action(self):
        original = copy.deepcopy(self.r.outputs[self.key])
        self.snapshot['bindings']['alpha']['aim']['epoch'] += 1
        self.r.outputs[self.key]['binding_epoch'] = self.snapshot['bindings']['alpha']['aim']['epoch']
        current = copy.deepcopy(self.r.outputs[self.key])
        self.deliver(aim_status_for(self.o, 'no_target'))
        self.assertEqual(self.r.outputs[self.key], current)
        self.assertNotEqual(current['binding_epoch'], original['binding_epoch'])

    def test_replayed_status_faults_without_clearing_another_robot(self):
        self.r.outputs[('beta', 'aim')] = {'fixture': 'unrelated'}
        self.o['observed_seq'] = 1
        self.deliver(aim_status_for(self.o, 'no_target'))
        self.assertEqual(self.r.status[self.key], 'invalid_result')
        self.assertIn(self.key, self.r._fault_epochs)
        self.assertEqual(self.r.outputs[('beta', 'aim')], {'fixture': 'unrelated'})

    def projected_context(self, context=None):
        sid=self.binding['owner']
        ctx=context or self.r._aim_status_context[self.key]
        value=dict(episode=1,robots=[],algorithm_status_context={'alpha':{'aim':ctx},
            'beta':{'aim':dict(ctx,private_target='NOT_FOR_OPERATOR')}})
        return project_state(value,self.snapshot,session_id=sid,role='operator')

    def test_projection_exposes_only_own_live_original_identity(self):
        self.deliver(aim_status_for(self.o,'no_target'))
        result=self.projected_context()
        ctx=result['algorithm_status_context']['alpha']['aim']
        self.assertEqual(ctx['source_frame_id'],1)
        self.assertEqual(ctx['status'],'no_target')
        self.assertEqual(set(ctx),{'episode','binding_epoch','adapter_id','status',
            'observed_seq','wall_deadline','source_frame_id'})
        self.assertNotIn('beta',result['algorithm_status_context'])
        self.assertNotIn('owner',ctx);self.assertNotIn('lease_epoch',ctx)

    def test_projection_rejects_stale_foreign_or_malformed_context(self):
        self.deliver(aim_status_for(self.o,'pending_result'))
        original=self.r._aim_status_context[self.key]
        for key,value in [('episode',0),('binding_epoch',999),('adapter_id','other'),
            ('owner','other'),('lease_epoch',999),('wall_deadline',self.clock()-1.),
            ('observed_seq',True),('status','raw:private path')]:
            with self.subTest(key=key):
                ctx=dict(original);ctx[key]=value
                self.assertNotIn('algorithm_status_context',self.projected_context(ctx))
        value=dict(episode=1,robots=[],algorithm_status_context=['malformed'])
        self.assertNotIn('algorithm_status_context',project_state(value,self.snapshot,
            session_id=self.binding['owner'],role='operator'))
