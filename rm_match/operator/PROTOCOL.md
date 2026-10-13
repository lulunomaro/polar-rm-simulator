# POLAR simulation operator v1

This is a **simulation-only, local native-client** API. It has no hardware,
serial, DT7, CAN, MQTT, paid service or inference API transport. The bridge
binds exactly `127.0.0.1`, by default port `8768`. It rejects unexpected Host
headers, every browser Origin, CORS preflight, non-JSON control, non-finite
numbers, and oversized bodies. Do not expose it through a proxy or public port.

## Session and control

`GET /session` returns schema `polar.sim.operator.v1`, fresh process `session_id`,
integer `epoch`, selected `robot_id` (`red_infantry` by default),
`server_time_ms` (Unix milliseconds), `ttl_ms=250`, state and limits. Client
estimates a clock offset using the response and its request midpoint. It must
clear all keys, mouse deltas, fire and deadman when connecting or changing
session/epoch/vehicle. Focus regain never restores previously held input.

`POST /control`, Content-Type `application/json`, body <=4096 bytes:

```json
{
  "session_id": "from-session", "epoch": 0, "robot_id": "red_infantry",
  "seq": 1, "sent_at_ms": 1791784800000,
  "focus": true, "deadman": true,
  "vx_mps": 0.0, "vy_mps": 0.0,
  "yaw_rate_rps": 0.0, "pitch_rate_rps": 0.0, "fire": false
}
```

`seq` is a nonnegative safe JSON integer strictly greater than the last accepted
sequence; gaps are allowed, repeats and reordering are rejected. Timestamp must
be less than 250 ms old and at most 50 ms in the future. The remaining lease is
reduced by transit age, and expires using monotonic time, not simulation time.
Unix-clock rollback cannot prolong it. Send fresh state at 20–50 Hz.

Coordinates are **chassis-body**: vx forward (W positive/S negative), vy left
(A positive/D negative). Each axis is limited to 1 m/s and diagonal motion is
normalized to 1 m/s. Gimbal yaw rate is left-positive, so mouse-right is negative;
pitch rate is up-positive, so mouse-up is positive. Both are limited to 2 rad/s.
This version has no chassis-yaw input. Gimbal position limits are ±3.14 rad and
[-0.4,0.5] rad pitch. Commands drive the provisional actuator model, never qpos
teleports. Fire is a held **virtual** trigger subject to the existing referee.

Success HTTP 200 or rejected control HTTP 409 returns `accepted`, `reason`,
`session_id`, `epoch`, `robot_id`, `seq`, `last_seq`, `server_time_ms`, and `schema`.
A client must verify acknowledgement identity and sequence. Malformed HTTP/JSON
returns 400/413/415 and may have only `accepted:false` and `reason`.

Focus loss or deadman release neutralizes synchronously when received. Invalid
control also neutralizes. A lost TCP connection alone is not a disconnect signal
because HTTP requests are stateless: lost heartbeats neutralize within the
250 ms control lease. Client should send an explicit release on blur/disconnect,
then stop its input producer. Only a fresh, valid, higher-sequence command with
focus and deadman enabled can reacquire control. New process IDs and epoch or
vehicle changes invalidate old commands and frames. Reset remains unavailable.
The optional selection extension advertises `/select_robot` only after actual
model-role validation; see ROBOT_SELECTION.md for its neutral/rearm barriers.
CLI `--robot` still chooses the launch identity.

Neutral means zero chassis force/torque, held gimbal pose, and no fire; a physical
body can coast. Physics rechecks the gate every step. HTTP input and camera
rendering use independent threads; rendering operates on a separate copied
MjData and cannot hold an old control live by blocking the physics watchdog.

## Telemetry

`GET /telemetry` is a cached JSON snapshot plus current control state. Fields:

- identity/time: schema, session_id, epoch, robot_id, server_time_ms, sim_time
- phase, countdown (null), remaining_seconds, terminal_reason
- own: object with robot_id, team, role, hp, max_hp, ammo, heat, heat_max,
  xy:[x,y], chassis_yaw, gimbal_yaw, pitch, alive
