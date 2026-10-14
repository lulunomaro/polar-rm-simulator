"""Synthetic compute callback; no second detector or real-time claim."""
import io
import json
import subprocess
import sys
from pathlib import Path
import pytest
from rm_match.integrations.aim_jsonl_peer import serve_aim_plugin
from rm_match.integrations.ros2_bridge import JSONL_SCHEMA
from rm_match.platform_v2.aim_contracts import aim_status_for
from rm_match.platform_v2.contracts import ContractError
from rm_match.platform_v2.test_contracts import sample

def requests(o):
    return [dict(schema=JSONL_SCHEMA,op='reset',context={k:o[k] for k in ('episode','robot_id','binding_epoch')},config={}),
        dict(schema=JSONL_SCHEMA,op='act',observation=o)]
def run(rows,compute):
    output=io.BytesIO();serve_aim_plugin(compute,io.BytesIO(('\n'.join(json.dumps(r) for r in rows)+'\n').encode()),output)
    return [json.loads(r) for r in output.getvalue().splitlines()]

def test_explicit_no_target_keeps_exact_capture_source_no_hold():
    o=sample(True)
    def compute(b,current):
        assert b.source_context['frame_id']==current['sensors']['camera']['frame_id']
        assert b.source_context['wall_deadline']==o['wall_deadline']
        return aim_status_for(current,'no_target')
    result=run(requests(o),compute)
    assert result[-1]['status']==aim_status_for(o,'no_target') and 'action' not in result[-1]
def test_missing_result_is_not_implicit_success_or_zero_action():
    with pytest.raises(ContractError):run(requests(sample(True)),lambda b,o:None)
def test_stale_result_cannot_be_associated_with_new_source():
    o=sample(True);old=aim_status_for(o,'no_target');o['observed_seq']+=1
    with pytest.raises(ContractError):run(requests(o),lambda b,current:old)
def test_callback_mutation_cannot_change_original_response_identity():
    def compute(bundle,current):
        current['binding_epoch']+=1
        return aim_status_for(current,'no_target')
    with pytest.raises(ContractError):run(requests(sample(True)),compute)
def test_replay_and_bool_generation_are_rejected():
    o=sample(True);rows=requests(o);rows.append(rows[-1])
    with pytest.raises(ContractError,match='replayed'):run(rows,lambda b,o:aim_status_for(o,'pending_result'))
    rows=requests(o);rows[0]['context']['episode']=True
    with pytest.raises(ContractError):run(rows,lambda b,o:aim_status_for(o,'no_target'))

def test_actual_harmless_wrapper_factory_and_library_stdout_are_protocol_safe(tmp_path):
    root=Path(__file__).resolve().parents[1];wrapper=tmp_path/'peer.py'
    wrapper.write_text('import os,sys\nsys.path.insert(0,'+repr(str(root))+')\n'
        'from rm_match.integrations.aim_jsonl_peer import run_aim_plugin\n'
        'from rm_match.platform_v2.aim_contracts import aim_status_for\n'
        'def factory():\n'
        ' os.write(1,b"synthetic library startup\\n")\n'
        ' def compute(bundle,o):\n'
        '  print("synthetic callback log",flush=True)\n'
        '  return aim_status_for(o,"no_target")\n'
        ' return compute\n'
        'raise SystemExit(run_aim_plugin(factory))\n')
    o=sample(True);raw=('\n'.join(json.dumps(r) for r in requests(o))+'\n').encode()
    child=subprocess.run([sys.executable,str(wrapper)],input=raw,capture_output=True,timeout=2.)
    assert child.returncode==0
    rows=[json.loads(r) for r in child.stdout.splitlines()]
    assert len(rows)==2 and rows[-1]['status']==aim_status_for(o,'no_target')
    assert b'synthetic library startup' in child.stderr and b'synthetic callback log' in child.stderr
