---
name: ARC 2 walk-forward validation
description: Nightly WF job at 17:30 ET — OOS envelope, Arc-0 filters, status thresholds, schema phases
---

## Walk-forward validation module
- File: `trading-platform/analysis/arc2_walk_forward.py` (distinct from Kraken optimizer at `analysis/walk_forward.py`)
- Runs nightly at 17:30 ET Mon-Fri via scheduler Job 5: `nightly_walk_forward`
- In `_ALWAYS_ACTIVE_JOBS` → persists when trading disabled

## OOS Envelopes (pre-registered)
- **oracle**: pooled Sharpe 0.633, worst-window floor **-0.153** (2021), pooled maxDD 17%
- **spy_qqq_trend**: pooled Sharpe 0.862, worst-window floor **-1.889** (2022), pooled maxDD 6.5%
- **jerome_macro**: DISQUALIFIED (no OOS run)
- **buck_futures**: DISQUALIFIED (no OOS run)

## Status thresholds
- GREEN: trailing-90d Sharpe ≥ OOS floor
- AMBER: below floor < 60 consecutive job-run days
- RED: below floor ≥ 60 days
- INSUFFICIENT_DATA: < 10 closed trades in 90d OR Sharpe uncomputable
- Protocol: RED 60d → halve size; RED 120d → halt entries (human executes)

## Arc-0 ghost exclusions
- **oracle (trades)**: exclude `status=Active`, `closed_at IS NULL`, `realized_pnl IS NULL`, `exit_reason LIKE '%[v1_duplicate]%'`, `reconciler_race_phantom`, **`stf_v1_liquidation`**
- **spy_qqq (alpaca_etf_positions)**: `status=closed`, exclude `multi_lot_primary_closed`
- **jerome**: `opened_at >= 2026-05-28` (pre-v2 LLM rows excluded)
- **buck**: `opened_at >= 2026-05-29`

## Schema (Phase K + L in ensure_schema)
- Phase K: `oos_envelope` table + 4-row seed (idempotent, ON CONFLICT DO NOTHING)
- Phase L: 13 ADD COLUMN IF NOT EXISTS on `bot_evaluation_history`: `wf_sharpe_30d/90d`, `wf_maxdd_30d/90d`, `wf_trades_30d/90d`, `wf_win_rate_30d/90d`, `wf_expectancy_30d/90d`, `wf_status`, `wf_consecutive_below_floor`, `wf_oos_floor_sharpe`

## Dry-run result (first run, 2026-07-14)
- oracle: INSUFFICIENT_DATA (0 real trades after Arc-0; all 90d closes were stf_v1_liquidation artefacts)
- spy_qqq_trend: INSUFFICIENT_DATA (0 rows in alpaca_etf_positions; blackbeard running but no positions closed yet)
- jerome_macro: DISQUALIFIED ✓
- buck_futures: DISQUALIFIED ✓

## Integration points
- Discord: RED/AMBER banners prepended to 05:00 AEST daily brief
- Claude report: `walk_forward_status` key in JSON + `_format_text` section
- `get_current_wf_status()` reads most-recent WF row per bot (DISTINCT ON bot_id ORDER BY snapshot_at DESC)

**Why:** Live performance must be continuously compared against OOS-validated statistical properties. INSUFFICIENT_DATA is the expected initial state until ≥10 real trades close.
