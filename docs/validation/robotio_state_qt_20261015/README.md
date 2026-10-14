# Typed identity, transactional registration and client lease ordering

Parent development commit: `f73532898c7b7ede7fe7119f405465b630ce11cf`.
This package preserves the exact source, failed attempts, tests and actual Qt protocol records from the next development checkpoint. It does not qualify any new team algorithm or milestone.

- Canonical action identity: 21 focused tests passed. Type and value must match all six original source fields; equivalent int/float substitutions and bool are rejected with the existing error semantics. Original legal time representations remain valid. Before/after reproduction is preserved.
- Graph registration: 18 focused tests passed, including actual file and in-memory interleavings, late graph/component changes and transactional rollback. The graph cannot describe component A while publishing reread component B. Factories do not execute during registration. The original registry is untouched on failure.
- Client ordering: a third independent combined patch from fixed client base `0cedf99b70b1beec99865b9980af6789e6c53d99` discards complete typed, strictly older lease snapshots after claim ACK. It does not refresh HUD/time anchors or release the new lease. Mixed/missing/bool epochs, current owner mismatch and real later revocation still stop control; claim stays disarmed. Both older patches/manifests/checkouts remain unchanged.
- Final actual Qt offscreen client regression: 330 passed, 103 subtests, zero skips; pytest 11.94 s, driver 12.4185 s, source unchanged and owned process reaped. Backend fixtures are not physical/algorithm qualification. Initial fixture/locale failures and the original deterministic race are preserved. Earlier after02/03 driver runs collected only the eight ordering cases and must not be described as full suite runs; after04 and after05 did run all sixteen modules.

## Actual original PlatformWindow attempts: all failed

These are actual original client window/runtime events under offscreen QPA, actual HTTP MuJoCo camera pixels, Jello selection, original F2/claim/arm/HUD/focus/input/SDK control guards and two independent synthetic JSONL navigation/decision peers. The sensor profile uses actual ray/IMU at 1000 points/s. They contain no ROS/WSL/NN/team algorithm, raw aim80ms, visible desktop, SLAM/goal arrival, RTF or match qualification. World state is confined to independent evaluation.

01: first F2 followed by release; no second F2, no motion. Original reason evidence is insufficient to assign a cause. Outer 15.2321109 s, exit2, source unchanged/reaped. Physical cleanup succeeded, but original result predicates also conflated protocol failure with clean exit. No old result is rewritten. The isolated stale-state reproduction is not proof of this actual attempt's root cause.

02: both F2 events and binding, eight SDK activations, two independent source actions, 81 receipts and 27 nonzero physical steps; identity/SDK150ms join had no errors. Original Handoff budget pressure revoked authority. The old probe then waited after authority loss, and the original Qt Job cleanup proof failed because its shared cleanup deadline had expired. Later SDK release/close ACKs and empty thread references do not repair that Job proof. Outer 15.4175183 s, exit2, source unchanged/reaped. The original full diagnostic ledger lacked earlier RTT maxima, so it does not establish the exact forecast or which request created pressure.

03: third client patch, explicit host and Qt CV4 and CPython switch1ms, actually set/read back/restored. Real frame display, all eight original guards, both F2 and binding; 38 SDK activations, eleven independent source actions, 477 receipts and 159 nonzero physical steps. The original typed6/SDK150ms audit had no errors, but GO+2.424 s the original scheduler forecast157ms exceeded TTL150ms and revoked authority. Recorded max costs: window31ms, pulse32ms, control32ms; the unchanged formula includes sample20ms/wake5ms/margin5ms and two manual controls. The probe now stops immediately on original guard loss; every owned Job, SDK/HTTP/camera worker was clean inside the original budgets. Runtime join .0487345 s. Outer11.7951674 s, exit2, source unchanged/reaped, no forced termination. Cleanup improvement does not turn this failed control run into a pass. PNG is only the actual offscreen preclaim Qt view.

Camera80ms, SDK/control150ms, reset2s and host cleanup1.5s are unchanged. No stale identity retagging, fake focus/HUD/frame, rearm retry, synthetic zero/hold rescue or relaxed forecast is used. The next control work is reducing actual HTTP round trips and then repeating a fresh, separately recorded actual window run.

## Final quality and limits

Final quality07 uses the original explicitly selected CPU4 WSL build spec, without fallback. Its driver captures exact program/test/provenance hashes before and after. Counts, timings, warnings and every step status are preserved in the quality manifest and logs, and reported in IMPLEMENTATION_PROGRESS.md. Earlier quality06 and every prior published package remain immutable. Package sealing and post-QA prose are integrity work, not part of the prior execution check.

Decision v1 estimated navigation/perception feedback is still unavailable. PB actual single-goal navigation and T2 explicit static live qualification remain their historical scopes; PB aim still fails the original80ms chain and Tongji has no live image evidence. Moving/multicar/auto fire, continuous visible client, two-computer LAN, full3v3/7v7, clean-machine release and M0-M5 remain open. No team algorithm or real hardware was run by these probes.

## Integrity

PRESERVATION_MANIFEST.json binds each original byte stream and its literal/gzip stored representation. FILES.json binds every package file except itself. Run `python verify_archives.py` to check decoded bytes, hashes and exact package coverage; it does not execute tests or algorithms. Raw credentials, private SDK events, model/ELF binaries and unrelated artifacts are excluded.
