# DDG Finance: road from today to a self-running fund

Written by Claude (Fable 5.2), Tue 17 Nov 2026, for Markus. AGREED by Markus, Tue 17 Nov 2026 09:17 Brisbane ("Yes, I agree to the plan"). This is a plan for building and testing software. It is not financial advice, and no step can promise a profit or a result against the S&P 500.

## The goal, in one line
Markus puts in his own money; the system works out what kind of market it is, which proven strategies to run, how much to give each, and trades it, with hard limits that stop it when something is wrong.

## The honest shape of that goal
- "Knows the market regime and picks the best strategy" is the hardest part and the part most likely not to work. So it is built last, tested in shadow for a year, and only switched on if it beats the simple alternative (equal money to each proven strategy).
- The AI advises in shadow first (it may only reduce or skip, never add). It earns control only with a year of evidence.
- One year of data gives a shortlist, not proof. Real money starts small and steps up.

## Rule for the whole plan: no new accounts, no new paid services
- Trading accounts stay as they are: 3 Alpaca paper accounts and 1 OANDA practice account. Shadows are fake-money records inside our own database; they need no account.
- Data: only the price feeds the platform already uses. No strategy may need a new paid data source. (This is why the Defensive stocks strategy below picks by price steadiness only, not by company profits, which would need a paid fundamentals feed.)
- Free tiers only for anything added: GitHub's test runs, and two free outside-monitor checks.
- Two things that can still cost more, so they need Markus's yes first: extra AI calls for the Allocator's AI shadow (Phase 3), and Replit Agent credits if the Agent is used for checks.
- The only new account in the whole plan is a real-money broker account in Phase 5, and only if Phase 4 passes.

## Phase 0: make the engine trustworthy (now to about Sat 5 Dec 2026)
One small pull request each, tests green on GitHub, published with the US market closed.
1. Publish PR #108 (one order per send, Forex read-back, vault obeys pause).
2. Time limit on every broker call (audit F5).
3. BTC stop-fill closes its ledger row.
4. Daily closing snapshot taken after the US close.
5. Kill switch per bot: one broker's failed reads pause only that bot, after 3 failed checks in a row. Then arm it again.
6. Momentum: recompute the trend brake by hand from Alpaca bars; fix it if wrong.
7. Delete dead code (short selling, old Navigator forex routes, the 17 Aug job, dead bots_state rows). Add the display-name table. Account keys never change.
8. Outside heartbeat on (Markus: two monitor URLs).
9. GATE: 5 US sessions with no incident and nothing merged. Target Mon 7 to Fri 11 Dec.
Done when: gate clean, 0 open alarms, broker and ledger agree on all four accounts.

## Phase 1: build the Shadow League (December 2026)
The AI twins engine already runs fake-money accounts on real prices with no orders. Extend it; do not build a second engine.
1. One registration file per strategy (rules, universe, rebalance day, gearing, stops, pass mark), hashed and dated, like TWINS-V2.
2. One shared cost model: slippage per trade, borrowing interest on geared positions, AI cost. Starts from estimates; recalibrated monthly from the four real accounts' actual fills.
3. Nightly run after the US close: every shadow valued at the close, append-only logs, hash check.
4. Leaderboard page in the dashboard: return after costs, worst fall, days in cash, gap to S&P 500, and a "luck check" column.
5. Real accounts (4): Atlas (trend, 1.5x), Defensive stocks (the 50 S&P 500 stocks with the steadiest prices over the past year, equal weight, monthly; replaces Atlas V2 at the lock), Momentum (fixed brake, weekly re-entry, 25% sector cap), Forex AI council.
6. Yardsticks (3): S&P 500 buy-and-hold; 60/40 shares and bonds; cash.
   Shadows (16), exact rules fixed in each registration file before the start:
   - Trend and gearing (4): the Atlas trend rule at 1x; at 1.5x; at 2x; today's multi-asset Atlas (FLEET-V1-F1).
   - Stock picking (4): Momentum (MOMO-V2 with the brake fixed); Momentum with the 25% sector cap; Defensive stocks; equal-weight S&P 500.
   - Diversifiers (3): trend on bonds, gold, commodities and the dollar only (no shares); gold trend alone; risk-balanced shares, bonds and gold.
   - Short-term (2): buy index dips and hold a few days; hold the index only around the turn of each month.
   - Forex (3): the 3-AI council; the registered non-AI baseline (FX-BT1); a simple currency trend rule.
7. Lock weekend (target 12 to 13 Dec): registrations merged, cutover of Atlas V2's account, record restarts once.
Done when: all 23 lines produce a number every night for 5 sessions and the four mirror twins match their real accounts within the agreed tolerance.

## Phase 2: run 2027 without touching the rules (1 Jan to 31 Dec 2027)
1. No rule changes. A changed rule is a new dated strategy with its own record.
2. Reliability fixes only, market closed, tests green.
3. Month end: freeze the numbers, copy to GitHub, one-page report (every strategy, good or bad).
4. Each quarter: live versus shadow gap for the four real bots. A growing gap means the cost model is wrong; fix the model, never the history.

## Phase 3: build the Allocator in shadow (build Jan to Mar 2027, shadow Apr to Dec 2027)
This is the "knows the regime, picks the strategy" brain. Rules first, AI second.
1. Regime label, once a day, from four plain measurements: is the S&P 500 above its long trend; how jumpy is the market; are interest rates rising or falling; are most stocks rising or only a few. Four regimes: calm up, rough up, calm down, rough down.
2. Allocation table: for each regime, a fixed share for each strategy family. Written down before it starts.
3. Hard limits the brain cannot break: no strategy above 40% of the fund; total gearing at most 1.5x; if the fund falls 15% from its high, go to cash and wait for a human.
4. Three shadow funds run side by side: (a) equal money to every strategy, (b) the rules Allocator, (c) the rules Allocator with the AI council allowed to reduce or skip.
5. "Global": start with US-listed funds that hold world shares, bonds, gold and commodities, plus currencies at OANDA. No extra brokers or exchanges until this works.
Done when: nine months of side-by-side data exist for (a), (b) and (c).

## Phase 4: decide (January 2028)
1. A strategy passes if, after costs, it matched or beat the S&P 500, or came close with a clearly smaller worst fall, and passes the luck check adjusted for 16 tries.
2. The Allocator passes only if (b) beat (a) after costs. The AI passes only if (c) beat (b) after its own bill.
3. If nothing passes: say so, and the answer is "an index fund is better". That is a valid result.
4. Passing strategies move to the real paper accounts for 3 months of confirmation.

## Phase 5: Markus's own money (from about April 2028, only if Phase 4 passed)
1. Before any money: per-bot kill switch armed; no position without a stop for more than 60 seconds; 90 clean paper days; operator login on the dashboard; database backups on.
2. Step up in three stages with a month between each: 10% of the intended amount, then 30%, then 100%. A stage is repeated, not skipped, after any incident.
3. Fund-level stop: down 15% from the high means cash and a human decision.
4. Monthly report continues unchanged. Real results are compared with the shadow of the same strategy; a widening gap pauses new money.

## Decided by Markus, 17 Nov 2026 09:17 Brisbane
1. The plan is agreed.
2. Defensive stocks replaces Atlas V2's strategy at the lock (the BTC line stays frozen as agreed earlier).
3. The lock moves to about 12 to 13 Dec so the Shadow League starts with the record.
