"""Static/unit setup checks. No compiler, native executable, model inference, or simulator."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import struct
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('rmcs_portable', HERE / 'build_portable.py')
portable = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portable)


class PortableSetupTests(unittest.TestCase):
    @staticmethod
    def elf_fixture(machine=62, elf_class=2):
        ident = b'\x7fELF' + bytes((elf_class, 1, 1, 0)) + bytes(8)
        return struct.pack('<16sHHIQQQIHHHHHH', ident, 3, machine, 1, 4096, 64, 0, 0, 64, 56, 1, 0, 0, 0) + bytes(56)

    def test_original_source_hashes_and_closure_remain_exact(self):
        manifest = portable.verify_sources(HERE)
        self.assertEqual(len(manifest['files']), 94)
        self.assertEqual(len(manifest['translation_units']), 29)

    def test_plan_commands_do_not_reuse_old_objects(self):
        commands = portable.make_commands(Path('/source with space'), Path('/new output'), prefix='/opt/ov/runtime/cmake', jobs=3)
        self.assertEqual(commands[0][0:3], ['cmake', '-S', str(Path('/source with space'))])
        self.assertIn('-DCMAKE_PREFIX_PATH=/opt/ov/runtime/cmake', commands[0])
        self.assertEqual(commands[1][-2:], ['--parallel', '3'])
        self.assertNotIn('079a', ' '.join(commands[0] + commands[1]))
        self.assertNotIn('.o', ' '.join(commands[0] + commands[1]))

    def test_frontend_choice_is_explicit_and_unknown_choice_refused(self):
        original=portable.make_commands(HERE,Path('/fresh'))[0]
        contour=portable.make_commands(HERE,Path('/fresh'),corner_refinement='contour-v3')[0]
        self.assertNotIn('-DRMCS_USE_CONTOUR_CORNERS=ON',original)
        self.assertIn('-DRMCS_USE_CONTOUR_CORNERS=ON',contour)
        with self.assertRaises(ValueError):
            portable.make_commands(HERE,Path('/fresh'),corner_refinement='unreviewed')

    def test_cli_uses_repaired_frontend_and_original_is_an_explicit_reproduction(self):
        with patch.object(portable,'input_identity',return_value={}) as identity,patch('builtins.print'):
            portable.main(['plan'])
            self.assertEqual(identity.call_args.kwargs['corner_refinement'],'contour-v3')
            portable.main(['plan','--corner-refinement','original'])
            self.assertEqual(identity.call_args.kwargs['corner_refinement'],'original')

    def test_contour_identity_binds_actual_source_and_keeps_original_tracker(self):
        model=HERE.parents[1]/'models/shenzhen-0526.onnx'
        hook=HERE.parent/'prepare_fov_hook.py'
        original=portable.input_identity(HERE,model,hook)
        contour=portable.input_identity(HERE,model,hook,corner_refinement='contour-v1')
        source=contour['algorithm_identity']; frontend=source['vision_frontend']
        self.assertEqual(source['tracker_patch_sha256'],original['algorithm_identity']['patch_sha256'])
        self.assertNotEqual(source['patch_sha256'],source['tracker_patch_sha256'])
        self.assertEqual(frontend['source_sha256'],portable.sha(HERE/frontend['source_path']))
        self.assertEqual(contour['additional_source_files'],{frontend['source_path']:frontend['source_sha256']})
        self.assertEqual(contour['source_files'],original['source_files'])

    def test_prepared_contour_copy_is_in_the_frozen_input_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'fresh'
            identity=portable.prepare(HERE,out,HERE.parents[1]/'models/shenzhen-0526.onnx',
                                      HERE.parent/'prepare_fov_hook.py',corner_refinement='contour-v1')
            actual=portable.sha(out/'generated/corners_contour_v1.cpp')
            self.assertEqual(actual,identity['additional_source_files']['overlays/corners_contour_v1.cpp'])
            self.assertEqual(actual,identity['generated_sha256']['generated/corners_contour_v1.cpp'])

    def test_syntax_command_preserves_spaces_without_shell(self):
        row = {'command': 'g++ -std=c++23 -I"/inc with space" -o "out file.o" -c "source file.cpp"'}
        self.assertEqual(portable.syntax_command(row), ['g++', '-std=c++23', '-I/inc with space', '-fsyntax-only', 'source file.cpp'])
        with self.assertRaises(ValueError):
            portable.syntax_command({'arguments': ['g++', 'source.cpp']})

    def test_simulation_profile_omits_hardware_and_calibration(self):
        profile = json.loads((HERE / 'simulation_profile.json').read_text())
        self.assertEqual(set(profile['autoaim']), {'detector', 'tracker', 'pose_estimator', 'virtual_rune'})
        self.assertEqual(profile['autoaim']['virtual_rune'], {'enable': False})
        self.assertEqual(set(profile['executor']), {'auto_aim_component'})
        self.assertEqual(set(profile['executor']['auto_aim_component']['ros__parameters']), {'manual_shoot', 'fire_control'})
        self.assertFalse(profile['executor']['auto_aim_component']['ros__parameters']['manual_shoot'])
        for value in ('camera_matrix', 'distort_coeff', 'camera_name', 'monitor_host', 'password', '/workspace/'):
            self.assertNotIn(value, json.dumps(profile))

    def test_missing_model_fails_before_any_process(self):
        with patch.object(portable.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                portable.input_identity(HERE, Path('/definitely-missing/shenzhen-0526.onnx'), Path('/missing/hook.py'))
            run.assert_not_called()

    def test_output_reuse_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(portable, 'input_identity', return_value={}), patch.object(portable.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    portable.prepare(HERE, Path(directory), Path('/fake/model'), Path('/fake/hook'))
                run.assert_not_called()

    def test_generated_spec_binds_actual_bytes_not_historical_hash(self):
        # Byte fixtures solely test hashing; this is NOT an executable qualification.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'fixture-not-executable'
            binary.write_bytes(self.elf_fixture())
            model = root / 'shenzhen-0526.onnx'
            model.write_bytes(b'unit-test-model-byte-fixture')
            configs = root / 'configs'
            configs.mkdir()
            for name in ('simulation_executor.yaml', 'simulation_autoaim.yaml'):
                (configs / name).write_text('{}\n')
            with patch.object(portable, 'MODEL_HASH', portable.sha(model)):
                result = portable.make_spec(binary, configs, model, {'algorithm_identity': {'base_commit': '079a + T2 fixture'}}, 'manifest-fixture')
            self.assertEqual(result['operator_identity'], 'rmcs-sim-operator-fov-v1')
            self.assertEqual(result['sha256']['binary'], portable.sha(binary))
            self.assertEqual(result['frozen_build']['binary_sha256'], portable.sha(binary))
            self.assertEqual(result['runtime_mode_sha256'], hashlib.sha256(b'multi_ekf\n').hexdigest())
            self.assertTrue(Path(result['autoaim_config']).is_absolute())
            self.assertIn('no inference', result['qualification'])
            self.assertNotEqual(result['sha256']['binary'], 'e69fbb9eb39bb421458ada703656d7d83446fe0f749fa5bdf28ac612d397e795')

    def test_non_elf_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fake'
            path.write_text('not native')
            with self.assertRaises(ValueError):
                portable.make_spec(path, Path(directory), path, {}, 'fixture')

    def test_wrong_architecture_and_truncated_elf_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture'
            for content in (b'\x7fELF', self.elf_fixture(machine=183), self.elf_fixture(elf_class=1), self.elf_fixture()[:64]):
                path.write_bytes(content)
                with self.assertRaises(ValueError):
                    portable.elf_identity(path)

    def test_non_linux_native_build_refused_before_process(self):
        with patch.object(portable.platform, 'system', return_value='Windows'), patch.object(portable.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError):
                portable.build(HERE, Path('/unused'), Path('/unused'), Path('/unused'))
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
