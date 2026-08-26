---
name: Published and dev runner collision
description: The published VM starts the trading runner alongside APIs, so a dev runner can create duplicate execution.
---

The published VM currently starts the trading runner, trading API, and API server; the dashboard is served statically. The dev runner uses the same runner code and account credentials, and no cross-environment singleton lock was found.

**Why:** A dev workflow restart can look harmless while a published runner is already active, creating a duplicate-execution risk on shared broker accounts.

**How to apply:** Treat the dev runner and published runner as mutually exclusive until an independent ownership/monitoring mechanism exists. A health check inside either process cannot detect a complete outage of that process or its host.