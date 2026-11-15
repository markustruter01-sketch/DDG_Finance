# DDG Finance — order-path audit and "must never happen" list (plan item 7)
Started by Claude (Fable 5.2), finished by Claude (Opus 5.5), Mon 16 Nov 2026 ~05:30 Brisbane. Code read at main = 4f11dde. Code only: no live system was read or changed.
Labels: VERIFIED = read in code (file:line given). INFERRED = reasoned, not proven. PROPOSED = not yet agreed.

## Bottom line
- One real bug can turn a single order into two (F1, Alpaca). Paper money, needs a broker timeout at the wrong moment, but it is exactly the "timed-out order may have filled" case. Fix before the lock.
- Forex treats any unclear answer to an order as "not filled" (F2). The trade still has its stop at OANDA; the records go wrong.
- "No position without a stop for more than 60 s" is NOT true today. Real bound: up to about one hour, with an alarm within 15 min. Good enough for paper; must be tightened before real money.
- Everything else on the list holds, with the guard named below.

## Map: every code path that can place, cancel or change an order
| Path | Account | Live? | Where |
|---|---|---|---|
| Bot cycles (Atlas F1, Atlas V2 C1, Momentum) through AlpacaEtfEngine | each bot's own | yes, hourly, only on the published runner when unpaused | kraken-bot/alpaca_etf_engine.py; sleeve_runtime/trend_executor.py; sleeve_runtime/fleet_live.py; momo_live.py |
| Stop upkeep while paused | each Alpaca bot | yes | kraken-bot/runner.py:677-705 (`reconcile_protective_stops` only) |
| SGOV cash parking | Alpaca bots | yes, inside the bot cycle | kraken-bot/sgov_parking.py |
| Forex execution | OANDA practice | yes, once per NY day | kraken-bot/forex_execution.py; trading-platform/core/oanda_trader.py |
| Per-bot vault (BIL buys, VOO sells) | each Alpaca bot | yes: PER_BOT_VAULT_ENABLED="true" (.replit:33); scheduler every 15 min in market hours | trading-platform/execution/per_bot_vault.py:641 |
| Kill switch cancels non-protective orders | all | NO while KILL_SWITCH_ARMED="false" (.replit:38) | trading-platform/core/kill_switch.py:683-697 |
| Manual endpoints: /emergency/liquidate, /vault/sweep | oracle's key only (execution/broker.py:48-57) | only if someone calls them (behind TRADING_API_SECRET + ReplShield) | routes/control.py:148; routes/portfolio.py:778 |
| Rehearsal script | spy_qqq_trend | only when run by hand | kraken-bot/rehearsal.py |
| Short selling (place_short_order, buy-stop) | — | DEAD: no live module imports oracle_short_executor or ratchet_stop | execution/broker.py:446-580 |
| One-time 17 Aug cleanup (cancel all + close all) | oracle | DEAD: date-guarded, cannot fire | core/scheduler.py:341-358 |

## Findings

### F1 🔴 Alpaca: a timed-out order can be sent twice — VERIFIED
1. Both Alpaca libraries resend any request, POST included, on HTTP 429 or 504: 3 more tries, 3 s apart (alpaca-trade-api 3.2.0 rest.py:183-186 and 217-231; alpaca-py 0.35.0 constants.py:11-13). No APCA_RETRY_* setting in .replit; Replit Secrets not checked.
2. The resend carries the same client_order_id. If the first try had in fact been accepted, Alpaca refuses the resend as a duplicate id. On its own that is safe.
3. But our wrapper `submit_with_unique_client_order_id` (trading-platform/core/order_ids.py:63-81) treats a duplicate-id error as an id collision, makes a NEW id and sends the order AGAIN. Shown by a local test with a fake submit: 2 orders sent, 2 different ids.
4. A real collision is practically impossible (16 random hex characters). So that retry branch only ever runs in the dangerous case.
5. Used by every bot order: engine place_order 679, buy_market 709, close_position 894, stop submit 1401, close_partial 1606; execution/broker.py 166, 206, 308, 353.
- Effect (INFERRED): a doubled buy, bought with cash the plan did not have (may use paper margin = leverage outside the rules); the ledger records one fill, the broker holds two; the quantity invariant alarms. A doubled full-close sell could open a short if the account allows shorting (account setting NOT checked).
- The vault already does this right: on a duplicate id it looks the order up and adopts it (per_bot_vault.py:409-421).
- FIX (Opus): on a duplicate-id error, look the order up by its client id and return it. Never send a second order. One place (order_ids.py) plus a lookup passed by each caller (alpaca-trade-api has `get_order_by_client_order_id`). Test on the fake broker: accept, then time out, then refuse the resend → exactly one order, recorded once, protected.

### F2 Forex: an unclear order answer is recorded as "not filled" — VERIFIED
- `market_order` returns filled=False for anything but HTTP 201 with a trade id (core/oanda_trader.py:95-99). A 504 or a lost connection after OANDA executed it looks the same as a refusal.
- forex_execution.py:201-206 then logs "not filled" and line 222 marks the day done. The trade, if it exists, has its stop (stopLossOnFill is sent with the order, line 91) but no ledger row: reconciliation flags it; nothing adopts it.
- Safe parts, VERIFIED: closes run before opens; a held pair is never reopened (forex_risk.py:120); a trade without a confirmed stop is closed at once (forex_execution.py:207-214); trades OANDA closed are synced every cycle (110-125).
- FIX (Opus): send a client id with every order (OANDA `clientExtensions` / `tradeClientExtensions`). After any answer that is not a clear fill or a clear refusal, read the order by `@clientID` before deciding; if it filled, check its stop and record it. A failed close needs nothing new (the next sync sees it).

