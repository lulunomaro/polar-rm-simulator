# First actual Windows / WSL live run: failed before native result

The first bounded 10-second run used the actual Windows NVIDIA GeForce RTX 5070
Ti Laptop GPU camera, six vehicles at 2 ms timestep, original 1440x1080 optics,
15 total FPS / one view, real time factor target 1, real operator SDK/admission
and server-issued 150 ms input windows. Startup created the renderer and loaded
the original identified ELF/model, with zero captured frames, inference ticks
or physics steps. Native process readiness was proven by its owned Linux
`read(0)` state. No synthetic inference warmed the model.

The run failed live qualification. Physics achieved RTF 0.997893 over 10.0211
seconds and 5,000 steps. There were 147 raw encodes, 146 raw publications and 145
display publications. All measured exposure-to-raw-encode ages were below 80
ms: P50 25.951, P95 28.891, P99 42.185, maximum 51.816 ms. The frame sent toward
native inference matched the actual rendered RGB hash.

Only one native request was attempted, with no native result or active actuator
receipt. The first request's raw encode → adapter enqueue took 22.012 ms;
adapter enqueue → native request callback took 67.063 ms. Thus capture → native
request had already reached 117.061 ms, before the WSL host transport recorded
its request. A `TimeoutError` fault made the original binding fail closed. This
is a real preparation/validation/serialization bottleneck, not a valid pose or
live control result. Zero fire was recorded and no stale actuator was consumed.

The native result's absent stage samples remain empty; they are not assigned
zero latency. The original core's source budget at this attempt used a 200 ms
wall deadline while its native simulation deadline was 80 ms; this mismatch is
recorded in the ledger and requires the core to use the declared 80 ms wall
budget. No gate is relaxed by this diagnostic.

All execution source hashes were unchanged during the run. The runtime aggregate
cleanup was clean, the worker ended, and native child PID 697 was terminated and
reaped with return code -15; the bridge recorded successful Linux child reaping.
Its startup, host timeline and cleanup are preserved in the raw artifact.

The original harness attempted SDK release after the runtime's natural 10-second
stop and recorded `ClientError:runtime_stopped`. This evidence remains untouched.
A subsequent harness fix recognizes only that exact remote code after actual
runtime/control stop as an expected terminal event, explicitly recording that
no remote session-close acknowledgement occurred. Other SDK errors still fail.
The revised harness has not been retroactively substituted into this result.

The checked ELF SHA was
`4d3570674a7a150da0e86f64bbbd25adcfa8bb9e2731672ac6aeaa296cf92b42`,
with spec SHA
`a808f11e8f8088ba89c2cf2a8e94d4bf18c386dc69d3d4114b9b2b40e57a3cdd`.
The original model and frozen contour-v3 frontend were used. Reviewed client
patch SHA was
`91e3653df439289e25d64eb334f9c6f6a73e0c4aa8e3615ce968010e3b1860ee`.

`ATTEMPT1_RESULT.json`, `ATTEMPT1_EXECUTED_SOURCE.json`, the plan and startup
admission retain complete measurements and identities. The evidence manifest
binds the raw files in `artifacts/wsl-native-live-20261013-attempt1`, including
frame hashes, SDK acknowledgements, native process readiness and cleanup. This
attempt establishes neither live native control, full-match behavior, aim
accuracy, GUI operation nor hardware deployment qualification. The successful
prior OFFLINE24 qualification remains a separate bounded result.
