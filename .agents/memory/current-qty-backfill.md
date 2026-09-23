---
name: ETF current quantity backfill
description: Durable rules for initializing live ETF quantities without changing entry sizing quantities.
---

The ETF ledger treats `qty` as the immutable entry quantity used by scale-out sizing. Startup repair initializes NULL values, zeros every nonzero closed row, and reconciles an open scaled-out row only when `current_qty == qty`, using a canonical-symbol match to the broker's live GET response. Canceled rows remain NULL. Broker failures or missing symbols must leave affected rows unchanged while recording an error degradation and continuing with safe updates.

**Why:** Entry sizing and live broker reconciliation represent different quantities; guessing an open quantity or overwriting an existing value could hide a position mismatch or corrupt later scale-out behavior.

**How to apply:** Keep startup repair idempotent: only target NULL rows, nonzero closed rows, or scaled-out open rows still equal to immutable `qty`; never overwrite `qty`. Later readers may switch to `current_qty` only after repair has run through the published startup path. Verify the deployed Alpaca client exposes the intended GET positions method; the production `alpaca_trade_api.REST` adapter does not expose `get_all_positions()`, so an incompatible call must remain fail-closed rather than guessing open quantities.

**Why:** The first published run updated closed rows but left all open rows NULL because the deployed REST adapter lacked that method; this preserved safety but showed that local fake/API compatibility can diverge from the published broker client.