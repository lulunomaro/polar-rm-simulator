"""Atomic operator-window contract; synthetic clocks and real loopback HTTP only."""
import copy
import http.client
import json
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from rm_match.platform_v2.control import CHANNELS, KINDS, ControlPlane, Rejected
from rm_match.platform_v2.server import PlatformHTTPServer, TransportConfig
from rm_match.platform_v2.spin import capability
from rm_match.platform_v2.test_support_admission import fixture_policy, OPERATOR_CREDENTIAL


class Clock:
    def __init__(self):
        self.now = 100.
        self.reads = None
    def __call__(self):
        if self.reads:
            self.now = self.reads.pop(0)
        return self.now


def value(channel):
    return dict(motion=dict(frame='base_link', vx_mps=.2, vy_mps=0., wz_rps=0.),
                gimbal=dict(frame='base_link', yaw_rad=.3, pitch_rad=.1),
                fire=dict(fire=True))[channel]


def setup(bound=('navigation',), *, spin=False, profile='server_window_v1'):
    clock = Clock()
    mapping = {key: True for key in ('joint_transmission', 'hinge_joint', 'own_qpos',
        'own_dof', 'axis_positive_z', 'unit_gear', 'fixed_unit_gain', 'no_bias',
        'no_dynamics', 'control_limited', 'no_force_limit')}
    mapping.update(ctrl_min=-1., ctrl_max=1.)
    plane = ControlPlane(['alpha', 'beta'], clock=clock,
                         spin_capabilities={'alpha': capability(mapping)} if spin else None)
    session = plane.open_session('operator', profile, allowed_robots=['alpha'])
    token = session['token']
    epochs = plane.claim(token, 'alpha', list(CHANNELS))['lease_epochs']
    adapters = []
    for kind in bound:
        ack = plane.bind(token, 'alpha', kind, {channel: epochs[channel] for channel in KINDS[kind]},
                         'synthetic_test_binding', {})
        adapters.append(dict(kind=kind, binding_epoch=ack['binding_epoch'], seq=0))
    if profile == 'server_window_v1':
        window = plane.control_window(token, 'alpha', epochs)
    else:
        window = dict(window_id=0)
    controls = [dict(channel=channel, lease_epoch=epochs[channel], seq=0, value=value(channel))
                for channel in CHANNELS if not any(channel in KINDS[kind] for kind in bound)]
    body = dict(robot_id='alpha', lease_epochs=epochs, window_id=window['window_id'],
                valid_for_s=.15, adapter_inputs=adapters, controls=controls)
    return plane, clock, token, body, session


def send(plane, token, body):
    return plane.control_batch(token, body['robot_id'], body['lease_epochs'], body['window_id'],
                               body['valid_for_s'], body['adapter_inputs'], body['controls'])


def authority(plane):
    return dict(leases={key: copy.deepcopy(vars(entry)) for key, entry in plane.leases.items()},
                bindings={key: copy.deepcopy(vars(entry)) for key, entry in plane.bindings.items()},
                revision=plane.revision)


