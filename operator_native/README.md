# Independent operator FOV adapter delta

This directory contains only a narrow delta and build/spec entry scripts. It does
not include the old complete headless runner, algorithm source, weights, binaries,
objects, private paths, logs or rendered images. No frozen source file is edited.

Supply the existing qualified `headless_rebuild` tree as `EXTERNAL_BASE`.
`prepare_fov_hook.py` verifies the original main.cpp and clock-header hashes and
generates local build files. It is idempotent. The human-readable patch documents
the same change: actual 2D detector centers are filtered before source PnP and
tracking, by a centered image ellipse intersected with the calibrated angular
cone. FOV changes require a fresh process; output counters reveal admission.
The native identity is `rmcs-sim-operator-fov-v1`. The detector, PnP, tracker and
fire-control translation units are unchanged; this is not the frozen match runner.

    python prepare_fov_hook.py --base EXTERNAL_BASE
    python build_native.py --base EXTERNAL_BASE --full
    python prepare_operator_spec.py --base-spec ORIGINAL_SOURCE_SPEC --binary build/rmcs_sim_operator_fov --out operator_source.local.json

`--full` recompiles all candidate translation units into this directory's build
folder, using the external qualified compiler commands. It verifies the external
source tree against that build manifest, runs syntax checks before compilation,
and hashes inputs/output. Without `--full`, unchanged qualified objects are reused
and hashed; that shortcut is not a clean rebuild claim. The generated binary uses
explicit local library paths and is not a portable distributed executable.

The original spec's source-config and detector hashes are checked when preparing
the new spec. Only the newly built binary's exact hash is admitted by the Python
operator adapter. Keep generated files local; they are not part of this source
increment. If an external dependency or identity is missing, stop and report it;
do not substitute a detector, simulator truth or zero-policy output.
