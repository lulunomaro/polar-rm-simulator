Git index audit of the authorized work/plan-t01-t03 checkpoint.

The frozen quality checks passed; only two documentation clarifications and Git TSV byte-preservation attributes changed afterward. All checked executable/config/model files still match the quality SHA map. The two docs have exact before/after records in the production archive. The new TSV attribute prevents CRLF normalization of the frozen index; no evidence bytes were rewritten.

stage_checkpoint.py records the payload index before its own report is added. The final artifact audit verifies every staged file, including this report.
