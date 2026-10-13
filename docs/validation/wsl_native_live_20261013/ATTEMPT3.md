# Third actual live attempt and independent Linux-local diagnosis

Attempt 3 remained a live failure. The actual NVIDIA Windows renderer produced
148 raw encodes, all within 80 ms: P50 25.774, P95 28.317, P99 30.985, maximum
34.478 ms. Physics ran 4,995 steps with RTF 0.992233 over 10.0682 seconds. The
actual SDK admission and 150 ms server-window activation were acknowledged.
The native wall and simulation sensor budgets were both actually 80 ms, source
hashes were unchanged and cleanup was clean. No fire action occurred.

Compared with attempt 1, raw encode → adapter enqueue improved from 22.012 to
7.525 ms and adapter enqueue → native request callback from 67.063 to 23.221 ms.
The measured image conversion/file/hash preparation took 13.013 ms in this
actual sample; individual stage durations are retained in the result.

There was one native adapter request and no native result or active actuator
receipt. The host WSL transport trace contains only startup-ready and close,
without a bridge `native_request` event. Therefore the original neural model
did not receive that live image through the bridge. A host preparation timeout
faulted the binding. This does not establish that neural compute caused this
live failure. Three scheduling samples expired under the original camera
deadline and were rejected. The terminal SDK runtime-stopped response was
explicitly recorded as expected after actual runtime stop, rather than masking
an active-session transport error.

Raw ledger, frame hashes, SDK events and runtime observations were written before
derived statistics in this attempt. The complete report and source/startup
bindings are copied with `ATTEMPT3_` prefixes; the raw artifact is
`artifacts/wsl-native-live-20261013-attempt3`. The manifest preserves all original
files. No empty native stage is assigned an artificial zero latency.

A separate Linux-local diagnostic used the exact actual BGR file and recorded
own capture state from attempt 3. Capture time stayed 422 ms and control time
448 ms throughout. It sent the original packet fifteen times in one original
ELF process, followed by three independent fresh ELF first requests. Every
process first reached its genuine `read(0)` readiness without capture or neural
inference. It used a diagnostic 2-second response timeout, separate from the
unchanged live 80 ms gate, and ran no GL or physics.

There were four actual first-inference responses; their combined native
file-read/detector/PnP/tracker/control latency had P50 84.873, P95 100.222 and
maximum 102.780 ms. All produced one valid native pose and tracking. The other
fourteen identical-exposure requests were rejected by original exposure
deduplication and did not infer again; their P50 2.998 ms is explicitly a
non-inference result, not a model throughput measurement.

Independent reads of the same 4.6656 MB BGR file across Windows-mounted DrvFs
took P50 58.456, P95 81.141 and maximum 84.578 ms. SHA-256 took P50 2.030 ms and
packet JSON encoding 0.075 ms. These unpaired filesystem measurements must not
be subtracted from response latencies to claim an exact neural-only time. They
show that the shared filesystem data path can consume most or all of the live
budget before camera and host work are considered. A transport repair must
deliver the same real sensor bytes more efficiently; it may not relax deadlines,
substitute pixels or update exposure timestamps.

The first Linux diagnostic omitted the required `tracking_mode` file and all
four processes exited before model readiness. That failure remains at
`artifacts/linux-native-saved-compute-20261013`. The corrected diagnostic writes
the original spec's exact LF `multi_ekf` mode in each process directory; its
results and child reaping proofs are at
`artifacts/linux-native-saved-compute-fixed-20261013` and copied here as
`LINUX_SAVED_COMPUTE_RESULT.json` with a complete manifest. Four processes exited
and were reaped; their `/proc` entries were absent and pipes closed. The optional
own hp/ammo/heat fields were not archived by the live trace and were omitted
from reconstruction; the original native Runner does not read them.

This Linux experiment is an offline saved-image compute/filesystem diagnostic.
It does not supplement the failed live pose/control results or qualify live,
full-match, hardware or GUI behavior. The previously successful OFFLINE24
static native control chain remains a distinct qualification.
