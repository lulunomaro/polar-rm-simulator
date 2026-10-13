"""Algorithm preservation and actual Linux loader collision regression."""
from copy import deepcopy
import ctypes
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import os
import time
import unittest
from unittest.mock import patch,Mock
import signal
import xml.etree.ElementTree as ET
from tools.build_pb_nav2_plugins import rename_layers,parse_args,main,stop_build_group,build_command


def source():
    return {'CMakeLists.txt':b'ament_auto_add_library(layers SHARED\n  src/layers/intensity_voxel_layer.cpp\n)\n',
        'costmap_plugins.xml':b'<class_libraries><library path="layers"><class type="pb_nav2_costmap_2d::IntensityVoxelLayer" base_class_type="nav2_costmap_2d::Layer"/></library></class_libraries>',
        'src/layers/intensity_voxel_layer.cpp':b'// algorithm input fixture: exact original bytes retained\n',
        'include/layer.hpp':b'// unchanged class ABI header\n'}


class BindingTests(unittest.TestCase):
    def test_build_budget_default_bounds_and_invalid_cli_never_spawns(self):
        argv=['--source-root','missing','--environment','missing','--out','missing']
        self.assertEqual(parse_args(argv).build_timeout_seconds,1800)
        for value in ('60','3600'):
            self.assertEqual(parse_args(argv+['--build-timeout-seconds',value]).build_timeout_seconds,int(value))
        with patch('tools.build_pb_nav2_plugins.subprocess.Popen') as popen:
            for value in ('59','3601','nan','60.5'):
                with self.subTest(value=value),self.assertRaises(SystemExit):main(argv+['--build-timeout-seconds',value])
            popen.assert_not_called()

    def test_package_scopes_are_explicit_and_mutually_exclusive_before_spawn(self):
        argv=['--source-root','missing','--environment','missing','--out','missing']
        self.assertTrue(parse_args(argv+['--controller-only']).controller_only)
        self.assertFalse(parse_args(argv+['--controller-only']).plugins_only)
        with patch('tools.build_pb_nav2_plugins.subprocess.Popen') as popen:
            with self.assertRaises(SystemExit):main(argv+['--controller-only','--plugins-only'])
            popen.assert_not_called()

    def test_both_cmake_python_keys_use_trusted_environment_interpreter(self):
        command=build_command(Path('owned'),{'venv_python':sys.executable})
        self.assertIn('-DPython3_EXECUTABLE='+sys.executable,command)
        self.assertIn('-DPYTHON_EXECUTABLE='+sys.executable,command)
        self.assertEqual(build_command(Path('owned'),{}),command)
        for candidate in ('relative/python','/missing/owned/python',True):
            with self.subTest(candidate=candidate),self.assertRaises(ValueError):build_command(Path('owned'),{'venv_python':candidate})

    def test_timeout_kills_owned_descendants_even_when_leader_reaped_after_term(self):
        proc=Mock(pid=7341);proc.poll.return_value=-15
        with patch('tools.build_pb_nav2_plugins.os.killpg',create=True) as kill,patch('tools.build_pb_nav2_plugins.signal.SIGKILL',9,create=True):
            stop_build_group(proc)
        self.assertEqual(kill.call_args_list,[unittest.mock.call(7341,signal.SIGTERM),unittest.mock.call(7341,9)])
        proc.wait.assert_called_once_with(timeout=.5)

    @unittest.skipUnless(sys.platform=='linux','actual POSIX process group required')
    def test_actual_timeout_cleans_term_ignoring_compiler_after_leader_exits(self):
        # Isolated harness adopts/reaps the grandchild; no orphan survives the test.
        harness='''
import ctypes,os,signal,subprocess,sys,tempfile,time
from pathlib import Path
from tools.build_pb_nav2_plugins import stop_build_group
assert ctypes.CDLL(None).prctl(36,1,0,0,0)==0
with tempfile.TemporaryDirectory() as td:
 path=Path(td)/'child.pid'
 child="import os,signal,time,sys;pid=os.fork();\\nif pid==0:\\n signal.signal(signal.SIGTERM,signal.SIG_IGN);open(sys.argv[1],'w').write(str(os.getpid()));time.sleep(60)\\nelse:time.sleep(60)"
 proc=subprocess.Popen([sys.executable,'-c',child,str(path)],start_new_session=True)
 try:
  deadline=time.monotonic()+2
  while not path.exists() and time.monotonic()<deadline:time.sleep(.01)
  assert path.exists()
  pid=int(path.read_text());stop_build_group(proc)
  assert proc.poll() is not None
  deadline=time.monotonic()+2
  while time.monotonic()<deadline:
   reaped,status=os.waitpid(pid,os.WNOHANG)
   if reaped:break
   time.sleep(.01)
  assert reaped==pid and os.WIFSIGNALED(status) and os.WTERMSIG(status)==signal.SIGKILL
 finally:
  try:os.killpg(proc.pid,signal.SIGKILL)
  except ProcessLookupError:pass
  proc.wait(timeout=1)
print('LEADER_AND_OWNED_CHILD_REAPED')
'''
        result=subprocess.run([sys.executable,'-c',harness],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('LEADER_AND_OWNED_CHILD_REAPED',result.stdout)

    def test_binding_changes_both_target_and_xml_without_algorithm_or_class_changes(self):
        files=source();original=deepcopy(files);patched,metadata=rename_layers(files)
        self.assertEqual(files,original)
        self.assertIn(b'OUTPUT_NAME pb_intensity_layers',patched['CMakeLists.txt'])
        self.assertEqual(ET.fromstring(patched['costmap_plugins.xml']).find('library').attrib['path'],'pb_intensity_layers')
        self.assertEqual([c.attrib for c in ET.fromstring(patched['costmap_plugins.xml']).iter('class')],
            [c.attrib for c in ET.fromstring(original['costmap_plugins.xml']).iter('class')])
        for name in ('src/layers/intensity_voxel_layer.cpp','include/layer.hpp'):self.assertEqual(patched[name],original[name])
        self.assertEqual(metadata['before'],'liblayers.so');self.assertEqual(metadata['after'],'libpb_intensity_layers.so')

    def test_unknown_class_and_duplicate_anchors_reject(self):
        for kind in ('class','duplicate','library'):
            with self.subTest(kind=kind):
                files=source()
                if kind=='class':files['costmap_plugins.xml']=files['costmap_plugins.xml'].replace(b'IntensityVoxelLayer',b'OtherClass')
                elif kind=='duplicate':files['CMakeLists.txt']*=2
                else:files['costmap_plugins.xml']=files['costmap_plugins.xml'].replace(b'path="layers"',b'path="other"')
                with self.assertRaises(ValueError):rename_layers(files)

    @unittest.skipUnless(sys.platform=='linux' and shutil.which('g++') and shutil.which('readelf'),'actual Linux ELF compiler/loader required')
    def test_same_soname_self_dependency_fails_but_unique_output_loads_actual_base(self):
        # Real ELF fixtures, not Nav2 or an alternative navigation algorithm.
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);base=root/'base';pb=root/'pb';base.mkdir();pb.mkdir()
            (root/'base.cpp').write_text('extern "C" int base_value(){return 37;}\n')
            (root/'plugin.cpp').write_text('extern "C" int base_value(); extern "C" int own_value(){return base_value()+5;}\n')
            subprocess.run(['g++','-shared','-fPIC',str(root/'base.cpp'),'-Wl,-soname,liblayers.so','-o',str(base/'liblayers.so')],check=True,capture_output=True)
            def compile(name):
                path=pb/name
                subprocess.run(['g++','-shared','-fPIC',str(root/'plugin.cpp'),str(base/'liblayers.so'),
                    '-Wl,-soname,'+name,'-Wl,-rpath,'+str(base),'-o',str(path)],check=True,capture_output=True)
                return path
            collided=compile('liblayers.so');dynamic=subprocess.check_output(['readelf','-d',str(collided)],text=True)
            self.assertIn('Library soname: [liblayers.so]',dynamic);self.assertIn('Shared library: [liblayers.so]',dynamic)
            with self.assertRaises(OSError):ctypes.CDLL(str(collided))
            unique=compile('libpb_intensity_layers.so');dynamic=subprocess.check_output(['readelf','-d',str(unique)],text=True)
            self.assertIn('Library soname: [libpb_intensity_layers.so]',dynamic);self.assertIn('Shared library: [liblayers.so]',dynamic)
            loaded=ctypes.CDLL(str(unique));self.assertEqual(loaded.own_value(),42)


if __name__=='__main__':unittest.main()
