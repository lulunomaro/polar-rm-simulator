import math
import unittest
from rm_match.telemetry import TimingLedger


class TimingTests(unittest.TestCase):
    def test_empty_is_unmeasured_not_zero_latency(self):
        value=TimingLedger(['render']).snapshot()['render']
        self.assertIsNone(value['p95_s']);self.assertEqual(value['sample_count'],0)

    def test_bounded_window_percentiles_and_all_time_max(self):
        ledger=TimingLedger(['render'],capacity=3)
        for v in (9.,1.,2.,3.):ledger.record('render',v)
        value=ledger.snapshot()['render']
        self.assertEqual(value['sample_count'],4);self.assertEqual(value['retained_count'],3)
        self.assertEqual(value['p50_s'],2.);self.assertAlmostEqual(value['p95_s'],2.9)
        self.assertEqual(value['max_s'],9.);self.assertEqual(value['mean_s'],3.75)

    def test_invalid_clock_deltas_rejected(self):
        ledger=TimingLedger(['render'])
        for value in (-1,math.nan,math.inf,True):
            with self.assertRaises(ValueError):ledger.record('render',value)
