---
name: Production paginated export
description: Production tables can grow while paginated reads are in progress; use a read-only snapshot and verify counts before and after.
---

For large production exports, count drift can occur between pages because the source table may receive new rows during the read. Use one read-only transaction with bounded, small fetches, write only the local archive, and compare the archive count with both the initial snapshot count and a final production count.

**Why:** An offset-based export began with 8,051 rows but encountered 8,052 by its final page, proving that a single initial count is not sufficient for exact backup verification.

**How to apply:** Prefer a transaction-consistent `SELECT ... ORDER BY id` with `fetchmany()` pagination, then re-query the production count after the local file is written. Never use production DDL or DML for backup work.