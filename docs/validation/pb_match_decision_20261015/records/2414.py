"""Validate the plan's development preset without granting acceptance labels."""
from __future__ import annotations

import math

REQUIREMENT_TESTS = {
    'R01': ['A07', 'A08'], 'R02': ['A01', 'A02', 'A03', 'A05', 'A11'],
    'R03': ['A02', 'A09'], 'R04': ['A03', 'A04', 'A08'],
    'R05': ['A04', 'A05', 'A06', 'A14'], 'R06': ['A07', 'A10'],
    'R07': ['A10', 'A11'], 'R08': ['A06', 'A12'], 'R09': ['A01'],
    'R10': ['A13'], 'R11': ['A14'], 'R12': ['A15'],
}
TEST_IDS = {f'A{i:02d}' for i in range(1, 16)}
MODEL_SHA256 = 'b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255'


def validate_preset(value):
    """Return unresolved freeze fields. Invalid invariants raise ValueError.

    This is configuration validation, never certification of a test result.
    """
    if value.get('schema') != 'polar.acceptance.v1' or value.get('revision') != 1:
        raise ValueError('unsupported_acceptance_version')
    if value.get('requirements') != REQUIREMENT_TESTS:
        raise ValueError('requirement_test_traceability_mismatch')
    if set(value.get('acceptance', {})) != TEST_IDS:
        raise ValueError('acceptance_matrix_incomplete')
    allowed = {'not_run', 'failed', 'blocked', 'requires_separate_hardware_authorization'}
    if any(s not in allowed for s in value['acceptance'].values()):
        raise ValueError('acceptance_preset_cannot_claim_pass_without_evidence')
    if value.get('components', {}).get('model_sha256') != MODEL_SHA256:
        raise ValueError('default_model_identity_changed')
    profiles = value.get('profiles', {})
    if set(profiles) != {'live', 'offline'}:
        raise ValueError('independent_live_offline_profiles_required')
    for name, expected_clock, wait in [('live', 'wall_deadline_live', False),
                                      ('offline', 'offline_modeled_latency_v1', True)]:
        p = profiles[name]
        if p.get('clock_profile') != expected_clock or p.get('wait_for_algorithm') is not wait:
            raise ValueError('clock_semantics_changed:' + name)
        for key, expected in [('native_image_max_age_s', .08), ('input_window_s', .15)]:
            if type(p.get(key)) not in (int, float) or p[key] != expected:
                raise ValueError('original_native_deadline_changed:' + name + ':' + key)
    if profiles['live'].get('real_time_factor') != 1 or profiles['offline'].get('real_time_factor') is not None:
        raise ValueError('offline_cannot_claim_live_rtf')
    c = value.get('conditions', {})
    for key in ('physics_step_s', 'camera_total_fps_limit', 'duration_s'):
        if type(c.get(key)) not in (int, float) or not math.isfinite(c[key]) or c[key] <= 0:
            raise ValueError('invalid_test_condition:' + key)
    for key in ('robot_count', 'active_views', 'seed'):
        if type(c.get(key)) is not int or c[key] < (0 if key == 'seed' else 1):
            raise ValueError('invalid_test_condition:' + key)
    if c['active_views'] > c['robot_count']:
        raise ValueError('views_exceed_roster')
    if c.get('camera_resolution') != [1440, 1080]:
        raise ValueError('default_native_camera_resolution_changed')
    if not value.get('unresolved') or any(not row.get('responsible_role') for row in value['unresolved']):
        raise ValueError('unresolved_items_need_responsible_roles')
    pending = ['conditions.' + k for k, v in c.items() if v is None]
    pending += ['quality_thresholds.' + k for k, v in value.get('quality_thresholds', {}).items() if v is None]
    pending += [row['id'] for row in value['unresolved'] if not row.get('owner')]
    if value.get('status') not in ('draft', 'frozen'):
        raise ValueError('invalid_freeze_status')
    if value['status'] == 'frozen' and pending:
        raise ValueError('cannot_freeze_unresolved_preset')
    return pending
