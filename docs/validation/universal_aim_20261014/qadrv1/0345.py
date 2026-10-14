"""Static source generation only. No C++ build, OpenCV API or NN execution."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'operator_native/runtime'
spec=importlib.util.spec_from_file_location('cv_api_portable',RUNTIME/'build_portable.py')
portable=importlib.util.module_from_spec(spec);spec.loader.exec_module(portable)


class NativeOpencvApiGenerationTests(unittest.TestCase):
    def test_only_explicit_diagnostic_generated_main_has_api_call_before_any_runner(self):
        original=portable.verify_sources(RUNTIME)
        with tempfile.TemporaryDirectory() as temporary:
            model=ROOT/'models/shenzhen-0526.onnx';hook=RUNTIME.parent/'prepare_fov_hook.py'
            ordinary=Path(temporary)/'original'
            portable.prepare(RUNTIME,ordinary,model,hook,corner_refinement='contour-v3')
            ordinary_main=(ordinary/'generated/main.cpp').read_text()
            self.assertNotIn('configure_opencv_threads()',ordinary_main)
            self.assertEqual(portable.sha(ordinary/'generated/main.cpp'),portable.OPERATOR_MAIN_HASH)
            diagnostic=Path(temporary)/'diagnostic'
            portable.prepare(RUNTIME,diagnostic,model,hook,corner_refinement='contour-v3',performance_profile='first-frame-trace')
            main=(diagnostic/'generated/main.cpp').read_text()
            self.assertEqual(main.count('rmcs::first_frame_trace::configure_opencv_threads();'),1)
            self.assertLess(main.index('configure_opencv_threads();'),main.index('Runner runner('))
            self.assertLess(main.index('Runner runner('),main.index('while (std::getline(std::cin,line))'))
            self.assertFalse((diagnostic/'bin').exists());self.assertFalse((diagnostic/'operator_source.local.json').exists())
        self.assertEqual(portable.verify_sources(RUNTIME),original)


if __name__=='__main__':unittest.main()
