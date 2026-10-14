"""Source identity/scope tests; no C++ build or claimed ROS integration."""
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from rm_match.integrations.pb_navigation_workspace import git_snapshot,verify,replace_once,write_owned,sha


class WorkspaceTests(unittest.TestCase):
    def test_original_git_bytes_ignore_dirty_checkout_and_windows_autocrlf(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);subprocess.run(['git','init',str(p)],check=True,capture_output=True)
            for k,v in [('user.name','Local test'),('user.email','local@example.invalid'),('core.autocrlf','true')]:
                subprocess.run(['git','-C',str(p),'config',k,v],check=True,capture_output=True)
            (p/'sensor.msg').write_bytes(b'float32 x\nfloat32 y\n')
            subprocess.run(['git','-C',str(p),'add','sensor.msg'],check=True,capture_output=True)
            subprocess.run(['git','-C',str(p),'commit','-m','fixture'],check=True,capture_output=True)
            commit=subprocess.check_output(['git','-C',str(p),'rev-parse','HEAD'],text=True).strip()
            (p/'sensor.msg').write_bytes(b'changed working file\r\n')
            files=git_snapshot(p,commit)
            self.assertEqual(files,{'sensor.msg':b'float32 x\nfloat32 y\n'})
            verify(files,{'sensor.msg':sha(b'float32 x\nfloat32 y\n')})
            with self.assertRaises(ValueError):git_snapshot(p,'0'*40)

    def test_archive_link_and_parent_escape_are_rejected(self):
        for name,kind in [('../escape',tarfile.REGTYPE),('link',tarfile.SYMTYPE)]:
            with self.subTest(name=name):
                data=io.BytesIO()
                with tarfile.open(fileobj=data,mode='w') as tar:
                    item=tarfile.TarInfo(name);item.type=kind;item.linkname='/etc/passwd';tar.addfile(item)
                with patch('rm_match.integrations.pb_navigation_workspace.subprocess.check_output',side_effect=['1'*40+'\n',data.getvalue()]):
                    with self.assertRaises(ValueError):git_snapshot('unused','1'*40)

    def test_overlay_anchor_and_hash_changes_fail_closed(self):
        with self.assertRaises(ValueError):replace_once(b'anchor anchor','anchor','replacement')
        with self.assertRaises(ValueError):verify({'file':b'changed'},{'file':sha(b'original')})
        self.assertEqual(replace_once(b'unique anchor\n','anchor','replacement'),b'unique replacement\n')

    def test_owned_output_no_overwrite_escape_and_manifest_actual_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'new';value=b'actual unchanged bytes\n'
            report=write_owned(out,{'msg/a.msg':value},{'upstream_commit':'1'*40})
            self.assertEqual((out/'msg/a.msg').read_bytes(),value)
            self.assertEqual(report['files']['msg/a.msg'],dict(bytes=len(value),sha256=sha(value)))
            with self.assertRaises(ValueError):write_owned(out,{'msg/a.msg':b'replace'}, {})
            with self.assertRaises(ValueError):write_owned(Path(td)/'escape',{'../leak':b'x'}, {})
            self.assertFalse((Path(td)/'leak').exists())


if __name__=='__main__':unittest.main()
