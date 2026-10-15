"""Fake asynchronous Nav2 action interleavings, never real ROS qualification."""
import copy
from array import array
from types import SimpleNamespace as NS

import numpy as np
import pytest

from rm_match.integrations.nav2_goal_backend import Nav2GoalBackend, Nav2GoalSettings, STATUS_SCHEMA, _uuid
from rm_match.platform_v2.contracts import ContractError, IDENTITY


class Future:
    def __init__(self):
        self.value = None
        self.error = None
        self.complete = False
    def done(self):
        return self.complete
    def result(self):
        assert self.complete, 'A pending future must never be waited on or read'
        if self.error:
            raise self.error
        return self.value
    def resolve(self, value):
        self.value = value
        self.complete = True
    def fail(self):
        self.error = RuntimeError('synthetic asynchronous failure')
        self.complete = True


def uid(number):
    return NS(uuid=[number] * 16)


class Handle:
    def __init__(self, number, accepted=True):
        self.goal_id = uid(number)
        self.accepted = accepted
        self.result = Future()
        self.cancel = Future()
        self.cancel_calls = 0
        self.result_calls = 0
    def get_result_async(self):
        self.result_calls += 1
        return self.result
    def cancel_goal_async(self):
        self.cancel_calls += 1
        return self.cancel


class Client:
    def __init__(self):
        self.available = True
        self.sent = []
        self.futures = []
        self.destroyed = False
    def server_is_ready(self):
        return self.available
    def send_goal_async(self, goal):
        self.sent.append(goal)
        future = Future()
        self.futures.append(future)
        return future
    def destroy(self):
        self.destroyed = True


def pose():
    return NS(header=NS(frame_id='', stamp=NS(sec=0, nanosec=0)),
              pose=NS(position=NS(x=0., y=0., z=0.), orientation=NS(x=0., y=0., z=0., w=0.)))


def backend(mode='navigate_to_pose'):
    clients = []
    def factory(node, action_type, name):
        client = Client()
        clients.append(client)
        return client
    settings = (Nav2GoalSettings(mode, navigation_action='/owned/navigate_to_pose') if mode == 'navigate_to_pose'
                else Nav2GoalSettings(mode, planner_action='/owned/compute_path_to_pose',
                    controller_action='/owned/follow_path', planner_id='GridBased',
                    controller_id='FollowPath', goal_checker_id='general_goal_checker'))
    result = Nav2GoalBackend(object(), settings, client_factory=factory,
        action_types={name: NS(Goal=NS) for name in ('navigate_to_pose', 'compute_path_to_pose', 'follow_path')},
        pose_factory=pose)
    return result, clients


def source():
    return dict(robot_id='red_sentry', episode=0, binding_epoch=1, observed_seq=7,
                sim_time=1., wall_deadline=12345.)


def goal():
    return dict(frame='map', position_m=[1.2, -.3], yaw_rad=.4)


def begin(mode='navigate_to_pose'):
    result, clients = backend(mode)
    operation = result.start(goal(), source(), operation_id='operation_a')
    return result, clients, operation


def assert_status(status):
    assert set(status) == {'schema', 'operation_id', 'source', 'state', 'goal_uuids',
                          'terminal', 'cancel_acknowledged', 'stop_confirmed', 'error_code'}
    assert status['schema'] == STATUS_SCHEMA
    assert set(status['goal_uuids']) == {'planner', 'navigation'}
    assert status['source'] == source()
    assert all(type(status['source'][key]) is type(source()[key]) for key in IDENTITY)


def test_navigate_mode_is_async_and_preserves_detached_typed_source_and_goal_geometry():
    result, clients = backend()
    original = source()
    requested = goal()
    operation = result.start(requested, original, operation_id='operation_a')
    original['observed_seq'] = 99
    requested['position_m'][0] = 999
    status = result.poll(operation)
    assert_status(status)
    assert status['state'] == 'sending' and not status['terminal'] and not status['stop_confirmed']
    message = clients[0].sent[0]
    assert message.pose.header.frame_id == 'map'
    assert (message.pose.header.stamp.sec, message.pose.header.stamp.nanosec) == (1, 0)
    assert message.pose.pose.position.x == 1.2 and message.pose.pose.position.y == -.3
    handle = Handle(1)
    clients[0].futures[0].resolve(handle)
    active = result.poll(operation)
    assert active['state'] == 'active' and active['goal_uuids']['navigation'] == '01' * 16
    handle.goal_id.uuid = [2] * 16
    assert result.poll(operation)['goal_uuids'] == active['goal_uuids']
    handle.result.resolve(NS(status=4, result=NS()))
    done = result.poll(operation)
    assert done['state'] == 'succeeded' and done['terminal'] and done['stop_confirmed']
    done['source']['observed_seq'] = 100
    assert_status(result.poll(operation))


