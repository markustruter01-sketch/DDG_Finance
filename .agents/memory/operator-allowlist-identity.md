---
name: Operator allowlist identity
description: The operator authorization boundary uses verified Clerk user IDs because the current Clerk session verifier exposes only the subject claim.
---

The operator allowlist is keyed by exact Clerk user IDs, not email addresses. The current Clerk verification adapter returns the verified `sub` identity and intentionally does not resolve or persist a user's email. The allowlist therefore remains fail-closed until the operator's Clerk user ID is configured.

**Why:** Email is not present in the verified session fields available to the current adapter, while a Clerk user ID is the durable identity needed to bind both Clerk sessions and passkey credentials.

**How to apply:** Configure `TRADING_API_OPERATOR_ALLOWLIST` as a comma-separated list of approved Clerk user IDs. Keep the internal scheduler secret check ahead of the operator check so server-to-server liveness remains independent of browser operator access.