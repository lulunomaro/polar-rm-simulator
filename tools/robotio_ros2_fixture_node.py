"""Synthetic RobotIO DDS protocol fixture, NOT a team's navigation/decision.

No simulator, localization, planning, model or actuator is instantiated.
Only the observation's exact source identity can be echoed into a fixture DTO.
"""
from __future__ import annotations
import argparse
import copy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rm_match.integrations.robotio_ros2_bridge import RobotIOSettings
from rm_match.integrations.ros2_bridge import ENVELOPE_SCHEMA, MAX_REQUEST, MAX_RESPONSE, parse_json, encode_json
from rm_match.platform_v2.contracts import ContractError, exact, identity, action_for


class ProtocolFixture:
    def __init__(self, settings):
        self.settings = settings; self.context = None; self.last_seq = -1
        if settings.kind == 'navigation':
            from rm_match.deployment.navigation_plugin import CAPABILITIES
        else:
            from rm_match.deployment.decision_plugin import CAPABILITIES
        self.capabilities = copy.deepcopy(CAPABILITIES)

    def response(self, payload):
        packet = parse_json(payload, MAX_REQUEST)
        if type(packet) is not dict or type(packet.get('schema')) is not str or packet['schema'] != ENVELOPE_SCHEMA or type(packet.get('adapter_id')) is not str or packet['adapter_id'] != self.settings.adapter_id:
            raise ContractError('fixture_route_mismatch')
        if packet.get('type') == 'capabilities_request':
            exact(packet, ('schema', 'type', 'adapter_id', 'context', 'capabilities'), 'fixture_capability_request')
            exact(packet['context'], ('episode', 'robot_id', 'binding_epoch'), 'fixture_context')
            identity(dict(packet['context'], observed_seq=0, sim_time=0., wall_deadline=0.))
            if self.context is not None: raise ContractError('fixture_negotiation_once')
            if self.settings.kind == 'navigation':
                from rm_match.deployment.navigation_plugin import validate_capabilities
            else:
                from rm_match.deployment.decision_plugin import validate_capabilities
            if validate_capabilities(packet['capabilities']) != self.capabilities:
                raise ContractError('fixture_unknown_capabilities')
            self.context = dict(packet['context'])
            result = dict(type='capabilities', context=dict(self.context), capabilities=copy.deepcopy(self.capabilities))
        elif packet.get('type') == 'observation':
            exact(packet, ('schema', 'type', 'adapter_id', 'observation'), 'fixture_observation_request')
            if self.context is None: raise ContractError('fixture_negotiation_required')
            if self.settings.kind == 'navigation':
                from rm_match.platform_v2.navigation_contracts import validate_navigation_observation
                o = validate_navigation_observation(packet['observation'])
            else:
                from rm_match.platform_v2.decision_contracts import validate_decision_observation
                o = validate_decision_observation(packet['observation'])
            if any(type(o[k]) is not type(v) or o[k] != v for k,v in self.context.items()) or o['observed_seq'] <= self.last_seq:
                raise ContractError('fixture_source_generation_or_sequence')
            if self.settings.kind == 'navigation':
                value = action_for(o, 'navigation', 'velocity_body', dict(frame='base_link', vx_mps=.2, vy_mps=.1, wz_rps=.3))
                result = dict(type='action', action=value)
            else:
                from rm_match.platform_v2.decision_contracts import decision_intent_for
                result = dict(type='intent', intent=decision_intent_for(o, dict(behavior='hold', reason='synthetic_protocol_fixture')))
            self.last_seq = o['observed_seq']
        else: raise ContractError('fixture_unknown_envelope_type')
        return encode_json(dict(schema=ENVELOPE_SCHEMA, adapter_id=self.settings.adapter_id, **result), MAX_RESPONSE).decode()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ('adapter-id', 'kind', 'node-name', 'observation-topic', 'action-topic'):
        p.add_argument('--'+name, required=True)
    p.add_argument('--domain-id', type=int, required=True)
    settings = RobotIOSettings(**vars(p.parse_args(argv)))
    fixture = ProtocolFixture(settings); transport = None; fault = []; code = 0
    try:
        from rm_match.integrations.ros2_bridge_transport import RclpyTransport
        # Reverse topics so this node receives requests and publishes responses.
        reverse = RobotIOSettings(adapter_id=settings.adapter_id, kind=settings.kind,
            node_name=settings.node_name, observation_topic=settings.action_topic,
            action_topic=settings.observation_topic, domain_id=settings.domain_id)
        def receive(payload):
            try: transport.publish(fixture.response(payload))
            except Exception as exc:
                if not fault: fault.append(type(exc).__name__)
                raise
        transport = RclpyTransport(reverse, receive)
        while not fault: transport.spin_once(.01)
        raise ContractError('fixture_invalid_request')
    except KeyboardInterrupt: code = 130
    except Exception:
        print('robotio_fixture_node_failed', file=sys.stderr, flush=True); code = 2
    finally:
        try:
            if transport is not None: transport.close()
        except Exception:
            print('robotio_fixture_node_cleanup_incomplete', file=sys.stderr, flush=True); code = 2
    return code


if __name__ == '__main__': raise SystemExit(main())
