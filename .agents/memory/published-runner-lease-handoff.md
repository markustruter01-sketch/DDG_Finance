---
name: Published runner lease handoff
description: Operational constraint when a published deployment replaces a runner process that uses database-backed ownership leases.
---

The published runner must have an explicit lease handoff during deployment. A replacement process can be alive while all strategy threads fail closed because old rows still hold the published leases and their heartbeat age has not crossed the stale threshold. Lock diagnostics must label `incoming_pid` separately from `holder_pid`: the PID printed from a lock row is the recorded holder, not necessarily the runner process. Legacy rows can point at a live sibling artifact PID such as the API.

**Why:** A published replacement can reuse the same process identity while the database still contains the previous published owner, so process liveness and strategy-cycle liveness diverge. Generic `os.kill(pid, 0)` checks can mistake a sibling process for the lease owner, while unlabeled PID logs can send diagnosis down the wrong path.

**How to apply:** After publishing, verify fresh `runner_account_locks` heartbeats and successful `bot_cycle_health` updates, not merely the runner health port or API availability. Keep PID checks for non-legacy owners; handle stale `legacy:` rows with an explicitly scoped published-only migration rule. Never clear leases blindly while a live runner may still own them.