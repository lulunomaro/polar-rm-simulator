"""Startup evidence parser cases only: no OpenVINO/NN/renderer execution."""
import json
import unittest

from tools.native_model_properties import PREFIX, PROPERTIES, parse_native_model_properties


def fixture():
    values = (['CPU'], 12, 1, 'LATENCY', 'bf16', True, 'ANY_CORE')
    known = lambda value: dict(status='known', value=value, reason=None)
    return dict(schema='rmcs.compiled-model-properties.v1', profile='first-frame-trace',
                startup=True, native_ticks=0, inference_calls=0,
                clock_domain='linux_steady_diagnostic_only', linux_steady_ns=123456,
                properties={key: known(value) for key, value in zip(PROPERTIES, values)},
                cv_num_threads=known(16), report_error=None)


def line(row):
    return (PREFIX + json.dumps(row, separators=(',', ':')) + '\n').encode()


class NativeModelPropertiesTests(unittest.TestCase):
    def test_real_properties_are_separate_from_opencv_threads_and_other_protocols(self):
        row = fixture()
        result = parse_native_model_properties(b'[RMCS-FIRST-FRAME] unrelated\n' + line(row),
                                              expected_profile='first-frame-trace')
        self.assertTrue(result['valid']); self.assertTrue(result['core_properties_known'])
        self.assertEqual(result['record']['properties']['inference_num_threads']['value'], 12)
        self.assertEqual(result['record']['cv_num_threads']['value'], 16)

    def test_unknown_optional_is_explicit_but_core_unknown_is_not_experiment_qualified(self):
        for key in ('enable_cpu_pinning', 'inference_num_threads'):
            row = fixture()
            row['properties'][key] = dict(status='unknown', value=None, reason='unsupported_property')
            result = parse_native_model_properties(line(row))
            self.assertTrue(result['valid'])
            self.assertEqual(result['core_properties_known'], key == 'enable_cpu_pinning')
        row = fixture()
        for key in PROPERTIES:
            row['properties'][key] = dict(status='unknown', value=None, reason='supported_properties_query_failed')
        result = parse_native_model_properties(line(row))
        self.assertTrue(result['valid']); self.assertFalse(result['core_properties_known'])

    def test_unresolved_actual_stream_value_is_preserved_without_known_core_qualification(self):
        for value in (-1, 0):
            row = fixture(); row['properties']['num_streams']['value'] = value
            result = parse_native_model_properties(line(row))
            self.assertTrue(result['valid']); self.assertFalse(result['core_properties_known'])
            self.assertEqual(result['record']['properties']['num_streams']['value'], value)

    def test_nonstartup_wrong_identity_bool_numeric_alias_and_type_changes_rejected(self):
        cases = [('startup', False), ('native_ticks', True), ('native_ticks', 1),
                 ('inference_calls', 1), ('inference_calls', 0.0), ('linux_steady_ns', True),
                 ('linux_steady_ns', -1), ('clock_domain', 'host_perf_counter')]
        for key, value in cases:
            row = fixture(); row[key] = value
            with self.subTest(key=key, value=value):
                self.assertFalse(parse_native_model_properties(line(row))['valid'])
        self.assertFalse(parse_native_model_properties(line(fixture()), expected_profile='other')['valid'])
        for name, value in [('inference_num_threads', True), ('num_streams', 1.0),
                            ('enable_cpu_pinning', 1), ('execution_devices', 'CPU'),
                            ('execution_devices', []), ('execution_devices', ['CPU', 'CPU']),
                            ('inference_precision', '')]:
            row = fixture(); row['properties'][name]['value'] = value
            with self.subTest(name=name, value=value):
                self.assertFalse(parse_native_model_properties(line(row))['valid'])

    def test_unknown_missing_reason_wrong_allowlist_or_report_error_cannot_be_known(self):
        mutations = [lambda r: r['properties']['num_streams'].update(status='unknown', value=None, reason=None),
                     lambda r: r['properties']['num_streams'].update(reason='unsupported_property'),
                     lambda r: r['properties'].pop('num_streams'),
                     lambda r: r['properties'].update(other=dict(status='known', value=1, reason=None))]
        for mutate in mutations:
            row = fixture(); mutate(row)
            self.assertFalse(parse_native_model_properties(line(row))['valid'])
        row = fixture(); row.update(properties=None, cv_num_threads=None, report_error='report_construction_failed')
        result = parse_native_model_properties(line(row))
        self.assertTrue(result['available']); self.assertFalse(result['valid'])
        self.assertEqual(result['errors'], ['report_construction_failed'])
        row.update(startup=False, native_ticks=None, inference_calls=None, report_error='report_not_startup')
        self.assertFalse(parse_native_model_properties(line(row))['valid'])

    def test_duplicate_missing_truncated_malformed_oversize_and_nonfinite_rejected(self):
        raw = line(fixture())
        inputs = [b'', raw + raw, raw.rstrip(b'\n'), raw.replace(b'] ', b']', 1),
                  raw.replace(b'"linux_steady_ns":123456', b'"linux_steady_ns":123456,"linux_steady_ns":1'),
                  raw.replace(b'"linux_steady_ns":123456', b'"linux_steady_ns":NaN'),
                  raw.replace(b'"linux_steady_ns":123456', b'"linux_steady_ns":1e999'),
                  PREFIX.encode() + b' ' * 4096 + b'\n']
        for candidate in inputs:
            with self.subTest(candidate=candidate[:90]):
                result = parse_native_model_properties(candidate)
                self.assertFalse(result['valid']); self.assertFalse(result['core_properties_known'])
        row = fixture(); row['properties']['execution_devices']['value'] = ['CPU'] * 9
        self.assertFalse(parse_native_model_properties(line(row))['valid'])
        row = fixture(); row['properties']['performance_mode']['value'] = 'X' * 65
        self.assertFalse(parse_native_model_properties(line(row))['valid'])


if __name__ == '__main__':
    unittest.main()
