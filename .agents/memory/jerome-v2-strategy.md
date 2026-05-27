---
name: Jerome v2 strategy
description: EMA/ADX/ATR commodity trend-following live on blackbeard; LLM parachute retained; migration pattern for prod.
---

# Jerome v2 — EMA/ADX/ATR Commodity Trend-Following

## What was built
`kraken-bot/jerome_v2_strategy.py` (~400 LOC) — pure quant strategy replacing the Groq LLM cycle.

## Key parameters (validated by 28-month backtest)
- Universe: 12 instruments across ENERGY/PRECIOUS_METALS/INDUSTRIAL/BROAD
- RISK_PER_TRADE=0.04, SINGLE_POS_CAP=0.50, ADX_LONG_MIN=30, ADX_SHORT_MIN=25
- TRAIL_ATR_MULT=5.0, MAX_POSITIONS=6, THEME_CAP=2
- Entry scan: once/day at 13:30–13:50 UTC (5 min after NYSE open)
- Exit management: every 900s cycle

## Wiring
- runner.py BOTS: `("blackbeard", "jerome_v2_strategy", "run_jerome_v2_cycle")`
- LLM parachute: revert by flipping back to `jerome_strategy` / `run_jerome_cycle` (one line)
- config.py: `GROQ_CYCLE_HOURS` commented out (jerome_v2 ignores it anyway)

## Schema
- jerome_positions gained two columns: `entry_price NUMERIC`, `highest_price_seen NUMERIC`
- Migration in `ensure_schema()` (postgres.py, JEROME V2 SCHEMA — 2026-05-28)
- Production columns are applied by Replit Publish flow (dev schema diff → prod)
- COPX pre-existing position backfilled with avg_entry_price=86.989133 via idempotent UPDATE in ensure_schema()

## P&L reconciler
- `_reconcile_jerome_pnl()` is imported FROM `jerome_strategy.py` — reused, not duplicated.

**Why:** Avoids code duplication; if reconciler ever needs updating, single source of truth.

## Data layer
- `_yahoo_daily_ohlcv(ticker, days=250)` from `alpaca_etf_engine` — returns dict with lists
- Convert to pd.Series for `ta` library (EMA21/55/200, ADX14, ATR14)
- Need 210+ bars for EMA200 warm-up (250-day fetch gives margin)
