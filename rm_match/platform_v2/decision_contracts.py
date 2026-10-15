"""Own-referee decision inputs and source-bound high-level navigation intents.

No ideal localization, enemy state, actuator command, or fire authority is part
of this profile. A map goal declares an intent; it does not prove map calibration.
"""
from __future__ import annotations

import copy
import math

from .contracts import (ContractError, IDENTITY, boolean, exact, finite, identity,
                        string, vector)
from .navigation_contracts import validate_navigation_observation

DECISION_OBSERVATION_SCHEMA = 'polar.sim.decision-observation.v1'
DECISION_INTENT_SCHEMA = 'polar.sim.decision-intent.v1'
UNAVAILABLE_REASON = 'not_provided_in_own_referee_v1'


def validate_decision_observation(value):
    value = copy.deepcopy(value)
    exact(value, ('schema', *IDENTITY, 'own', 'referee', 'navigation', 'perception'),
          'decision_observation')
    if type(value['schema']) is not str or value['schema'] != DECISION_OBSERVATION_SCHEMA:
        raise ContractError('unsupported_decision_observation')
    identity(value)
    own = value['own']
    exact(own, ('team', 'role', 'hp', 'ammo', 'heat', 'alive'), 'decision_own')
    for name in ('team', 'role'):
        string(own[name], name)
    for name in ('hp', 'ammo', 'heat'):
        finite(own[name], name, 0)
    boolean(own['alive'], 'decision_alive')
    referee = value['referee']
    exact(referee, ('phase', 'remaining_seconds', 'emergency_stop'), 'decision_referee')
    if (type(referee['phase']) is not str or referee['phase'] not in
            ('running', 'paused', 'idle', 'finished', 'countdown')):
        raise ContractError('invalid_decision_phase')
    finite(referee['remaining_seconds'], 'decision_remaining_seconds', 0)
    boolean(referee['emergency_stop'], 'decision_emergency_stop')
    for name in ('navigation', 'perception'):
        exact(value[name], ('available', 'reason'), 'decision_' + name)
        if (value[name]['available'] is not False or
                type(value[name]['reason']) is not str or
                value[name]['reason'] != UNAVAILABLE_REASON):
            raise ContractError('unsupported_decision_' + name + '_profile')
    return value


def build_decision_observation(navigation_observation):
    """Project a validated own-only sensor DTO, never its ideal odometry."""
    original = validate_navigation_observation(navigation_observation)
    unavailable = dict(available=False, reason=UNAVAILABLE_REASON)
    return validate_decision_observation(dict(
        schema=DECISION_OBSERVATION_SCHEMA,
        **{name: original[name] for name in IDENTITY},
        own=copy.deepcopy(original['own']), referee=copy.deepcopy(original['referee']),
        navigation=copy.deepcopy(unavailable), perception=copy.deepcopy(unavailable)))


def _decision_intent_header(value):
    value = copy.deepcopy(value)
    exact(value, ('schema', *IDENTITY, 'kind', 'mode', 'command'), 'decision_intent')
    identity(value)
    if (type(value['schema']) is not str or value['schema'] != DECISION_INTENT_SCHEMA or
            type(value['kind']) is not str or value['kind'] != 'decision' or
            type(value['mode']) is not str or value['mode'] != 'navigation_intent'):
        raise ContractError('decision_intent_identity_or_mode')
    return value


def _decision_intent_command(value):
    command = value['command']
    if type(command) is not dict or type(command.get('behavior')) is not str:
        raise ContractError('invalid_decision_command')
    behavior = command['behavior']
    if behavior in ('hold', 'cancel'):
        exact(command, ('behavior', 'reason'), 'decision_stop_intent')
    elif behavior == 'navigate_to_pose':
        exact(command, ('behavior', 'reason', 'goal'), 'decision_pose_intent')
        goal = command['goal']
        exact(goal, ('frame', 'position_m', 'yaw_rad'), 'decision_goal')
        if type(goal['frame']) is not str or goal['frame'] != 'map':
            raise ContractError('unsupported_decision_goal_frame')
        vector(goal['position_m'], 2, 'decision_goal_position', -100000, 100000)
        finite(goal['yaw_rad'], 'decision_goal_yaw', -math.pi, math.pi)
    else:
        raise ContractError('unsupported_decision_behavior')
    string(command['reason'], 'decision_reason')
    if '\0' in command['reason']:
        raise ContractError('invalid_decision_reason')
    return value


def validate_decision_intent_shape(value):
    """Check a goal-only envelope; this does not prove a sensor or authority.

    Goal lifecycle consumers need no fabricated own/referee observation. The
    normal decision/navigation path still compares against the original input.
    """
    return _decision_intent_command(_decision_intent_header(value))


def validate_decision_intent(value, observation):
    observation = validate_decision_observation(observation)
    value = _decision_intent_header(value)
    if any(type(value[name]) is not type(observation[name]) or
           value[name] != observation[name] for name in IDENTITY):
        raise ContractError('decision_intent_identity_or_mode')
    return _decision_intent_command(value)


def decision_intent_for(observation, command):
    observation = validate_decision_observation(observation)
    return validate_decision_intent(dict(
        schema=DECISION_INTENT_SCHEMA, **{name: observation[name] for name in IDENTITY},
        kind='decision', mode='navigation_intent', command=copy.deepcopy(command)), observation)
