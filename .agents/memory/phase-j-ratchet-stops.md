---
name: Phase J ratchet_stops cleanup
description: Jun-26 post-autopsy DB fix — stale rows removed, stop_order_ids linked. ratchet_stops now fully consistent with broker.
---

## What was done (2026-06-26)
Applied directly to production Neon DB via psycopg2 (NEON_DATABASE_URL):

**Part A — linked live GTC stop_order_ids:**
- ARM  → b5c5020c (21 shares, GTC stop at broker)
- MS   → d9df546c (65 shares)
- MU   → e2ea75e3 (8 shares)
- PANW → b289f55a (51 shares)

**Part B — deleted 12 stale rows:** INTC, NUE, QCOM, TXN, UNH, AMD (orphan_db_reconciler Jun-10), DDOG, FTNT, HPE (reconciler_market_exit Jun-9), APD, CCL, USO (Kraken-era).

**Part C — cleared MRVL stale order ref:** d96941eb was gone from broker (sub-share position can't hold a whole-share stop).

## Final state
6 rows remain: DELL, ARM, MS, MU, PANW (all with correct stop_order_ids), MRVL (NULL — correct).
All 5 live GTC orders at Alpaca have a matching ratchet_stops row with the correct stop_order_id.

## Why this matters
NULL stop_order_id causes maybe_ratchet to skip cancel_order() → places a second GTC stop → duplicate orders → potential over-sell / short. MU profit was above the ratchet trigger threshold when this was fixed.

Also added Phase J to ensure_schema() in postgres.py (idempotent) so it self-applies on next publish.
