# Fourth actual live attempt: v2 binary transfer timed out partway through

This actual 10-second run explicitly selected `wsl_stdio_bgr_v2`; the default v1
was unchanged. Its immutable instance plan and actual Linux startup transport
matched. Windows NVIDIA rendered the real camera pixels, with six vehicles,
2 ms timestep, 1440x1080, 15 total FPS / one view and real-time-factor target 1.
The actual SDK/admission and 150 ms server-window activation were acknowledged.
Original model, contour-v3 source, K/D, own-state fields, exposure/control times
and 80 ms wall/simulation budgets remained unchanged. No startup capture or
synthetic warmup inference occurred.

The run failed live qualification: there was one native adapter request, no
native result and no active actuator receipt. It achieved RTF 0.991554, 4,996
physics steps and 148 raw encodes. All measured exposure-to-raw-encode ages were
below 80 ms: P50 25.556, P95 27.869, P99 30.307, maximum 33.132 ms. Source hashes
were unchanged, every fire action was false and cleanup was clean.

For the first eligible native frame, raw encode → adapter enqueue took 6.566 ms,
enqueue → native request callback 20.453 ms. Actual image conversion/file/hash
preparation took 10.698 ms. The host bridge's preparation took a further
11.605 ms: path check 6.677, BGR file read 2.909, SHA-256 1.897 ms. It recorded its
first real binary transaction at 63.880 ms after exposure, leaving only
16.125 ms of the original budget. These are host-clock measurements.

`SUPERVISOR_ERROR.json` proves the subsequent failure happened during payload
reception: Linux received 1,835,008 of 4,665,600 bytes before its allowed local
timeout expired. Its completed Linux receive/hash/tmpfs-write stage dictionary
is empty. Thus the complete live image did not reach the original neural
pipeline. This failure must not be assigned to neural inference. Nor may the
separate idle harmless-pipe test's approximately 8.47 ms receive time be used as
the missing actual live transfer latency.

Five scheduling samples expired under the original camera deadline and were
rejected. The incomplete binary transaction caused a timeout fault; no stale
output was consumed. Native child PID 699 was terminated and reaped with return
code -15; the owned 0700 tmpfs directory was removed. Runtime aggregate shutdown
was clean with no unfinished slots or lifecycle errors, and report errors were
empty. The expected terminal SDK runtime-stop was recorded separately.

The complete copied result, runtime observation, source/startup bindings,
instance plan and supervisor partial-payload error have the `ATTEMPT4_PIPE_V2_`
prefix here. The evidence manifest binds every original raw file in
`artifacts/wsl-native-live-20261013-attempt4-pipe-v2`. Earlier failures and the
separate Linux filesystem/compute diagnostic remain preserved.

The next transport repair may reuse trusted immutable actual BGR bytes to avoid
redundant host file/path reads and may reduce Linux polling overhead. It must
still verify the same pixel SHA across the boundary, preserve finite deadlines
and cancellation, retain original source/model and run a fresh actual test.
This attempt does not qualify live native control, full match, GUI, hardware or
aim quality. Windows rendering plus WSL-native execution is explicitly distinct
from Windows-native execution.
