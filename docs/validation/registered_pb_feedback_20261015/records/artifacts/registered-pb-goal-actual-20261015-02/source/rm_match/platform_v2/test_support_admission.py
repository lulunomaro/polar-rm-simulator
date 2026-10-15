"""Explicit synthetic credentials for local HTTP fixtures, never deployment secrets."""
import hashlib
from .admission import AdmissionPolicy

OPERATOR_CREDENTIAL='test-only-operator-credential-not-for-deployment'
AUDIT_CREDENTIAL='test-only-audit-credential-not-for-deployment'


def fixture_policy(robot_ids):
    return AdmissionPolicy([
        dict(credential_sha256=hashlib.sha256(OPERATOR_CREDENTIAL.encode()).hexdigest(),
             role='operator',allowed_robots=list(robot_ids),audit_authorized=False),
        dict(credential_sha256=hashlib.sha256(AUDIT_CREDENTIAL.encode()).hexdigest(),
             role='spectator',allowed_robots=[],audit_authorized=True),
    ])
