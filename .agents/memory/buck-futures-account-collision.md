---
name: Buck futures Alpaca account collision
description: buck_futures used Oracle's Alpaca account. Bot is HALTED until a 4th account is provisioned.
---

## Current State (2026-05-28)
Buck Futures is HALTED. It was removed from runner.py BOTS list and a safety guard
was added to run_buck_futures_cycle. It cannot trade until ALPACA_BUCK_API_KEY exists.

## Root Cause
`ALPACA_API_KEY` / `ALPACA_SECRET_KEY` env vars (the "navigator slot") point to
Oracle's Alpaca paper account: `caa2a89b-d35c-4c19-8f19-596d36ebb1ef`.
The forex navigator never had its own Alpaca account — it also shared this one.

## Account inventory (3 total, all confirmed)
| Bot | Env vars | Key prefix |
|-----|----------|------------|
| Oracle | ALPACA_API_KEY / ALPACA_SECRET_KEY | PKKBYO... |
| Jerome (blackbeard) | ALPACA_JEROME_API_KEY / SECRET | PKG42L... |
| SPY/QQQ (bot2_spy_qqq) | ALPACA_BB_API_KEY / SECRET | PK6OIL... |
| Buck Futures | MISSING — needs new account | — |

## Oracle account confirmed clean
- Verified no DBB/PICK/DBC/PDBC/GSG open positions or orders from buck_futures
- 6 PDBC orders in history are from Jerome's old broad universe (April, all closed)
- jerome_positions has zero rows for bot_id='buck_futures'

## Why
No 4th Alpaca paper account existed when buck_futures was created. It was
erroneously assigned the retired forex navigator slot which shared Oracle's account.

## How to re-enable Buck Futures
1. Markus creates a new Alpaca paper account at alpaca.markets
2. Add `ALPACA_BUCK_API_KEY` + `ALPACA_BUCK_SECRET_KEY` to Replit Secrets
3. Update `kraken-bot/config.py` buck_futures profile:
   `"ALPACA_API_KEY": os.environ.get("ALPACA_BUCK_API_KEY", "")`
   `"ALPACA_SECRET_KEY": os.environ.get("ALPACA_BUCK_SECRET_KEY", "")`
4. Uncomment `("buck_futures", "buck_futures_strategy", "run_buck_futures_cycle")` in runner.py
5. Remove the ALPACA_BUCK_API_KEY safety halt block from run_buck_futures_cycle
6. Restart kraken-bot-runner workflow
