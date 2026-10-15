"""Qualification entry guard only: never creates GL or starts physics."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from . import qa_camera

class CameraEntryGuardTests(unittest.TestCase):
    def test_existing_output_is_refused_before_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            sentinel=Path(directory)/'evidence.txt';sentinel.write_text('preserve existing record')
            with patch.object(qa_camera,'MuJoCoBackend',side_effect=AssertionError('backend must not start')):
                with self.assertRaises(FileExistsError):qa_camera.run(directory)
            self.assertEqual(sentinel.read_text(),'preserve existing record')
    def test_optimized_interpreter_refuses_before_output_or_physics(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'new-evidence'
            result=subprocess.run([sys.executable,'-O','-m','rm_match.platform_v2.qa_camera','--out',str(target)],capture_output=True,text=True,timeout=5)
            self.assertNotEqual(result.returncode,0);self.assertIn('without -O',result.stderr);self.assertFalse(target.exists())

if __name__=='__main__':unittest.main()
