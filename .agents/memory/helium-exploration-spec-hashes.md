---
name: Helium exploration spec hashes
description: How to distinguish the frozen strategy-spec hash from Helium's row-level exploration hash.
---

Helium recalculates `exploration_runs.spec_hash` with a `BEFORE INSERT` trigger, so the column can differ across runs from the frozen strategy-spec SHA-256. Keep the canonical global hash in `parameters.spec_hash` and use that field when verifying the experiment specification.

**Why:** The trigger derives a row-level hash for each result, which is not the same contract as the frozen specification hash shared by a batch.

**How to apply:** Before interpreting exploration-run metadata, compare `parameters.spec_hash` with the printed frozen hash; disclose the trigger when the `spec_hash` column appears inconsistent.