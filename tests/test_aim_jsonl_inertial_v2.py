"""Version negotiation and synthetic callbacks; no moving algorithm qualification."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest

from rm_match.deployment.aim_plugin import CAPABILITIES, CAPABILITIES_V2
from rm_match.integrations.aim_jsonl_peer import serve_aim_plugin
from rm_match.integrations.ros2_bridge import JSONL_SCHEMA
from rm_match.platform_v2.aim_contracts import aim_status_for
from rm_match.platform_v2.contracts import ContractError
from rm_match.platform_v2.test_contracts import sample


def messages(o, caps):
    challenge = {} if caps is None else {'capabilities': copy.deepcopy(caps)}
    return [dict(schema=JSONL_SCHEMA, op='prepare', config={}, **challenge),
        dict(schema=JSONL_SCHEMA, op='reset', context={k:o[k] for k in ('robot_id','episode','binding_epoch')},
             config={}, **copy.deepcopy(challenge)),
        dict(schema=JSONL_SCHEMA, op='act', observation=o)]


def serve(rows, local_caps, compute=None):
    output = io.BytesIO()
    if compute is None:compute = lambda bundle,o: aim_status_for(o, 'pending_result')
    data = b''.join(json.dumps(x).encode()+b'\n' for x in rows)
    serve_aim_plugin(compute, io.BytesIO(data), output, capabilities=local_caps)
    return [json.loads(x) for x in output.getvalue().splitlines()]


def test_v2_challenge_matches_independent_local_declaration_before_any_compute():
    o = sample(True);calls = []
    def compute(bundle, value):
        calls.append(bundle.source_context)
        return aim_status_for(value, 'no_target')
    rows = serve(messages(o, CAPABILITIES_V2), CAPABILITIES_V2, compute)
    assert rows[:2] == [dict(schema=JSONL_SCHEMA, op=op, ok=True, capabilities=CAPABILITIES_V2)
                       for op in ('prepare','reset')]
    assert rows[2]['status'] == aim_status_for(o, 'no_target')
    assert len(calls) == 1 and calls[0]['wall_deadline'] == o['wall_deadline']


@pytest.mark.parametrize('local,challenge', [(None, CAPABILITIES_V2), (CAPABILITIES_V2, None),
                                           (CAPABILITIES_V2, CAPABILITIES)])
def test_no_silent_upgrade_or_downgrade(local, challenge):
    with pytest.raises(ContractError):serve(messages(sample(True), challenge), local)


@pytest.mark.parametrize('op_index', [0,1])
def test_v2_does_not_echo_arbitrary_peer_requested_capabilities(op_index):
    rows = messages(sample(True), CAPABILITIES_V2)
    rows[op_index]['capabilities']['gimbal_reference'] = 'latest_base_or_target_guess'
    calls = []
    with pytest.raises(ContractError):
        serve(rows, CAPABILITIES_V2, lambda *_: calls.append(True))
    assert calls == []


def test_v1_keeps_original_three_field_acknowledgements():
    rows = serve(messages(sample(True), None), CAPABILITIES)
    assert rows[:2] == [dict(schema=JSONL_SCHEMA, op=op, ok=True) for op in ('prepare','reset')]


def test_v2_requires_original_own_odometry_and_never_uses_capture_as_current():
    o = sample(True);o['own']['odom_xyyaw'] = None;o['own']['odom_vxyw'] = None
    calls = []
    with pytest.raises(ContractError, match='odometry_unavailable'):
        serve(messages(o, CAPABILITIES_V2), CAPABILITIES_V2, lambda *_: calls.append(True))
    assert calls == []


def test_real_harmless_process_uses_explicit_v2_and_preserves_source(tmp_path):
    root = Path(__file__).resolve().parents[1];wrapper = tmp_path/'reviewed_fixture.py'
    wrapper.write_text('import sys\nsys.path.insert(0,'+repr(str(root))+')\n'
        'from rm_match.deployment.aim_plugin import CAPABILITIES_V2\n'
        'from rm_match.integrations.aim_jsonl_peer import run_aim_plugin\n'
        'from rm_match.platform_v2.aim_contracts import aim_status_for\n'
        'def factory():\n'
        ' def compute(bundle,o):return aim_status_for(o,"pending_result")\n'
        ' return compute\n'
        'raise SystemExit(run_aim_plugin(factory,capabilities=CAPABILITIES_V2))\n', encoding='utf8')
    o = sample(True);data = b''.join(json.dumps(x).encode()+b'\n' for x in messages(o, CAPABILITIES_V2))
    child = subprocess.run([sys.executable,str(wrapper)], input=data, capture_output=True, timeout=3.)
    assert child.returncode == 0
    rows = [json.loads(x) for x in child.stdout.splitlines()]
    assert rows[0]['capabilities'] == rows[1]['capabilities'] == CAPABILITIES_V2
    assert rows[2]['status'] == aim_status_for(o, 'pending_result')
