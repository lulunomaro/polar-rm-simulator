"""Synthetic source-reference/authority/actuator proofs; no NN, ROS or live run."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import math
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from rm_match.platform_v2.aim_contracts import AIM_PLUGIN_CONTRACT_V2, aim_status_for
from rm_match.platform_v2.aim_reference import INERTIAL_FROM_SOURCE_BASE, SourceBaseAim
from rm_match.platform_v2.backend import MuJoCoBackend
from rm_match.platform_v2.contracts import ContractError, IDENTITY, action_for
from rm_match.platform_v2.runtime import PlatformRuntime
from rm_match.platform_v2.test_contracts import sample
from rm_match.platform_v2.test_control import Clock
from rm_match.platform_v2.test_runtime import FakeBackend


def aim(o, yaw=.4, *, active=True):
    return action_for(o, 'aim', 'gimbal_target', dict(frame='base_link', yaw_rad=yaw,
        pitch_rad=.1, active=active, confidence=None, fire_permission=False))


def cartesian_oracle(source_yaw, source_command, current_yaw):
    def rotation(angle):
        return np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    own_direction = np.array([math.cos(source_command), math.sin(source_command)])
    current_direction = rotation(current_yaw).T @ rotation(source_yaw) @ own_direction
    return math.atan2(current_direction[1], current_direction[0])


@pytest.mark.parametrize('source_yaw,current_yaw,yaw', [(.6, 1.3, .4), (-2.8, 2.9, -.7),
    (2.8, -2.9, .7), (.2, .2, -.9), (0., 2 * math.pi + .3, .4)])
def test_source_reference_matches_independent_cartesian_oracle_without_rewriting_action(source_yaw, current_yaw, yaw):
    o = sample(True); o['own']['odom_xyyaw'][2] = source_yaw
    original = aim(o, yaw); before = deepcopy(original)
    budget = dict(frame_id=1, capture_wall=10., wall_deadline=10.08)
    reference = SourceBaseAim.accepted(original, o, budget)
    command, receipt = reference.target(current_yaw)
    assert command['yaw_rad'] == pytest.approx(cartesian_oracle(source_yaw, yaw, current_yaw))
    assert command['pitch_rad'] == before['command']['pitch_rad']
    assert original == before
    assert receipt['source'] == {k:o[k] for k in IDENTITY}
    assert receipt['original_command'] == original['command']
    assert receipt['sensor_budget'] == budget
    assert receipt['current_base_yaw_rad'] == current_yaw
    assert receipt['mechanical_yaw_rad'] == command['yaw_rad']
    with pytest.raises(FrozenInstanceError):
        reference.source_base_yaw_rad = 99.
    receipt['source']['observed_seq'] += 1
    receipt['sensor_budget']['wall_deadline'] += 1.
    assert reference.matches(original, budget)


@pytest.mark.parametrize('field,value', [('robot_id','other'), ('episode',True),
    ('binding_epoch',2), ('observed_seq',2), ('sim_time',1), ('wall_deadline',11.)])
def test_reference_cannot_be_rebound_to_other_or_equal_wrong_typed_identity(field, value):
    o = sample(True); original = aim(o); reference = SourceBaseAim.accepted(original, o, None)
    changed = deepcopy(original); changed[field] = value
    assert not reference.matches(changed, None)


@pytest.mark.parametrize('odometry', [None, [0.,0.], [0.,0.,float('nan')], [0.,0.,True]])
def test_reference_requires_original_finite_own_odometry(odometry):
    o = sample(True); o['own']['odom_xyyaw'] = odometry
    with pytest.raises(ContractError):SourceBaseAim.accepted(aim(o), o, None)


def test_reference_rejects_mutated_command_or_original_budget():
    o = sample(True); action = aim(o); budget = dict(frame_id=1, wall_deadline=10.08)
    reference = SourceBaseAim.accepted(action, o, budget)
    action['command']['yaw_rad'] += .1
    assert not reference.matches(action, budget)
    action = aim(o); budget['wall_deadline'] += .1
    assert not reference.matches(action, budget)
    assert not reference.matches(action, None)


class SyntheticRegistry:
    def __init__(self, reference=INERTIAL_FROM_SOURCE_BASE, *, stationary=False):
        self.metadata = dict(adapter_id='synthetic_aim', kind='aim', available=True,
            output_modes=['gimbal_target'], required_sensors=['camera','odometry'],
            aim_plugin_contract=AIM_PLUGIN_CONTRACT_V2, aim_reference=reference, stationary_only=stationary)
    def get(self, _):return SimpleNamespace(descriptor=deepcopy(self.metadata))


class PoseBackend(FakeBackend):
    def __init__(self):
        super().__init__(('alpha','beta'))
        self.episode = 1; self.sim_time = 1.; self.yaws = dict(alpha=1.3, beta=-2.)
        self.enabled = True; self.moving = False
    def own_pose(self, rid):
        return dict(yaw=self.yaws[rid], vx=.04 if self.moving else 0., vy=0., wz=0.,
            gimbal_yaw=.05, gimbal_pitch=.02)
    def allowed(self, _):return self.enabled


@pytest.fixture
def host():
    clock = Clock(); backend = PoseBackend(); registry = SyntheticRegistry()
    runtime = PlatformRuntime(backend, registry=registry, clock=clock)
    control = runtime.control; token = control.open_session('operator')['token']
    leases = control.claim(token, 'alpha', ['gimbal','motion','fire'])['lease_epochs']
    runtime.bind(token, 'alpha', 'aim', {'gimbal':leases['gimbal']}, 'synthetic_aim', {})
    runtime._episode = backend.episode
    binding = control.snapshot()['bindings']['alpha']['aim']
    o = sample(True); o.update(robot_id='alpha', binding_epoch=binding['epoch'], wall_deadline=clock()+.08)
    o['own']['odom_xyyaw'][2] = .6
    budget = dict(robot_id='alpha', episode=1, frame_id=1, capture_wall=clock(),
        capture_sim_time=1., wall_deadline=clock()+.08, sim_deadline=1.08)
    value = SimpleNamespace(r=runtime, b=backend, registry=registry, clock=clock, control=control,
        token=token, leases=leases, binding=deepcopy(binding), o=o, budget=budget, key=('alpha','aim'))
    yield value
    runtime.slots.clear(); runtime.close()


def deliver(h, value, *, observation=None, budget=True):
    result = dict(job=dict(kind='aim', observation=observation or h.o, binding=deepcopy(h.binding),
        sensor_budget=h.budget if budget else None), value=value, error=None, completed=h.clock())
    h.r.slots[h.key] = SimpleNamespace(poll=Mock(side_effect=[result, None]))
    h.r._collect(h.control.snapshot(), h.b.sim_time)


def target(h):return h.r._targets(h.control.snapshot(), h.b.sim_time)['alpha']['gimbal']


def test_runtime_binds_original_source_and_uses_current_own_yaw_only(host):
    h = host; original = aim(h.o); deliver(h, original)
    assert h.r.outputs[h.key] == original
    assert target(h)['yaw_rad'] == pytest.approx(cartesian_oracle(.6, .4, 1.3))
    h.b.yaws['alpha'] = -.8; h.b.yaws['beta'] = 2.7
    assert target(h)['yaw_rad'] == pytest.approx(cartesian_oracle(.6, .4, -.8))
    assert h.r.outputs[h.key] == original
    receipt = h.r._aim_reference_receipts[h.key]
    assert receipt['source'] == {k:h.o[k] for k in IDENTITY}
    assert receipt['sensor_budget'] == h.budget
    assert receipt['current_base_yaw_rad'] == -.8
    assert receipt['original_command'] == original['command']


@pytest.mark.parametrize('reason', ['wall_expiry','sim_expiry','lease_release','rebind','pause','camera_invalid'])
def test_original_authority_or_camera_expiry_clears_source_and_cannot_resume_it(host, reason):
    h = host; deliver(h, aim(h.o)); assert target(h) is not None
    if reason == 'wall_expiry':h.clock.advance(.08)
    elif reason == 'sim_expiry':h.b.sim_time = 1.081
    elif reason == 'lease_release':h.control.release(h.token, 'alpha', {'gimbal':h.leases['gimbal']})
    elif reason == 'rebind':h.r.bind(h.token, 'alpha', 'aim', {'gimbal':h.leases['gimbal']}, 'synthetic_aim', {})
    elif reason == 'pause':h.b.enabled = False
    else:h.r.camera = SimpleNamespace(sensor_capture_valid=lambda *args:False, stop=lambda:None,
        status=lambda:dict(available=False,reason='synthetic_camera_revoked'))
    assert target(h) is None
    assert h.key not in h.r._aim_sources and h.key not in h.r._aim_reference_receipts
    if reason == 'pause':
        h.b.enabled = True
        assert target(h) is None


@pytest.mark.parametrize('status', ['no_target','pending_result'])
def test_v2_status_clears_direction_without_synthesizing_a_hold_command(host, status):
    h = host; deliver(h, aim(h.o)); assert target(h) is not None
    observation = deepcopy(h.o); observation['observed_seq'] += 1
    deliver(h, aim_status_for(observation, status), observation=observation)
    assert target(h) is None
    assert h.key not in h.r.outputs and h.key not in h.r._aim_sources
    assert h.r.status[h.key] == 'waiting_for_aim:'+status


@pytest.mark.parametrize('reference', ['base_link', 'inertial_from_source_base_v1'])
def test_stationary_gate_is_independent_of_explicit_reference(host, reference):
    h = host; h.registry.metadata.update(aim_reference=reference, stationary_only=True)
    deliver(h, aim(h.o)); assert target(h) is not None
    h.b.moving = True
    assert target(h) is None and h.r.status[h.key] == 'stationary_required'
    assert h.key not in h.r._aim_sources


def test_legacy_base_link_keeps_original_mechanical_angle(host):
    h = host; h.registry.metadata.pop('aim_reference'); deliver(h, aim(h.o))
    h.b.yaws['alpha'] = -2.
    assert target(h)['yaw_rad'] == .4
    assert h.key not in h.r._aim_sources


def test_pause_fence_does_not_change_legacy_base_link_resume_behavior(host):
    h = host; h.registry.metadata.pop('aim_reference'); deliver(h, aim(h.o))
    assert target(h)['yaw_rad'] == .4
    h.b.enabled = False; assert target(h) is None
    assert h.key not in h.r._aim_source_fences
    h.b.enabled = True; assert target(h)['yaw_rad'] == .4


@pytest.mark.parametrize('reference', [True, 1, None, 'world', 'inertial_from_source_base_v2'])
def test_unknown_or_wrong_typed_local_reference_fails_closed(host, reference):
    h = host; h.registry.metadata['aim_reference'] = reference; deliver(h, aim(h.o))
    assert h.r.status[h.key] == 'invalid_result'
    assert target(h) is None and h.key not in h.r._aim_sources


def test_explicit_reference_requires_v2_contract_and_original_odometry(host):
    h = host; h.registry.metadata['aim_plugin_contract'] = 'camera_gimbal_v1'
    deliver(h, aim(h.o))
    assert h.r.status[h.key] == 'invalid_result' and target(h) is None


@pytest.mark.parametrize('change', ['missing','navigation_source','robot','episode_type','frame',
    'capture_time','wall_extension','sim_extension'])
def test_inertial_action_requires_original_camera_budget_without_any_test_bypass(host, change):
    h = host
    if change == 'navigation_source':h.budget['source'] = 'navigation_sensor_v1'
    elif change == 'robot':h.budget['robot_id'] = 'beta'
    elif change == 'episode_type':h.budget['episode'] = True
    elif change == 'frame':h.budget['frame_id'] = 2
    elif change == 'capture_time':h.budget['capture_sim_time'] -= .001
    elif change == 'wall_extension':h.budget['wall_deadline'] += .001
    elif change == 'sim_extension':h.budget['sim_deadline'] += .001
    deliver(h, aim(h.o), budget=change != 'missing')
    assert target(h) is None
    assert h.key not in h.r.outputs and h.key not in h.r._aim_sources


def test_receipt_clears_on_new_episode(host):
    h = host; deliver(h, aim(h.o)); assert target(h) is not None
    h.b.enabled = False; assert target(h) is None
    assert h.key in h.r._aim_source_fences
    h.r.slots.clear(); h.r._schedule = lambda *args:None
    h.b.episode += 1; h.b.sim_time = 0.; h.r.step_once()
    assert not h.r._aim_sources and not h.r._aim_reference_receipts and not h.r._aim_source_fences


def test_pending_pre_pause_source_cannot_revive_after_resume_with_same_live_binding(host):
    """Real scheduler/AdapterSlot thread; a synthetic camera never renders."""
    h = host; entered = threading.Event(); release = threading.Event(); seen = []
    class BlockingAim:
        def reset(self, context):pass
        def act(self, observation):
            seen.append(deepcopy(observation)); entered.set()
            if not release.wait(1.):raise RuntimeError('synthetic_pending_timeout')
            return aim(observation)
        def close(self):pass
    class Camera:
        max_views = 1
        def sensor_packet(self, *args):
            return dict(camera=deepcopy(h.o['sensors']['camera']), budget=deepcopy(h.budget))
        def capture_from_authority(self, *args):pass
        def status(self):return dict(available=True, reason='synthetic_no_renderer')
        def fault(self, reason):raise AssertionError(reason)
        def stop(self):pass
    h.registry.create = lambda *args:BlockingAim()
    h.r.camera = Camera(); h.b._sim = object()
    h.r._schedule(h.control.snapshot(), h.b.sim_time)
    slot = h.r.slots[h.key]
    try:
        assert entered.wait(1.) and slot.running
        before = h.control.snapshot()['bindings']['alpha']['aim']
        original = seen[0]
        assert h.r.observed[h.key] == original['observed_seq']
        # Retain the pending real worker; prevent a newer test capture from
        # masking whether its old result revives after the pause boundary.
        h.r._schedule = lambda *args:None
        h.b.enabled = False; h.r.step_once()
        assert h.b.targets['alpha']['gimbal'] is None
        assert h.key not in h.r._aim_sources
        h.clock.advance(.01); h.b.enabled = True; release.set()
        deadline = time.perf_counter()+1.
        while slot.results.empty() and time.perf_counter()<deadline:time.sleep(.001)
        assert not slot.results.empty()
        assert h.clock() < original['wall_deadline']
        assert h.control.snapshot()['bindings']['alpha']['aim'] == before
        h.r.step_once()
        assert h.b.targets['alpha']['gimbal'] is None
        assert h.key not in h.r._aim_sources and h.key not in h.r.outputs
        # A new synthetic exposure of this SAME binding remains eligible. No
        # token, lease, binding epoch or OLD source deadline is refreshed.
        fresh = deepcopy(original); fresh['observed_seq'] += 1
        fresh['sim_time'] = h.b.sim_time; fresh['wall_deadline'] = h.clock()+.08
        fresh['sensors']['camera'].update(frame_id=2, capture_sim_time=h.b.sim_time)
        h.budget = dict(h.budget, frame_id=2, capture_wall=h.clock(), capture_sim_time=h.b.sim_time,
            wall_deadline=fresh['wall_deadline'], sim_deadline=h.b.sim_time+.08)
        deliver(h, aim(fresh), observation=fresh)
        assert target(h) is not None
        assert h.r.outputs[h.key]['wall_deadline'] == fresh['wall_deadline']
        assert original['wall_deadline'] == h.o['wall_deadline']
        assert h.control.snapshot()['bindings']['alpha']['aim'] == before
    finally:
        release.set(); slot.close(); slot.thread.join(1.)
        assert not slot.thread.is_alive()
        h.r.slots.clear()


def test_stop_clears_source_without_extending_original_authority(host):
    h = host; deliver(h, aim(h.o)); assert target(h) is not None
    h.b.enabled = False; assert target(h) is None
    assert h.key in h.r._aim_source_fences
    h.r.request_stop()
    assert not h.r._aim_sources and not h.r._aim_reference_receipts and not h.r._aim_source_fences


def test_pause_fence_is_bound_to_original_binding_generation(host):
    h = host; deliver(h, aim(h.o)); assert target(h) is not None
    h.b.enabled = False; assert target(h) is None
    assert h.key in h.r._aim_source_fences
    h.r.bind(h.token, 'alpha', 'aim', {'gimbal':h.leases['gimbal']}, 'synthetic_aim', {})
    h.binding = deepcopy(h.control.snapshot()['bindings']['alpha']['aim'])
    fresh = deepcopy(h.o); fresh['binding_epoch'] = h.binding['epoch']
    h.b.enabled = True; deliver(h, aim(fresh), observation=fresh)
    assert target(h) is not None and h.key not in h.r._aim_source_fences


def test_private_consumption_receipts_keep_original_source_and_each_current_yaw(host):
    h = host; original = aim(h.o); deliver(h, original)
    h.r.slots.clear(); h.r._schedule = lambda *args:None
    events = []; h.r.trace = events.append
    def guarded_step(targets, guard, clock):
        for phase, yaw in [('actuator',.8), ('integration',1.2), ('integration_entry',1.5)]:
            h.b.yaws['alpha'] = yaw
            h.b.targets = guard('alpha', None, phase, clock() if phase == 'integration_entry' else None)
        h.b.sim_time += h.b.timestep
    h.b.guarded_step = guarded_step
    h.r.step_once()
    receipts = [e for e in events if e['event'] == 'actuator_consumed']
    assert len(receipts) == 3
    for receipt, yaw in zip(receipts, [.8,1.2,1.5]):
        reference = receipt['aim_reference']
        assert reference['source'] == {k:h.o[k] for k in IDENTITY}
        assert reference['original_command'] == original['command']
        assert reference['current_base_yaw_rad'] == yaw
        assert reference['mechanical_yaw_rad'] == receipt['target']['gimbal']['yaw_rad']
        assert receipt['consume_wall'] < reference['source']['wall_deadline']
        assert reference['sensor_budget'] == h.budget
    assert h.r.outputs[h.key] == original


@pytest.mark.parametrize('revoke_at_entry', [False, True])
def test_backend_guard_updates_real_command_at_each_phase_and_survives_target_alias_mutation(revoke_at_entry):
    """Exercise the actual backend final closure with a harmless synthetic engine."""
    backend = MuJoCoBackend.__new__(MuJoCoBackend)
    backend.robot_ids = ('alpha',); backend.timestep = .002; backend._authority = None
    backend._resupply = SimpleNamespace(apply=lambda *args:None)
    backend._gimbal_hold = {}; backend._gimbal_was_active = {'alpha':False}
    q = np.zeros(5); q[3:] = [.05,.02]
    sim = SimpleNamespace(time=1., episode=1, model=SimpleNamespace(actuator_ctrlrange=np.array(
        [[-60,60],[-60,60],[-20,20],[-math.pi,math.pi],[-1,1]])),
        data=SimpleNamespace(qpos=q, qvel=np.zeros(5), ctrl=np.zeros(5), actuator_force=np.zeros(5)),
        qindices={'alpha':list(range(5))}, vindices={'alpha':list(range(5))},
        aindices={'alpha':list(range(5))}, commands={})
    backend._sim = sim; backend.allowed = lambda _:True
    original = sample(True); original['own']['odom_xyyaw'][2] = .6
    source = SourceBaseAim.accepted(aim(original), original, None)
    targets = {'alpha':dict(motion=None, gimbal=aim(original)['command'], fire=False)}
    applied = []

    def step(commands, *, command_guard, integration_clock):
        for phase, yaw in [('actuator',.8), ('integration',1.2), ('integration_entry',1.5)]:
            q[2] = yaw
            command = command_guard('alpha', commands['alpha'], phase,
                integration_clock() if phase == 'integration_entry' else None)
            commands['alpha'] = command
            sim.data.ctrl[3:] = [command.gimbal_yaw, command.gimbal_pitch]
            applied.append((phase, yaw, sim.data.ctrl[3:].copy()))
        sim.commands = commands; sim.time += .002
    sim.step = step

    def guard(rid, command, phase, sampled_wall=None):
        derived, _ = source.target(backend.own_pose(rid)['yaw'])
        # Deliberately mutate the original container to cover the alias edge.
        targets[rid]['gimbal'] = None if revoke_at_entry and phase == 'integration_entry' else derived
        return targets[rid]
    backend.guarded_step(targets, guard, clock=lambda:1000.)
    for phase, yaw, ctrl in applied:
        if revoke_at_entry and phase == 'integration_entry':
            assert ctrl == pytest.approx([.05,.02])
        else:
            assert ctrl[0] == pytest.approx(cartesian_oracle(.6, .4, yaw)), phase
            assert ctrl[1] == .1
    assert backend.last_commands['alpha']['gimbal_yaw'] == applied[-1][2][0]
