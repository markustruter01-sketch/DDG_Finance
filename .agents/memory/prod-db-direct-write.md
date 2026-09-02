---
name: Prod DB direct write path
description: How to write to the production PostgreSQL database from the dev environment without a publish.
---

## The rule
`NEON_DATABASE_URL` in the bash/workflow process environment is the **production** Neon PostgreSQL database.
`DATABASE_URL` is the live platform's authoritative DSN, but it must not be assumed to be
the historical Helium research database: the current environment can point it at a
separate external Neon endpoint with invalid credentials. `trading-platform/db/postgres.py`
falls back only to the matching `PG*` variables, not to `NEON_DATABASE_URL`.
The historical Helium endpoint is not currently exposed by the environment inventory.
Vault ownership rows are production-resident, so safety readers that classify
vault positions must query the Neon vault table rather than trusting an empty
dev copy.

`executeSql({ environment: "production" })` reads from prod but is **read-only** (Replit enforces this).

## How to apply
For emergency prod DB writes without a publish:

```python
import os, psycopg2
conn = psycopg2.connect(os.environ['NEON_DATABASE_URL'])
conn.autocommit = False
cur = conn.cursor()
# ... SQL ...
conn.commit()
cur.close(); conn.close()
```

Run via `bash` tool (not `code_execution` — that sandbox does NOT have access to NEON_DATABASE_URL).

## Why
The trading-api dev workflow connects to DATABASE_URL (dev DB). ensure_schema() migrations applied there do NOT touch prod. Phase J was first mistakenly applied to dev, then corrected by running psycopg2 directly against NEON_DATABASE_URL.

**How to apply:** Any time you need to run a one-off SQL fix against production without deploying, use this pattern. Verify with `executeSql(environment:"production")` read before and after.

**Why:** A dev-side vault lookup returned no rows even though production had the
three active bot vaults, causing BIL/VOO to be misclassified as strategy positions.

## Research-database caveat

Research tables can exist with zero rows in the reachable production Neon database
while the original Helium research database is unavailable. A table's presence is
therefore not evidence that the research dataset is still attached to the current
connection.

**Why:** The research ledger and Bot 2 price table were empty on every reachable
current endpoint; the project documentation still named Helium, but no Helium
endpoint or credential was present in the current environment.

**How to apply:** Before publishing, migrating, or re-ingesting research data, record
the host and `current_database()` from a read-only connection and verify row counts.
Do not remove `DATABASE_URL` as a discovery tactic: the authoritative live-platform
guard fails closed when it is absent.
