# Atomic control batch and two actual original-window protocol passes

Parent development commit: `3e6094ce9c2775e7651c6e82ecc549e51a746a54`.
The opt-in batch endpoint reduces actual HTTP round trips within the existing operator window. It preserves all original leases, typed window/binding/sequence identities, bounded manual gimbal/fire inputs, admission and deadlines. Every member validates before one atomic commit; any invalid member rejects the batch without partial sequence/input/activation writes. Existing expiry and motion mode conflict may only remove authority. No new window, lease renewal, target truth or algorithm fire permission is created.

The synchronous SDK sends once, checks complete typed outer and member ACKs, rejects duplicate JSON fields and derives each local expiry from original window request start plus the same-window expiry-issued delta. A late or uncertain response is never replayed. The fourth independent Qt client patch enables batch only after explicit integer version1 negotiation. Missing capability retains the unchanged single-request formula/path; malformed capability fails closed. The original post-ACK fresh sample, watch/own HUD/two F2/focus/input and all real revocation guards remain active. Handoff measures real batch RTT session maxima with original window RTT/sample20ms/wake5ms/margin5ms/maintenance costs; it does not lower old single costs or reset observed peaks.

## Independent evidence levels

- Backend: 36 focused tests passed, including actual bounded loopback HTTP, complete atomic rejection, type/NaN/limit/scope failures, real lock-wait expiry, final fresh-clock expiry, original lease/window caps, same-window activation bounds and motion conflict fail-closed behavior. Synthetic clocks/authority only, no physics/GL/ROS/NN.
- SDK: 53 tests passed including original client/window regressions and actual HTTP with a synthetic backend. New complete-batch typed ACKs, missing/extra/duplicate/wrong identities, short-TTL ACK transit expiry, no replay, capability fallback and all-binding/manual controls are covered. Driver3.4094219s, exit0, source unchanged, owned Job reaped/empty and reader joined.
- Client: focused second run21 passed/38subtests;17-module full run351 passed/141subtests;final29-module installed Qt offscreen suite484 passed/347subtests/zero skips, pytest21.72s/driver22.2378568s, exit0/source unchanged/owned tree and reader clean. These use backend fixtures and do not independently qualify physical consumption or a visible desktop. Both earlier suite runs and source snapshots are preserved. The fourth full-BASE patch and manifest inspect/reverse-apply and every source-covered byte of all three older versions are verified unchanged.
- Before actual execution, review found the new evidence hook incorrectly rejecting legal first sequence0. A new12-check stdlib fixture uses the real fourth SDK response through the AST-extracted current hook; legal0 is accepted while negative/bool/float sequences and nonpositive epochs/windows are rejected. Before/after peer bytes and diagnostics remain exact. This was a pre-execution code correction, not a fabricated failed Qt run.

## Actual original PlatformWindow camera/SDK/MuJoCo runs

Both use actual original window/runtime under internal offscreen QPA, real HTTP MuJoCo image pixels/preclaim original QPainter view, watch/Jello selection, first F2 claim, fresh own HUD, second F2 arm and original bound pipeline, Qt focus/exposed/input guards and ordinary timer samples. Two independent stdlib JSONL peers are synthetic decision/navigation fixtures. Physics uses original2ms steps and actual ray/IMU1000points/s. World truth is confined to independent evaluation, never peer input.

| Fresh attempt | Batch ACKs | Independent original policy actions | Nonzero physical consume steps | Receipts | Internal / driver seconds |
| --- | --- | --- | --- | --- | --- |
| batch01 | 53 | 21 | 543 | 1621 | 10.6882914 / 13.5278223 |
| batch02 | 49 | 21 | 601 | 1798 | 10.1062680 / 12.1504109 |

Each completes the original3-second GO measurement and then actual F12, release and close ACKs, with source unchanged, exit0/reaped/no forced termination. All20 root checks pass: actual camera, both original F2/guard stages, real batch and both manual gimbal/fire ACKs, nonzero physical motion, exact original typed6/SDK150ms receipt join without errors, no adapter fault, and every owned process/SDK/HTTP/camera worker clean under original budgets. Second runtime join .0412382s. Host and Qt explicitly set/read back CV4 and CPython switch1ms, then restore CV32/switch5ms. No CPU affinity, system timer, priority, power, original clock or deadline change is made.

This qualifies two short offscreen low-rate synthetic protocol SIL runs only. It is not a visible desktop, longer session, performance matrix/RTF, full MID360/SLAM/goal arrival, team navigation/decision/aim, raw aim80ms, auto-fire or full-match acceptance. The prior three failed original-window attempts and their cleanup deficiencies remain byte-exact in the previous [state/Qt package](../robotio_state_qt_20261015/README.md). These new passes do not rewrite or hide them.

## Final quality and remaining scope

Quality08 retains the exact original CPU4 WSL build spec, with no fallback. All program/test/provenance bytes are captured before/after and unchanged; precise counts, six existing warnings, skips, step exits and timings are in the quality log and IMPLEMENTATION_PROGRESS.md. Package sealing/post-QA prose is integrity work, not part of prior execution testing.

T2 explicit static live and PB actual single-goal navigation retain their historical boundaries. PB aim still lacks a timely original80ms ROS image chain; Tongji lacks live image evidence; decision v1 estimated pose/perception feedback stays unavailable. Long/visible client sessions, moving/multicar/automatic fire, team algorithm composition, LAN, full3v3/7v7, clean-machine release and M0-M5 remain open. No training, new team algorithm, real hardware, main merge or public release was run here.

## Integrity

PRESERVATION_MANIFEST.json records original byte hashes and literal/gzip hashes, FILES.json binds exact package coverage except itself. `python verify_archives.py` checks decompression/hash/coverage only and does not execute tests or algorithms. Models/ELFs, real credentials/private SDK events and unrelated artifacts are excluded. Every prior published package and the older client versions remain immutable.
