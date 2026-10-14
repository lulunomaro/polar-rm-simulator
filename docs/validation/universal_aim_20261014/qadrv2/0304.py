"""Optional spectator annotations of recorded physics, never sensor inputs.

``update`` only copies projectile samples and the cumulative contact ledger.
Call it every physics step, after the referee has resolved that step's contacts.
Also calling it immediately after firing preserves the exact muzzle sample.
``draw`` appends temporary geoms to the supplied *spectator* MjvScene only;
it must never be called from the raw ``image``/``observe`` sensor path.

Trails connect adjacent recorded centers without extrapolation. Impact markers
are centered on the ledger's finite-radius projectile center at contact, not an
invented surface point. Marker size and line width are readability annotations,
not projectile dimensions. No model, MjData, projectile, or referee is modified.
"""
from collections import OrderedDict, deque
from dataclasses import dataclass
import math
from typing import Iterable, Mapping, Sequence

import mujoco
import numpy as np


@dataclass(frozen=True)
class ProjectileSample:
    sim_time: float
    position: tuple[float, float, float]


@dataclass(frozen=True)
class TrailRecord:
    uid: str
    owner: str
    radius: float
    samples: tuple[ProjectileSample, ...]


@dataclass(frozen=True)
class ImpactRecord:
    event_index: int  # Chronological within this episode, starting at zero.
    ledger_index: int  # Original index in MatchSimulation.contact_events.
    projectile_uid: str
    owner: str
    sim_time: float
    position: tuple[float, float, float]
    geom: str
    damage_applied: bool
    kind: str


@dataclass
class _Track:
    owner: str
    radius: float
    samples: deque


def _point(value) -> tuple[float, float, float]:
    point = np.asarray(value, dtype=float)
    if point.shape != (3,) or not np.isfinite(point).all():
        raise ValueError("Spectator positions must be finite three-vectors")
    return tuple(float(v) for v in point)