- robots: list of the same object shape; map_source is
  `simulator_truth_display_only`. This is explicitly simulator map/debug data,
  not a claim of sensed enemy positions. It is never an input to operator/AI aim.
- vp:{red,blue}, control_owner, events:list of recent referee events
- control: current gate status, including state/reason/last_seq and input values
- camera: available, first_person:true, robot_id, overlays:false; when ready
  frame_seq, sim_time, width, height, epoch
- applied_operator_command: actuator command for QA, no hardware output
- performance: wall_seconds, physics_seconds, real_time_factor, camera_target_fps
- limitations, simulation_only:true, hardware_transport:false

Unknown state is null or absent until initialized. Do not replace it with a
fake live value. `runtime_state` may be starting/running/finished/stopped/error.

## Camera

`GET /frame.jpg` returns HTTP 503 until ready. Then it returns an actual JPEG
from `{robot_id}__aim`, never arena_overview. Headers include Content-Type
image/jpeg, Content-Length, X-Sim-Session-Id, X-Sim-Epoch, X-Frame-Seq,
X-Sim-Time, X-Robot-Id, X-Camera-Name, X-Frame-Width, X-Frame-Height, and
X-Camera-Overlays:false. Client verifies identity, increasing sequence, bounded
body size and image dimensions. Frames are cache snapshots and may be repeated.
Physical projectile spheres can appear; no trajectory line, hit marker, target
truth label or other spectator overlay is drawn in raw camera input.

## Scope and provenance

The original six-robot shared-world MuJoCo core and verified-subset judge remain
in use. Only the selected vehicle's actuator command is replaced by human input.
Other five use existing navigation and colour-pixel policies, with rate-limited
cameras. Original virtual supply-zone ammo purchasing is retained, including for
the selected infantry. This is a new interactive scenario, not the frozen v5
231-second evaluation or the actual-source sentry/RL benchmark.

Low-FPS CPU/llvmpipe is supported as a demonstrator; real-time FPS, calibrated
hardware dynamics and full official rule conformance are not claimed.

## Optional mode-request extension 1: actual spin, Free frame only

Check `session.capabilities.operator_modes_version == 1` before sending this
extension. Add the complete optional `mode_request` object to the existing
`POST /control` body; it shares exactly the same identity, sequence, focus,
deadman and 250 ms lease. Omitting it preserves the legacy no-spin behavior:

```json
{
  "spin_enabled": true,
  "spin_direction": "ccw",
  "spin_speed_dps": 120,
  "chassis_follow": "free"
}
```

Directions are lowercase `cw`, `ccw`, or `auto`. Positive world yaw is CCW;
`auto` deterministically resolves to CCW, with no target-dependent decision.
Speed is the requested angular speed in degrees/second, finite 120–720 inclusive,
matching the existing ModList unit. Unknown keys, unsupported enum values and
out-of-range numbers reject the whole control and neutralize immediately. The
initial process mode is off regardless of the client's saved module defaults.
Clients should clear movement/mouse/trigger and require explicit re-arming after
an intentional mode change; continuously repeating the same request does not
reset it.

Spin drives the existing MuJoCo base-yaw actuator through a provisional yaw-rate
servo (damping feedforward plus rate error, bounded by the model's ±20 torque
limit). It changes actual physical orientation and velocity. The requested
maximum need not be reached under torque saturation, contact or dynamics. An
explicit spin-off request brakes toward zero angular velocity while the lease
is active. Lease loss instead removes drive torque and fire immediately; the
physical body can coast. Nothing teleports qpos or changes the original model.

`telemetry.operator_modes` contains:

- `requested`: last validated mode request; `request_seq`: its sequence
- `effective`: spin_enabled, direction_resolved (null when inactive), requested
  spin_speed_dps (zero when inactive), target_yaw_rate_rps, chassis_follow
