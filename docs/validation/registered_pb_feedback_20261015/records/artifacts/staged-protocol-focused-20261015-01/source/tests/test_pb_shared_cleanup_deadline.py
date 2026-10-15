"""Shared resource deadline checks with deterministic process/executor doubles."""
from unittest.mock import Mock, patch
import pytest

from tools.pb_navigation_stack import PBNavigationStack
from rm_match.integrations.pb_navigation_transport import HumbleNavigationTransport
from rm_match.integrations.ros2_bridge import BridgeError


def test_stack_does_not_give_reap_or_executor_a_new_budget(tmp_path):
    stack=PBNavigationStack({},tmp_path/'unused')
    process=Mock(pid=45678)
    process.poll.return_value=0;process.wait.return_value=0
    stack.processes={'fixture':process};stack._members=lambda pid:[]
    stack.executor=Mock();stack.executor.shutdown.return_value=True
    with patch('tools.pb_navigation_stack.time.perf_counter',return_value=10.),patch('tools.pb_navigation_stack.os.killpg'):
        result=stack.stop(grace_s=.15,deadline=10.04)
    assert result['clean']
    assert 0<=process.wait.call_args.kwargs['timeout']<=.0400001
    assert 0<=stack.executor.shutdown.call_args.kwargs['timeout_sec']<=.0400001


def test_expired_stack_deadline_reports_failure_and_does_not_wait_again(tmp_path):
    stack=PBNavigationStack({},tmp_path/'unused')
    process=Mock(pid=45678);process.poll.return_value=0;process.wait.return_value=0
    stack.processes={'fixture':process};stack._members=lambda pid:[]
    stack.executor=Mock();stack.executor.shutdown.return_value=True
    with patch('tools.pb_navigation_stack.time.perf_counter',return_value=10.),patch('tools.pb_navigation_stack.os.killpg'):
        result=stack.stop(grace_s=.15,deadline=9.99)
    assert not result['clean'] and 'shared_cleanup_deadline_exceeded' in result['errors']
    assert process.wait.call_args.kwargs['timeout']==0
    assert stack.executor.shutdown.call_args.kwargs['timeout_sec']==0


def transport():
    value=HumbleNavigationTransport.__new__(HumbleNavigationTransport)
    value._closed=False;value._close_error=False
    value.node=Mock();value.context=Mock();value._rclpy=Mock();value.executor=Mock()
    value.executor.shutdown.return_value=True
    return value


def test_transport_uses_remaining_resource_deadline_and_still_releases_context():
    value=transport()
    with patch('rm_match.integrations.pb_navigation_transport.time.perf_counter',return_value=10.):
        value.close(deadline=10.02)
    assert 0<value.executor.shutdown.call_args.kwargs['timeout_sec']<=.0200001
    value.node.destroy_node.assert_called_once();value._rclpy.try_shutdown.assert_called_once_with(context=value.context)


def test_expired_transport_deadline_never_claims_clean():
    value=transport()
    with patch('rm_match.integrations.pb_navigation_transport.time.perf_counter',return_value=10.):
        with pytest.raises(BridgeError,match='shutdown_incomplete'):value.close(deadline=9.99)
    assert value.executor.shutdown.call_args.kwargs['timeout_sec']==0 and value._close_error


@pytest.mark.parametrize('deadline',[True,float('nan'),float('inf'),'10'])
def test_invalid_cleanup_deadline_rejected_before_resource_mutation(tmp_path,deadline):
    stack=PBNavigationStack({},tmp_path/'unused');value=transport()
    with pytest.raises(ValueError):stack.stop(deadline=deadline)
    with pytest.raises(BridgeError):value.close(deadline=deadline)
    assert not stack.closed and not value._closed
