---
name: Fleet equity snapshot table
description: Per-bot mark-to-market history is kept separate from the legacy aggregate equity curve table.
---

The legacy `equity_snapshots` table is an aggregate time series used by existing charts and reports, so per-bot 24-hour baselines use a separate fleet-specific snapshot table rather than changing its schema or semantics.

**Why:** Existing consumers depend on the aggregate columns and one-row-per-fleet snapshot shape; mixing one-row-per-bot records into it would corrupt those consumers.

**How to apply:** Use the fleet-specific table for nearest-24h per-bot baselines and leave legacy aggregate snapshot reads/writes unchanged.