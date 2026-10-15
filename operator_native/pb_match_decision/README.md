# PB match decision scoped runner

This MIT-licensed project code executes the real BehaviorTree.CPP 4.6.2 runtime
and the byte-identical PB `IsGameStatus`, `IsStatusOK`, `IsRfidDetected` and
`PubNav2Goal::setMessage` implementations. It does not implement the tree again
in Python. The PB implementation/fork headers retain their Apache-2.0 notices;
the preparation tool copies the original PB full license. BehaviorTree.CPP
retains its MIT notices/license in its separately pinned build. Generated
protocol messages retain the license of their original interface package.
These components do not become MIT merely by linking to this runner.

The fresh owned XML overlay disables unsupported 7 rad/s spin, turns the
original zero Twist into a synchronous high-level hold sink, and replaces the
two field constants with local waypoints anchored to the first actual supplied
map estimate. The original PB conditions and fallback structure remain. This
is an explicit local scenario, not calibration of the competition field.
Removing those stateful zero-duration publishers also removes their original
RUNNING intermediate tick: every incoming observation gets exactly one real
`tickExactlyOnce`, not a cached goal with a new identity.

`ScopedPubNavGoal::setMessage` calls the original PB method before capturing a
per-tick PoseStamped. Missing estimate prevents a call with a manufactured pose.
Missing RFID remains an absent blackboard key; the real RFID condition fails,
and the supply output is withheld with `rfid_unavailable` rather than fabricated
NOT_DETECTED. Only hp/ammo/time floor and heat ceil map legal own/referee values
into consumed integer message fields. Other referee fields and all perception
remain unavailable. Healthy behavior keeps emitting the original tree's goal;
there is no extra synthetic completion policy.

The native binary speaks the existing `polar.sim.adapter.jsonl.v1` protocol:
prepare/reset ACKs contain the complete decision-v2 capabilities, and act takes
one complete decision-observation.v2 and returns one intent.v1 with the same
typed six identity values. It never compares the opaque Windows deadline to a
Linux clock and never obtains velocity, gimbal or fire authority. Factory/tree
initialization and reset perform zero ticks; only act ticks. Duplicate JSON
keys, including nested duplicates, are errors. There is no automatic tree-client
retry or async latest-topic output association.

Launch only through the source/ELF/XML/ENV-verified Python peer and the existing
owned WSL supervisor. Native CLI is exactly `--spec PATH --sha256 SHA256`. The
peer uniquely creates its output directory; native exclusively creates
`READY.json`, `native_ticks.jsonl`, and `CLEANUP.json`. READY follows actual
native self/XML SHA verification and factory/tree initialization. The tick
ledger preserves original observation, source, intent, actual tick monitors,
setMessage events, anchor provenance and integer mappings. stdout is duplicated
for JSONL, with normal C++/BT/ROS output redirected to stderr. Cleanup halts and
destroys the tree, destroys its node, shuts down context, and flushes/closes its
ledger before sampling resource cleanup time. The host measures complete owned
exit independently; a cleanup-file write is not a stronger total-I/O guarantee.

Build only (no nodes/ticks) using the fixed Linux environment and actual prefixes:

```text
<verified Python3.10> tools/prepare_pb_match_decision.py --out <fresh ext4 build>
  --btcpp-prefix <fixed BT4 install> --interface-prefix <fixed protocol install>
  --environment <fixed ENV.json> --build
```

The helper records owned command exits/cleanup, copied and original input SHA,
the actual BT4 library SHA, executable/XML SHA and loader evidence. Copy
BUILD_RESULT and SOURCE_IDENTITY into fresh shared artifacts for host audit;
keep the original executable, library and XML at their ext4 paths. With the
copied BUILD_RESULT, `--spec-from-build BUILD_RESULT --environment ENV --out
<fresh shared artifacts>` creates a pinned local scenario spec and a new derived
ENV including only the verified BT4/message loader prefix delta. Old ENV and
upstream/installed assets are not changed. Actual builds/runs and navigation
acceptance are separate from pure preparation/static tests.

## Fixed sources, licenses and executed checks

The fixed inputs are PB behavior
`d111b635d326775c6c19aa12500a0bbd6a27a588`, the PB ROS2 wrapper fork
`7d177dcfbd7dbb7f5e5cd79c4e5e3e744e389c56`, BT.CPP 4.6.2
`2a8a226fbbd99f524f0796e0d8a3145773c61c06`, and protocol-v1.7.0
`8912fa565a7ac57ef070df218957379123d238ee`.
The XML overlay has exactly five declared edits: two spin publishers disabled,
one zero-Twist publisher replaced with `ScopedHold`, and two goals replaced
with explicit estimated-anchor local waypoints. Neither original C++ condition
logic nor the upstream `setMessage` implementation is rewritten.

| Actual evidence | Result and scope |
| --- | --- |
| BT4 build01 | 43.4268 s; 391 source files unchanged; clean 4.6.2 build, no tree ticks |
| Protocol interfaces01/02 | 01 failed on ROS_DISTRO environment; 02 succeeded in 23.1202 s with 17 source files unchanged; original failure preserved |
| Runner02/03 | 02 failed on missing `plugins.hpp`; 03 succeeded in 45.853 s with owned commands/reaping and loader proof; no navigation acceptance inferred |
| Standalone01 | Five real C++ ticks using explicit synthetic DTOs: healthy goal, hp199.9/missing-RFID hold, paused hold, e-stop hold, unavailable-estimate hold |

