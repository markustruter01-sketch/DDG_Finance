---
name: Degradation lifecycle policy
description: Conditions required before automatic resolution of high-severity monitoring events.
---

Automatic resolution requires explicit live recovery evidence for the event type; elapsed time or a successful process start is never sufficient. A database-paused bot is intentionally not stale, and that state must suppress both stale reporting and stale resolution pressure.

**Why:** Historical failure rows are useful audit evidence, but treating them as permanently active obscures current health; conversely, resolving on age alone can hide an ongoing incident.

**How to apply:** Require current canonical database state plus the relevant broker-backed invariant, reconciliation, cycle, or portfolio heartbeat. Leave the row open when any required read is missing or ambiguous, and store the evidence reason with `resolved_at`.