# Actual contour-v3 static native control chain

The complete, separately identified contour-v3 native build passed the actual
OFFLINE24 fixed-scene camera → detector → PnP → original multi-EKF tracker →
fire controller → gimbal actuator chain. The original model, confidence and PnP
gates were unchanged. This supplements the independently rendered positive and
negative holdout evidence in `../pnp_contour_v3_20261013`; that frozen holdout
summary records the earlier stage when the complete chain was still pending.

`artifacts/pnp-native-contour-v3-offline24-attempt4-20261013` completed with 24
actual rendered captures, 13 native request/result pairs, 471 physics steps and
241 active gimbal steps. All 13 results contained one accepted 3D pose, tracking
and `should_control=true`; target age was 0.02 simulation seconds throughout.
Every active step wrote the exact native-derived yaw/pitch to the actuator
control and changed the actual gimbal joints. The first active pitch target was
-0.1358036694 rad; the corresponding joint moved from -0.0230053063 to
-0.0236671033 rad in that integration step.

The original fire controller reported `should_shoot=true` on 7 of 13 responses.
The adapter supplied `fire_permission=false` throughout, and the actual physics
trace contains zero fire actions. These are distinct measurements.

The actual pinned Qt client admitted a fresh rendered display frame, remained
healthy, closed its session with acknowledgement and exited without network
lifecycle errors. The native, camera, worker and server shutdown checks passed.
There were no result errors. Two JPEG display publications were dropped; all 24
raw sensor exposures were published and consumed. Renderer initialization took
5.329 seconds and the bounded execution took 18.077 wall seconds.

Native sensor packets are built from actual rendered RGB converted to contiguous
BGR, original K/D calibration, exposure time and capture-time own state. Target
truth and generated geometric corners are absent from the packet construction.
Each request/result pair has matching image hash, capture frame, schedule and
own-state bindings. This combines source inspection with actual execution logs;
the complete native packet bytes were not independently archived for every
frame. Sensor calibration/resolution association remains the existing source
assumption, with no physical-camera calibration claim.

The client used reviewed patch
`91e3653df439289e25d64eb334f9c6f6a73e0c4aa8e3615ce968010e3b1860ee`
at fixed commit `0cedf99b70b1beec99865b9980af6789e6c53d99`. The runtime validated
native spec `28d051057118c62e36fd6c7fb7adc924819168335a01e164fcea440fcaebad8b`,
ELF `4d3570674a7a150da0e86f64bbbd25adcfa8bb9e2731672ac6aeaa296cf92b42`,
original model `b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255`
and the sealed base plus contour-v3 composite source identity. The unchanged
overlay SHA is `0a90e0089a2531a476091d75c3085a6d26a843feba7c0f5cd429ea2928aa812c`.
`CHAIN_REPORT.json` retains identities, actual counts, first/last active physics
samples, admission checks and raw evidence hashes. `NATIVE_RESULTS.json` retains
all 13 complete native result records.

Attempts 2 and 3 remain preserved: attempt 2 exhausted the original binding
window while Qt was importing; attempt 3 exposed the client's strict metadata
schema mismatch. The repaired startup handshake actually creates QApplication
and loads cv2/numpy before local readiness. It does not replace session/watch or
lease acknowledgements. Setup took 5.203 seconds within its separate 15-second
bound; no capture, inference or physics occurred before readiness. The original
parent 5-second and client 3.5-second admission windows remain unchanged.

This qualifies the bounded static offline chain. It does not qualify realtime,
full-match behavior, visible desktop interaction, aim quality, hardware or
cross-machine deployment. The far-3.85 m original-model detection miss in the
independent suite remains unresolved. Simulator source hashes in this report
were taken immediately after execution, not independently before execution;
the later native cancellation/resource cleanup revision is not qualified by
this run and requires a separate actual check after its source is frozen.
The recorded acceptance criteria retained a historical baseline failure note;
the execution result establishes success. The note was subsequently clarified
in the runner for future runs, without modifying this execution evidence.

Reproduce with the same registered native spec and frozen client in WSL/Linux:

```sh
.venv-linux/bin/python tools/smoke_offline_deployment.py \
  --native-spec artifacts/native-contour-v3-build/operator_source.local.json \
  --client-root external/polar-rm-client-state-review \
  --client-python /absolute/project/.venv-linux/bin/python \
  --out artifacts/fresh-static-chain --run
```

Use a new output directory. Readiness and sensor admission are validated against
the actual child PID, nonce, fresh directory and original network deadlines.
