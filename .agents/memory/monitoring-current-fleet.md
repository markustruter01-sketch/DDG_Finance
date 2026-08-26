---
name: Current fleet monitoring
description: Rules for DEV monitoring after the equity-only fleet consolidation.
---

Monitoring must read the canonical state, portfolio, cycle-health, trades, fleet-equity-snapshot, and degradation tables. It must not recreate a parallel snapshot table or infer HEALTHY from empty metrics.

**Why:** Retired exchange identities and shared legacy state files produced false crypto findings and hid missing monitoring data.

**How to apply:** Evaluate paused bots as PAUSED before metrics; active bots with missing or empty critical data are UNKNOWN or FAIL. Attach canonical bot_id and cycle_id to runner cycle failures.