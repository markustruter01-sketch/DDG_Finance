---
name: ETF current quantity backfill
description: Durable rules for initializing live ETF quantities without changing entry sizing quantities.
---

The ETF ledger treats `qty` as the immutable entry quantity used by scale-out sizing. A startup backfill initializes `current_qty` only where it is NULL: closed rows become zero, open rows use a canonical-symbol match to the broker's live GET response, and canceled rows remain NULL. Broker failures or missing symbols must leave the affected open rows NULL while recording an error degradation and continuing with any safe updates.

**Why:** Entry sizing and live broker reconciliation represent different quantities; guessing an open quantity or overwriting an existing value could hide a position mismatch or corrupt later scale-out behavior.

**How to apply:** Keep the backfill idempotent with `current_qty IS NULL` guards. Later readers may switch to `current_qty` only after the backfill has run through the published startup path.