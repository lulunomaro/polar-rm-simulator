"""Local enrollment and source-composition boundaries; no native execution."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from rm_match.deployment.enrollment import provision_operator
from rm_match.deployment import profile, launcher
from rm_match.platform_v2.admission import AdmissionPolicy
from rm_match.platform_v2.control import Rejected


class EnrollmentTests(unittest.TestCase):
    def test_default_grant_never_writes_clear_credential_and_cannot_elevate(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'admission.json'; credential=provision_operator(path)
            self.assertNotIn(credential,path.read_text())
            policy=AdmissionPolicy.from_manifest(path)
            grant=policy.authenticate('operator',credential)
            self.assertEqual(grant.allowed_robots,('red_sentry',))
            self.assertFalse(grant.audit_authorized)
            with self.assertRaises(Rejected):policy.authenticate('spectator',credential)
            with self.assertRaises(FileExistsError):provision_operator(path)

    def test_clean_subprocess_environment_removes_enrollment_secret(self):
        with patch.dict('os.environ',{'POLAR_SIM_ADMISSION_CREDENTIAL':'private'}):
            self.assertNotIn('POLAR_SIM_ADMISSION_CREDENTIAL',launcher.clean_environment())


class SourceCompositionTests(unittest.TestCase):
    def test_own_tracker_and_frontend_are_both_required(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); overlay=root/'overlays/corners_contour_v1.cpp'
            overlay.parent.mkdir(); overlay.write_bytes(b'unit fixture, never compiled')
            digest=profile.digest(overlay)
            composition=dict(schema='rmcs-own-source-composition.v1',
                tracker_patch_sha256=profile.T2_PATCH,vision_frontend_sha256=digest)
            composite=hashlib.sha256(json.dumps(composition,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            source=dict(base_commit=profile.T2_BASE,tracker_patch_sha256=profile.T2_PATCH,
                patch_identity_format='rmcs-own-source-composition.v1',patch_sha256=composite,
                vision_frontend=dict(id='image_contour_corners_v1',source_path='overlays/corners_contour_v1.cpp',source_sha256=digest))
            with patch.object(profile,'RUNTIME_ROOT',root):
                self.assertEqual(profile.validate_source_identity(source),('contour-v1',{'overlays/corners_contour_v1.cpp':digest}))
                for key,value in [('tracker_patch_sha256','0'*64),('patch_sha256',profile.T2_PATCH),('base_commit','40f7')]:
                    wrong=deepcopy(source);wrong[key]=value
                    with self.assertRaises(ValueError):profile.validate_source_identity(wrong)
                for key,value in [('id','unknown'),('source_path','../escape.cpp'),('source_sha256','0'*64)]:
                    wrong=deepcopy(source);wrong['vision_frontend'][key]=value
                    with self.assertRaises(ValueError):profile.validate_source_identity(wrong)
                overlay.write_bytes(b'changed')
                with self.assertRaises(ValueError):profile.validate_source_identity(source)
