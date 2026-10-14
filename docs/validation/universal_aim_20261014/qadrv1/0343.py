"""One-factor diagnostic source/parser contracts; no native process or inference."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tools import compare_native_opencv_threads as compare
from tools.native_model_properties import INFERENCE_ENV, INFERENCE_PREFIX, parse_native_inference_threads

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'operator_native/runtime'


def receipt(four=True):
    return dict(schema='rmcs.inference-thread-api.v1',profile='first-frame-trace',startup=True,
        native_ticks=0,inference_calls=0,clock_domain='linux_steady_diagnostic_only',linux_steady_ns=123,
        requested='4' if four else 'original',action='core_set_property' if four else 'none',
        effective_threads=4 if four else 16,other_properties_unchanged=True,error=None)


def wire(value):return (INFERENCE_PREFIX+json.dumps(value,separators=(',',':'))+'\n').encode()


def properties(four=False):
    expected=copy.deepcopy(compare.EXPECTED)
    if four:expected['inference_num_threads']=4
    known=lambda value:dict(status='known',value=value,reason=None)
    return dict(valid=True,core_properties_known=True,record=dict(
        properties={key:known(value) for key,value in expected.items()},cv_num_threads=known(32)))


class InferenceCandidateTests(unittest.TestCase):
    def test_abba_changes_exactly_one_explicit_api_env_and_preserves_parent(self):
        base={compare.CV_KEY:'1',INFERENCE_ENV:'99','OPENCV_FOR_THREADS_NUM':'1','OMP_NUM_THREADS':'1'}
        before=dict(base)
        a=compare.case_environment(base,'default','ov4');b=compare.case_environment(base,'ov4','ov4')
        self.assertEqual(base,before)
        self.assertEqual({k for k in set(a)|set(b) if a.get(k)!=b.get(k)},{INFERENCE_ENV})
        self.assertNotIn(INFERENCE_ENV,a);self.assertEqual(b[INFERENCE_ENV],'4')
        self.assertNotIn(compare.CV_KEY,b);self.assertNotIn('OPENCV_FOR_THREADS_NUM',b)
        self.assertEqual(a['OMP_NUM_THREADS'],b['OMP_NUM_THREADS'])
        plan=compare.plan('ov4')
        self.assertEqual(plan['sequence'],['default','ov4','ov4','default','default','ov4','ov4','default'])
        self.assertEqual(plan['expected_cv_threads'],{'default':32,'ov4':32})
        self.assertFalse(plan['live_budget_or_timestamp_changes'])
        for factor in (True,'threads4','cv4',None):
            with self.subTest(factor=factor),self.assertRaises(ValueError):compare.plan(factor)
        with self.assertRaises(ValueError):compare.case_environment(base,'cv1','ov4')

    def test_actual_api_and_complete_actual_properties_both_required(self):
        for four in (False,True):
            variant='ov4' if four else 'default'
            parsed=parse_native_inference_threads(wire(receipt(four)),expected_profile='first-frame-trace',expected_threads=4 if four else 16)
            self.assertTrue(parsed['valid']);compare.check_api_setting(parsed,variant,'ov4')
            compare.check_properties(properties(four),variant,'ov4')
            with self.assertRaises(ValueError):compare.check_properties(properties(not four),variant,'ov4')
        for key in compare.PROPERTIES:
            changed=properties(True);changed['record']['properties'][key]['status']='unknown'
            with self.subTest(key=key),self.assertRaises(ValueError):compare.check_properties(changed,'ov4','ov4')
        for key,value in [('num_streams',2),('inference_precision','bf16'),('enable_cpu_pinning',1),
                          ('scheduling_core_type','PCORE_ONLY'),('execution_devices',['GPU']),('performance_mode','THROUGHPUT')]:
            changed=properties(True);changed['record']['properties'][key]['value']=value
            with self.subTest(key=key),self.assertRaises(ValueError):compare.check_properties(changed,'ov4','ov4')
        changed=properties(True);changed['record']['cv_num_threads']['value']=1
        with self.assertRaises(ValueError):compare.check_properties(changed,'ov4','ov4')

    def test_receipt_requires_exact_types_setting_startup_and_no_hidden_error(self):
        for key,value in [('effective_threads',True),('effective_threads',4.),('effective_threads',16),
            ('requested','04'),('action','none'),('other_properties_unchanged',1),('other_properties_unchanged',False),
            ('startup',False),('native_ticks',True),('inference_calls',1),('linux_steady_ns',1.),('profile','other'),
            ('clock_domain','host_perf'),('error','inference_thread_api_not_effective')]:
            row=receipt();row[key]=value
            with self.subTest(key=key,value=value):
                self.assertFalse(parse_native_inference_threads(wire(row),expected_profile='first-frame-trace',expected_threads=4)['valid'])
        raw=wire(receipt())
        for bad in (b'',raw+raw,raw.rstrip(),raw.replace(b'"effective_threads":4',b'"effective_threads":4,"effective_threads":4'),
                    raw.replace(b'"linux_steady_ns":123',b'"linux_steady_ns":NaN'),raw.replace(b'"error":null',b'"error":null,"private":{}')):
            with self.subTest(raw=bad[:60]):self.assertFalse(parse_native_inference_threads(bad)['valid'])
        self.assertFalse(parse_native_inference_threads(raw,expected_threads=True)['valid'])

    def test_generated_only_hook_before_compile_and_verification_before_any_request(self):
        spec=importlib.util.spec_from_file_location('ov4_static_portable',RUNTIME/'build_portable.py')
        portable=importlib.util.module_from_spec(spec);spec.loader.exec_module(portable)
        before=portable.verify_sources(RUNTIME)
        with tempfile.TemporaryDirectory() as temporary:
            model=ROOT/'models/shenzhen-0526.onnx';hook=RUNTIME.parent/'prepare_fov_hook.py'
            ordinary=Path(temporary)/'ordinary'
            portable.prepare(RUNTIME,ordinary,model,hook,corner_refinement='contour-v3')
            self.assertEqual(portable.sha(ordinary/'generated/main.cpp'),portable.OPERATOR_MAIN_HASH)
            self.assertFalse((ordinary/'generated/first_frame_trace.hpp').exists())
            diagnostic=Path(temporary)/'diagnostic'
            identity=portable.prepare(RUNTIME,diagnostic,model,hook,corner_refinement='contour-v3',performance_profile='first-frame-trace')
            armor=(diagnostic/'generated/armor_detection_profile.cpp').read_text(encoding='utf-8')
            start=armor.index('configure_inference_threads(openvino_core);')
            compiled=armor.index('model.compile(openvino_core, config.model_location);')
            checked=armor.index('verify_inference_threads(openvino_model);')
            report=armor.index('report_compiled_model(openvino_model);')
            self.assertLess(start,compiled);self.assertLess(compiled,checked);self.assertLess(checked,report)
            self.assertLess(checked,armor.index('cached_ready     = false;'))
            header=(diagnostic/'generated/first_frame_trace.hpp').read_text(encoding='utf-8')
            self.assertIn('core.set_property("CPU",ov::inference_num_threads(4));',header)
            self.assertIn('const int expected=inference_threads_four?4:16;',header)
            self.assertIn('multiple_diagnostic_thread_factors',header)
            self.assertIn('inference_thread_api_other_property_changed',header)
            self.assertTrue(identity['performance_profile']['diagnostic_only'])
            self.assertFalse((diagnostic/'bin').exists())
        self.assertEqual(portable.verify_sources(RUNTIME),before)


if __name__=='__main__':unittest.main()
