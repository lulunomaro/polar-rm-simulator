"""Entrypoint validation/lifecycle; actual physics safety is tested separately."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import pytest
from rm_match.platform_v2 import __main__ as cli


@pytest.mark.parametrize('invalid',['nan','inf','-inf','-1','100.001','1e999'])
def test_invalid_interval_rejects_before_admission_or_model_preparation(invalid):
    with patch('rm_match.platform_v2.admission.AdmissionPolicy.from_manifest') as policy,\
            patch.object(cli,'MuJoCoBackend') as backend:
        with pytest.raises(SystemExit) as failure:
            cli.main(['--admission-manifest','must-not-be-read.json','--telemetry-publish-interval-ms='+invalid])
        assert failure.value.code==2
        policy.assert_not_called();backend.assert_not_called()


class TelemetryCliTests(unittest.TestCase):
    def fixture(self,fail=None):
        spec=importlib.util.spec_from_file_location('telemetry_cli_fixture',Path(__file__).with_name('test_platform_wsl_navigation_cli.py'))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module.CliLifecycleTests.setup(self,fail=fail)

    def test_explicit_interval_reaches_runtime_and_startup_report(self):
        events,created=self.fixture()
        cli.main(['--admission-manifest','fixture.json','--telemetry-publish-interval-ms','20'])
        self.assertEqual(created['runtime_kwargs']['telemetry_publish_interval_s'],.02)
        self.assertEqual(json.loads(created['stdout'].getvalue())['telemetry_publish_interval_s'],.02)
        self.assertIn('runtime_close',events);self.assertIn('http_close',events)

    def test_omitted_interval_preserves_every_step_default(self):
        _,created=self.fixture()
        cli.main(['--admission-manifest','fixture.json'])
        self.assertEqual(created['runtime_kwargs']['telemetry_publish_interval_s'],0.)
        self.assertEqual(json.loads(created['stdout'].getvalue())['telemetry_publish_interval_s'],0.)

    def test_explicit_interval_does_not_skip_cleanup_on_failure(self):
        events,created=self.fixture(fail='run')
        with self.assertRaisesRegex(ValueError,'run_failed'):
            cli.main(['--admission-manifest','fixture.json','--telemetry-publish-interval-ms','20'])
        self.assertIn('runtime_close',events);self.assertIn('http_close',events)