def test_cancel_before_late_accept_never_claims_stopped_and_issues_one_real_cancel():
    result, clients, operation = begin()
    result.cancel(operation)
    result.cancel(operation)
    pending = result.poll(operation)
    assert pending['state'] == 'canceling' and not pending['stop_confirmed']
    handle = Handle(3)
    clients[0].futures[0].resolve(handle)
    result.poll(operation)
    result.cancel(operation)
    assert handle.cancel_calls == 1
    handle.cancel.resolve(NS(return_code=0, goals_canceling=[NS(goal_id=uid(3))]))
    ack = result.poll(operation)
    assert ack['cancel_acknowledged'] and not ack['terminal'] and not ack['stop_confirmed']
    handle.result.resolve(NS(status=5, result=NS()))
    done = result.poll(operation)
    assert done['state'] == 'canceled' and done['terminal'] and done['stop_confirmed']


@pytest.mark.parametrize('reply', [
    NS(return_code=0, goals_canceling=[NS(goal_id=uid(9))]),
    NS(return_code=1, goals_canceling=[NS(goal_id=uid(1))]),
    NS(return_code=True, goals_canceling=[NS(goal_id=uid(1))]),
])
def test_cancel_ack_requires_real_success_and_original_owned_uuid(reply):
    result, clients, operation = begin()
    handle = Handle(1)
    clients[0].futures[0].resolve(handle)
    result.poll(operation)
    result.cancel(operation)
    handle.cancel.resolve(reply)
    status = result.poll(operation)
    assert not status['cancel_acknowledged'] and not status['stop_confirmed']
    assert status['state'] in ('fault', 'canceling')
    handle.result.resolve(NS(status=5, result=NS()))
    assert result.poll(operation)['stop_confirmed']


def test_planner_success_is_not_navigation_success_and_follow_uses_actual_path():
    result, clients, operation = begin('compute_path_then_follow')
    planner = Handle(4)
    clients[0].futures[0].resolve(planner)
    assert result.poll(operation)['state'] == 'active'
    assert clients[1].sent == []
    actual_path = NS(header=NS(frame_id='map'), poses=[pose(), pose()])
    planner.result.resolve(NS(status=4, result=NS(path=actual_path)))
    status = result.poll(operation)
    assert status['state'] == 'sending' and not status['stop_confirmed']
    assert clients[0].sent[0].use_start is False and clients[0].sent[0].planner_id == 'GridBased'
    assert clients[1].sent[0].path is not actual_path
    assert len(clients[1].sent[0].path.poses) == 2
    assert clients[1].sent[0].controller_id == 'FollowPath'
    assert clients[1].sent[0].goal_checker_id == 'general_goal_checker'
    navigation = Handle(5)
    clients[1].futures[0].resolve(navigation)
    accepted = result.poll(operation)
    assert accepted['goal_uuids'] == dict(planner='04' * 16, navigation='05' * 16)
    result.cancel(operation)
    navigation.cancel.resolve(NS(return_code=0, goals_canceling=[NS(goal_id=uid(5))]))
    assert not result.poll(operation)['stop_confirmed']
    navigation.result.resolve(NS(status=5, result=NS()))
    stopped = result.poll(operation)
    assert stopped['stop_confirmed'] and stopped['cancel_acknowledged']


def test_stop_on_planner_completion_does_not_dispatch_follow_or_invent_cancel_ack():
    result, clients, operation = begin('compute_path_then_follow')
    planner = Handle(6)
    clients[0].futures[0].resolve(planner)
    result.poll(operation)
    planner.result.resolve(NS(status=4, result=NS(path=NS(header=NS(frame_id='map'), poses=[pose()]))))
    result.cancel(operation)
    status = result.poll(operation)
    assert status['state'] == 'stopped' and status['terminal'] and status['stop_confirmed']
    assert status['goal_uuids']['navigation'] is None and not status['cancel_acknowledged']
    assert clients[1].sent == []


