"""Strict parsing of startup-only compiled model observations; no model import."""
from __future__ import annotations

import json
import math

PREFIX = '[RMCS-COMPILED-MODEL] '
SCHEMA = 'rmcs.compiled-model-properties.v1'
MAX_REPORT_BYTES = 4096
MAX_STDERR_BYTES = 16 * 1024 * 1024
OPENCV_PREFIX = '[RMCS-OPENCV-THREADS] '
OPENCV_ENV = 'RMCS_DIAGNOSTIC_OPENCV_THREADS'
INFERENCE_PREFIX = '[RMCS-INFERENCE-THREADS] '
INFERENCE_ENV = 'RMCS_DIAGNOSTIC_OV_INFERENCE_THREADS'
PROPERTIES = ('execution_devices', 'inference_num_threads', 'num_streams',
              'performance_mode', 'inference_precision', 'enable_cpu_pinning', 'scheduling_core_type')
FIELDS = {'schema', 'profile', 'startup', 'native_ticks', 'inference_calls',
          'clock_domain', 'linux_steady_ns', 'properties', 'cv_num_threads', 'report_error'}
REASONS = {'supported_properties_query_failed', 'unsupported_property',
           'property_query_or_value_failed', 'opencv_threads_query_failed'}


def _json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate_json_key')
            value[key] = item
        return value
    def invalid(_):
        raise ValueError('nonfinite_json')
    def number(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError('nonfinite_json')
        return value
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid, parse_float=number)


def _text(value):
    return type(value) is str and 0 < len(value) <= 64 and all(32 <= ord(c) <= 126 for c in value)


def _record(value, name):
    if type(value) is not dict or set(value) != {'status', 'value', 'reason'}:
        raise ValueError('property_record_fields:' + name)
    if value['status'] == 'unknown':
        if value['value'] is not None or type(value['reason']) is not str or value['reason'] not in REASONS:
            raise ValueError('unknown_without_reason:' + name)
        if name != 'cv_num_threads' and value['reason'] == 'opencv_threads_query_failed':
            raise ValueError('wrong_property_reason:' + name)
        return
    if value['status'] != 'known' or value['reason'] is not None:
        raise ValueError('property_status:' + name)
    item = value['value']
    if name == 'execution_devices':
        good = type(item) is list and 1 <= len(item) <= 8 and all(_text(v) for v in item)
        good = good and len(set(item)) == len(item)
    elif name in ('inference_num_threads', 'num_streams', 'cv_num_threads'):
        good = type(item) is int and -1 <= item <= 65536
    elif name == 'enable_cpu_pinning':
        good = type(item) is bool
    else:
        good = _text(item)
    if not good:
        raise ValueError('property_value_type_or_bound:' + name)


