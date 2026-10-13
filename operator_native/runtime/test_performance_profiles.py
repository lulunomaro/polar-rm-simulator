"""Static/prepare-only profiles: never invoke compiler, native code, or NN."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('performance_portable_test',HERE/'build_portable.py')
portable=importlib.util.module_from_spec(spec);spec.loader.exec_module(portable)
gen_spec=importlib.util.spec_from_file_location('performance_generator_test',HERE/'overlays/prepare_first_frame_profile.py')
generator=importlib.util.module_from_spec(gen_spec);gen_spec.loader.exec_module(generator)
MODEL=HERE.parents[1]/'models/shenzhen-0526.onnx';HOOK=HERE.parent/'prepare_fov_hook.py'


class PerformanceProfileTests(unittest.TestCase):
    def test_default_source_identity_and_configure_command_have_no_profile_delta(self):
        old=portable.input_identity(HERE,MODEL,HOOK,corner_refinement='contour-v3')
        explicit=portable.input_identity(HERE,MODEL,HOOK,corner_refinement='contour-v3',performance_profile='original')
        self.assertEqual(old,explicit)
        self.assertNotIn('runtime_performance_profile',old['algorithm_identity'])
        self.assertEqual(old['algorithm_identity']['patch_sha256'],'3ced3a3e41b4e6b6567f2b3b94f218817a043588fb0691b175ab55d5e3edbdf7')
        self.assertNotIn('RMCS_PERFORMANCE_PROFILE',' '.join(sum(portable.make_commands(HERE,Path('/out')),[])))

    def test_diagnostic_identity_is_explicit_distinct_and_binds_both_sources(self):
        previous=None
        for name in portable.PERFORMANCE_PROFILES[1:]:
            identity=portable.input_identity(HERE,MODEL,HOOK,corner_refinement='contour-v3',performance_profile=name)
            selected=identity['performance_profile'];algorithm=identity['algorithm_identity']
            self.assertEqual(selected['id'],name);self.assertTrue(selected['diagnostic_only'])
            self.assertFalse(selected['inference_during_setup'])
            self.assertEqual(selected['request_preallocated'],name=='request-preallocate-trace')
            self.assertEqual(algorithm['runtime_performance_profile'],selected)
            self.assertEqual(algorithm['patch_identity_format'],'rmcs-own-source-performance-composition.v1')
            self.assertEqual(algorithm['performance_base_patch_sha256'],'3ced3a3e41b4e6b6567f2b3b94f218817a043588fb0691b175ab55d5e3edbdf7')
            self.assertNotEqual(algorithm['patch_sha256'],algorithm['performance_base_patch_sha256'])
            if previous:self.assertNotEqual(algorithm['patch_sha256'],previous)
            previous=algorithm['patch_sha256']
            for rel in portable.PERFORMANCE_SOURCES:self.assertEqual(identity['additional_source_files'][rel],portable.sha(HERE/rel))
        with self.assertRaises(ValueError):portable.input_identity(HERE,MODEL,HOOK,performance_profile='warm-infer')

    def test_prepare_has_no_native_build_or_warm_inference_and_sealed_sources_remain_exact(self):
        sealed=portable.verify_sources(HERE);corner=portable.sha(HERE/'overlays/corners_contour_v3.cpp')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            original=portable.prepare(HERE,root/'original',MODEL,HOOK,corner_refinement='contour-v3')
            self.assertEqual(portable.sha(root/'original/generated/main.cpp'),portable.OPERATOR_MAIN_HASH)
            self.assertFalse((root/'original/generated/armor_detection_profile.cpp').exists())
            for name in portable.PERFORMANCE_PROFILES[1:]:
                out=root/name
                identity=portable.prepare(HERE,out,MODEL,HOOK,corner_refinement='contour-v3',performance_profile=name)
                armor=(out/'generated/armor_detection_profile.cpp').read_text(encoding='utf-8')
                main=(out/'generated/main.cpp').read_text()
                compile_body=armor.split('auto compile_model_with() -> void {',1)[1].split('auto allocate_cached_request',1)[0]
                self.assertNotIn('.infer(',compile_body);self.assertNotIn('.set_input_tensor(',compile_body)
                self.assertEqual(armor.count('request.infer();'),1)
                self.assertEqual(armor.count('cached_request.set_input_tensor(cached_input_tensor);'),1)
                self.assertEqual(armor.count('cached_request = openvino_model.create_infer_request();'),1)
                self.assertEqual('allocate_cached_request(true)' in compile_body,name=='request-preallocate-trace')
                self.assertIn('input_attach',armor);self.assertIn('post_nms',armor)
                for anchor in ('submitted.accept(exposure,Clock::now())','consumed.accept(exposure,Clock::now())',
                    'processed.accept(exposure,Clock::now())','results.shoot_allowed()',
                    'config.min_confidence','config.nms_threshold'):
                    self.assertIn(anchor,main if 'config.' not in anchor else armor)
                self.assertIn('diagnostic_tick.start(f["frame_id"].as<std::int64_t>(),exposure_ns,control_ns)',main)
                self.assertNotIn('std::cout',(out/'generated/first_frame_trace.hpp').read_text())
                self.assertNotEqual(portable.sha(out/'generated/main.cpp'),portable.OPERATOR_MAIN_HASH)
                self.assertEqual(identity['generated_sha256']['generated/main.cpp'],portable.sha(out/'generated/main.cpp'))
                self.assertFalse((out/'bin').exists());self.assertFalse((out/'operator_source.local.json').exists())
        self.assertEqual(portable.verify_sources(HERE),sealed);self.assertEqual(portable.sha(HERE/'overlays/corners_contour_v3.cpp'),corner)

    def test_generation_rejects_changed_unique_anchor_before_writing_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out';portable.prepare(HERE,out,MODEL,HOOK)
            main=out/'generated/main.cpp';main.write_text(main.read_text().replace('const auto exposure_ns=','const auto altered_ns='))
            with self.assertRaisesRegex(ValueError,'anchor changed'):generator.generate_profile(HERE,out/'generated','first-frame-trace')
            self.assertFalse((out/'generated/armor_detection_profile.cpp').exists())

    def test_single_exact_timestamp_pair_and_bounded_stderr_only(self):
        header=(HERE/'overlays/first_frame_trace.hpp').read_text()
        self.assertIn('emit(phase,"begin",startup,began)',header)
        self.assertIn('emit(phase,"end",startup,ended,ended-began',header)
        self.assertIn('emit("first_tick","end",false,ended,ended-began',header)
        self.assertIn('max_records = 96',header);self.assertIn('std::fflush(stderr)',header)
        self.assertNotIn('Clock::injected',header);self.assertNotIn('stdout',header)

    def test_explicit_cmake_variant_and_default_original(self):
        cmake=(HERE/'CMakeLists.txt').read_text()
        self.assertIn('set(RMCS_PERFORMANCE_PROFILE "original" CACHE STRING',cmake)
        self.assertIn('${RMCS_ARMOR_DETECTION_SOURCE}',cmake)
        for profile in portable.PERFORMANCE_PROFILES[1:]:
            commands=portable.make_commands(HERE,Path('/fresh'),performance_profile=profile)
            self.assertIn('-DRMCS_PERFORMANCE_PROFILE='+profile,commands[0])
        with self.assertRaises(ValueError):portable.make_commands(HERE,Path('/fresh'),performance_profile='unknown')


if __name__=='__main__':unittest.main()
