---
name: Fleet equity SSOT
description: /fleet/equity is the authoritative data source for all bot PnL, equity, and win rate — never recompute these client-side.
---

## Rule
`GET /trading-api/fleet/equity` is the single source of truth for:
- Per-bot equity, pnl, pnl_pct, win_rate (30-day)
- Fleet totals: fleet_total.equity, fleet_total.pnl, fleet_total.pnl_pct, fleet_total.win_rate

Frontend must read these fields directly. Never divide equity by a hardcoded starting balance.

**Why:** Phase 2 refactor found 6+ places computing PnL as `equity - 100_000` or assembling win_rate client-side from dead Kraken endpoints. These diverged silently and displayed wrong numbers for spy_qqq_trend and jerome_macro whose starting capital differs from oracle's.

**How to apply:**
- `win_rate` field: populated by `_fetch_win_rates()` in `fleet_equity.py`. Queries `trades` (oracle via momentum_equity, spy_qqq_trend via momentum_etf) and `jerome_positions` (jerome_macro, buck_futures). Returns `None` if no trades in the 30-day window — handle gracefully in UI.
- `pnl_pct` field: `(pnl / starting) * 100` — use directly, never recompute.
- `useFleetEquity()` hook in frontend returns this data with SWR caching.
- Dead Kraken hooks to never re-add: `useKrakenPerformance(botId)`, `useKrakenStatus(botId)` with specific bot IDs.
