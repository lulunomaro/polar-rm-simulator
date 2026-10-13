# Fifth actual live attempt: immutable private bytes improved host preparation

The fifth run used explicit `wsl_stdio_bgr_v2` and the original public static
scene, real Windows NVIDIA camera, six vehicles, 2 ms timestep, 1440x1080,
15 total FPS / one view and real-time-factor target 1. Capture-to-consumption
wall and simulation budgets stayed 80 ms; SDK server-window authority stayed
150 ms. Native model/contour-v3/own-state/calibration and timestamps were unchanged.
Renderer and original native model readiness were established without captures,
inference or physics. The actual source snapshot was unchanged during execution.

The trusted adapter passed immutable actual BGR bytes privately to the pipe,
avoiding redundant host path queries and file reads. No bytes were added to the
public DTO or trace. The actual image artifact was still written, and both
sides retained the pixel SHA checks. Host bridge preparation improved from
11.605 ms in attempt 4 to 2.455 ms here, with hash validation taking 2.297 ms.
Actual image conversion/artifact/hash preparation took 10.618 ms, including
4.325 ms artifact write. The bridge had 26.693 ms of the original budget left.

The actual run still failed live control. Linux received only 3,211,264 of
4,665,600 BGR bytes before its finite original deadline. Its completed local
receive/hash/tmpfs-write stage dictionary remained empty. Therefore no complete
live image reached the original neural pipeline: native results and actuator
receipts were both zero. This is a measured transfer failure, not measured
neural inference latency. The idle harmless transport test is separate evidence
and does not replace the missing live result.

Physics achieved RTF 0.991542 with 4,998 steps over 10.0813 seconds. All 148 raw
encodes stayed below 80 ms: P50 22.645, P95 25.390, P99 27.027, maximum 30.817 ms.
For the attempted native frame, raw encode → enqueue took 9.661 ms and enqueue
→ native request callback 19.175 ms. Four scheduling samples expired and were
rejected; one timeout faulted the native binding. No stale actuator receipt or
fire action was recorded. SDK admission and actual window acknowledgement were
valid; expected terminal runtime-stop was handled explicitly.

Runtime shutdown was clean. Original native child PID 695 was terminated/reaped
with return code -15; its private 0700 tmpfs directory was removed. Reports had
no errors, and raw ledger/frames/SDK/runtime observations were saved before
derived statistics. Original files remain at
`artifacts/wsl-native-live-20261013-attempt5-pipe-v2-private`, with copied
`ATTEMPT5_PRIVATE_V2_` reports and a complete raw-file hash manifest here.

An additional clock inspection found that this Windows interpreter's
`time.monotonic()` uses GetTickCount64 with 15.625 ms resolution, while
`time.perf_counter()` uses QPC. Their observed offset was approximately 35.6 ms.
Consequently the old native trace's `wall_time` cannot be subtracted from QPC
callback times to estimate hashing overhead. All stage joins and budgets in
this live tool used its own `host_received_wall`/QPC timestamps, and Linux clocks
were never subtracted from host clocks. Earlier informal attribution of that
cross-clock difference to hashing was withdrawn; actual image preparation and
bridge timing fields are the valid measurements.

The next repair must increase actual transfer throughput or reduce real
preparation cost while retaining original deadlines, cancellation and exact
pixels. This attempt does not qualify native live control, full match, GUI,
hardware or aim quality, and Windows rendering with WSL-native execution remains
explicitly distinct from Windows-native execution.
