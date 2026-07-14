---
name: Bot2 safety fixes
description: Three post-OOS safety fixes applied to bot2_spy_qqq.py after Jul-7 double-buy incident and OOS analysis.
---

## Fix #1 — Empty-response entry guard
**Rule:** If `engine.get_positions()` returns `[]` but `engine.get_db_positions(BOT_ID)` has open rows, set `_entry_scan_ok = False` and skip the entire `for symbol in UNIVERSE` entry loop. Records `entry_empty_response_guard` (severity=high) via `degradation_tracker`.

**Why:** Jul-7 double-buy happened because `held_symbols` derived from live Alpaca positions; empty response → `held_symbols = {}` → re-entered SPY. Same pattern as Oracle D4 reconciler fix, applied to bot2's entry guard.

**How to apply:** Check `_entry_scan_ok` is the first gate in the UNIVERSE loop. degradation_tracker import is inside a try/except (non-fatal if DB unavailable).

## Fix #2 — 3-day exit: last 3 bars only
**Rule:** `_should_exit_trend` 3-day check is now `closes[-1] / closes[-4] - 1 <= -0.05`. Was `for i in range(3, len(closes))` which scanned all 80 bars.

**Why:** The all-80-bars scan caused pathological churn in the OOS harness — 45/57 trades in 2020 were 3-day exits from historical drops. Ancient drops that already recovered would fire every cycle until they aged out of the 80-day window.

**How to apply:** 2022 OOS re-run with fix applied: identical result (-5.0%). 2022 failure was entirely `price_below_ema50`, zero 3-day exits. Fix #2 is safe but does not change 2022 outcome.

## Fix #3 — Multi-lot TP deduplication
**Rule:** At the top of the exit loop, group `db_positions` by symbol via `_lots_by_sym` (defaultdict, sorted by `opened_at`). Secondary lots (not `lots[0]`) get trailing-stop DB update only — skip `run_exit_checks` entirely (which calls `close_partial` internally). Track `_closed_this_cycle: set[str]`; if primary fires a full close, secondary lots get `record_close(…, "multi_lot_primary_closed", None)`.

**Why:** Two DB rows for same symbol (e.g. SPY Jun-25 + Jul-7) → `run_exit_checks` on both → two independent `close_partial` calls for TP → overlapping sell orders. `close_position` called twice → second call errors on Alpaca (position already gone).

**How to apply:** `is_primary = (db_pos is lots[0])` uses object identity, relies on same dict objects returned by `get_db_positions`. If `get_db_positions` rebuilds dicts each call, identity check would break — use `opened_at` key comparison as fallback.
