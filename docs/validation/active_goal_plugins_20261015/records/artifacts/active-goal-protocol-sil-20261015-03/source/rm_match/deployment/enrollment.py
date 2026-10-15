"""Provision a local operator grant; retain the clear credential only in memory."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import secrets
from ..platform_v2.admission import AdmissionPolicy


def provision_operator(path, allowed_robots=('red_sentry',)):
    credential = secrets.token_urlsafe(32)
    value = dict(schema='polar.sim.admission.v1', grants=[dict(
        credential_sha256=hashlib.sha256(credential.encode()).hexdigest(),
        role='operator', allowed_robots=list(allowed_robots), audit_authorized=False)])
    AdmissionPolicy(value['grants'])
    path = Path(path)
    encoded = (json.dumps(value, indent=2) + '\n').encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(encoded)
    return credential
