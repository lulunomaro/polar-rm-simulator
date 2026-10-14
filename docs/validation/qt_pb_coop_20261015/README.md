# Real manual infantry and PB navigation coexistence

Parent development commit: `82029a6aec74a303253fb9417d63a6d669e54cc1`.
User plan SHA256: `299b58e785778ae143ff86808f333d2c6ff4e470a00d4dd9138ee1c7380a21fd`.

The original fifth client patch is unchanged. A separate opt-in joint probe gives original Qt infantry keyboard/mouse control and actual sourced PB Point-LIO/SLAM/Nav2/PID navigation separate operator credentials, robot scopes, leases, windows and outputs. Both share the same Windows MuJoCo physics with actual infantry HTTP camera and sentry ray/IMU200000points/s. The runtime core, nav algorithm, model/build/config, original input timestamps and all80ms/150ms/reset2s/graph1s/nav50ms gates remain unchanged. Only the existing PB descriptor explicitly opts into the generic post-reset capture discard policy already implemented by runtime.

## Evidence levels

Read-only preflight actually checks11 ELF assets and22 referenced configuration/provenance/environment identities, source HEAD, ext4 runtime/Python3.10.12 and package XML versions. No ROS/GL/algorithm was started for that check. rclpy package XML was absent at the searched share path and its version entry is null; that is not evidence of a missing runtime module. The following real runs separately execute ROS and navigation. Preflight literal stdout.bin is JSON data, not an ELF/model; no binary asset is published.

The new cleanup helper invokes only exact reviewed owner classes, signals all selected owners before parallel original close calls and holds one caller host1.5s deadline. Each original owner retains its Linux1.3s internal budget and birth-bound cleanup verification. It inspects actual host returncode, closed pipes/stderr, owner IO/close threads, stored failure and original Linux run/spec/boot/PID/group proof. Late, nonzero/uncertain, partial receipt or foreign-owner outcomes stay unclean; no force-kill, timeout extension or later upgrade. Actual joint runs pass only the external owner into this helper while runtime lifecycle exclusively closes navigation; no competing nav close or monkeypatch. Helper focused11 tests/14subtests use explicit mock owners/receipts and real host Threads, not WSL cleanup qualification. Raw stdout/JUnit are preserved; this focused record does not contain an owned process-reap driver proof, and none is fabricated.

Post-reset regressions use real Registry/WslNavigationAdapter/AdapterSlot with an explicit session stub and controlled134ms reset. A saved old descriptor without policy leaves16ms and produces the original-deadline TimeoutError; new policy discards first and queued old scans, then passes only the unchanged new six identities/frame/capture/deadline. Relabelled frame/sim/host-capture and reset failure remain rejected/sticky. Final focused17 pass (new7 plus original reset/registry regressions). Initial5pass/1fail was a test hook synchronization error: a previously blocked queue.get consumed the next job before the newly installed observation hook. Corrected Event ordering and the intermediate16-pass run are preserved. No product error is inferred from that fixture failure. The complete initial failing test-source snapshot and an owned focused-run process driver proof were not captured; raw stdout/JUnit and the final test source are retained without fabricating either missing record.

## Actual joint runs

WSL configuration preparation runs with physics0/sensor0 and no algorithm-data warmup. The independent ROS observer never publishes sensors, cmd_vel or lifecycle changes; its navigation target is one metre relative to the real algorithm-estimated map-to-base TF, with original stamp. The source-conditioned PID output is checked against actual cloud acquisition, LIO localization and controller source events and original host SDK window ACKs. World truth is confined to isolated evaluation, not either control input.

Original Qt watch/Jello Manual/preclaim QPainter camera, first F2 claim/fresh own HUD/second F2 arm, ordinary W/S key events and two actual QMouseEvents generate manual inputs through the original timer/input bridge/runtime. Navigation authority is activated only after the original manual arm stage; there are no substituted Qt guards, camera/HUD/focus data, manufactured actions, automatic rearm, extra client control ticks or retagged timestamps. The same host GO-to-F12 interval and original2ms step numbers prove simultaneous nonzero physical consumption, rather than joining separate single-robot runs. A separate manual ACK/receipt audit preserves exact window/lease/seq/value/expiry. Linux-local clocks are never subtracted from Windows host clocks.

