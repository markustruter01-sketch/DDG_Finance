---
name: Server-truth rebuild
description: Rules and decisions from the all-server-truth dashboard rebuild. What was changed and why.
---

## Rule 27 — server is SSOT for all P&L values

All P&L, win rate, and equity numbers come from `/fleet/equity` or `/journal` endpoints.
Client-side arithmetic (avg_pnl×total, wins/trades, reduce over position list) was removed
from the 6 targeted locations and must not be reintroduced.

**Why:** Client math diverged from server math silently. Server computes from real DB rows.

**How to apply:** If you need a P&L or win-rate number in the frontend, use a hook that
queries a server endpoint. Do not compute from raw trade lists in the browser.

## 3-bot fleet — buck_futures permanently retired

Fleet is exactly 3 active bots: oracle, spy_qqq_trend, jerome_macro.
buck_futures retired May 2026 (last heartbeat May 30). It still exists in:
- FleetEquityResp type (kept optional for graceful fallback rendering)
- use-portfolio.ts BotEquity type (server still sends it, always stale)

**Why:** buck merged into jerome account. Showing it as active was misleading.

**How to apply:** Filter stale bots dynamically: `!fleet[id]?.stale`. Never hardcode 4-bot arrays.
`ACTIVE_BOT_IDS = ["oracle", "spy_qqq_trend", "jerome_macro"]` is the canonical frontend list.

## Version endpoint for deploy verification

`GET /trading-api/version` returns `{running_hash, latest_hash, match, started_at}`.
Hash captured once at module load via `subprocess git rev-parse --short HEAD`.

**Why:** After a publish, the running process might still be the old binary until restart.
If `match: false`, the deployment needs a restart to pick up the new code.

**How to apply:** Check this endpoint after every publish. If `match` is false, restart the service.

## 24h P&L in fleet/equity

`GET /fleet/equity` now includes `pnl_24h` and `pnl_24h_pct` on each bot slice and on
`fleet_total`. Computed by `_fetch_24h_pnl()`: oracle/spy from `trades` table (asset_class),
jerome from `jerome_positions` (bot_id=jerome_macro, closed_at > NOW()-24h).

**Why:** Discord and dashboard both need 24h change; sourcing from one place prevents drift.

## Discord — exactly 3 lines (plain content, no embed)

`notify_daily_pnl_report()` now sends a single `{"content": "line1\nline2\nline3"}` POST.
Line 1: 24h %. Line 2: 24h $. Line 3: Regime label.
Rich embed, per-bot lines, WF banners, fleet fields all deleted.

**Why:** Discord embeds were noisy and hard to scan on mobile.

## Best/worst trade — server journal summary

`get_journal_summary()` now returns `best_trade_usd`, `best_trade_symbol`,
`worst_trade_usd`, `worst_trade_symbol` from the `trades` table (all-time, closed trades).
StreamHeaderBar uses these instead of a 50-trade window `reduce()`.

**Why:** 50-trade window misses older best/worst trades. Server query is authoritative.
