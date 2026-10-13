"""A successful goal and lengthy cleanup cannot qualify an early physics stop."""
import unittest
from tools.pb_sil_duration import completed_physics_duration

class DurationQualificationTests(unittest.TestCase):
    def test_cleanup_crossing_deadline_never_fills_missing_physics(self):
        self.assertGreater(29.4+.7,30.)
        self.assertFalse(completed_physics_duration(14700,.002,29.4,30.))
    def test_full_physics_and_wall_sampling_boundary_both_required(self):
        self.assertTrue(completed_physics_duration(15000,.002,29.9995142,30.))
        self.assertFalse(completed_physics_duration(14000,.002,30.1,30.))
        self.assertFalse(completed_physics_duration(15000,.002,28.,30.))
    def test_missing_or_nonnumeric_measurement_does_not_qualify(self):
        for elapsed in (None,True,float('nan'),float('inf'),0.):
            with self.subTest(elapsed=elapsed):self.assertFalse(completed_physics_duration(15000,.002,elapsed,30.))

if __name__=='__main__':unittest.main()
