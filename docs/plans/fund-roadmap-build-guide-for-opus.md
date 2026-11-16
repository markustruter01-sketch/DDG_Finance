# Build guide for Opus 5.5: from today's platform to the fund roadmap

Written by Claude (Fable 5.2), Tue 17 Nov 2026. You (Opus 5.5) are the only builder. Fable is NOT in the loop: do not wait for a Fable review, a Fable spec or a Fable decision. Where older notes say "FABLE decides", you propose, write the reason down, and Markus decides.

The plan you are building is `fund-roadmap-2026-11-17.md` (same folder). Markus agreed to it on 17 Nov 2026 (plan agreed; Defensive stocks replaces Atlas V2 at the lock; lock moves to about 12 to 13 Dec).

## Read first, in this order
1. `docs/plans/README.md` (how to work, Replit facts, publish rules).
2. `docs/plans/finance-2027-plan.md` (history; see "Status 17 Nov": the old gate is stopped).
3. `docs/plans/fund-roadmap-2026-11-17.md` (the target).
4. `docs/plans/order-path-audit-2026-11-16.md` (findings F1 to F5 and the "must never happen" list).
5. `.agents/memory/MEMORY.md` and any memory file named for the area you are about to touch.

## Rules that never bend
1. No new trading accounts, no new paid services, no new paid data. Free tiers only. Ask Markus before anything that could add a cost (extra AI calls, Replit Agent credits).
2. Account keys never change: `oracle`, `jerome_macro`, `spy_qqq_trend`, `forex_ai`. Names shown to people come from one display-name table.
3. One change per pull request. The GitHub test run (`.github/workflows/tests.yml`) must be green before you ask for a merge. Never weaken or delete a test to get green; if a test is wrong, say why in the pull request.
4. Publish only with the US market closed (after 21:00 UTC, before 14:30 UTC), with read-only checks before and after, as README describes.
5. Stop and ask Markus before: production database writes, placing or cancelling orders, changing stops, gearing or strategy rules, anything that cannot be undone.
6. Never invent a number or a result. Write VERIFIED (with file and line), INFERRED or UNKNOWN.
7. After every work session add a dated "Status" entry to `finance-2027-plan.md`: what changed, what was published, what is unknown, what is next.
8. You review your own work, since no second model does: before asking for a merge, re-read the whole diff once as a hostile reviewer and list in the pull request what could go wrong and how you checked it.

## Phase 0 work orders (in this order)
Each line: what to build, where to start looking, and the test that proves it. File paths come from the audit and notes; confirm each in the code before editing.

1. **Publish PR #108.** Already merged. Pre-check, publish, post-check. Proof: post-check clean, four bots cycling.
2. **Time limits on broker calls (F5).** Start: `kraken-bot/alpaca_etf_engine.py`, `trading-platform/execution/broker.py`, `trading-platform/core/oanda_trader.py`. Proof: fake-broker test where a call hangs; the cycle ends with an alarm, no second order.
3. **BTC stop-fill closes its ledger row.** Start: status entry of 15 Nov (ETH case) and the code that tracks owner-kept holdings. Proof: test that replays a filled stop; the row closes once, no repeating alarm.
4. **Daily snapshot after the US close.** Start: where `bot_daily_returns.equity_close` is written (scheduler). Proof: test with a fixed clock on both sides of the US clock change.
5. **Kill switch per bot.** Start: `trading-platform/core/kill_switch.py`; `.replit` holds `KILL_SWITCH_ARMED="false"`. Build: a failed read from one broker affects only that bot, and only after 3 failed checks in a row. Proof: tests for one bad broker (only that bot pauses), one blip (nobody pauses), and recovery. Arm it only after Markus says yes.
6. **Momentum brake check.** Recompute the book index, 100-day average and volatility by hand from Alpaca bars for the dates in the 10 Nov note. If the code is wrong, fix it with a test; if it is right, write that down. Do not change the strategy rule here.
7. **Dead code and names.** Delete: short-selling paths, old Navigator forex routes, the 17 Aug one-time job, dead `bots_state` rows (rows need Markus's yes: production write). Add the display-name table. Do NOT rename folders. Proof: test suite green, nothing imports the deleted modules.
8. **Outside heartbeat.** Needs two free monitor URLs from Markus set as `HEARTBEAT_URL_RUNNER` and `HEARTBEAT_URL_API`. Proof: both monitors show a ping.
9. **Gate.** Five US sessions, nothing merged, daily read-only check written into the plan. Any incident restarts the count.

## Phase 1 work orders: Shadow League (December 2026)
Build on `trading-platform/twins/` and `research_harness/registrations/`. Do not write a second engine.
1. Registration format: one JSON file per strategy, hashed and dated, same pattern as `TWINS-V2`. Fields: rules, universe, rebalance day, gearing, stops, pass mark, data needed.
2. Strategy interface: a pure function from "prices up to today" to "target holdings". No broker calls, no clock reads inside it. Each shadow is a twin with fake starting money.
3. Cost model, one module used by every shadow: slippage per trade, borrowing interest on geared holdings, AI cost. Start from written estimates; add a monthly job that re-measures slippage from the four real accounts' fills.
4. Build the 16 shadows and 3 yardsticks listed in the roadmap, one pull request per family, each with a test on recorded prices that checks the holdings by hand for two dates.
5. Defensive stocks: the 50 S&P 500 stocks with the lowest price volatility over the past 252 trading days, equal weight, first trading day of the month. Price data only.
6. Momentum changes (weekly brake re-check, 25% sector cap) are a NEW dated strategy version. If sector data would need a paid source, use a free, committed sector list and say so.
7. Leaderboard page in `artifacts/dashboard`: return after costs, worst fall, days in cash, gap to S&P 500, luck check.
8. Lock weekend: registrations merged, Atlas V2's account cut over to Defensive stocks (rehearse on the idle account first, as `kraken-bot/rehearsal.py` does), `RUN_START` in `trading-platform/core/fleet_capital.py` restarted once.
Proof for the phase: all 23 lines write a value on 5 nights in a row; the four mirror twins match their real accounts within the agreed tolerance.

## Phase 2: 2027
No rule changes. Month-end job: freeze, hash, copy to GitHub, one-page report. Quarterly: live versus shadow gap per real bot; a growing gap means fix the cost model going forward, never rewrite history.

## Phase 3 work orders: Allocator in shadow (build Jan to Mar 2027)
1. Regime label once a day from four measurements built from existing price data only: S&P 500 against its 200-day average; 20-day volatility against its own one-year middle value; direction of a Treasury fund over 60 days; share of S&P 500 stocks above their own 200-day average. Four labels: calm up, rough up, calm down, rough down. Register the exact numbers before the first run.
2. Allocation table per label, registered before the first run.
3. Limits in code, tested: 40% cap per strategy, 1.5x total gearing, 15% fall from the high means cash and an alarm.
4. Three shadow funds: equal money; rules Allocator; rules Allocator plus AI reduce-or-skip. The AI version needs Markus's yes first (extra AI cost).
5. No orders from any of this. It only reads shadow results and writes its own shadow record.

## Phases 4 and 5
Do not start them. In January 2028 produce the scorecard exactly as the roadmap's Phase 4 defines it, including the case "nothing passed". Real money is Markus's decision alone.

## If you are stuck
Stop, write what you know and do not know into the plan's Status entry, and ask Markus one clear question with your recommended answer.
