---
name: Published and dev runner collision
description: The published VM starts the trading runner alongside APIs, so a dev runner can create duplicate execution.
---

The published VM starts the trading runner, trading API, and API server; the dashboard is served statically. The published runner is authoritative: it claims one PostgreSQL lease per canonical bot and refreshes those leases every cycle. Dev is explicitly read-only and does not claim leases or write cycle/liveness records.

**Why:** A dev workflow restart can look harmless while a published runner is already active, creating a duplicate-execution risk on shared broker accounts. A process-local health check cannot prevent a second process from trading or detect a dead runner from the API process.

**How to apply:** Keep the published runner in `live` mode and Dev in `read_only` mode. A fresh lease refuses another environment; a lease older than three cycle intervals may be taken over. The published trading API independently probes the runner health port and alerts after consecutive failures.

Standing-invariant results must be labeled with their database source. The dashboard Dev workflow can report stale ledger/broker mismatches from `DATABASE_URL` while a production run against `NEON_DATABASE_URL` is clean; a Dev log is not production evidence.

**Why:** A recent audit showed the same broker activity represented consistently in production but as three mismatches in the Dev process, because the two database snapshots had different ledger/reconciliation state.

**How to apply:** For production incidents, run the invariant with its production DSN override and read the production reconciliation log directly; include the DSN scope and capture time in the report before interpreting any mismatch.