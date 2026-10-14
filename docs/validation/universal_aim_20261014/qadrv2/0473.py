#!/usr/bin/env python3
"""Bind an existing OFFLINE24 execution; never render, infer, or modify evidence."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out = args.out.resolve()
    run = args.run_root.resolve()
    result = json.loads((run / 'RESULT.json').read_text())
    ledger = [json.loads(line) for line in (run / 'ledger.jsonl').read_text().splitlines()]
    requests = [x for x in ledger if x['event'] == 'native_request']
    responses = [x for x in ledger if x['event'] == 'native_result']
    physics = [x for x in ledger if x['event'] == 'offline_physics']
    consumed = [x for x in physics if (x['target'].get('gimbal') or {}).get('active') is True]
    for req, res in zip(requests, responses, strict=True):
        for key in ('frame_id', 'episode', 'observed_seq', 'raw_bgr_sha256', 'schedule', 'own_at_capture'):
            assert req[key] == res[key], key
    assert len(requests) == len(responses) == 13
    assert result['qualified_static_offline_chain'] is True
    assert result['clean_shutdown'] is True
    assert result['counts']['fire_true'] == 0
    assert len(consumed) == result['counts']['native_gimbal_consumed']
    matching_controls = [x for x in consumed if x['actuator_ctrl'][3:] == [
        x['target']['gimbal']['yaw_rad'], x['target']['gimbal']['pitch_rad']]]
    changed_joints = [x for x in consumed if x['qpos_before'][3:] != x['qpos_after'][3:]]
    assert len(matching_controls) == len(changed_joints) == len(consumed)
    source_files = ['tools/smoke_offline_deployment.py',
        'tools/offline_smoke/offline_client_driver.py', 'tools/offline_smoke/preload_contract.py',
        'rm_match/platform_v2/offline_runtime.py', 'rm_match/platform_v2/offline_native.py',
        'rm_match/platform_v2/native_adapter.py', 'rm_match/operator/source_aim.py',
        'rm_match/platform_v2/state_projection.py',
        'operator_native/runtime/overlays/corners_contour_v3.cpp']
    report = dict(schema='polar.pnp.static-chain-evidence.v1', run_root=run.relative_to(ROOT).as_posix(),
        result={k: result[k] for k in ('profile', 'state', 'reason', 'wall_seconds', 'sim_time',
            'counts', 'native_binary_sha256', 'spec_sha256', 'client_identity', 'errors',
            'clean_shutdown', 'qualified_static_offline_chain', 'live_default_qualified', 'full_match_qualified')},
        native_measurements=dict(results=len(responses),
            pose_results=sum(x['response']['pose_estimated3d'] > 0 for x in responses),
            total_estimated_poses=sum(x['response']['pose_estimated3d'] for x in responses),
            tracking=sum(x['response']['tracking'] is True for x in responses),
            should_control=sum(x['response']['should_control'] is True for x in responses),
            observation_shoot_allowed=sum(x['response']['observation_shoot_allowed'] is True for x in responses),
            should_shoot=sum(x['response']['should_shoot'] is True for x in responses),
            target_age_s=sorted(set(x['response']['target_age_s'] for x in responses)),
            mode=sorted(set(x['response']['runtime_mode_observed_config'] for x in responses)),
            source_frame_ids=[x['frame_id'] for x in responses],
            request_result_sensor_binding_verified=True),
        physical_consumption=dict(active_steps=len(consumed), exact_actuator_target_matches=len(matching_controls),
            steps_with_actual_joint_change=len(changed_joints), first_active_step=consumed[0], last_active_step=consumed[-1]),
        preload_admission=json.loads((run/'PRELOAD_ADMISSION.json').read_text()),
        input_boundary=dict(native_image='Actual MuJoCo RGB rendered pixels converted to contiguous BGR; no synthetic corners',
            packet='BGR image, source K/D calibration, exposure time and own capture-state only',
            no_target_truth='Target truth is absent from native_adapter frame construction; ledger sensor binding records own state only',
            qualification='Source inspection plus actual trace; complete input bytes were not independently logged for all frames'),
        source_snapshot_semantics='Hashes taken immediately after run, not an independent pre-execution snapshot. Native ELF/spec/model validated by runtime; later cancellation cleanup revision is not qualified by this execution.',
        simulator_post_run_source_sha256={p:sha(ROOT/p) for p in source_files},
        native_model_sha256='b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255',
        evidence_sha256={p.name:sha(p) for p in run.iterdir() if p.is_file() and p.name != 'admission.json'},
        preserved_failures=[f'artifacts/pnp-native-contour-v3-offline24-attempt{i}-20261013' for i in (2,3)],
        scope='Fixed-scene OFFLINE24 static tracker/actuator chain only; no realtime, full match, physical calibration, hardware or later cancellation-repair qualification')
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out/'CHAIN_REPORT.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    (args.out/'NATIVE_RESULTS.json').write_text(json.dumps(responses, indent=2)+'\n', encoding='utf-8')
    files = [*args.out.iterdir(), Path(__file__).resolve()]
    (args.out/'EVIDENCE_MANIFEST.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p) for p in files}, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report['native_measurements'], indent=2))


if __name__ == '__main__':
    main()
