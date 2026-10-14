from dataclasses import dataclass
from typing import Protocol
import numpy as np

@dataclass(frozen=True)
class Observation:
    episode: int
    sim_time: float
    rgb: np.ndarray  # Empty (0,0,3) if caller explicitly disables camera capture.
    fovy_degrees: float
    # Ideal own-joint sensors only. No enemy poses, target IDs or segmentation.
    own_qpos: tuple[float, ...]
    own_qvel: tuple[float, ...]
    own_hp: int
    ammo: int
    robot_id: str = "robot0"
    odom_xyyaw: tuple[float, float, float] | None = None
    odom_vxyw: tuple[float, float, float] | None = None
    ranges: tuple[float, ...] = ()
    range_angles: tuple[float, ...] = ()
    range_max: float = 8.0
    own_heat: float = 0.
    own_weak: bool = False
    team: str = ""
    role: str = ""
    remaining_seconds: float = 0.
    # Optional capture timestamp and own pose at capture; never target truth.
    camera_sim_time: float | None = None
    camera_own_qpos: tuple[float, ...] | None = None
    camera_odom_xyyaw: tuple[float, float, float] | None = None
    # Referee/status inputs, never adversary truth. Unknown phases fail closed.
    match_phase: str = "running"
    emergency_stop: bool = False
    own_max_hp: float = 0.

@dataclass(frozen=True)
class Command:
    force_x: float = 0.
    force_y: float = 0.
    yaw_torque: float = 0.
    gimbal_yaw: float = 0.
    gimbal_pitch: float = 0.
    fire: bool = False

class Controller(Protocol):
    def reset(self, episode: int) -> None: ...
    def act(self, observation: Observation) -> Command: ...

@dataclass(frozen=True)
class NavigationIntent:
    # Matches repository intent level, not a motor or ground-truth teleport API.
    behavior: str
    target_point: tuple[float, float]
    reason: str = ''
