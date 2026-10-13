# Public source provenance

This is a selected, source-only extraction of lulunomaro/llm-RM-navigation commit 7663ae744d69b27813abaefeaa9ae3e73be46a9f, subtree simulation/mujoco_match. The original repository and Git history remain unchanged. This repository does not claim to contain that full history or every historical evidence file.

EXTRACTION_MANIFEST.json records each unchanged file's original path, Git blob SHA-1, SHA-256, size and mode. The function-only reference fixture is explicitly listed as derived, with original-file identity and function hash; runtime algorithm sources are unchanged. New standalone documentation, license, ignore rules and verification tools are repository packaging additions.

The exact rule_decide body is tested against the attributed source-text fixture. HTTP/LLM code and unrelated ROS reference files are omitted. No LLM, ROS, Nav2, CAN, serial or hardware integration is run by the extraction checks.

The scene is a provisional shared-world MuJoCo 3v3 simulation and documented 2026 RMUL referee subset. Analytic geometry and source-dimensioned armor do not establish physical calibration or full official rules compliance. The separately recovered historical detector weight and unchanged interface references have pinned provenance in `models/MODEL_PROVENANCE.json`; they are not part of the initial subtree extraction. The recovered native source and portable build entry are now under `operator_native/runtime/`: `RECOVERY_MANIFEST.json` records all 94 unchanged source files and the distinct `079a7fe + T2 tracker` algorithm identity; `PORTABLE_SUPPLEMENT_MANIFEST.json` records portable setup additions. This is a separate source addition, not a rerun or replacement of historical full-match evidence. External libraries, compiled native output and other missing model/vehicle assets remain external inputs with separate provenance and licensing requirements. See THIRD_PARTY_NOTICES.md and PUBLICATION_SCOPE.md.

A later clean native build and bounded software smoke validation are recorded in `docs/NATIVE_BUILD_VALIDATION.json`, including exact source, script, dependency, generated adapter, model and new binary hashes. The report distinguishes its build-script snapshot from the final reviewed status-order-only update and explicitly excludes historical binary equivalence, complete simulator validation and cross-machine deployment claims. No compiled artifact is distributed.

## Subsequent plan implementation

The extraction manifest and prior validation reports remain historical baselines.
`DEVELOPMENT_CHANGES.json` separately attributes intentional changes to extracted
files, binding the original manifest SHA-256 and current reviewed bytes to task
IDs. `verify_standalone.py` reports unchanged files and these amendments separately;
it does not relabel modified sources as unchanged. Git records packaging changes
and newly authored modules outside that extraction.

`.gitattributes` preserves LF source bytes when cloning on Windows. The recovered
94-file native source remains unchanged. The portable CMake layer supplies
`<algorithm>` explicitly to `shoot_evaluator.cpp` for GCC 15, instead of relying
on a transitive standard-header include. Previous supplement hashes describe the
historical packaging snapshot; each new build binds its current CMake and entry
hashes in its own BUILD_MANIFEST. Build logs, local dependency archives and runtime
specs remain under ignored artifacts; no native binary, private calibration or
credential is added. Development reports include consumer-local build paths and
require a separate release-specific package review.
