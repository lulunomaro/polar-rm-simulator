# Second attempt: actual execution followed by a report failure

Attempt 2 admitted the actual NVIDIA renderer and owned native ELF/model with
zero inference/capture/physics at startup. The transport timeline records one
native request, no response, and a cancelled/reaped native child. The subsequent
report calculation failed because `image_stages` contains string metadata
(`converter`, `clock_domain`) alongside numeric duration fields. The reporting
helper incorrectly passed those strings to a percentile calculation.

The outer error handler wrote `SETUP_FAILED`, an inaccurate phase label after
startup was already admitted. That original `RESULT.json` is preserved exactly.
`RESULT_RECOVERED.json` supplements it with the startup, native host timeline,
actual child cleanup and original result hash. It explicitly leaves physics RTF,
raw frame count and actuator count unknown: the in-memory ledger was not saved
before the failed report, and the Python process had exited. No missing runtime
measurement is invented, and this attempt is not qualified as a live pass.

The tool was repaired to summarize only numeric duration fields ending `_s`,
while retaining complete metadata in the raw ledger. A regression uses the
actual mixed metadata/duration shape. The tool now writes frame bindings, SDK
events, raw ledger and runtime/cleanup observations before derived statistics.
Future exceptional reports save the original Python traceback and distinguish
failure after startup admission from failure during setup.

The originals are in `artifacts/wsl-native-live-20261013-attempt2`; copied result,
partial recovery and source/startup bindings are prefixed `ATTEMPT2_` here. The
evidence manifest binds the original result and all retained native evidence.
The first attempt remains separately preserved. Further live measurements must
use a fresh output directory and unchanged 80 ms / 150 ms safety gates.
