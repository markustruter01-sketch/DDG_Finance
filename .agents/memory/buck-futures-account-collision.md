---
name: Buck futures Alpaca account collision
description: buck_futures bot uses the same Alpaca account as oracle, causing fleet equity double-counting of ~$96k.
---

## Rule
Do NOT treat buck_futures equity as independent until it has its own Alpaca account. Fleet equity double-counts while the collision exists.

## Detail
- `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` env vars (the "navigator slot" assigned to buck_futures in kraken-bot/config.py) point to the same Alpaca paper account as oracle (PA33G6QCIHDS).
- `bot_portfolio` for `buck_futures` shows AMD, INTC, NUE, QCOM, TXN, UNH — identical to oracle's positions.
- `/fleet/equity` sums BOTH rows → fleet equity overstated by ~$96,683.
- Reported fleet equity ~$901,517. True (deduplicated) ~$804,834.

## Why this happened
Buck Futures was assigned the ALPACA_API_KEY/SECRET env vars which were originally the forex navigator slot, but that slot's Alpaca credentials were the same as oracle's.

## Fix required before Phase 2
Either: assign buck_futures a dedicated paper Alpaca account, or exclude buck_futures from fleet_total until resolved.
