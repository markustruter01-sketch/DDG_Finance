---
name: Bot DB Aliasing
description: Map of bot_id → actual DB table/bot_id for bots with non-standard DB names.
---

## Alias Map
| Bot ID | Table | DB bot_id |
|---|---|---|
| forex_gump | forex_trades | navigator |
| spy_qqq_trend | alpaca_etf_positions | bot2_spy_qqq |

## Singletons (no bot_id column in table)
| Bot ID | Table | Note |
|---|---|---|
| jerome_macro | jerome_positions | No bot_id; implicit singleton |

## Broker Label → Alpaca Account
- oracle → alpaca_PA33G6QCIHDS (ALPACA_API_KEY / ALPACA_SECRET_KEY)
- spy_qqq_trend → alpaca_PA3X9UBVZ6T8 (ALPACA_BB_API_KEY / ALPACA_BB_SECRET_KEY)
- jerome_macro → alpaca_PA37SP8ID1XU (ALPACA_JEROME_API_KEY / ALPACA_JEROME_SECRET_KEY)

**Why:** These bots predate the standardized bot_id column convention.
**How to apply:** Any new report or query touching these bots must use the alias, not the bot_id literal. The alias map lives in `_BOT_TRADE_ALIAS` in `claude_report.py`.
