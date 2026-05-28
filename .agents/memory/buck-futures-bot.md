---
name: Buck Futures bot
description: Architecture and key decisions for the Buck Futures commodity trend bot built 2026-05-28.
---

## What it is
Buck Futures is a clone of Jerome v2 (EMA21/55/200 + ADX + 5×ATR trailing stop) running on the Industrial & Broad commodity ETF universe slice: DBB, PICK, DBC, PDBC, GSG (5 instruments).

Jerome v2 retains Energy + Precious Metals: XLE, USO, XOP, GLD, SLV, GDX, GDXJ (7 instruments). The universes are mutually exclusive — no ticker overlap.

## Key files
- `kraken-bot/buck_futures_strategy.py` — strategy (clone of jerome_v2_strategy.py)
- `kraken-bot/config.py` → `"buck_futures"` profile (db_id=6)
- `kraken-bot/runner.py` → BOTS includes `("buck_futures", "buck_futures_strategy", "run_buck_futures_cycle")`

## Alpaca account
Uses `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` (the plain/unclaimed env vars = the retired forex navigator slot, ~$96k paper pool).

## DB design
Shares `jerome_positions` table with Jerome. Rows tagged by `bot_id` column:
- `jerome_macro` = Jerome v2 rows
- `buck_futures` = Buck Futures rows

**Why:** Avoids creating a second positions table; bot_id column added via `ADD COLUMN IF NOT EXISTS` migration that runs in both `trading-platform/db/postgres.py:ensure_schema()` AND via `_ensure_bot_id_column()` called on first cycle in each strategy (so kraken-bot-runner doesn't depend on trading-api startup order).

## Scheduling
- Entry scan: 13:35–13:55 UTC daily (Jerome scans 13:30–13:50, 5-min offset to avoid thundering herd)
- Exits: every 900s cycle

## What NOT to reactivate
Forex navigator is disabled (`trading-platform/main.py` scheduler.add_job commented out 2026-05-28). Code stays on disk as parachute. Reason: 2 backtests (EMA trend + CSM momentum) both NO-GO over 2024–2026 period; best Sharpe achieved was +0.24.
