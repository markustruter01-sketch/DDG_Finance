---
name: Oracle bot_portfolio heartbeat gap
description: Why oracle last_updated goes stale outside market hours and how it's fixed
---

The Oracle pipeline writes `bot_portfolio.last_updated` only at the END of
`_run_pipeline_inner` (via `write_portfolio`). But `pipeline.py` has an
early return when the market is closed (line ~676):

    if not crypto_only and not force and not is_market_open():
        ...
        return result   # bot_portfolio write never reached

This means `last_updated` only ticks during NYSE market hours (09:01–15:46 ET).
Over a 3-day holiday weekend the gap exceeds the 108,000s stale threshold.

**Fix (applied 2026-05-27):**
- `core/bot_state.py` — `touch_portfolio(bot_id)`: timestamp-only UPDATE, no
  equity/cash change
- `core/pipeline.py` market_closed block — calls `touch_portfolio("oracle")`
  before returning, non-fatal try/except

**Why touch-only (not full write_portfolio):**
The equity/cash values are not available on the market-closed path (no Alpaca
call is made). Touching only `last_updated` keeps live data intact.

**All other bots** write their own heartbeats from their Kraken/forex runners
independently of the Oracle pipeline — they are not affected by this gap.