@pytest.mark.parametrize('bound', [(), ('navigation',), ('aim',), ('navigation', 'aim')])
def test_single_commit_preserves_all_channels_and_original_window(bound):
    plane, clock, token, body, session = setup(bound)
    before = authority(plane)
    window = copy.deepcopy(plane.sessions[session['session_id']].windows['alpha'])
    with patch.object(plane, 'control', side_effect=AssertionError('No per-item writes')), \
         patch.object(plane, 'adapter_input', side_effect=AssertionError('No per-item writes')):
        ack = send(plane, token, body)
    assert set(ack) == {'accepted', 'robot_id', 'lease_epochs', 'window_id', 'batch_version',
                        'adapter_inputs', 'controls'}
    assert ack['accepted'] is True and type(ack['batch_version']) is int and ack['batch_version'] == 1
    assert ack['lease_epochs'] == body['lease_epochs'] and ack['window_id'] == window['window_id']
    assert plane.revision == before['revision'] + 1
    assert plane.sessions[session['session_id']].windows['alpha'] == window
    assert plane.sessions[session['session_id']].next_window_id == window['window_id']
    for entry in ack['adapter_inputs']:
        assert set(entry) == {'accepted', 'robot_id', 'kind', 'binding_epoch', 'seq',
                              'window_id', 'activation_expires'}
        assert entry['activation_expires'] == window['expires_wall']
        binding = plane.bindings['alpha', entry['kind']]
        assert binding.activation_seq == 0 and binding.activation_expires == window['expires_wall']
    for entry in ack['controls']:
        assert set(entry) == {'accepted', 'robot_id', 'channel', 'lease_epoch', 'seq',
                              'window_id', 'input_expires'}
        assert entry['input_expires'] == window['expires_wall']
        lease = plane.leases['alpha', entry['channel']]
        assert lease.seq == 0 and lease.input == value(entry['channel'])
    assert plane.leases['alpha', 'fire'].input == {'fire': True}
    assert all(plane.leases['alpha', channel].expires == before['leases']['alpha', channel]['expires']
               for channel in CHANNELS)
    assert all(vars(plane.leases['beta', channel]) == before['leases']['beta', channel] for channel in CHANNELS)
    body['controls'][-1]['value']['fire'] = False
    ack['lease_epochs']['fire'] = 999
    assert plane.leases['alpha', 'fire'].input == {'fire': True}
    assert plane.leases['alpha', 'fire'].epoch == 1


@pytest.mark.parametrize('mutate', [
    pytest.param(lambda b: b['controls'].pop(), id='missing-fire'),
    pytest.param(lambda b: b['controls'].append(copy.deepcopy(b['controls'][-1])), id='duplicate-fire'),
    pytest.param(lambda b: b['adapter_inputs'].append(copy.deepcopy(b['adapter_inputs'][0])), id='duplicate-kind'),
    pytest.param(lambda b: b['controls'].append(dict(channel='motion', lease_epoch=1, seq=0, value=value('motion'))), id='overlapping-channel'),
    pytest.param(lambda b: b['controls'][-1]['value'].update(fire=1), id='nonboolean-fire'),
    pytest.param(lambda b: b['controls'][0]['value'].update(pitch_rad=float('nan')), id='nan-gimbal'),
    pytest.param(lambda b: b['controls'][0]['value'].update(yaw_rad=4.), id='gimbal-limit'),
    pytest.param(lambda b: b['adapter_inputs'][0].update(fire_permission=True), id='adapter-fire-authority'),
    pytest.param(lambda b: b['lease_epochs'].update(motion=True), id='boolean-epoch'),
    pytest.param(lambda b: b['adapter_inputs'][0].update(binding_epoch=1.), id='float-binding'),
    pytest.param(lambda b: b.update(window_id=1.), id='float-window'),
    pytest.param(lambda b: b['controls'][-1].update(seq=True), id='boolean-seq'),
    pytest.param(lambda b: b.update(valid_for_s=.151), id='expanded-lifetime'),
    pytest.param(lambda b: b.update(valid_for_s=True), id='boolean-lifetime'),
    pytest.param(lambda b: b.update(robot_id='beta'), id='outside-robot-scope'),
])
def test_any_malformed_member_rejects_entire_batch_without_sequence_or_input_mutation(mutate):
    plane, clock, token, body, session = setup()
    before = authority(plane)
    mutate(body)
    with pytest.raises(Rejected):
        send(plane, token, body)
    assert authority(plane) == before


@pytest.mark.parametrize('stale_member', ['gimbal', 'fire', 'aim'])
def test_late_stale_member_cannot_partially_renew_other_members(stale_member):
    bound = ('navigation', 'aim') if stale_member == 'aim' else ('navigation',)
    plane, clock, token, body, session = setup(bound)
    send(plane, token, body)
    before = authority(plane)
    for entry in body['adapter_inputs'] + body['controls']:
        entry['seq'] = 1
        if entry.get('kind', entry.get('channel')) == stale_member:
            entry['seq'] = 0
    body['controls'][-1]['value']['fire'] = False
    with pytest.raises(Rejected, match='stale_'):
        send(plane, token, body)
    assert authority(plane) == before


