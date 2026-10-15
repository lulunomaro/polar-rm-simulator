"""Controlled decision-v2 envelope checks; no actual DDS evidence."""
import copy
import pytest

from rm_match.integrations.robotio_ros2_bridge import RobotIOEnvelopeBridge, RobotIOSettings
from rm_match.deployment.decision_plugin import NAVIGATION_CAPABILITIES, CAPABILITIES
from rm_match.platform_v2.contracts import ContractError, IDENTITY
from rm_match.platform_v2.decision_contracts import build_decision_observation
from rm_match.platform_v2.navigation_feedback_contracts import unavailable_navigation_feedback
from test_navigation_plugin import observation
from test_robotio_ros2_bridge import Clock, Transport, context


def settings(profile='own_referee_navigation_v2'):
    return RobotIOSettings('custom_estimated_decision','decision','decision_v2_fixture',
        '/fixture/input','/fixture/output',80,.15,decision_profile=profile)


def test_explicit_v2_negotiates_and_passes_original_feedback_unchanged():
    clock=Clock();core=RobotIOEnvelopeBridge(settings(),clock=clock)
    nav=observation();nav['wall_deadline']=17.
    feedback=unavailable_navigation_feedback(nav,'pending_localization')
    current=build_decision_observation(nav,feedback,profile='own_referee_navigation_v2')
    core.reset(context(nav),{});transport=Transport(core,clock)
    core.negotiate(transport)
    assert core.capabilities==NAVIGATION_CAPABILITIES
    result=core.exchange(current,transport)
    assert transport.published[-1]['observation']==current
    assert all(type(result[k]) is type(nav[k]) and result[k]==nav[k] for k in IDENTITY)
    assert result['command']['behavior']=='hold' and 'fire' not in result['command']
    assert core.clock()==100. and current['wall_deadline']==17.


@pytest.mark.parametrize('profile,wrong',[('own_referee_v1','own_referee_navigation_v2'),
    ('own_referee_navigation_v2','own_referee_v1')])
def test_reset_negotiation_never_allows_other_observation_profile(profile,wrong):
    clock=Clock();core=RobotIOEnvelopeBridge(settings(profile),clock=clock);nav=observation()
    core.reset(context(nav),{});transport=Transport(core,clock);core.negotiate(transport)
    other=build_decision_observation(nav,profile=wrong)
    count=len(transport.published)
    with pytest.raises(ContractError):core.exchange(other,transport)
    assert len(transport.published)==count


def test_v2_handshake_cannot_accept_v1_capability_response():
    clock=Clock();core=RobotIOEnvelopeBridge(settings(),clock=clock);nav=observation()
    core.reset(context(nav),{})
    transport=Transport(core,clock,alter=lambda row:row.update(capabilities=copy.deepcopy(CAPABILITIES)))
    with pytest.raises(ContractError,match='capability_mismatch'):core.negotiate(transport)
    assert not core._negotiated