Standalone01 is in
[`artifacts/pb-match-native-standalone-20261015-01`](../../artifacts/pb-match-native-standalone-20261015-01/RESULT.json).
It joins each original input/source/intent to actual native tick evidence, not
real referee-triggered branches. Native cleanup records a 2.565 ms SIGTERM
resource shutdown, `protocol_interrupted=true`, and halted/destroyed tree,
node and context; the outer owned cleanup separately proves reaped/empty trees.
Protocol interruption is not relabeled as a completed client exchange.

See [third-party notices](../../THIRD_PARTY_NOTICES.md) for verbatim PB behavior
and PB ROS2 Apache-2.0 texts, BT.CPP MIT and protocol-message MIT. The new owned
runner's MIT notice does not relicense upstream material. Executables and shared
libraries are external build outputs, not published repository payloads.

## Registered-route failures and current limit

The real-BT/navigation registered
[actual02](../../artifacts/pb-match-route-actual-20261015-02/RESULT.json)
failed the original host transaction deadline at the default 0.05 s SDK cadence:
zero public actions or motion. The independent
[actual03](../../artifacts/pb-match-route-actual-20261015-03/RESULT.json)
used explicit 0.02 s fresh SDK authorization, without changing sensor samples
or the original 150 ms authority window. It produced two timely public actions
and 72 nonzero consumed steps, but the next final Linux 50 ms gate expired by
0.739304 ms. Peer/adapter and shared cleanup errors make the whole run FAIL.
Outer reaping and a final empty Job do not erase SDK release/close timeouts or
internal cleanup failures. Original source identities and failures remain.

Source-bound action-to-status withholding and transactional wire-history
repair completed actual04 without adapter faults or shared cleanup failure.
Its 101 real ticks and 95 exact estimates produced no public actions: the
actual Nav2 planner aborted the first goal while its start was outside the
initial costmap. The whole motion run remains FAIL. A real costmap bounds
readiness gate now uses actual global-costmap metadata and the same estimate's
TF start bounds, preserving the lifecycle's deliberate failed-goal stickiness.
Its 106 helper tests do not prove planner feasibility. The repair
preserves original source/intent/selection and never grants zero-velocity or
late-action authority. Protocol details are in
[navigation feedback](../../docs/NAVIGATION_FEEDBACK_PROTOCOL.md).

[Actual05](../../artifacts/pb-match-route-actual-20261015-05/RESULT.json)
returned 148 results for 149 observations/intents: five actions, 143 statuses,
and one shutdown-aborted transaction. Public action/source matching proves
206 nonzero physical steps. Its 137 available estimates are public declarations
only: all navigation-peer journals were missing at exit, so original native
TF/LIO, UUID, terminal-state and final emit evidence cannot be audited. The
decision Linux owned-cleanup proof is also missing. Neither native CLOSE nor
eventual outer Job reaping replaces those proofs; the whole run is FAIL.
The separate raw review failed with FileNotFoundError on missing ROS_SOURCE;
there is no raw audit pass, and no missing original is reconstructed.

The old owned-tree TERM signaled the leader and Nav2 children together,
interrupting cooperative shutdown and evidence persistence. The repair
requests stop on all owned peers before waiting, gives the Linux leader at most
0.8 s cooperative grace, and adds idempotent signals, PRE_CLOSE and evidence
write timing. This uses the same original 1.17 s KILL phase, Linux 1.3 s and
shared host 1.5 s budgets. Actual06 hit the original host deadline on its third
capture, then stopped with complete bounded cleanup; the whole run is FAIL.
Failed attempts02–06 retain their own sources and qualifications.

Final [actual07](../../artifacts/pb-match-route-actual-20261015-07/RESULT.json)
passes all 23 checks: 147 real BT ticks/exchanges, 136 exact native LIO/TF
estimates, 15 returned actions, 132 statuses and 620 nonzero physical steps.
Two actual late action candidates were withheld as same-source statuses and
later captures continued. The original goal succeeded with terminal/stop proof.
All 15 final action gates satisfy the unchanged 50 ms budget; host cleanup is
0.9927301 s under the shared 1.5 s limit, with original Linux 1.3 s unchanged.
This explicitly selects `--python-switch-interval-s .001`, reads it back and
restores the original .005 s. SDK activations remain .02 s and authorization
.15 s. One successful run does not prove a scheduling-only causal improvement.
Independent raw review joins original costmap metadata and the same exact TF
start position; it does not certify occupancy or path validity.
Final QA15 passes all four checks: 3041 passed, 45 explicit skips and 1024
subtests, with 460 program/test/provenance files unchanged. This sentence was
added after QA; no program bytes changed. See the
[permanent integrity package](../../docs/validation/pb_match_decision_20261015/README.md).

The original healthy tree continues to choose its goal after navigation
completion: there is no receipt-based completion guard or synthetic final-hold
policy added here. RFID supply, perception/combat, spin, fire, calibrated match
waypoints, multi-robot play and complete matches remain unqualified. The earlier
synthetic-decision navigation success and QA14 apply only to their old scope.