def test_manually_populating_a_bound_channel_is_not_a_batch_fallback():
    plane, clock, token, body, session = setup()
    body['adapter_inputs'].clear()
    body['controls'].insert(0, dict(channel='motion', lease_epoch=1, seq=0, value=value('motion')))
    before = authority(plane)
    with pytest.raises(Rejected, match='channel_bound_to_adapter'):
        send(plane, token, body)
    assert authority(plane) == before


def test_parsing_outside_lock_still_rechecks_original_window_after_real_lock_wait():
    plane, clock, token, body, session = setup()
    before = authority(plane)
    parsed = threading.Event()
    errors = []
    original = plane._batch_control_value
    def parse(rid, channel, raw):
        result = original(rid, channel, raw)
        if channel == 'fire':
            parsed.set()
        return result
    def worker():
        try:
            send(plane, token, body)
        except BaseException as error:
            errors.append(error)
    with patch.object(plane, '_batch_control_value', side_effect=parse):
        with plane.lock:
            thread = threading.Thread(target=worker)
            thread.start()
            assert parsed.wait(1.)
            clock.now += .151
        thread.join(1.)
    assert not thread.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], Rejected)
    assert errors[0].reason == 'expired_control_window'
    assert authority(plane) == before


@pytest.mark.parametrize('expired', ['window', 'lease', 'session', 'activation'])
def test_fresh_final_clock_after_member_validation_can_only_fail_closed(expired):
    plane, clock, token, body, session = setup()
    if expired == 'lease':
        plane.leases['alpha', 'fire'].expires = 100.05
    elif expired == 'session':
        plane.sessions[session['session_id']].expires = 100.05
    elif expired == 'activation':
        binding = plane.bindings['alpha', 'navigation']
        binding.activation_seq = 0
        binding.activation_expires = 100.05
        body['adapter_inputs'][0]['seq'] = 1
    clock.reads = [100., 100.151 if expired == 'window' else 100.06]
    with pytest.raises(Rejected):
        send(plane, token, body)
    assert all(plane.leases['alpha', channel].seq == -1 and plane.leases['alpha', channel].input is None
               for channel in CHANNELS)
    assert plane.bindings['alpha', 'navigation'].activation_seq <= 0


def test_original_leases_cap_each_member_deadline_and_same_window_cannot_extend_activation():
    plane, clock, token, body, session = setup()
    for index, channel in enumerate(CHANNELS):
        plane.leases['alpha', channel].expires = 100.07 + index * .01
    body['valid_for_s'] = .05
    first = send(plane, token, body)
    assert first['adapter_inputs'][0]['activation_expires'] == 100.05
    clock.now += .02
    body['valid_for_s'] = .15
    for entry in body['adapter_inputs'] + body['controls']:
        entry['seq'] += 1
    second = send(plane, token, body)
    assert second['adapter_inputs'][0]['activation_expires'] == first['adapter_inputs'][0]['activation_expires']
    for entry in second['controls']:
        assert entry['input_expires'] == plane.leases['alpha', entry['channel']].expires


def test_motion_mode_fault_revokes_only_motion_and_commits_no_other_member():
    plane, clock, token, body, session = setup((), spin=True)
    send(plane, token, body)
    before = authority(plane)
    for entry in body['controls']:
        entry['seq'] = 1
        if entry['channel'] == 'motion':
            entry['value'] = dict(mode='spin_v1', frame='base_link', vx_mps=0., vy_mps=0.,
                                  direction='ccw', speed_dps=360.)
    with pytest.raises(Rejected, match='mode_change_requires_release'):
        send(plane, token, body)
    assert plane.leases['alpha', 'motion'].mode_fault is True
    assert plane.leases['alpha', 'motion'].input is None
    assert plane.leases['alpha', 'motion'].seq == before['leases']['alpha', 'motion']['seq']
    assert all(vars(plane.leases['alpha', channel]) == before['leases']['alpha', channel]
               for channel in ('gimbal', 'fire'))


