"""Memory-only SDK and environment admission; no sockets, Qt or real secrets."""
import json
from unittest.mock import patch
import unittest

from rm_client.sim_platform_client import PlatformClient
from rm_client.sim_platform_transport import PlatformTransport


class AdmissionTests(unittest.TestCase):
    def test_open_sends_credential_but_diagnostics_and_return_do_not_expose_it(self):
        secret='synthetic-test-credential-1234567890123456'
        c=PlatformClient('http://127.0.0.1:8766',admission_credential=secret)
        sent=[]
        def request(path,body,**kwargs):
            sent.append(dict(body))
            return dict(token='synthetic-session-token',session_id='s',role='operator',
                        session_expires=101.,server_monotonic_s=100.,admission_credential=secret)
        c._request=request
        result=c.open('operator')
        self.assertEqual(sent[0]['credential'],secret)
        self.assertNotIn(secret,json.dumps(result));self.assertNotIn(secret,json.dumps(c.diagnostics()))
    def test_transport_environment_is_read_into_sdk_memory_and_explicit_value_wins(self):
        with patch.dict('os.environ',{'POLAR_SIM_ADMISSION_CREDENTIAL':'synthetic-env-credential-1234567890123456'}):
            transport=PlatformTransport(role='operator')
            self.assertEqual(transport.client._admission_credential,'synthetic-env-credential-1234567890123456')
            explicit=PlatformTransport(role='operator',admission_credential='synthetic-explicit-credential-1234567890123456')
            self.assertEqual(explicit.client._admission_credential,'synthetic-explicit-credential-1234567890123456')
            self.assertNotIn('synthetic-env-credential',json.dumps(transport.diagnostics()))
    def test_invalid_admission_values_fail_without_storing_or_diagnostic_secret(self):
        for value in (True,15,'short','x'*257):
            with self.subTest(type=type(value).__name__),self.assertRaisesRegex(ValueError,'Invalid admission credential'):
                PlatformClient('http://127.0.0.1:8766',admission_credential=value)


if __name__=='__main__':unittest.main()
