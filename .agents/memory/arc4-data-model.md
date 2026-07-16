---
name: ARC 4 Data Model Cleanup + Shadow-Signal Ledger
description: Two new tables (reconciliation_events, shadow_signals), is_recon_tracking column on trades, WR filter migration, and per-bot signal decision logging.
---

## What was built

**reconciliation_events**: replaces RECON-* string-matching as the audit trail.
- Both reconcilers write here: forward reconciler → event_type="recon_insert"; inverse → event_type="orphan_close"
- record_reconciliation_event() is a fire-and-forget helper in db/postgres.py

**trades.is_recon_tracking (BOOLEAN DEFAULT FALSE)**: the clean predicate.
- Forward reconciler: after log_trade(), does UPDATE trades SET is_recon_tracking=TRUE WHERE trade_id=X
- _ARC4_BACKFILL_SQL tags existing RECON-* rows on every startup (idempotent)
- WR filters: `AND NOT COALESCE(is_recon_tracking, FALSE)` — fleet_equity.py + claude_report.py

**shadow_signals**: decision-level logging without execution.
- One row per scan candidate per cycle across all 4 bots
- executed=TRUE if order was submitted; skip_reason = cap_full / regime_gate / crisis / cash / theme_cap / already_holding / signal_fail / order_failed / atr_invalid / min_position / empty_response_guard
- 90-day retention sweep registered in scheduler.py at 18:00 ET

## Bot wiring locations
- Oracle (Larry): core/pipeline.py, after regime filter block, before "Edge case: filter emptied..."
- Moe (bot2): kraken-bot/bot2_spy_qqq.py, _shadow_b2() helper before the for-symbol loop
- Curly (jerome): kraken-bot/jerome_v2_strategy.py, _shadow_jv2() before for-cand loop
- Curly Jr (buck): kraken-bot/buck_futures_strategy.py, _shadow_buck() before for-cand loop

**Why:**
Primary motivation was the "60-candidates-seen-zero-taken" blind spot during the frozen-book period — without shadow signals there was no way to tell if the scanner was generating candidates that were being blocked by capacity/regime gates. The is_recon_tracking column removes the fragile LIKE 'RECON-%' hack from all WR/expectancy queries.
