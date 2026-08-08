---
name: ETF cross-bot position status key
description: alpaca_etf_positions uses 'open'/'closed' — never 'Active'. Cross-bot helpers must query status='open', not 'Active'.
---

## Rule
`AlpacaEtfEngine.record_open()` writes `status='open'`.
`AlpacaEtfEngine.record_close()` writes `status='closed'`.
**Never** `'Active'` or `'Closed'` — those are from older tables (`trades`, `jerome_positions`).

## Why
`_get_cross_bot_held_etfs()` in both `asia_trend_strategy.py` and `latam_trend_strategy.py`
originally queried `status='Active'` — making cross-bot correlation cap permanently blind
(returned `[]` every cycle even when other bots had live positions).

Fixed: both files now query `status='open'`.

## How to apply
Any code that reads other bots' open positions from `alpaca_etf_positions` must use
`WHERE status = 'open'`, not `'Active'`. Same for same-bot reads:
`get_db_positions()` already uses `'open'` correctly.

The older `trades` and `jerome_positions` tables use different status vocabularies —
do not mix them.
