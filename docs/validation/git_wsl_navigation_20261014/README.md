# Literal Git-index verification

`BEFORE_ATTRIBUTE_REPAIR.json` is an actual precommit comparison of five raw ASCII `.bin` receipts and their initial staged blobs. Git's text-auto conversion changed CRLF bytes, and the literal index guard rejected the checkpoint before commit. No original evidence file was modified.

The repair adds `docs/validation/**/*.bin binary` and explicitly restages the twelve new `.bin` receipts with `git add --renormalize`. `PAYLOAD_INDEX_AUDIT.json` records the successful comparison of all **404 then-staged source/evidence files**, including the attribute repair, against their exact working bytes. `git diff --cached --check` also passed. This report predates the addition of this four-file audit package; it does not claim to hash itself or this README.

`stage_checkpoint.py` is the exact staging/audit recipe snapshot originally executed from repository `artifacts/`. It checks archive inventories and compares `git cat-file --batch` blobs byte-for-byte. Its relative root assumes that original location; it is a provenance snapshot, not a directly runnable script from this archive directory. The final staging is checked again after adding these records. This is Git-byte preservation evidence, separate from pytest, ROS, physics or milestone qualification.

The successful quality report was completed before these Git attributes and documentation records were added; executable simulator/bridge/algorithm source remains unchanged from that checked version.
