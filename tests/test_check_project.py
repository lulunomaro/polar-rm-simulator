"""Quality evidence must not count its own output as new source code."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from tools import check_project


class QualitySourceTests(unittest.TestCase):
    def test_nonignored_output_is_excluded_but_real_untracked_source_is_bound(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            subprocess.run(['git','init',str(root)],check=True,capture_output=True)
            source=root/'source.py';source.write_bytes(b'original source')
            subprocess.run(['git','-C',str(root),'add','source.py'],check=True,capture_output=True)
            helper=root/'new_helper.py';helper.write_bytes(b'new source')
            out=root/'quality-run';out.mkdir()
            with patch.object(check_project,'ROOT',root):
                before=check_project.source_hashes(exclude_output=out)
                self.assertEqual(set(before),{'source.py','new_helper.py'})
                (out/'manifest.json').write_bytes(b'evidence')
                (out/'camera').mkdir();(out/'camera/frame.png').write_bytes(b'pixels')
                self.assertEqual(check_project.source_hashes(exclude_output=out),before)
                helper.write_bytes(b'changed implementation')
                after=check_project.source_hashes(exclude_output=out)
                self.assertNotEqual(after,before)
                self.assertEqual(after['new_helper.py'],hashlib.sha256(helper.read_bytes()).hexdigest())