def parse_native_model_properties(stderr, *, expected_profile=None):
    """Return evidence validity separately from resolved CPU properties.

    Unknown optional properties are valid observations with explicit reasons.
    Absent, duplicated, malformed or non-startup reports never qualify; no value
    comes from environment variables or a requested configuration.
    """
    result = dict(schema='polar.native-model-properties-report.v1', available=False,
                  valid=False, core_properties_known=False, record=None, errors=[])
    try:
        if type(stderr) is str:
            stderr = stderr.encode('utf-8')
        if type(stderr) is not bytes or len(stderr) > MAX_STDERR_BYTES:
            raise ValueError('stderr_type_or_bound')
        lines = [line for line in stderr.splitlines(keepends=True)
                 if line.startswith(b'[RMCS-COMPILED-MODEL]')]
        result['available'] = bool(lines)
        if len(lines) != 1:
            raise ValueError('missing_report' if not lines else 'duplicate_report')
        line = lines[0]
        if len(line) > MAX_REPORT_BYTES or not line.endswith(b'\n'):
            raise ValueError('report_bound_or_truncated')
        text = line.decode('utf-8', errors='strict')
        if not text.startswith(PREFIX):
            raise ValueError('malformed_report_prefix')
        row = _json(text[len(PREFIX):])
        if type(row) is not dict or set(row) != FIELDS:
            raise ValueError('report_fields')
        if row['schema'] != SCHEMA or type(row['schema']) is not str or not _text(row['profile']):
            raise ValueError('schema_or_profile')
        if expected_profile is not None and (type(expected_profile) is not str or row['profile'] != expected_profile):
            raise ValueError('profile_mismatch')
        if (row['startup'] is not True or type(row['native_ticks']) is not int or row['native_ticks'] != 0
                or type(row['inference_calls']) is not int or row['inference_calls'] != 0
                or row['clock_domain'] != 'linux_steady_diagnostic_only'
                or type(row['linux_steady_ns']) is not int or row['linux_steady_ns'] < 0):
            raise ValueError('startup_or_clock_identity')
        result['record'] = row
        if row['report_error'] is not None:
            if (row['report_error'] != 'report_construction_failed' or row['properties'] is not None
                    or row['cv_num_threads'] is not None):
                raise ValueError('report_error_fields')
            raise ValueError('report_construction_failed')
        if type(row['properties']) is not dict or set(row['properties']) != set(PROPERTIES):
            raise ValueError('property_allowlist')
        for name, value in row['properties'].items():
            _record(value, name)
        _record(row['cv_num_threads'], 'cv_num_threads')
        result['valid'] = True
        core = row['properties']
        result['core_properties_known'] = all(core[key]['status'] == 'known' for key in PROPERTIES[:3])
        if result['core_properties_known']:
            result['core_properties_known'] = (core['inference_num_threads']['value'] > 0
                                               and core['num_streams']['value'] > 0)
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        result['errors'].append(str(exc))
    return result


def parse_native_opencv_threads(stderr, *, expected_profile=None, expected_threads=None):
    """Verify an explicit diagnostic API action, separate from model properties."""
    result = dict(schema='polar.native-opencv-thread-api-report.v1', available=False,
                  valid=False, record=None, errors=[])
    try:
        if type(stderr) is str: stderr = stderr.encode('utf-8')
        if type(stderr) is not bytes or len(stderr) > MAX_STDERR_BYTES:
            raise ValueError('stderr_type_or_bound')
        lines = [line for line in stderr.splitlines(keepends=True) if line.startswith(b'[RMCS-OPENCV-THREADS]')]
        result['available'] = bool(lines)
        if len(lines) != 1: raise ValueError('missing_api_report' if not lines else 'duplicate_api_report')
        if len(lines[0]) > 768 or not lines[0].endswith(b'\n'): raise ValueError('api_report_bound_or_truncated')
        text = lines[0].decode('utf-8', errors='strict')
        if not text.startswith(OPENCV_PREFIX): raise ValueError('malformed_api_report_prefix')
        row = _json(text[len(OPENCV_PREFIX):])
        fields = {'schema','profile','startup','native_ticks','inference_calls','clock_domain',
                  'linux_steady_ns','requested','action','before_threads','after_threads','error'}
        if type(row) is not dict or set(row) != fields: raise ValueError('api_report_fields')
        result['record'] = row
        if row['schema'] != 'rmcs.opencv-thread-api.v1' or not _text(row['profile']): raise ValueError('api_schema_or_profile')
        if expected_profile is not None and (type(expected_profile) is not str or row['profile'] != expected_profile):
            raise ValueError('api_profile_mismatch')
        if (row['startup'] is not True or type(row['native_ticks']) is not int or row['native_ticks'] != 0
            or type(row['inference_calls']) is not int or row['inference_calls'] != 0
            or row['clock_domain'] != 'linux_steady_diagnostic_only'
            or type(row['linux_steady_ns']) is not int or row['linux_steady_ns'] < 0):
            raise ValueError('api_startup_or_clock')
        if row['error'] is not None:
            if row['error'] not in {'invalid_diagnostic_opencv_threads','opencv_thread_api_not_effective',
                                    'opencv_thread_api_query_or_set_failed'}:
                raise ValueError('api_error_reason')
            raise ValueError(row['error'])
        if any(type(row[k]) is not int or not 1 <= row[k] <= 65536 for k in ('before_threads','after_threads')):
            raise ValueError('api_thread_type_or_bound')
        if row['requested'] == 'original':
            if row['action'] != 'none' or row['after_threads'] != row['before_threads']:
                raise ValueError('api_original_setting_changed')
        elif row['requested'] == '1':
            if row['action'] != 'set_num_threads' or row['after_threads'] != 1:
                raise ValueError('api_single_thread_not_effective')
        else: raise ValueError('api_requested_enum')
        if expected_threads is not None:
            if type(expected_threads) is not int or expected_threads not in (1,32): raise ValueError('api_expected_threads_enum')
            expected_request = '1' if expected_threads == 1 else 'original'
            if row['requested'] != expected_request or row['after_threads'] != expected_threads:
                raise ValueError('api_requested_or_effective_mismatch')
        result['valid'] = True
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        result['errors'].append(str(exc))
    return result


