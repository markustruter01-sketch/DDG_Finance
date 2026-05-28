---
name: Fleet equity key mismatches
description: /fleet/equity uses DB bot_ids as keys; frontend screens access wrong keys causing null equity for spy_qqq_trend and jerome_macro.
---

## Rule
When reading from `/fleet/equity`, use DB canonical bot_ids as keys, not Kraken runtime IDs or legacy aliases.

## Key map
| Bot | DB bot_id (correct key) | Wrong keys used in frontend |
|-----|------------------------|-----------------------------|
| SPY/QQQ Trend | `spy_qqq_trend` | `davy_jones` (StreamingBotsScreen line ~261, ~293) |
| Jerome Macro | `jerome_macro` | `blackbeard` (StreamingBotsScreen line ~262, ~304) |
| Forex Gump | `navigator` | — (retired, key will be absent) |

## Why
Kraken runner uses `davy-jones` and `blackbeard` as its internal bot_ids. These are valid for `/kraken/status?bot_id=` and `/kraken/performance?bot_id=` calls (Kraken API uses them). But `bot_portfolio` stores the canonical DB bot_ids (`spy_qqq_trend`, `jerome_macro`), so `/fleet/equity` returns those keys. StreamingBotsScreen reads `fleetEq.davy_jones` and `fleetEq.blackbeard` → always undefined → equity shows null for those two bots.

## How to apply
Any new code reading `fleetEq[botId]` must use the canonical DB bot_id. If you have a Kraken runtime ID, resolve it through `bot-identity.ts` canonicalId first.