def test_failed_planner_does_not_dispatch_follow_and_server_loss_is_not_claimed_available():
    result, clients, operation = begin('compute_path_then_follow')
    planner = Handle(7)
    clients[0].futures[0].resolve(planner)
    planner.result.resolve(NS(status=6, result=NS()))
    status = result.poll(operation)
    assert status['state'] == 'aborted' and status['stop_confirmed']
    assert clients[1].sent == []
    clients[1].available = False
    rejected = result.start(goal(), source(), operation_id='operation_b')
    status = result.poll(rejected)
    assert status['state'] == 'rejected' and status['stop_confirmed']
    assert status['error_code'] == 'action_server_unavailable'
    assert len(clients[0].sent) == 1


def test_controller_disappears_after_planning_without_dispatching_follow():
    result, clients, operation = begin('compute_path_then_follow')
    planner = Handle(8)
    clients[0].futures[0].resolve(planner)
    result.poll(operation)
    clients[1].available = False
    planner.result.resolve(NS(status=4, result=NS(path=NS(header=NS(frame_id='map'), poses=[pose()]))))
    status = result.poll(operation)
    assert status['state'] == 'rejected' and status['stop_confirmed']
    assert clients[1].sent == []
    # A graph reappearance must not resurrect an already terminal operation.
    clients[1].available = True
    assert result.poll(operation) == status
    assert clients[1].sent == []
    replacement = result.start(goal(), source(), operation_id='operation_b')
    assert result.poll(operation) == status
    assert result.poll(replacement)['state'] == 'sending'
    assert clients[1].sent == []


def test_unresolved_or_failed_send_blocks_replacement_destroy_and_stop_claim():
    result, clients, operation = begin()
    with pytest.raises(ContractError, match='previous_operation_not_stopped'):
        result.start(goal(), source(), operation_id='operation_b')
    with pytest.raises(ContractError, match='operations_not_stopped'):
        result.destroy()
    clients[0].futures[0].fail()
    result.cancel(operation)
    status = result.poll(operation)
    assert status['state'] == 'fault' and not status['terminal'] and not status['stop_confirmed']
    other, _ = backend()
    with pytest.raises(ContractError, match='foreign_operation'):
        other.cancel(operation)


@pytest.mark.parametrize('mutate', [
    lambda request: request.update(frame='world'),
    lambda request: request.update(position_m=[float('nan'), 0.]),
    lambda request: request.update(truth_pose=[0., 0.]),
])
def test_invalid_goal_never_reaches_action_client(mutate):
    result, clients = backend()
    request = goal()
    mutate(request)
    with pytest.raises(ContractError):
        result.start(request, source(), operation_id='operation_a')
    assert clients[0].sent == []


def test_unexpected_result_status_never_counts_as_terminal_or_stopped():
    result, clients, operation = begin()
    handle = Handle(1)
    clients[0].futures[0].resolve(handle)
    result.poll(operation)
    handle.result.resolve(NS(status=2, result=NS()))
    status = result.poll(operation)
    assert status['state'] == 'fault' and not status['terminal'] and not status['stop_confirmed']


def test_explicit_endpoints_and_complete_optional_dependencies():
    with pytest.raises(ContractError, match='absolute_action'):
        Nav2GoalSettings('navigate_to_pose', navigation_action='navigate_to_pose')
    with pytest.raises(ContractError, match='unused_action'):
        Nav2GoalSettings('navigate_to_pose', navigation_action='/navigate_to_pose', planner_action='/compute')
    settings = Nav2GoalSettings('navigate_to_pose', navigation_action='/navigate_to_pose')
    with pytest.raises(ContractError, match='complete_dependency'):
        Nav2GoalBackend(object(), settings, client_factory=Client)


@pytest.mark.parametrize('wire', [bytes(range(16)), bytearray(range(16)), array('B', range(16)),
                                list(range(16)), tuple(range(16)), np.arange(16, dtype=np.uint8)])
def test_strict_supported_uuid_wire_formats_have_identical_bytes(wire):
    assert _uuid(NS(uuid=wire)) == bytes(range(16)).hex()


@pytest.mark.parametrize('wire', [np.arange(16, dtype=np.float64), np.arange(16, dtype=np.int16),
    np.arange(16, dtype=np.uint8).reshape(4, 4), np.arange(15, dtype=np.uint8),
    np.arange(16, dtype=np.uint8).astype(object), [True] * 16, [1.] * 16,
    array('H', range(16)), list(np.arange(16, dtype=np.uint8))])