def parse_native_inference_threads(stderr, *, expected_profile=None, expected_threads=None):
    """Strict startup API evidence, separate from the actual model property report."""
    result=dict(schema='polar.native-inference-thread-api-report.v1',available=False,valid=False,record=None,errors=[])
    try:
        if type(stderr) is str:stderr=stderr.encode('utf-8')
        if type(stderr) is not bytes or len(stderr)>MAX_STDERR_BYTES:raise ValueError('stderr_type_or_bound')
        lines=[line for line in stderr.splitlines(keepends=True) if line.startswith(b'[RMCS-INFERENCE-THREADS]')]
        result['available']=bool(lines)
        if len(lines)!=1:raise ValueError('missing_inference_api_report' if not lines else 'duplicate_inference_api_report')
        if len(lines[0])>768 or not lines[0].endswith(b'\n'):raise ValueError('inference_api_bound_or_truncated')
        text=lines[0].decode('utf-8',errors='strict')
        if not text.startswith(INFERENCE_PREFIX):raise ValueError('inference_api_prefix')
        row=_json(text[len(INFERENCE_PREFIX):])
        fields={'schema','profile','startup','native_ticks','inference_calls','clock_domain','linux_steady_ns',
                'requested','action','effective_threads','other_properties_unchanged','error'}
        if type(row) is not dict or set(row)!=fields:raise ValueError('inference_api_fields')
        result['record']=row
        if row['schema']!='rmcs.inference-thread-api.v1' or not _text(row['profile']):raise ValueError('inference_api_schema_or_profile')
        if expected_profile is not None and (type(expected_profile) is not str or row['profile']!=expected_profile):
            raise ValueError('inference_api_profile_mismatch')
        if (row['startup'] is not True or type(row['native_ticks']) is not int or row['native_ticks']!=0
            or type(row['inference_calls']) is not int or row['inference_calls']!=0
            or row['clock_domain']!='linux_steady_diagnostic_only'
            or type(row['linux_steady_ns']) is not int or row['linux_steady_ns']<0):raise ValueError('inference_api_startup_or_clock')
        if row['error'] is not None:
            if type(row['error']) is not str or row['error'] not in {'inference_thread_api_not_effective',
                'inference_thread_api_other_property_changed','inference_thread_api_query_failed'}:
                raise ValueError('inference_api_error_reason')
            raise ValueError(row['error'])
        if row['other_properties_unchanged'] is not True:raise ValueError('inference_api_other_properties_unproved')
        if type(row['effective_threads']) is not int:raise ValueError('inference_api_thread_type')
        request,action,count=(row['requested'],row['action'],row['effective_threads'])
        if (request,action,count) not in (('original','none',16),('4','core_set_property',4)):
            raise ValueError('inference_api_setting_not_effective')
        if expected_threads is not None:
            if type(expected_threads) is not int or expected_threads not in (4,16) or count!=expected_threads:
                raise ValueError('inference_api_expected_mismatch')
        result['valid']=True
    except (ValueError,TypeError,UnicodeError,RecursionError) as exc:result['errors'].append(str(exc))
    return result
