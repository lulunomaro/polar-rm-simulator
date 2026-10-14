"""Small server-owned local enrollment policy, separate from bearer sessions.

No accounts, remote listener or credential logging. Missing policy fails closed
at HTTP enrollment; trusted administrative in-process sessions are explicit in
ControlPlane.open_session and cannot be requested by a network body.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import secrets
from .control import Rejected


@dataclass(frozen=True)
class AdmissionGrant:
    role: str
    allowed_robots: tuple[str, ...]
    audit_authorized: bool


class AdmissionPolicy:
    def __init__(self, grants):
        if type(grants) is not list or not 1 <= len(grants) <= 64:
            raise ValueError('invalid_admission_grant_count')
        entries=[];seen=set()
        for row in grants:
            if type(row) is not dict or set(row) != {'credential_sha256','role','allowed_robots','audit_authorized'}:
                raise ValueError('invalid_admission_grant_fields')
            digest=row['credential_sha256'];role=row['role'];robots=row['allowed_robots'];audit=row['audit_authorized']
            if type(digest) is not str or not re.fullmatch(r'[a-f0-9]{64}',digest) or digest in seen:
                raise ValueError('invalid_or_duplicate_admission_digest')
            if role not in ('operator','spectator') or type(audit) is not bool:
                raise ValueError('invalid_admission_role')
            if type(robots) is not list or len(robots)>64 or any(type(r) is not str or not r or len(r)>128 for r in robots) or len(set(robots))!=len(robots):
                raise ValueError('invalid_admission_robot_scope')
            if (role=='operator' and (not robots or audit)) or (role=='spectator' and (not audit or robots)):
                raise ValueError('role_requires_explicit_scope_or_audit_authorization')
            seen.add(digest);entries.append((digest,AdmissionGrant(role,tuple(robots),audit)))
        self._entries=tuple(entries)
        self.manifest_sha256=None

    @classmethod
    def from_manifest(cls, path):
        path=Path(path)
        if not path.is_file() or path.stat().st_size>65536:
            raise ValueError('bounded_local_admission_manifest_required')
        def pairs(rows):
            value={}
            for key,item in rows:
                if key in value:raise ValueError('duplicate_admission_key')
                value[key]=item
            return value
        def constant(_):raise ValueError('invalid_admission_number')
        with path.open('rb') as stream:raw=stream.read(65537)
        if len(raw)>65536:raise ValueError('bounded_local_admission_manifest_required')
        value=json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)
        if type(value) is not dict or set(value)!={'schema','grants'} or value['schema']!='polar.sim.admission.v1':
            raise ValueError('invalid_admission_manifest')
        policy=cls(value['grants'])
        policy.manifest_sha256=hashlib.sha256(raw).hexdigest()
        return policy

    def verify_manifest_unchanged(self,path):
        """Pin the exact parsed bytes, not a second independent identity read."""
        with Path(path).open('rb') as stream:raw=stream.read(65537)
        if not self.manifest_sha256 or len(raw)>65536 or hashlib.sha256(raw).hexdigest()!=self.manifest_sha256:
            raise ValueError('admission_manifest_changed_after_loading')
        return self.manifest_sha256

    def validate_robots(self, robot_ids):
        available=set(robot_ids)
        if any(set(grant.allowed_robots)-available for _,grant in self._entries):
            raise ValueError('admission_scope_contains_unknown_robot')

    def authenticate(self, role, credential):
        if type(credential) is not str or not 32<=len(credential)<=256:
            raise Rejected('admission_required',401)
        digest=hashlib.sha256(credential.encode('utf-8')).hexdigest()
        grant=next((grant for expected,grant in self._entries if secrets.compare_digest(expected,digest)),None)
        if grant is None:raise Rejected('admission_denied',401)
        if role!=grant.role:raise Rejected('admission_role_forbidden',403)
        return grant

    def __repr__(self):
        return f'AdmissionPolicy(grants={len(self._entries)})'
