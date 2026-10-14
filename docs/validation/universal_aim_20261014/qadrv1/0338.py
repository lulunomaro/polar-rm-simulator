"""Migration byte/link identity only; no ROS, DLL loading, nodes or sensors."""
import os
from pathlib import Path,PurePosixPath
import unittest
from tempfile import TemporaryDirectory
from tools.migrate_humble_runtime_ext4 import copy_tree_checked,digest,remap_path


class RuntimeCopyTests(unittest.TestCase):
    def test_exact_regular_files_and_mode_are_recorded(self):
        with TemporaryDirectory() as td:
            src=Path(td)/'src';src.mkdir();(src/'lib').mkdir();p=src/'lib/payload';p.write_bytes(bytes(range(256))*7)
            dst=Path(td)/'dst';rows=[];copy_tree_checked(src,dst,[(src,dst)],rows.append)
            row=next(r for r in rows if r['kind']=='file')
            self.assertEqual(p.read_bytes(),(dst/'lib/payload').read_bytes())
            self.assertEqual(row['source_sha256'],digest(p));self.assertEqual(row['destination_sha256'],digest(p))
            self.assertEqual(row['source_mode'],row['destination_mode'])
            with self.assertRaises(ValueError):copy_tree_checked(src,dst,[(src,dst)],rows.append)

    def test_path_mapping_is_boundary_checked_and_specific(self):
        mapping=[(PurePosixPath('/old'),PurePosixPath('/new')),(PurePosixPath('/old/livox'),PurePosixPath('/new/custom'))]
        self.assertEqual(remap_path('/old/livox/lib',mapping),'/new/custom/lib')
        self.assertEqual(remap_path('/older/lib',mapping),'/older/lib')
        self.assertEqual(remap_path('/opt/ros/humble',mapping),'/opt/ros/humble')

    @unittest.skipUnless(os.name=='posix','POSIX link and mode proof')
    def test_links_not_followed_and_absolute_owned_targets_explicitly_mapped(self):
        with TemporaryDirectory() as td:
            src=Path(td)/'src';src.mkdir();p=src/'real';p.write_bytes(b'exact');os.chmod(p,0o640)
            (src/'relative').symlink_to('real');(src/'absolute').symlink_to(p)
            dst=Path(td)/'dst';rows=[];copy_tree_checked(src,dst,[(src,dst)],rows.append)
            self.assertEqual(os.readlink(dst/'relative'),'real')
            self.assertEqual(os.readlink(dst/'absolute'),str(dst/'real'))
            self.assertEqual((dst/'absolute').read_bytes(),b'exact')
            self.assertTrue(next(r for r in rows if r.get('source_link')==str(p))['mapped'])
            self.assertEqual((dst/'real').stat().st_mode & 0o777,0o640)
            alias=Path(td)/'alias';alias.symlink_to(src,target_is_directory=True)
            with self.assertRaises(ValueError):copy_tree_checked(alias,Path(td)/'other',[],rows.append)


if __name__=='__main__':unittest.main()
