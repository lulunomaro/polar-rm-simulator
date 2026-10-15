"""Pinned local identities for the existing stationary native camera wrapper.

This declaration selects identities, not new motion, calibration or fire
capabilities. It is never accepted through HTTP binding configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

from .contracts import ContractError, exact

SCHEMA = "polar.sim.native-robot-scope.v1"
MAX_BYTES = 1024 * 1024


@dataclass(frozen=True)
class NativeRobotIdentity:
    robot_id: str
    team: str
    role: str
    referee_id: int


def _plain_file(path):
    if type(path) is not str and not isinstance(path, Path):
        raise ContractError("native_robot_scope_local_path")
    text = str(path)
    if not text or "\0" in text or "://" in text or text.startswith(("\\\\", "//")):
        raise ContractError("native_robot_scope_local_path")
    selected = Path(path).absolute()
    if (".." in selected.parts or selected != selected.resolve()
        or any(p.is_symlink() for p in (selected, *selected.parents)) or not selected.is_file()):
        raise ContractError("native_robot_scope_plain_file")
    return selected


@dataclass(frozen=True)
class NativeRobotScope:
    robots: tuple[NativeRobotIdentity, ...]
    path: Path | None = None
    sha256: str | None = None

    @property
    def supported_robots(self):
        return [row.robot_id for row in self.robots]

    def verify_unchanged(self):
        if self.path is not None:
            try:
                path = _plain_file(self.path)
                with path.open("rb") as stream:raw = stream.read(MAX_BYTES + 1)
            except (OSError, ValueError):
                raise ContractError("native_robot_scope_changed") from None
            if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != self.sha256:
                raise ContractError("native_robot_scope_changed")
        return self.sha256

    def match(self, robot_id, team, role):
        if type(robot_id) is not str:raise ContractError("native_robot_unsupported")
        row = next((item for item in self.robots if item.robot_id == robot_id), None)
        if row is None:raise ContractError("native_robot_unsupported")
        if (type(team) is not str or team != row.team
            or type(role) is not str or role != row.role):
            raise ContractError("native_robot_scope_observation_mismatch")
        return row

    def declaration(self):
        return dict(schema=SCHEMA, path=None if self.path is None else str(self.path), sha256=self.sha256,
            robots=[dict(robot_id=row.robot_id, team=row.team, role=row.role, referee_id=row.referee_id)
                for row in self.robots], stationary_only=True,
            qualification="locally_declared_identity_not_motion_or_calibration_qualification")


def load_native_robot_scope(path=None):
    """Load and pin one trusted local file, or retain the legacy default.

    Passing the immutable result internally rechecks its original file. Local
    registries use that form for construction/preparation/handover boundaries.
    """
    if type(path) is NativeRobotScope:
        path.verify_unchanged()
        return path
    if path is None:
        return NativeRobotScope((NativeRobotIdentity("red_sentry", "red", "sentry", 7),))
    from ..deployment.profile import read_json_snapshot
    selected = _plain_file(path)
    try:value, digest = read_json_snapshot(selected, MAX_BYTES)
    except (OSError, ValueError):raise ContractError("native_robot_scope_json") from None
    exact(value, ("schema", "robots"), "native_robot_scope")
    if type(value["schema"]) is not str or value["schema"] != SCHEMA:
        raise ContractError("native_robot_scope_schema")
    rows = value["robots"]
    if type(rows) is not list or not 1 <= len(rows) <= 64:
        raise ContractError("native_robot_scope_robots")
    robots = [];seen = set()
    for row in rows:
        exact(row, ("robot_id", "team", "role", "referee_id"), "native_robot_scope_row")
        rid = row["robot_id"]
        if type(rid) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", rid) or rid in seen:
            raise ContractError("native_robot_scope_robot_id")
        if type(row["team"]) is not str or row["team"] not in ("red", "blue"):
            raise ContractError("native_robot_scope_team")
        if type(row["role"]) is not str or not row["role"].strip() or len(row["role"]) > 128 or "\0" in row["role"]:
            raise ContractError("native_robot_scope_role")
        if type(row["referee_id"]) is not int or not 1 <= row["referee_id"] <= 255:
            raise ContractError("native_robot_scope_referee_id")
        seen.add(rid);robots.append(NativeRobotIdentity(rid, row["team"], row["role"], row["referee_id"]))
    scope = NativeRobotScope(tuple(robots), selected, digest)
    scope.verify_unchanged()
    return scope
