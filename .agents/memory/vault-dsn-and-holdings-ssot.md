---
name: Vault DSN and holdings source of truth
description: Runtime vault ownership and reporting must use the shared DATABASE_URL and durable holdings rows.
---

The live platform's vault ownership lookup and vault quantity reporting must resolve only `DATABASE_URL`; BIL/VOO quantities come from `per_bot_vault_holdings`, not denormalized account quantity columns.

**Why:** A split database left the platform unable to see broker-held vault ETFs, and the account quantity columns were zero even after the durable holdings were present.

**How to apply:** Keep alternate database URLs out of runtime readers, fail closed when `DATABASE_URL` is absent, and aggregate holdings rows for safety classification and dashboard counts/reports.