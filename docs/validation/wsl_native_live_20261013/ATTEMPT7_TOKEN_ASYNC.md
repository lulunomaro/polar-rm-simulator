# Seventh actual live attempt: preserved evidence, unresolved control deadline

The seventh unique 10-second run used the new sealed camera observation token
and bounded asynchronous evidence writer with explicit `wsl_stdio_bgr_v2`.
The configuration remained six vehicles, 2 ms timestep, Windows NVIDIA rendering,
1440x1080, 15 total FPS / one view, RTF target 1, 80 ms capture wall/simulation
budgets, 150 ms SDK authority window, and no manual fire. The original model,
recovered 94 files, contour-v3 source, own-state/calibration and original capture
timestamps stayed fixed. Startup loaded the real ELF/model with zero camera
captures, inference requests or physics steps.

The strict result is FAIL. Physics completed 4,226 steps, simulation time 8.452 s,
over 10.060246 s of real wall time: RTF 0.840138. All 149 raw encodes remained
within 80 ms (P50 30.008, P95 33.503, P99 35.050, max 37.940 ms). There was one
native request, zero native responses, one sticky adapter timeout fault, one
incomplete request and zero active native actuator receipts. Earlier inactive
adapter hold responses are not native inference results. No fire occurred.
Both original 80 ms sensor budgets, SDK admission/window acknowledgement,
pixel identity, source stability and resource cleanup checks passed. These
checks do not compensate for failed physics/control criteria.

For the attempted sensor frame 10, raw encode to adapter enqueue took 7.196 ms,
and enqueue to the native callback took 15.734 ms. Image preparation took
12.424 ms: color conversion 5.786, immutable snapshot 0.996, BGR SHA 2.308,
RGB trace SHA 3.322 ms. Its former synchronous image-file write was replaced by
asynchronous receipt acceptance (the helper's file-write duration was 0.011 ms).
Host bridge preparation took 2.402 ms, leaving 24.302 ms of the original
capture deadline when the exact BGR transaction was submitted.

Linux received all 4,665,600 real BGR bytes and verified the same SHA. Its local
diagnostic stages were receive 12.052 ms, SHA 2.092 ms and tmpfs write 2.602 ms,
total 16.745 ms. The supervisor then recorded `control_timeout`, rather than
attempt 6's explicit receive/hash/write expiry. No native response or
`detector_executed` evidence was returned; the current trace does not count
actual writes to ELF stdin. Therefore this report does not claim completed
neural inference. Linux local durations are not subtracted from host QPC
timestamps, and saved-image or harmless transport benchmarks do not fill
missing live results.

The new evidence actor accepted one image and actually wrote one image plus
its manifest. `native_evidence_closed.status` reports clean true, submitted 1,
written 1, failed 0, pending 0 and worker_alive false. The retained
`actual_frames/sensor_10.bgr` is exactly 4,665,600 bytes, with independently
rechecked SHA `5d661eef2f1a90a0a12bb33662d35406c357f694d2a097efd613fe18cf784aed`,
matching its manifest and the submitted transport image. Runtime aggregate
shutdown took 0.058954 s within the original 1.5 s budget. Native PID 694 was
terminated and reaped with return code -15; the private tmpfs directory was
removed. No report errors were recorded.

One historical metadata inconsistency is preserved: `RESULT.native_identity`
still contains the checked host-spec's `wsl_stdio_v1` label and v1 transport
source list. The instance PLAN, executed Python source snapshot, actual
STARTUP/HOST_TRACE and command all identify v2; the classifier's transport
check uses actual startup evidence. The old label is not silently corrected
in the recorded run. An owner repair is needed for future identity metadata.

All original artifacts remain in
`artifacts/wsl-native-live-20261013-attempt7-token-async-evidence`; copied reports
here use the `ATTEMPT7_TOKEN_ASYNC_` prefix. The evidence manifest binds all
original files, including the actual BGR image. The RTF regression needs
separate runtime profiling, and the unresolved native deadline needs further
bounded repair. This attempt qualifies neither live control nor full match,
GUI, hardware or aim accuracy. Earlier failures and original evidence remain
unchanged.