- `effective_seq`: applied request sequence, null while safety-gated
- `reason`: spin_active, spin_off, torque_saturated, or the safety-gate reason
- `measured`: actual chassis_yaw_rate_rps and actuator yaw_torque from MuJoCo
- `saturated`: whether the servo requested torque outside the actuator range
- `supported`, coordinate_frame=chassis_body, gimbal_yaw_frame=relative_to_chassis

Effective here means the requested controller is engaged, not that its target
speed has been reached. Read `measured` for actual physics. Existing
`own.gimbal_yaw` remains relative to the chassis; `own.world_gimbal_yaw` is
chassis_yaw + gimbal_yaw, and `own.chassis_yaw_rate_rps` is measured base rate.
No world-stabilized gimbal is claimed. With spin enabled, a fixed relative gimbal
can rotate in world coordinates.

The legacy mode capability remains `chassis_follow_modes:['free']` for strict
older-client compatibility. Existing vx/vy remain chassis-body forward/left.
New driving-reference modes use the separately versioned `drive_axes` extension
below. Automatic chassis-yaw following, power limiting, buffer protection and
world-stabilized gimbal control remain unavailable. They are not inferred from
the ModList defaults. Explicit client-triggered spin-on-hit is documented in
ROBOT_SELECTION.md and retains its existing safety gates.
The hardware-specific Mock Output option does not create any hardware route.
The displayed map is a simple simulator XY rectangle x=[-6,6], y=[-4,4] metres;
it is not an authoritative competition terrain chart.

## Optional autoaim-request contract: source adapter unavailable

`capabilities.aim_request_version=1` accepts a complete `aim_request` object with
`enabled`, `hold` (booleans), `fov_degrees` (10–180), `circle_radius_x_norm` and
`circle_radius_y_norm` (each >0 and <=2). The radii are fractions of image width
and height. The contract has image/calibration FOV admission tests for a future
source adapter, but it does not run target selection or alter actuation here.

`telemetry.autoaim` always reports available=false, active=false,
authority=manual and fire_authority=manual_only. An enabled right-button request
reports source_adapter_unavailable. No colour baseline is silently substituted,
no enemy ground truth is consulted, and requested circles/FOV settings are not
reported as applied to a live detector. Invalid aim requests reject and neutralize
the whole command. Actual-source integration requires a separate qualification.

## Cached measurement identity and fail-closed boundaries

Telemetry retains the identity and simulation time of its physical sample. After
an epoch/vehicle change, the endpoint reports telemetry_available=false with
telemetry_identity_not_ready until a current-identity physics/control sample is
published; it does not relabel old own/mode data. During lease loss, effective
spin and effective_seq are cleared immediately in the response. The historical
measured torque is retained with measurement_sim_time, and
applied_operator_command with applied_command_sim_time; these are sampled values,
not a claim that a stopped physics loop has already applied zero torque.

An omitted aim_request preserves legacy behavior; an explicitly null request
is invalid and neutralizes the entire command. Nonfinite selected-robot qpos or
qvel yields a finite neutral adapter command, never a NaN hold position or torque.
This adapter check does not qualify recovery of an externally corrupted MuJoCo
world state or hardware sensor faults.


## Optional SIM driving reference directions (version 1)

Check `capabilities.chassis_drive_frame_version == 1` and
`capabilities.chassis_drive_modes == ["free", "gimbal", "field"]`. These are
WASD driving reference directions only. They do not turn chassis yaw toward the
gimbal and do not add world-stabilized gimbal control. The legacy
`chassis_follow_modes:["free"]` capability and top-level `coordinate_frame` are
unchanged so strict old clients retain their existing Free/spin behavior.
Each selected robot profile repeats the new capability and modes. No capability
means the client must stay on the old Free/vx/vy contract.

