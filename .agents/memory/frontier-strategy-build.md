---
name: Frontier Strategy Build (Stage 5)
description: Stage 5 build of frontier_trend_strategy.py; oracle scanner kill; all 4 ETF regions code-complete.
---

## Stage 5 — Frontier/EM ETF Strategy

**Date:** 2026-08-11

### What was built
- `kraken-bot/frontier_trend_strategy.py` — NEW (mirrors Asia/LatAm); BOT_ID="buck_futures", UNIVERSE=["EEM","EZA","EPOL","GREK","TUR"], MAX_POSITIONS=3, max_correlated=2 (default), within-universe ETFs excluded from corr check (like LatAm)
- `runner.py`: buck slot → `("buck_futures","frontier_trend_strategy","run_frontier_cycle")`
- `config.py`: buck_futures → etf_trend_frontier, LOOP=3600s, Jerome account keys
- `bot-identity.ts`: buck_futures → "Frontier" / 🌍
- `arc2_walk_forward.py`: Frontier seeded 0.77, ARC0 date 2026-08-11, _STRATEGY_PARAMS updated

### Oracle scanner killed
- `core/scheduler.py`: `_intraday_cycle()` now hard-returns immediately (Stage 3B retirement comment + is_paused check)
- `bots_state.oracle.paused=TRUE` written to PRODUCTION DB (NEON_DATABASE_URL)

**Why:** Oracle stock scanner was still live in production (fired every 15 min at market open). Had to disable before publishing new Asia bot or it would keep opening new stock positions.

### Oracle account broker state (2026-08-11)
- 5 GTC stops cancelled (ABT/BMY/MMM/PYPL/SCHW)
- 5 market-sell orders submitted (status=accepted) → fill at 9:30 AM ET 2026-08-12
- Positions still showing until fill; orders queued ✅

### Corr-cap verification results
- EWY/EWT: ρ=0.844 → correctly blocked by Asia's max_correlated=1
- EWJ/EWM: ρ=-0.310 → correctly allowed together
- Frontier EEM/EZA: allowed under max_correlated=2 (1 correlated neighbour is OK)

### Current dry-run signals (2026-08-11 close)
- US Core: SPY ✓, QQQ ✓ (both ENTRY)
- Asia: EWT ✓, EWJ ✓, EWM ✓ | EWY no_entry (px<EMA50), INDA BEAR, VNM BEAR
- LatAm: ECH ✓ | EWZ no_entry, EWW no_entry
- Frontier: EEM ✓, EPOL ✓, GREK ✓ | EZA BEAR, TUR no_entry

### Publish gate
BLOCKED: must confirm oracle flat first (market-sell orders fill at 2026-08-12 open).
After oracle confirmed flat → 4-region publish is clear.
