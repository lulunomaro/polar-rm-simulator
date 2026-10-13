# Saved-frame PnP rejection, 2026-10-13

The native program builds and executes. The original 24-exposure static integration case still fails tracking/control qualification. Preserve `ORIGINAL_OFFLINE_RESULT.json`; this diagnostic is not a replacement pass.

## What failed

The unchanged detector returned one blue infantry-3 plate, confidence 0.884. Its two IPPE pose candidates had positive depth and front-facing normals, but their pitches were −36.0146° and +59.0600°. Both violate the original +15° ±40° gate. The original estimator and original RobustPnP solver both returned zero poses.

The network's lightbar endpoint lengths are 37.13 and 36.68 pixels. Offline projection of the source 135×56 mm endpoint geometry yields 54.51 pixels; the actual 55 mm diffuser projects to 53.54 pixels and agrees with the saved rendered blue pixels. Even the narrower 50.3 mm luminous core projects to 49.02 pixels. The plate's physical pitch is 0°, inside the existing gate.

No configuration drift, corner-order swap, incorrect resize ratio, clipping, padding overlap, or gross camera projection error was found. The measured failure in this one saved synthetic frame is keypoint localization. Training annotation/preprocessing provenance is unavailable, so a more specific training-domain explanation remains unproven. No small code, threshold, brightness or bar-stretch change is justified by this case. Further optical/model adaptation requires separate validation.

## Evidence and boundaries

- `DIAGNOSTIC_REPORT.json`: binding hashes, measured gates and conclusions
- `result.txt`: original separate diagnostic executable output
- `saved_frame.bgr.gz`: exact unmodified saved image, gzip-compressed
- `saved_frame_metadata.json`: camera calibration and captured own state only
- `GEOMETRY_AUDIT.json`: offline projection audit; never algorithm input
- `render_bar_measurements.json`: read-only pixel measurements
- `CONFIG_COMPARISON.json`: current and historical detector/PnP/tracker config comparison
- `inspect_saved_frame.cpp`: diagnostic harness, linking the unchanged native source objects

The harness runs the unchanged detector once, calls the unchanged estimator/PnP APIs, and separately logs the original gate math. It does not change production source, production executable, thresholds or the original result. The geometry audit uses a public static scene and capture-time own pose, with no physics integration, rendering or truth injection.

The source gate/projection math derives from the bundled MIT-licensed RMCS code; its notice is preserved in `UPSTREAM_LICENSE`. Native sources of interest are `candidate/src/utility/math/solve_pnp/pnp_solution.cpp`, `candidate/src/kernel/pose_estimator.cpp`, and `candidate/src/module/detector/armor_detection.cpp` under the portable runtime directory. Fixture sources are `rm_match/armor_visual_v2.py`, `armor_visual_v22.py`, `platform_v2/camera.py`, and `camera_profile.py`.

## Optional bounded replay

First complete the documented portable native build using `CMAKE_GENERATOR=Ninja` and the exact documented dependencies. Keep the same runtime library environment that successfully starts that binary. The replay helper builds a separate diagnostic from the local objects left by that build and never edits the production build:

    python reproduce_saved_frame.py --build-root /your/native-build --out /your/fresh-diagnostic

To execute exactly one saved-frame inference as well, add `--run`. The image checksum, T2 identity, completed build manifest, production ELF, source/header seal, generated inputs, runtime configs and model bytes are checked. Individual object hashes were not bound by the original build manifest: their local provenance remains unverified. The helper records every current object hash and checks that those bytes remain unchanged during replay; it does not prove the objects correspond to the production ELF. Treat replay as a separately bound local diagnostic, not historical equivalence. Logs and a new replay binding are written only to the fresh output directory. This helper's CLI and construction were reviewed; the original one-frame diagnostic was executed successfully, but the newly packaged helper was not used for an additional inference. No additional benchmark is claimed.

For the independent geometry audit, use a Python environment with the repository's pinned MuJoCo, NumPy and OpenCV dependencies:

    python audit_geometry.py --repo-root /your/simulator-checkout --out /your/new-geometry-audit.json

This loads the saved public scene and captured own pose, performs one forward-kinematics calculation, and projects geometry mathematically. It does not render, advance physics, call the detector, or feed truth into the native program. The target pose is the saved initial static scene; unrecorded target chassis drift is not reconstructed. The packaged geometry entry point was parameterized from the executed audit and syntax-checked without rerunning it.