@pytest.mark.parametrize('case', ['legacy', 'partial-window', 'stale-window', 'spectator'])
def test_batch_requires_current_full_window_and_operator_profile(case):
    plane, clock, token, body, session = setup(profile='legacy_v2' if case == 'legacy' else 'server_window_v1')
    if case == 'partial-window':
        body['window_id'] = plane.control_window(token, 'alpha', {'motion': 1})['window_id']
    elif case == 'stale-window':
        plane.control_window(token, 'alpha', body['lease_epochs'])
    elif case == 'spectator':
        token = plane.open_session('spectator', 'server_window_v1')['token']
    before = authority(plane)
    with pytest.raises(Rejected):
        send(plane, token, body)
    assert authority(plane) == before


@pytest.fixture
def http_server():
    plane = ControlPlane(['alpha', 'beta'])
    runtime = SimpleNamespace(control=plane)
    server = PlatformHTTPServer(TransportConfig(port=0, max_http_workers=2,
        admission_policy=fixture_policy(plane.robot_ids)), runtime)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01})
    thread.start()
    def request(path, body, token=None):
        connection = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=1.)
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        try:
            connection.request('POST', path, json.dumps(body), headers)
            reply = connection.getresponse()
            return reply.status, json.loads(reply.read())
        finally:
            connection.close()
    try:
        yield plane, request
    finally:
        server.shutdown()
        server.server_close()
        thread.join(1.)
        assert not thread.is_alive()


def test_actual_loopback_http_advertises_and_returns_exact_single_batch_ack(http_server):
    plane, request = http_server
    status, session = request('/v2/sessions', dict(role='operator', credential=OPERATOR_CREDENTIAL,
                                                control_profile='server_window_v1'))
    assert status == 200 and type(session['control_batch_version']) is int and session['control_batch_version'] == 1
    token = session['token']
    status, claim = request('/v2/claim', dict(robot_id='alpha', channels=list(CHANNELS)), token)
    assert status == 200
    epochs = claim['lease_epochs']
    binding = plane.bind(token, 'alpha', 'navigation', {'motion': epochs['motion']}, 'synthetic_test_binding', {})
    status, window = request('/v2/control_window', dict(robot_id='alpha', lease_epochs=epochs), token)
    assert status == 200
    body = dict(robot_id='alpha', lease_epochs=epochs, window_id=window['window_id'], valid_for_s=.15,
        adapter_inputs=[dict(kind='navigation', binding_epoch=binding['binding_epoch'], seq=0)],
        controls=[dict(channel=channel, lease_epoch=epochs[channel], seq=0, value=value(channel))
                  for channel in ('gimbal', 'fire')])
    status, ack = request('/v2/control_batch', body, token)
    assert status == 200 and ack['schema'] == 'rm.sim.platform.v2'
    assert set(ack) == {'schema', 'accepted', 'robot_id', 'lease_epochs', 'window_id',
                        'batch_version', 'adapter_inputs', 'controls'}
    assert ack['adapter_inputs'][0]['kind'] == 'navigation'
    assert [entry['channel'] for entry in ack['controls']] == ['gimbal', 'fire']
    assert plane.leases['alpha', 'fire'].input == {'fire': True}
    before = authority(plane)
    body['truth_targets'] = []
    status, error = request('/v2/control_batch', body, token)
    assert status == 400 and error['accepted'] is False
    assert authority(plane) == before


def test_actual_loopback_http_legacy_does_not_advertise_or_accept_batch(http_server):
    plane, request = http_server
    status, session = request('/v2/sessions', dict(role='operator', credential=OPERATOR_CREDENTIAL))
    assert status == 200 and 'control_batch_version' not in session
    status, claim = request('/v2/claim', dict(robot_id='alpha', channels=list(CHANNELS)), session['token'])
    assert status == 200
    epochs = claim['lease_epochs']
    body = dict(robot_id='alpha', lease_epochs=epochs, window_id=0, valid_for_s=.15, adapter_inputs=[],
        controls=[dict(channel=channel, lease_epoch=epochs[channel], seq=0, value=value(channel)) for channel in CHANNELS])
    before = authority(plane)
    status, error = request('/v2/control_batch', body, session['token'])
    assert status == 409 and error['error'] == 'batch_window_profile_required'
    assert authority(plane) == before
