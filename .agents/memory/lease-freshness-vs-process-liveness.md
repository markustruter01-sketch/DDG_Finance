---
name: Lease freshness versus process liveness
description: Why runner process heartbeats and account-lease heartbeats must be evaluated as separate safety signals.
---

Account lease freshness is not equivalent to runner-process liveness. A process can continue writing a five-second heartbeat while a bot lease is refreshed only at the next strategy-cycle boundary, leaving failover blocked for much longer than process health suggests.

**Why:** The production audit showed healthy runner probes and a current process heartbeat alongside leases roughly 19 minutes old. Long cycle intervals make this gap materially affect recovery time and make the two signals easy to misread.

**How to apply:** Refresh leases on an independently bounded cadence, or expose the intentional maximum lease age and alert when it is exceeded. Keep process heartbeat, bot-cycle freshness, and lease freshness as separate health dimensions.