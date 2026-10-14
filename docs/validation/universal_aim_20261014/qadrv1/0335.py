"""Immutable parsed identities and enrollment preflight races; no subprocesses."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch
from rm_match.deployment import launcher,profile
from rm_match.platform_v2.admission import AdmissionPolicy
from rm_match.platform_v2.contracts import ContractError

# Reuse the existing bounded, non-executable byte fixture without modifying its
# tests or invoking unittest main. No compiler, model or native process runs.
native_fixture=runpy.run_path(str(Path(__file__).with_name('test_deployment.py')))['native_fixture']
CREDENTIAL_A='fixture-A-only-not-a-deployment-secret-32'
CREDENTIAL_B='fixture-B-only-not-a-deployment-secret-32'


def write_policy(path,robots=('red_sentry',),credential=CREDENTIAL_A):
    value=dict(schema='polar.sim.admission.v1',grants=[dict(
        credential_sha256=hashlib.sha256(credential.encode()).hexdigest(),
        role='operator',allowed_robots=list(robots),audit_authorized=False)])
    path.write_text(json.dumps(value),encoding='utf-8')
    return path.read_bytes()


class ParsedIdentityTests(unittest.TestCase):
    def test_policy_hash_binds_the_bytes_that_were_actually_parsed(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'admission.local.json';original=write_policy(path)
            policy=AdmissionPolicy.from_manifest(path)
            self.assertEqual(policy.manifest_sha256,hashlib.sha256(original).hexdigest())
            write_policy(path,robots=('blue_sentry',))
            self.assertEqual(policy.authenticate('operator',CREDENTIAL_A).allowed_robots,('red_sentry',))
            with self.assertRaisesRegex(ValueError,'changed_after_loading'):
                policy.verify_manifest_unchanged(path)

    def test_unchanged_policy_hash_is_available_for_doctor_and_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'admission.local.json';write_policy(path)
            policy=AdmissionPolicy.from_manifest(path)
            self.assertEqual(policy.verify_manifest_unchanged(path),policy.manifest_sha256)
            self.assertNotIn(CREDENTIAL_A,repr(policy))

    def test_native_spec_swap_after_own_lineage_read_cannot_return_foreign_source(self):
        with native_fixture() as (_,path,_):
            original=profile.read_json_snapshot
            def replace_after_snapshot(selected,*a,**kw):
                parsed,digest=original(selected,*a,**kw)
                if Path(selected)==path:
                    replacement=deepcopy(parsed)
                    replacement['source_identity']['base_commit']='FOREIGN_SOURCE_FIXTURE'
                    path.write_text(json.dumps(replacement))
                return parsed,digest
            with patch.object(profile,'read_json_snapshot',side_effect=replace_after_snapshot):
                with self.assertRaisesRegex(ContractError,'changed_after_registration'):
                    profile.validate_t2_spec(path)

    def test_native_spec_stable_snapshot_keeps_exact_input_identity(self):
        with native_fixture() as (_,path,value):
            checked,digest=profile.validate_t2_spec(path)
            self.assertEqual(checked['source_identity'],value['source_identity'])
            self.assertEqual(digest,hashlib.sha256(path.read_bytes()).hexdigest())


class CustomEnrollmentRaceTests(unittest.TestCase):
    def report(self,policy):
        return dict(ready_to_attempt=True,checks=[dict(name='local_admission',ok=True,
            detail=dict(manifest_sha256=policy.manifest_sha256,scope=['red_sentry'],audit_authorized=False)),
            dict(name='own_t2_native_assets',ok=True,detail=dict(spec_sha256='a'*64))])

    def test_policy_changed_after_doctor_fails_before_output_or_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'admission.local.json';write_policy(path)
            initial=AdmissionPolicy.from_manifest(path);report=self.report(initial)
            write_policy(path,robots=('blue_sentry',))
            plan=dict(provision_local_admission=False,admission_manifest=str(path),out=str(root/'fresh'))
            with patch.object(launcher,'doctor',return_value=report), \
                 patch.object(launcher.subprocess,'Popen') as start, \
                 patch.dict('os.environ',{'POLAR_SIM_ADMISSION_CREDENTIAL':CREDENTIAL_A}):
                with self.assertRaisesRegex(ValueError,'changed_after_doctor'):launcher.launch(plan)
                start.assert_not_called()
            self.assertFalse((root/'fresh').exists())

    def test_client_changed_during_ready_is_not_started_or_given_credential(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'admission.local.json';write_policy(path)
            policy=AdmissionPolicy.from_manifest(path)
            expected_patch=dict(base_commit=profile.CLIENT_COMMIT,patch_sha256='b'*64,manifest_sha256='c'*64)
            plan=dict(provision_local_admission=False,admission_manifest=str(path),out=str(root/'fresh'),
                server_argv=['unexecuted-server-fixture'],client_argv=['unexecuted-client-fixture'],
                sim_root=str(root),client_root=str(root),gl='egl',max_wall_seconds=1.,
                url='http://127.0.0.1:8766',client_patch=expected_patch)
            ready=dict(event='ready',profile=profile.PROFILE,url=plan['url'],spec_sha256='a'*64,
                admission_policy_sha256=policy.manifest_sha256,native_registered=True,
                transport='loopback_only',automatic_binding=False,fire_authority='manual_only',
                adapter_ids=['aim_native_rmcs_v1'])
            class Server:
                returncode=None
                stdout=io.BytesIO((json.dumps(ready)+'\n').encode())
                def poll(self):return self.returncode
                def terminate(self):self.returncode=0
                def kill(self):self.returncode=-9
                def wait(self,timeout):return self.returncode
            server=Server()
            with patch.object(launcher,'doctor',return_value=self.report(policy)), \
                 patch.object(launcher,'check_client',return_value={'client_patch':dict(expected_patch,patch_sha256='d'*64)}) as inspect, \
                 patch.object(launcher.subprocess,'Popen',return_value=server) as start, \
                 patch.dict('os.environ',{'POLAR_SIM_ADMISSION_CREDENTIAL':CREDENTIAL_A}), \
                 patch('builtins.print'):
                self.assertEqual(launcher.launch(plan),2)
                inspect.assert_called_once_with(plan['client_root'])
                self.assertEqual(start.call_count,1)
                self.assertNotIn('POLAR_SIM_ADMISSION_CREDENTIAL',start.call_args.kwargs['env'])
                self.assertEqual(server.returncode,0)
            result=json.loads((root/'fresh/launch_result.json').read_text())
            self.assertEqual(result['reason'],'launch_error')
            self.assertIn('client_patch_changed_after_plan',result['error'])
            for output in (root/'fresh').glob('*.json'):
                self.assertNotIn(CREDENTIAL_A,output.read_text())

    def test_different_scoped_credential_after_doctor_cannot_silently_change_grant(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'admission.local.json';write_policy(path)
            value=json.loads(path.read_bytes())
            value['grants'].append(dict(credential_sha256=hashlib.sha256(CREDENTIAL_B.encode()).hexdigest(),
                role='operator',allowed_robots=['blue_sentry'],audit_authorized=False))
            path.write_text(json.dumps(value));report=self.report(AdmissionPolicy.from_manifest(path))
            plan=dict(provision_local_admission=False,admission_manifest=str(path),out=str(root/'fresh'))
            with patch.object(launcher,'doctor',return_value=report), \
                 patch.object(launcher.subprocess,'Popen') as start, \
                 patch.dict('os.environ',{'POLAR_SIM_ADMISSION_CREDENTIAL':CREDENTIAL_B}):
                with self.assertRaisesRegex(ValueError,'grant_changed_after_doctor'):launcher.launch(plan)
                start.assert_not_called()
            self.assertFalse((root/'fresh').exists())


if __name__=='__main__':unittest.main()
