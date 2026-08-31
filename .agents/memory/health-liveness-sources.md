---
name: Health liveness sources
description: How architecture health distinguishes bot liveness from fleet snapshot activity.
---

Architecture health must evaluate both the bot portfolio heartbeat and the durable cycle success timestamp for every canonical active bot. A fleet equity snapshot proves only that the snapshot writer ran; it does not prove that bot cycles or portfolio writers are alive.

**Why:** The snapshot scheduler can continue inserting rows after bot cycles stop, which previously made the health architecture appear nominal despite stale bot state.

**How to apply:** Keep stale thresholds centralized with canonical liveness constants, treat unresolved high/critical degradation events as degraded, and map required database/read failures to unknown rather than green.