Add `drive_axes:{"forward_mps":0.4,"left_mps":0.0}` to `/control` and set
`mode_request.chassis_follow` to `free`, `gimbal`, or `field`. W is forward-positive,
A is left-positive. Both legacy `vx_mps` and `vy_mps` must be present and exactly
zero whenever `drive_axes` is present. Mixed nonzero legacy/new axes are rejected
with `mixed_drive_axes_and_legacy_velocity`. The axes object must contain exactly
those two finite numeric keys, each within [-1,1]. Booleans, NaN/Inf, enormous
integers, extras and missing keys are rejected. A diagonal norm above 1 is
normalized to the advertised resultant speed limit, 1 m/s. Non-Free modes must
include new axes, including zero-axis release packets; otherwise rejection is
`drive_axes_required_for_mode`. An unknown mode is `unsupported_chassis_follow`.

At each physics step the bridge reads its current selected robot's own physical
pose. It never uses a client-supplied pose, delayed telemetry, target/map truth,
or the commanded gimbal angle to compute the reference:

- Free: measured chassis world yaw
- Field: yaw zero, world +X forward and +Y left, for both teams; no blue mirror
- Gimbal: measured chassis world yaw plus measured relative gimbal yaw

All angles are radians, counterclockwise-positive viewed from above. With
reference yaw r, world target velocity is
`[cos(r)*forward - sin(r)*left, sin(r)*forward + cos(r)*left]`.
The unchanged provisional physical velocity servo applies bounded world forces;
it does not teleport the body. Spin remains an independently bounded yaw-rate
servo. A spin changes the Free/Gimbal reference on subsequent physics ticks;
Field remains fixed to world axes. The new capability does not add power or
buffer modeling.

Changing the reference while an active lease is armed revokes all input and
returns `drive_frame_release_required`. This barrier persists across subsequent
armed packets until a valid focus=false or deadman=false packet is accepted.
The client clears keys/mouse/fire, sends and acknowledges a neutral release,
changes mode, and requires explicit F2 re-arming. Repeated identical heartbeats
preserve the input revision. New-axis or reference changes invalidate in-flight
source results. Epoch/selection transitions, focus loss, expiry, invalid packets
and nonfinite physical own state neutralize the command. New axes, including a
tiny nonzero value with legacy vx/vy zero, count as requested movement and revoke
stationary-only source authority. Source never obtains automatic-fire authority.

`telemetry.operator_modes.drive` contains:

- `active`, `mode`, `input_kind` (`legacy_chassis` or `drive_axes`), and sampled
  `input_revision` (control safety revision)
- `reference_yaw_rad`, normalized to [-pi,pi] while active
- `world_velocity_target_mps:[x,y]`, the requested world velocity, not achievement
- `measured_world_velocity_mps:[x,y]`, current physical velocity, and
  `measurement_valid`; invalid components use zero placeholders with this flag
  false and cannot be presented as confirmed measurements
- `applied_world_force_n:[x,y]`, actual actuator inputs at publication
- `saturated`, whether translation force was clipped; separate from yaw saturation
- `reason`, `coordinate_frame:"world"`, explicit units, and
  `automatic_chassis_yaw_follow:false`

Inactive feedback uses mode Free, input_kind legacy_chassis, reference yaw zero
and zero targets. On a physical neutral tick the force command is zero. HTTP
reads may precede that next physical tick: focus loss, lease expiry or a newly
accepted input revision immediately revoke cached active/reference/target state,
while preserving historical measured velocity and applied force. The snapshot
adds `drive.measurement_sim_time` (also available on `operator_modes`) so these
values are not misrepresented as newly measured zeros. A fresh revision that
has not yet been physically sampled reports `new_input_pending`. Measured
velocity can remain nonzero while coasting. Identical heartbeats do not invalidate
a measurement merely because the packet sequence advanced.
`effective.chassis_follow` is the active requested reference or Free while
inactive; `effective_seq` and control identity must match before a client labels
it confirmed. `supported.chassis_drive_modes` and version expose the extension
without changing `supported.chassis_follow:["free"]`.

Run `python -m unittest rm_match.operator.test_drive_frames -v` for CPU safety and
transform checks. `python -m rm_match.operator.qa_drive_frames --out <new-dir>`
runs bounded no-render physical displacement/velocity checks and writes explicit
initial-condition and measurement evidence. Neither run qualifies the original
Qt UI, native detector execution, full matches, benchmark results or hardware.
