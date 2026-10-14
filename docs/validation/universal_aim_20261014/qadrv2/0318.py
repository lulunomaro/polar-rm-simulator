import copy
import json
from pathlib import Path
import unittest
from rm_match.acceptance import validate_preset

ROOT = Path(__file__).resolve().parents[1]


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.preset = json.loads((ROOT/'config/acceptance/m1-v1.json').read_text())

    def test_draft_exposes_missing_decisions(self):
        self.assertIn('conditions.target_hardware', validate_preset(self.preset))
        self.assertIn('U05', validate_preset(self.preset))

    def test_cannot_freeze_missing_hardware_or_owners(self):
        self.preset['status'] = 'frozen'
        with self.assertRaisesRegex(ValueError, 'cannot_freeze'): validate_preset(self.preset)

    def test_reject_gate_relaxation_and_offline_live_substitution(self):
        for profile,key,wrong in [('live','native_image_max_age_s',.15),
                                  ('live','input_window_s',.25),
                                  ('offline','wait_for_algorithm',False),
                                  ('offline','clock_profile','wall_deadline_live')]:
            p = copy.deepcopy(self.preset);p['profiles'][profile][key] = wrong
            with self.assertRaises(ValueError): validate_preset(p)

    def test_all_requirements_and_tests_are_mandatory(self):
        del self.preset['requirements']['R12']
        with self.assertRaisesRegex(ValueError, 'traceability'): validate_preset(self.preset)

    def test_preset_cannot_grant_acceptance(self):
        self.preset['acceptance']['A02'] = 'passed'
        with self.assertRaisesRegex(ValueError, 'claim_pass'): validate_preset(self.preset)

    def test_invalid_numeric_condition_fails_closed(self):
        for wrong in (True, float('nan'), float('inf'), -1):
            p = copy.deepcopy(self.preset);p['conditions']['duration_s'] = wrong
            with self.assertRaises(ValueError): validate_preset(p)
