---
name: Published runner lease handoff
description: Operational constraint when a published deployment replaces a runner process that uses database-backed ownership leases.
---

The published runner must have an explicit lease handoff during deployment. A replacement process can be alive while all strategy threads fail closed because old rows still hold the published leases and their heartbeat age has not crossed the stale threshold.

**Why:** A published replacement can reuse the same process identity while the database still contains the previous published owner, so process liveness and strategy-cycle liveness diverge.

**How to apply:** After publishing, verify fresh `runner_account_locks` heartbeats and successful `bot_cycle_health` updates, not merely the runner health port or API availability. Never clear leases blindly while a live runner may still own them.