### F3 Unprotected windows longer than 60 s — VERIFIED
| Case | Where | How it recovers |
|---|---|---|
| Full close cancels the stop, sell not filled in 30 s, and its cancel is unconfirmed: returns with no stop | engine 889-919 | next hourly cycle re-arms once the sell is gone (DAY orders expire at the close) |
| Full or partial close: error after the stop was cancelled | engine 924-941, 1655-1659 | same |
| A filled order the system thinks failed: broker position with no ledger row | trend_executor.py:80-88 freezes it; reconcile is ledger-driven (engine 1541-1579) | never re-armed automatically; alarm only |
| /emergency/liquidate cancels all orders (stops too) before selling | routes/control.py:152-185 | a failed sell is left with no stop |
- Backstop, VERIFIED: invariant `strategy_positions_have_covering_stops` reads broker positions and orders every 15 min and alarms (core/invariants.py:298; scheduler 227-237).
- PROPOSED rule for paper: "a position may be without its stop only until the next cycle, and never unalarmed for more than 15 min". The 60 s rule waits for real money.

### F4 Vault orders ignore pause and the kill latch — VERIFIED
- run_deployment_cycle and run_voo_liquidation never read bots_state.paused or the latch (no match for paused/latch/kill in per_bot_vault.py). They have a daily order cap.
- FIX (Opus, small): skip a paused bot and skip all when the latch is set.

### F5 No timeout on Alpaca calls in the bot engine — VERIFIED
- alpaca-trade-api sends with no timeout (rest.py:204-211). A hung connection stalls that bot's thread; the cycle-freshness invariant alarms.
- FIX (Opus, after F1): add a timeout. Only safe once F1 is in, because a timed-out order becomes an unclear answer.

### Checked and fine — VERIFIED
- Pause: the runner reads bots_state.paused before every cycle and fails closed (runner.py:879-881; fallback line 99). A cycle already running finishes.
- Dev workspace: the scheduler does not start in dev (main.py:177-201); the runner trades only when RUNNER_EXECUTION_MODE=live, default read_only (runner.py:156-163, 882; where production sets it was not checked); dev DB sessions are read-only (.replit:47).
- Stop replace: an order that cannot be re-read counts as open, so no second overlapping stop (engine 1124-1136); cancels are confirmed before a new order (1154-1167); new stops wait for shares to be released (1169-1206).
- Rate limits: the extra retry on emergency/broker paths fires on 429 only (execution/resilience.py:60-100). A 429 means not placed, so a resend is safe.

## Rule for unclear order answers (401, 5xx, timeout, dropped connection)
1. Never resend an order without first looking it up by its client id.
2. Found: adopt it (record it, check or place its stop).
3. Not found after a few reads over about 30 s: treat as not placed. The next cycle re-plans from the broker's positions, never from memory.
4. 429 = refused, not placed: a resend is safe.
5. Reads (GET) may be retried freely, with pauses.
6. A cancel with an unclear answer: re-read the order; never place a replacement while the old order may still be live (already the code's behaviour).

## Must never happen — list with today's guard
| # | Must never happen | Guard today | Status |
|---|---|---|---|
| 1 | Same order sent twice | none on duplicate-id retry | 🔴 F1 |
| 2 | Order the system does not know about | Forex: reconciliation flags; Alpaca: ledger/qty invariants flag | F1, F2 |
| 3 | Position without a covering stop past the next cycle / unalarmed >15 min | arm after fill, hourly reconcile, 15-min invariant | holds except a ledger-less position (F3) |
| 4 | Order while a bot is paused | runner gate | vault ignores it (F4) |
| 5 | Order from the dev workspace or a non-published process | scheduler off in dev, runner published-only, read-only DB | holds |
| 6 | Short sale or borrowing by any bot | short code is dead; buys capped to cash (trend_executor.py:146) | holds, except a doubled order (F1) |
| 7 | Forex trade without its stop | stop sent with the order, read back, closed if missing | holds |
| 8 | Publish with open non-protective orders | publish pre-check (procedure, not code) | holds by procedure |

## Tests Opus adds (fake broker, kraken-bot/fake_alpaca.py)
1. Submit accepted, answer times out, resend refused as duplicate → one order, adopted, stop placed.
2. Same for a full close and a partial close → one sell, no short.
3. OANDA order answered 504 but filled → trade adopted with its stop; answered 504 and not filled → recorded as not filled.
4. Paused bot or tripped latch → vault places nothing.

## Order of work (PROPOSED)
1. OPUS: F1 + F2 + F4 + tests as one PR. FABLE reviews.
2. Publish at the lock weekend (Sat 21 Nov, market closed) with the cutover, not during the gate (engine change).
3. After the lock: F5; delete the dead short-selling code and the 17 Aug one-time job.
- Tonight's rehearsal is unaffected beyond the F1 risk on 1-share orders (worst case one extra share).
