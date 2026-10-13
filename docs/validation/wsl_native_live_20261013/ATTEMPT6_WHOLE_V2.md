# Sixth actual live attempt: full exact payload, deadline before native tick

The sixth actual run kept explicit v2, Windows NVIDIA rendering, six vehicles,
2 ms timestep, 1440x1080, 15 total FPS / one view, real-time-factor target 1,
80 ms wall/simulation capture budgets, 150 ms SDK server window and actual image
artifact writes. Source/model, pixels, own-state/calibration and timestamps were
unchanged. Preload admitted the original model without captures or inference.
The new writer issued the entire bounded immutable image from its dedicated
thread, and the original per-tick mode file was preserved in the owned tmpfs
working directory. The recovered 94 source files were not changed.

The live control result remained failed: one native adapter/bridge request,
zero native responses and zero active actuator receipts. This attempt did,
however, transmit all 4,665,600 actual BGR bytes to Linux and pass its pixel SHA
validation. `SUPERVISOR_ERROR.json` retains actual local stages: receive 9.653 ms,
SHA-256 2.057 ms and tmpfs write 2.642 ms, together 14.352 ms. Only 12.557 ms of
the original budget remained at host submission. The worker explicitly rejected
the completed receive/hash/write phase before writing the request to the
original ELF's stdin. Thus neural inference on this live frame is still absent;
the independently observed byte transfer is not a live model/control pass.

Physics achieved RTF 0.994435 with 4,995 steps over 10.0459 seconds. All 148 raw
encodes stayed under 80 ms: P50 25.301, P95 28.379, P99 31.408, maximum 35.381 ms.
For the attempted native frame, raw encode → enqueue took 5.377 ms and enqueue
→ native callback 31.932 ms. Actual slot queue wait was only 0.363 ms; processing
inside the worker before the callback took 31.569 ms. Its image preparation
accounted for 22.348 ms, including artifact write 11.414, BGR hash 4.037, color
conversion 3.835, immutable snapshot 1.054 and RGB trace hash 2.008 ms. Host bridge
preparation remained short at 2.328 ms. These host durations use QPC; Linux
durations above stay in their separate local clock domain.

Five scheduling samples expired and were rejected. A timeout faulted the native
binding; no stale actuator was consumed. Fire count was zero. Actual SDK
admission/window acknowledgement, exact sensor pixel binding, both 80 ms budgets,
source stability and clean shutdown checks passed. Native child PID 701 was
terminated/reaped with return code -15 and its private tmpfs directory removed.
There were no report errors. Original raw ledger, frame bindings, SDK events,
startup and runtime observations remain intact in
`artifacts/wsl-native-live-20261013-attempt6-pipe-v2-whole`.

Complete copied reports and the supervisor error use `ATTEMPT6_WHOLE_V2_`
prefixes here; the evidence manifest binds every retained original file. All
previous failures and the separate Linux diagnostic remain unchanged. The idle
harmless throughput benchmark and saved-image inference measurements are not
used to fill missing live stage samples. This attempt does not qualify live
native control, full match, GUI, hardware or aim quality. Further repair must
remove measured preparation/recording cost while actually preserving the image
artifact, source/model and all deadline/cancellation rules.
