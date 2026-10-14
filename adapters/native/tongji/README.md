# Pinned native example for the common aim protocol

This prepares Tongji `sp_vision_25` commit
`bd9f5e798fa3c6dd3b483ae6627796afb41c608d` (MIT). The platform selects a reviewed
local adapter ID. No team or robot name selects an algorithm in core code.

The independent executable links original YOLOV5, Detector/Classifier, Solver,
Tracker and Planner/TinyMPC sources. It retains their thresholds, target models,
filtering and planner fire predicate. Hardware camera, serial, CAN and ROS
acquisition objects are excluded. The logging replacement writes to stderr.

Prepare on Linux so generated model paths are Linux paths. Use
`tools/prepare_tongji_aim_plugin.py --prepare --source-root SOURCE --model-root MODELS
--classifier ORIGINAL_TINY_RESNET --out FRESH --camera-profile CAMERA_JSON`.
The script copies checked sources/models only. It prints CMake commands and does
not execute them. After a real audited build, `write_instance(prepared, binary,
out, source_identity_sha256=...)` creates a locally hash-bound instance JSON.
Run its checked wrapper with `--spec INSTANCE --spec-sha256 SHA` through the
common local aim-plugin registration. External deployment/environment and
wrapper-source identity must also be frozen by the launching supervisor.

The wrapper accepts `polar.sim.adapter.jsonl.v1` reset/act messages containing
public V2 camera observations and emits canonical action or explicit aim status.
It echoes all six original authority fields, including the foreign host
`wall_deadline`; Linux never reinterprets that value as a local clock. Native
prediction uses differences of original capture/control simulation nanoseconds.
Captured own gimbal orientation is provided to the original solver. Original
planner inertial yaw is converted to base-relative yaw, and negative-up planner
pitch is converted to the public positive-up convention. Automatic fire remains
disabled; `would_fire` is diagnostic evidence only.

This first source adapter is limited to the original tracker's 1440×1080 image
center and a stationary capture origin. It rejects body speed above .03 m/s or
.03 rad/s, origin displacement above .025 m, mismatched camera calibration,
stale/replayed frames, mismatched source results and predicted `temp_lost`
authority. These are explicit adapter limitations. They do not qualify moving
localization, hardware calibration, detector accuracy or live deadlines.

Startup constructs the real models without inference. Its cost has not been
measured yet: the common reset deadline remains 2 s, so this instance must be
rejected if it cannot meet that gate. Any future zero-inference preparation must
be reviewed and preserve the owned process rather than fake readiness. Pure
tests here do not prove an ELF build, native cleanup, actual NN or live control.
Native stderr, request/result identities, asynchronous full BGR archives and
combined process/evidence cleanup remain in the fresh `evidence` directory;
owned tmpfs inputs are removed on exit. A failed archive drain fails cleanup.