class SpectatorEffects:
    """Bounded, simulation-time-based trail and contact recorder.

    The contact input is an append-only cumulative ledger. New contacts may be
    unordered within a completed physics step; they are sorted by timestamp and
    original ledger index before receiving chronological event indices. Calling
    ``update`` on every completed step is required, rather than at video cadence.
    Backward time or a shrinking ledger clears history; call ``reset`` explicitly
    on episode reset, including resets at unchanged simulation time.

    ``enabled`` controls drawing only, so toggling effects preserves recent
    samples. ``draw(..., trails=False)`` and ``draw(..., impacts=False)`` control
    each annotation independently. Start from a fresh ``update_scene`` (or clear
    viewer.user_scn.ngeom) before each draw; drawing twice appends twice.
    """

    IMPACT_COLORS = {
        "damage": (0.25, 1.0, 0.3, 1.0),
        "armor_no_damage": (1.0, 0.8, 0.15, 1.0),
        "body": (1.0, 0.4, 0.12, 1.0),
        "environment": (0.8, 0.84, 0.9, 1.0),
    }

    def __init__(
        self, *, enabled: bool = True, trail_seconds: float = 0.18,
        impact_seconds: float = 0.6, max_projectiles: int = 256,
        max_points_per_projectile: int = 256, max_impacts: int = 256,
        line_width: float = 2.5, marker_half_size: float = 0.14,
    ):
        for name, value in (("trail_seconds", trail_seconds),
                            ("impact_seconds", impact_seconds),
                            ("line_width", line_width),
                            ("marker_half_size", marker_half_size)):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for name, value, minimum in (("max_projectiles", max_projectiles, 1),
                                     ("max_points_per_projectile", max_points_per_projectile, 2),
                                     ("max_impacts", max_impacts, 1)):
            if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        self.enabled = enabled
        self.trail_seconds = float(trail_seconds)
        self.impact_seconds = float(impact_seconds)
        self.max_projectiles = max_projectiles
        self.max_points_per_projectile = max_points_per_projectile
        self.max_impacts = max_impacts
        self.line_width = float(line_width)
        self.marker_half_size = float(marker_half_size)
        self.reset()

    def reset(self):
        self._tracks: OrderedDict[str, _Track] = OrderedDict()
        self._impacts: deque[ImpactRecord] = deque(maxlen=self.max_impacts)
        self._ledger_cursor = 0
        self._event_count = 0
        self._last_event_time = -math.inf
        self._time = None

    @property
    def event_count(self) -> int:
        """Number of consumed contacts, including expired/bounded-out markers."""
        return self._event_count

    @property
    def trail_history(self) -> tuple[TrailRecord, ...]:
        return tuple(TrailRecord(uid, track.owner, track.radius, tuple(track.samples))
                     for uid, track in self._tracks.items())

    @property
    def impact_history(self) -> tuple[ImpactRecord, ...]:
        return tuple(self._impacts)

    def update(self, sim_time: float, projectiles: Iterable,
               contact_events: Sequence[Mapping]):
        """Copy actual points and newly finalized contacts; never step physics."""
        now = float(sim_time)
        if not math.isfinite(now):
            raise ValueError("sim_time must be finite")
        if ((self._time is not None and now < self._time) or
                len(contact_events) < self._ledger_cursor):
            self.reset()

        # Validate before copying, so absent/malformed evidence is never rendered
        # as a fabricated trajectory or assumed damage event.
        snapshots = []
        for p in projectiles:
            radius = float(p.radius)
            if not math.isfinite(radius) or radius <= 0:
                raise ValueError("Projectile radius must be finite and positive")
            snapshots.append((str(p.uid), str(p.owner), radius, _point(p.position)))
        new_contacts = []
        for index in range(self._ledger_cursor, len(contact_events)):
            event = contact_events[index]
            when = float(event["sim_time"])
            if not math.isfinite(when) or when > now + 1e-9:
                raise ValueError("Contact must have a finite, non-future timestamp")
            if when < self._last_event_time - 1e-9:
                raise ValueError("Late contact precedes already consumed contacts; reset and replay")
            applied = event["damage_applied"]
            if not isinstance(applied, (bool, np.bool_)):
                raise ValueError("damage_applied must be the finalized referee boolean")
            geom = str(event["geom"])
            # These are the engine's actual robot geom namespaces. Only the
            # referee boolean labels a contact as damage, never the geom name.
            kind = ("damage" if applied else "armor_no_damage" if "__armor_" in geom
                    else "body" if "__" in geom else "environment")
            new_contacts.append((when, index, str(event["projectile"]),
                                 str(event["owner"]), _point(event["position"]),
                                 geom, bool(applied), kind))
        new_contacts.sort(key=lambda item: (item[0], item[1]))
        self._time = now

        for uid, owner, radius, point in snapshots:
            if uid not in self._tracks:
                self._tracks[uid] = _Track(owner, radius,
                    deque(maxlen=self.max_points_per_projectile))
            track = self._tracks[uid]
            sample = ProjectileSample(now, point)
            if not track.samples or sample != track.samples[-1]:
                track.samples.append(sample)
            self._tracks.move_to_end(uid)
        for when, index, uid, owner, point, geom, applied, kind in new_contacts:
            record = ImpactRecord(self._event_count, index, uid, owner, when,
                                  point, geom, applied, kind)
            self._event_count += 1
            self._last_event_time = when
            self._impacts.append(record)
            track = self._tracks.get(uid)
            if track is not None:
                # Contacts often remove projectiles before update. Append the
                # actual TOI center to its old samples; never extend past it.
                if not track.samples or when >= track.samples[-1].sim_time:
                    sample = ProjectileSample(when, point)
                    if not track.samples or sample != track.samples[-1]:
                        track.samples.append(sample)
        self._ledger_cursor = len(contact_events)

        for uid, track in list(self._tracks.items()):
            while track.samples and now - track.samples[0].sim_time >= self.trail_seconds:
                track.samples.popleft()
            if not track.samples:
                del self._tracks[uid]
        while len(self._tracks) > self.max_projectiles:
            self._tracks.popitem(last=False)
        while self._impacts and now - self._impacts[0].sim_time >= self.impact_seconds:
            self._impacts.popleft()

    def _line(self, scene, start, end, color, width):
        if scene.ngeom >= scene.maxgeom:
            return False
        geom = scene.geoms[scene.ngeom]
        mujoco.mjv_initGeom(geom, mujoco.mjtGeom.mjGEOM_LINE,
                           np.zeros(3), np.zeros(3), np.eye(3).ravel(),
                           np.asarray(color, dtype=np.float32))
        mujoco.mjv_connector(geom, mujoco.mjtGeom.mjGEOM_LINE, width,
                            np.asarray(start, dtype=float), np.asarray(end, dtype=float))
        geom.category = mujoco.mjtCatBit.mjCAT_DECOR
        geom.objid = -1
        geom.segid = -1
        scene.ngeom += 1
        return True

    def draw(self, scene, *, trails: bool = True, impacts: bool = True) -> int:
        """Append spectator-only decorations; return number of added geoms.

        Damage is green, non-damaging armor yellow, robot body orange, and world
        geometry pale gray. All are visualization markers of actual contacts.
        Newer markers get scene capacity first. No geometry is added if disabled.
        """
        if not self.enabled or self._time is None:
            return 0
        initial = scene.ngeom
        if impacts:
            for hit in reversed(self._impacts):
                age = self._time - hit.sim_time
                color = (*self.IMPACT_COLORS[hit.kind][:3],
                         max(0.0, 1.0 - age / self.impact_seconds))
                point = np.asarray(hit.position)
                for axis in np.eye(3) * self.marker_half_size:
                    if not self._line(scene, point - axis, point + axis,
                                      color, self.line_width + 1):
                        return scene.ngeom - initial
        if trails:
            for track in reversed(self._tracks.values()):
                points = list(track.samples)
                base = ((1.0, 0.4, 0.25) if track.owner.startswith("red_")
                        else (0.3, 0.7, 1.0) if track.owner.startswith("blue_")
                        else (1.0, 0.9, 0.3))
                for a, b in reversed(list(zip(points, points[1:]))):
                    if a.position == b.position:
                        continue
                    alpha = max(0.0, 1.0 - (self._time - b.sim_time) / self.trail_seconds)
                    if not self._line(scene, a.position, b.position, (*base, alpha), self.line_width):
                        return scene.ngeom - initial
        return scene.ngeom - initial
