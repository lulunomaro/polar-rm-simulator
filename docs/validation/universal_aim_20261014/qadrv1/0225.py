"""Typed camera-driven aim progress without fabricated motion or detection.

Status retains the submitted observation identity. It is not an actuator command
or evidence of successful inference, tracking, firing, or real-time qualification.
"""
from __future__ import annotations
import copy
from .contracts import ContractError, IDENTITY, OBS_SCHEMA, exact, identity

AIM_STATUS_SCHEMA = 'polar.sim.aim-status.v1'
AIM_PLUGIN_CONTRACT = 'camera_gimbal_v1'


def validate_aim_status(value, observation):
    value = copy.deepcopy(value)
    exact(value, ('schema', *IDENTITY, 'kind', 'status'), 'aim_status')
    identity(value)
    if (type(observation) is not dict or observation.get('schema') != OBS_SCHEMA
        or type(value['schema']) is not str or value['schema'] != AIM_STATUS_SCHEMA
        or type(value['kind']) is not str or value['kind'] != 'aim'
        or type(value['status']) is not str or value['status'] not in ('no_target', 'pending_result')
        or any(type(value[k]) is not type(observation[k]) or value[k] != observation[k] for k in IDENTITY)):
        raise ContractError('aim_status_identity_or_state')
    return value


def aim_status_for(observation, status):
    return validate_aim_status(dict(schema=AIM_STATUS_SCHEMA,
        **{k: observation[k] for k in IDENTITY}, kind='aim', status=status), observation)