def test_uuid_never_coerces_malformed_dtype_shape_or_scalar_types(wire):
    with pytest.raises(ContractError, match='nav2_goal_uuid_invalid'):
        _uuid(NS(uuid=wire))


def test_actual_numpy_uint8_send_and_cancel_response_do_not_drop_accepted_goal():
    result, clients, operation = begin()
    handle = Handle(12)
    handle.goal_id.uuid = np.full((16,), 12, dtype=np.uint8)
    clients[0].futures[0].resolve(handle)
    active = result.poll(operation)
    assert active['state'] == 'active' and active['error_code'] is None
    assert active['goal_uuids']['navigation'] == '0c' * 16 and handle.result_calls == 1
    result.cancel(operation)
    handle.cancel.resolve(NS(return_code=0, goals_canceling=[
        NS(goal_id=NS(uuid=np.full((16,), 12, dtype=np.uint8)))]))
    ack = result.poll(operation)
    assert ack['cancel_acknowledged'] and not ack['stop_confirmed']
    handle.result.resolve(NS(status=5, result=NS()))
    terminal = result.poll(operation)
    assert terminal['state'] == 'canceled' and terminal['stop_confirmed'] and terminal['terminal']
    assert handle.cancel_calls == 1 and handle.result_calls == 1


def test_bad_accepted_uuid_still_cancels_and_observes_result_without_inventing_identity_proof():
    result, clients, operation = begin()
    handle = Handle(1)
    handle.goal_id.uuid = np.zeros((4, 4), dtype=np.uint8)
    clients[0].futures[0].resolve(handle)
    failed = result.poll(operation)
    assert failed['state'] == 'fault' and failed['goal_uuids']['navigation'] is None
    assert handle.cancel_calls == 1 and handle.result_calls == 1
    handle.cancel.resolve(NS(return_code=0, goals_canceling=[NS(goal_id=uid(1))]))
    handle.result.resolve(NS(status=5, result=NS()))
    still_uncertain = result.poll(operation)
    assert not still_uncertain['cancel_acknowledged'] and not still_uncertain['stop_confirmed']
    assert not still_uncertain['terminal']
    with pytest.raises(ContractError, match='operations_not_stopped'):
        result.destroy()


@pytest.mark.parametrize('wire', [np.ones((16,), dtype=np.float64), np.ones((4, 4), dtype=np.uint8)])
def test_malformed_numpy_cancel_uuid_is_not_accepted_as_the_owned_goal(wire):
    result, clients, operation = begin()
    handle = Handle(1)
    handle.goal_id.uuid = np.ones((16,), dtype=np.uint8)
    clients[0].futures[0].resolve(handle)
    accepted = result.poll(operation)
    result.cancel(operation)
    handle.cancel.resolve(NS(return_code=0, goals_canceling=[NS(goal_id=NS(uuid=wire))]))
    failed = result.poll(operation)
    assert failed['state'] == 'fault' and not failed['cancel_acknowledged']
    assert failed['goal_uuids'] == accepted['goal_uuids'] and not failed['stop_confirmed']
    assert handle.cancel_calls == 1


@pytest.mark.parametrize('recover', [True, False])
def test_get_result_getter_failure_preserves_handle_and_requires_genuine_terminal_proof(recover):
    result, clients, operation = begin()
    class FailingGetter(Handle):
        def get_result_async(self):
            self.result_calls += 1
            if self.result_calls == 1 or not recover:
                raise RuntimeError('synthetic synchronous getter failure')
            return self.result
    handle = FailingGetter(13)
    handle.goal_id.uuid = np.full((16,), 13, dtype=np.uint8)
    clients[0].futures[0].resolve(handle)
    failed = result.poll(operation)
    assert failed['state'] == 'fault' and not failed['stop_confirmed']
    assert handle.cancel_calls == 1 and handle.result_calls == 1
    handle.cancel.resolve(NS(return_code=0, goals_canceling=[
        NS(goal_id=NS(uuid=np.full((16,), 13, dtype=np.uint8)))]))
    if recover:
        handle.result.resolve(NS(status=5, result=NS()))
    for _ in range(4):
        status = result.poll(operation)
    assert handle.cancel_calls == 1 and handle.result_calls == 2
    assert status['cancel_acknowledged'] and status['state'] == 'fault'
    assert status['stop_confirmed'] is recover and status['terminal'] is recover
