---
name: Discord delivery boundary
description: Discord delivery is published-only, audited, environment-labeled, and routine findings belong in the daily digest.
---

All Discord webhook requests must pass through the shared delivery boundary. Non-published processes never make HTTP requests; they log a critical suppression and persist `skipped_not_published`. Published messages carry an environment label, while routine findings are persisted for the daily digest rather than sent individually.

**Why:** Development and read-only workflows can have production credentials or webhook configuration, so configuration presence alone is not a safe delivery condition.

**How to apply:** Route new Discord callers through the shared sender, keep immediate delivery limited to stop coverage, kill-switch, and runner-heartbeat conditions, and preserve the audit row for every attempted delivery.