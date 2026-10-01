---
name: Bot 3 rebalance stop policy
description: Confirmed stop-price behavior when Bot 3 trims or adds to an existing position.
---

For a Bot 3 sell or trim, retain the existing stored stop price while replacing the stop around the settled remaining quantity. For a buy or top-up, calculate the replacement stop from Alpaca's broker-reported post-fill average entry and the existing asset-specific stop percentage. Do not use the planned quote as the actual stop basis.

**Why:** The user confirmed this asymmetric policy so trims do not silently change their established price protection, while adds reset the stop consistently against the new blended entry.

**How to apply:** Reconcile the broker quantity and average entry after each held-position fill, then create exactly one replacement stop and persist its broker order ID and stop price to the existing open ledger row.