| Attempt | GO seconds | Manual batches / consumed | Manual consume steps | PB nonzero steps | Same-step nonzero overlap | PB requests / localization / controller results | Relative goal | Internal / driver seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 01, old descriptor | 5 | 82 / 82 | 1573 | 426 | 314 | 32 / 30 / 25 | completed | 24.5963907 / 26.7151630 |
| 02, old descriptor | requested30, failed after .802 | 15 / 15 | 282 | 0 | 0 | 1 / 0 / 0 | none | 16.8635494 / 18.9804055 |
| 03, discard policy | 30 | 486 / 486 | 9904 | 476 | 410 | 198 / 196 / 28 | completed | 48.9283522 / 51.1370498 |

01 and03 pass all25 root checks and both independent consumption audits, source unchanged, exit0/reaped/no forced direct termination. 03 completes30.0193222s original GO-F12,11 paired press/releases, initial W/S≥1s,1502 guard polls, diagnostic dropped0, actual F12/release/close. Qt cleanup .0454841s; original runtime adapter join .5303054s; external owner helper .4157285s; entire caller cleanup is inside its original1.5s deadline. Original Linux groups are empty/reaped with original birth identity and all HTTP/SDK/camera/IO/owned Job resources clean. Explicit host and Qt CV4/CPython1ms are read back and restored, with no system affinity/priority/timer/power changes.

The30s pass includes legitimate no-action state after the single target completes; it does not assert both robots move continuously for30s. It has no match decision tree, aiming/NN/auto-fire, visible desktop, measured performance matrix/RTF, LAN or full3v3/7v7 acceptance. The other four robots do not get substitute policy inputs. The fifth client and every older delivered archive/patch/checkouts remain immutable.

## Actual failure and correction

02 first reset host phase takes about134.8ms from exchange enter to the returned validated ACK, consuming most of the first original sampling window. The first act still receives that setup-era scan, whose remaining original deadline is insufficient for the unchanged50ms navigation response wait. The timely refusal faults navigation and the independent observer exits incomplete; no source response is relabelled or stale output consumed. The Qt input loop consequently releases before W reaches1s and never performs S. Original failure/error/phase/source/cleanup records remain intact.

The observer's protocol exit2 is retained as unclean by strict host owner verification even though its original Linux group cleanup proves empty/reaped without kill. The runtime/navigation cleanup separately succeeds and the shared elapsed budget is met. Do not rewrite these distinctions into an overall successful or fully clean protocol run. New descriptor policy discards successful-reset first/queued scans, waits for original new frame/sim/host capture, and keeps the same adapter instance. Reset failure still faults, and no deadline, sensor result, hold or zero action is fabricated. 03 is a fresh run, not a rewrite of02.

## Quality and remaining work

Final Quality10 passes all four steps:2178 tests/40 explicit skips/1024 subtests/6 existing warnings, pytest137.19s/driver167.9643966s exit0/reaped. It uses the unchanged explicit CPU4 WSL build spec; all program/test/provenance bytes are captured before/after unchanged and all four steps must pass before preservation. Exact pass/skip/subtest/warning counts and timing are in literal logs and IMPLEMENTATION_PROGRESS.md. Post-QA prose/package sealing is integrity work, not an execution test.

This completes one bounded two-robot navigation/manual scenario. PB's legacy single-goal wrapper still lacks the generic decision_intent_v1 goal/hold/cancel contract and versioned estimated localization/referee feedback. Traditional match behavior tree, moving/multicar actual aim, automatic fire, remaining four robots and full matches remain open. T2 static live, PB aim image expiry and Tongji prepare-only evidence retain their own scopes. M0-M5 are not signed off; no training, hardware, main merge or public release is performed.

## Integrity

PRESERVATION_MANIFEST.json binds original and stored/decompressed literal byte hashes. FILES.json binds exact coverage except itself; verify_archives.py verifies hash/decompression/coverage only. All three distinct source snapshots, failure and regression fixtures, real images, time/consumption and process proofs are separate records. Credentials, private SDK events, models/ELFs and unrelated artifacts are excluded.
