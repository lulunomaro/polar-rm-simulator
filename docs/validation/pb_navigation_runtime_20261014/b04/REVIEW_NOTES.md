Owned Point-LIO ingress repair, candidate 04
==========================================

Upstream remains Point-LIO 641424bf9d924f5ba0bd87ca9d91a4f148384925 and PB2025
cb97fb07ace54fcc617ddb884227ef85fe4b8f85. Original candidates 02/03, their source
manifests and compiled 02 binaries remain intact.

The two DDS readers now join by the original CustomMsg header/timebase and
request acquisition_start_ns. Each table contains at most eight entries. Arrival
order can differ on the two topics, and reversed request order is checked against
the actual sequence/frame/start relation. Original immutable context follows the
same scan into MeasureGroup. Replay watermarks advance at exact-pair consumption.
No latest request is attached to an older scan.

A later original acquisition_start_ns can retire unmatched requests only when it
strictly exceeds their original acquisition_end_ns. An unmatched raw scan uses
the maximum actual point offset as its last-point stamp, never a synthesized
window or a new wall deadline. Existing exact requests take precedence over that
raw-only retirement rule: a request window ending at 100 ms still permits its
98 ms last point when the next request starts at 100 ms. Complete pairs are
retained. Retirement emits bounded scalar counts and original discarded stamps;
full tables with valid pairs explicitly reject extra input. Changed generation
clears both pending tables and permanently fails the node.

This repair never changes sensor stamps, filter thresholds, algorithms, the
control deadline, or the host/Linux clock boundary. Expiration enables delivery
of subsequent exact pairs; it does not make an old result admissible. SDK and
controller identity/deadline checks remain responsible for accepting actions.

The subscriber request queue increases from one to eight. IMU reader depth 1024
and internal hard limit 4096 are unchanged. Fifty-one inclusive 2 ms samples
bracket each 100 ms window; suppressing a repeated boundary leaves fifty fresh
samples in the following window. The actual retained scan end can be 98 ms.
Dropped complete input windows must not be repaired with artificial IMU samples.

Tests: pb2025-lio-tf-window-retire-focused-20261014.log records 11 passed,
75 subtests passed, zero skipped, including standalone actual C++ fixtures.
They cover both reader orders, two requests before raw in either order, exact
original byte pointer/identity/deadline retention, missing-side retirement and
resumption, full stale-table admission, duplicate/conflicting/replayed input,
capacity limits, and irreversible generation failure. These tests are not a
ROS navigation or physical-control qualification.

Actual build uses a fresh Linux workspace and only builds point_lio. There is
no copied CMakeCache or object cache. Unchanged loam_interface and
sensor_scan_generation assets are reused only after canonical source hashes,
the original compiled source copies, and four actual ELF hashes all match.
REUSED_TF_SOURCE_PROOF.json records the proof. BUILD_COMMAND/RESULT and
BINARY_AUDIT record actual compilation and dependency checks; no nodes are
started by the build script.
