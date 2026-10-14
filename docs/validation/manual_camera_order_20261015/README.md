# Original manual Qt control and camera ordering

Parent development commit: `83c595bee600ab45daa7e75926af0d2edaa10dd6`.
User plan SHA256: `299b58e785778ae143ff86808f333d2c6ff4e470a00d4dd9138ee1c7380a21fd`.

The fifth independent full-base client patch keeps valid asynchronous camera frames from neutralizing a newly armed operator while the original HUD stream catches up. It checks all metadata, original TTL and actual JPEG decoding first, then rechecks identity/generation/session/episode/sequence/time under the final lock. A legal frame more than the original 50 ms ahead of the current original state is not installed and returns False. It updates no video time, frame sequence, HUD, clock anchor or expiry. Original state catch-up may subsequently admit the same still-valid original packet, without relabeling its ID or timestamps. Corrupt JPEG/calibration/scope, reversed time and genuine expiry still fail closed. Decode-time watch/episode changes cannot install an old frame.

Original camera alignment50ms, displayTTL, algorithm image80ms, SDK150ms, reset2s, graph1s/nav50ms and cleanup budgets remain unchanged. This is an operator display ordering fix, not a timely raw image pipeline qualification for team aiming. There is no truth input, retimestamping, artificial focus/HUD/camera, controller substitution or automatic rearm. The older four client checkouts, patches/manifests and all earlier evidence remain exact bytes; the new patch is complete from fixed BASE `0cedf99b70b1beec99865b9980af6789e6c53d99`, not an incremental overlay.

## Failures retained

Two actual manual runs with the fourth client failed after GO. Attempt01 recorded camera-loop ValueError without its original detailed message, so its root cause cannot be proven from that record alone. It consumed13 batches/379 physical steps, then revoked before the first W hold reached1s; no S movement was completed. Its RESULT conflated child nonzero exit with Job cleanup, but raw CLEANUP separately records a reaped empty Job. That original result is not rewritten.

Attempt02 added only an exception-observing original install_frame hook that records bounded original metadata/state before rethrowing unchanged. Its original message is `Camera time is ahead of state`: frame21/episode0/capture4.0639999999997745, state/sample4.00999999999978, frame age30.5035ms, watch1. The difference is54ms, exceeding the old50ms alignment check by4ms. Seven batches/116 physical steps had been consumed; the run still failed. It also recorded a parent qt_wait TimeoutExpired despite subsequent reaped empty owned Job. Cleanup facts are preserved separately and do not turn this failure into a pass.

The first audit-focused test run had one fixture aliasing failure because a receipt target mutation also changed the request object. The fixed fixture deep-copies targets; no audit guard was loosened. Final13 audit tests pass, including identity/expiry/owner/value/adapter-mixing corruption negatives. Initial client before01/focused01 attempts also had an erroneous test fixture writing HUD4.010 after4.011. They are preserved as fixture failures, not product reproductions. The corrected before02 test genuinely exercises the old ahead-frame exception; the final candidate uses the same original packet to test dropping without anchor updates and accepting after state catch-up.

## Client and actual execution evidence

The fifth client passes12 new tests/16 subtests and the complete30-module actual Qt offscreen suite496 tests/363 subtests/zero skips. Pytest21.83s, owned driver22.2994786s, exit0/source unchanged, Job empty/reaped and reader joined. Complete export inspect, reverse-apply and every covered byte of all four previous versions are verified by EXPORT_PROOF.json. The early peer AST check qualified schedule and bounded stdout only; its captured source predates the later transparent exception observer and is not relabelled as the final peer or an actual Qt run.

New actual runs use the original PlatformWindow under internal offscreen QPA, original Jello Manual choices, watch, real HTTP MuJoCo 1440x1080 images and preclaim QPainter screenshot, first F2 claim/fresh own HUD/second F2 arm, normal W and S key events and two actual QMouseEvents. The first W/S keys each stay held for at least1 actual host second. Original timers/input bridge/runtime produce full manual motion/gimbal/fire batches; the harness does not call extra control ticks, renewals or windows. A separate pure auditor joins original window/lease/seq/value/expiry ACKs to actual integration-entry actuator receipts. World state is isolated evaluation only.

| Actual attempt | GO seconds | Original SDK batches consumed | Physical consume steps | Positive / negative x steps | Nonzero gimbal steps | Internal / driver seconds |
| --- | --- | --- | --- | --- | --- | --- |
| 03 | 5 | 86 / 86 | 2511 | 1491 / 538 | 2511 | 11.4622931 / 13.4840867 |
| 04 | 30 | 479 / 479 | 15028 | 7977 / 6502 | 15028 | 36.7661493 / 38.8301222 |

Both pass all original-camera/input/guard/SDK receipt/root checks, exit0/source unchanged and no forced direct child termination, followed by actual F12/release/close and all owned Job/SDK/HTTP/camera cleanup. Attempt04 performs11 matched key press/release pairs, actual mouse delta14/8 pixels,477 changed gimbal ACKs and1502 guard polls; diagnostic dropped count0, Qt cleanup .0446569s under original1.5s. Host and Qt explicitly set/read back CV4 and CPython switch1ms and restore original settings. No machine affinity/priority/timer/power change or deadline extension is used.

These are real offscreen manual SIL runs, without a team navigation/decision/aim process, ROS/NN, visible desktop, firing/hit test, LAN, RTF/performance matrix or full3v3/7v7 acceptance. New ordinary manual launch config passes its dry plan only; it is not a new visible launcher run. The earlier two short synthetic navigation/decision protocol passes keep their previous qualification in the control_batch package.

## Quality and remaining work

Quality09 uses the same explicit CPU4 WSL spec without fallback; all four check steps and all captured program/test/provenance bytes must pass unchanged before preservation. Exact counts, six existing warnings, exclusions, step exit codes and times are in its literal logs and IMPLEMENTATION_PROGRESS.md. Documentation/archive sealing after QA does not rewrite executed program bytes.

The PB route note is a read-only implementation/config identity audit, not a new build/ROS or algorithm run. Previous real Point-LIO/Nav2/PID30s single-goal execution used actual ray/IMU200000points/s and remains historical. Its existing goal wrapper has no generic decision_intent_v1 goal/hold/cancel or complete estimated localization feedback. Generic decisionv1 still marks navigation/perception unavailable. Never use latest TF, simulator truth, fake hold/status or relabelled source scans to fill feedback. The next actual joint scenario is a manual infantry alongside real PB navigation, then versioned source-associated estimated/referee feedback and traditional match decisions.

T2 explicit static live retains its three historical passes, while moving/multicar/automatic fire remain open. PB aim still lacks an image within original80ms, Tongji lacks a live image chain, full match behavior/composition/LAN/clean-machine/Windows native and M0-M5 remain unaccepted. No training, hardware, main merge or public release occurred.

## Integrity

PRESERVATION_MANIFEST.json binds original and stored/decompressed byte hashes. FILES.json binds exact package coverage except itself; verify_archives.py checks integrity only, never executes tests or algorithms. Credentials/private SDK events, model binaries/ELFs and unrelated artifacts are excluded. Failure, candidate, final, actual source snapshots and original cleanup proofs are separate immutable records.
