"""Saved actual pixels selected by exact request identity; no GL/native/model."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.diagnose_native_saved_compute import select_saved_native_input,saved_storage_workspace


class SavedNativeInputTests(unittest.TestCase):
    raw=b'\x19'*4665600
    sha=hashlib.sha256(raw).hexdigest()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.request=dict(event='native_request',frame_id=10,raw_bgr_sha256=self.sha,
            capture_sim_time=.422,observation_sim_time=.448,episode=0,own_at_capture={'own_odom_at_capture':[1,2,3]})
        self.write_ledger([self.request])

    def write_ledger(self,rows):
        (self.root/'ledger.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in rows),encoding='utf-8')

    def legacy(self,directory='binding'):
        path=self.root/directory/'sensor_input.bgr';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(self.raw)
        return path

    def v2(self,directory='binding'):
        parent=self.root/directory/'actual_frames';parent.mkdir(parents=True,exist_ok=True)
        image=parent/'sensor_10.bgr';image.write_bytes(self.raw)
        manifest=dict(schema='polar.sim.actual_native_frame_evidence.v1',frame_id=10,
            encoding='bgr8',width=1440,height=1080,stride_bytes=4320,bytes=4665600,
            file='sensor_10.bgr',sha256=self.sha)
        path=parent/'sensor_10.json';path.write_text(json.dumps(manifest),encoding='utf-8')
        return image,path,manifest

    def test_legacy_exact_pixels_and_original_request_fields_preserved(self):
        source=self.legacy();got=select_saved_native_input(self.root)
        self.assertEqual(got['input_format'],'legacy_sensor_input_bgr')
        self.assertEqual(got['source'],source);self.assertIsNone(got['manifest'])
        self.assertEqual(got['content'],self.raw);self.assertEqual(got['request'],self.request)
        self.assertEqual(got['request']['capture_sim_time'],.422);self.assertEqual(got['request']['observation_sim_time'],.448)

    def test_v2_exact_manifest_pixels_and_source_provenance(self):
        source,manifest,_=self.v2();got=select_saved_native_input(self.root)
        self.assertEqual(got['input_format'],'v2_actual_frame_manifest')
        self.assertEqual(got['source'],source);self.assertEqual(got['manifest'],manifest)
        self.assertEqual(got['content'],self.raw);self.assertEqual(got['request'],self.request)
        self.assertEqual(got['provenance']['manifest'],'binding/actual_frames/sensor_10.json')
        self.assertEqual(got['provenance']['manifest_sha256'],hashlib.sha256(manifest.read_bytes()).hexdigest())

    def test_v2_manifest_fields_are_exact_and_cannot_redirect_frame(self):
        _,path,original=self.v2()
        for key,value in [('schema','other'),('frame_id',11),('frame_id',True),('width',1439),
            ('height',1079),('stride_bytes',4321),('bytes',4665599),('encoding','rgb8'),
            ('sha256','0'*64),('file','../sensor_10.bgr'),('file','C:/sensor_10.bgr'),
            ('file','sensor_11.bgr'),('unknown',{})]:
            with self.subTest(key=key,value=value):
                path.write_text(json.dumps(dict(original,**{key:value})),encoding='utf-8')
                with self.assertRaises(ValueError):select_saved_native_input(self.root)
        del original['sha256'];path.write_text(json.dumps(original),encoding='utf-8')
        with self.assertRaises(ValueError):select_saved_native_input(self.root)

    def test_tampered_bytes_or_truncated_image_refused_for_both_formats(self):
        for kind in ['legacy','v2']:
            with self.subTest(kind=kind):
                source=self.legacy(kind) if kind=='legacy' else self.v2(kind)[0]
                for content in [b'\x20'*4665600,b'short',self.raw+b'extra']:
                    source.write_bytes(content)
                    with self.assertRaises(ValueError):select_saved_native_input(self.root)
                # Remove each fixture before testing the other input format.
                for f in (self.root/kind).rglob('*'):
                    if f.is_file():f.unlink()

    def test_duplicate_legacy_candidates_and_mixed_formats_refused(self):
        self.legacy('a');self.legacy('b')
        with self.assertRaisesRegex(ValueError,'ambiguous'):select_saved_native_input(self.root)
        (self.root/'b/sensor_input.bgr').unlink();self.v2('b')
        with self.assertRaisesRegex(ValueError,'ambiguous'):select_saved_native_input(self.root)

    def test_duplicate_v2_candidates_refused_even_when_hashes_match(self):
        self.v2('a');self.v2('b')
        with self.assertRaisesRegex(ValueError,'ambiguous'):select_saved_native_input(self.root)

    def test_missing_manifest_or_wrong_filename_does_not_guess_image(self):
        image,path,_=self.v2();path.unlink()
        with self.assertRaisesRegex(ValueError,'missing'):select_saved_native_input(self.root)
        path.write_text('{}',encoding='utf-8');path.rename(path.with_name('sensor_11.json'))
        with self.assertRaisesRegex(ValueError,'missing'):select_saved_native_input(self.root)
        image.unlink()

    def test_missing_image_and_wrong_manifest_location_refused(self):
        image,path,_=self.v2();image.unlink()
        with self.assertRaises(FileNotFoundError):select_saved_native_input(self.root)
        path.rename(path.parent.parent/path.name)
        with self.assertRaisesRegex(ValueError,'outside actual_frames'):select_saved_native_input(self.root)

    def test_unique_well_formed_native_request_required(self):
        self.legacy()
        for rows in [[],[self.request,self.request],[dict(self.request,frame_id=True)],
            [dict(self.request,raw_bgr_sha256='not-sha')],[dict(self.request,raw_bgr_sha256='A'*64)]]:
            with self.subTest(rows=rows):
                self.write_ledger(rows)
                with self.assertRaises(ValueError):select_saved_native_input(self.root)

    def test_duplicate_json_keys_and_nonfinite_values_refused(self):
        _,path,_=self.v2();path.write_text('{"frame_id":10,"frame_id":11}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Duplicate'):select_saved_native_input(self.root)
        path.write_text('{"width":NaN}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Nonfinite'):select_saved_native_input(self.root)

    def test_windows_reparse_attribute_rejected_before_reading_image(self):
        image=self.legacy();original=Path.lstat
        def lstat(path,*args,**kwargs):
            if path==image:return SimpleNamespace(st_mode=original(path).st_mode,st_file_attributes=0x400)
            return original(path,*args,**kwargs)
        with patch.object(Path,'lstat',lstat):
            with self.assertRaisesRegex(ValueError,'reparse'):select_saved_native_input(self.root)

    def test_real_symbolic_link_outside_run_root_refused(self):
        image=self.legacy();external=tempfile.TemporaryDirectory();self.addCleanup(external.cleanup)
        target=Path(external.name)/'other.bgr';image.rename(target)
        try:os.symlink(target,image)
        except OSError as exc:self.skipTest('Host does not permit symlink fixture: '+str(exc))
        with self.assertRaisesRegex(ValueError,'symlink'):select_saved_native_input(self.root)

    def test_storage_variants_preserve_same_pixels_and_remove_only_owned_tempdir(self):
        for mode in ('drvfs','tmpfs'):
            with self.subTest(mode=mode):
                out=self.root/mode;out.mkdir()
                with saved_storage_workspace(out,self.raw,mode,tmpfs_parent=self.root) as state:
                    self.assertEqual(state['image'].read_bytes(),self.raw)
                    self.assertEqual((out/'saved_input.bgr').read_bytes(),self.raw)
                    self.assertEqual(state['image_sha256'],self.sha)
                    if mode=='tmpfs':
                        self.assertNotEqual(state['workspace'],out)
                        if os.name!='nt':self.assertEqual(state['workspace_mode'],'0o700')
                    else:self.assertEqual(state['workspace'],out)
                    (state['workspace']/'tracking_mode').write_bytes(b'multi_ekf\n')
                    self.assertEqual((state['workspace']/'tracking_mode').read_bytes(),b'multi_ekf\n')
                self.assertTrue(state['cleanup']['tmpfs_removed'])
                self.assertEqual(state['cleanup']['tmpfs_created'],mode=='tmpfs')
                self.assertTrue(out.exists());self.assertEqual((out/'saved_input.bgr').read_bytes(),self.raw)

    def test_temp_workspace_removed_and_cleanup_retained_on_exception(self):
        out=self.root/'out';out.mkdir()
        with self.assertRaisesRegex(RuntimeError,'fixture failure'):
            with saved_storage_workspace(out,self.raw,'tmpfs',tmpfs_parent=self.root) as state:
                owned=state['workspace'];self.assertTrue(owned.exists())
                raise RuntimeError('fixture failure')
        self.assertFalse(owned.exists());self.assertTrue(state['cleanup']['tmpfs_removed'])
        self.assertTrue(json.loads((out/'STORAGE_CLEANUP.json').read_text())['tmpfs_removed'])
        self.assertEqual((out/'saved_input.bgr').read_bytes(),self.raw)


if __name__=='__main__':unittest.main()
