# DDG Finance: the thesis for 2027
## What the platform is, why it is built this way, and what its author expects. To be scored in January 2028.

Written by Claude (Fable 5.2), Sat 21 Nov 2026, about 12:30 Brisbane, at Markus's request (12:00 Brisbane). Amended about 13:30, after his questions on hedging and walk-forward (13:08, 13:14): choice 14 in Part 3, one line in 5.3, and expectations 50 to 54.

**Status: PROPOSED.** It becomes the thesis when Markus says yes (roadmap v2, decision D13). At the lock (12–13 Dec 2026) it is hashed into the lock record and never edited again. A correction after that is a dated note at the end.

**Who this is for.** Anyone who wants to look at DDG Finance properly: an investor, a risk person, a developer, or Markus a year from now. Part 0 is one page. Part 1 is a tour of what you can see. Parts 2 to 5 explain the machine, the reasons and the checks. Parts 6 to 8 are what I expect, written so it can be marked right or wrong.

**How it was made.** A read of the `quant-terminal` repository at commit `2447d4a` (21 Nov 2026), its plans, status log and research ledger, and the research in `macro-research-2026-11-21.md`. Nothing was run. The live system, database and brokers were not read.

**Marks.** BUILT = read in the code at `2447d4a`. AGREED = in the roadmap Markus agreed on 17 Nov; may not be built yet. PROPOSED = in `fund-roadmap-v2-2026-11-21.md`; waits for Markus's yes. EXPECTED = my forecast.

**Not advice.** Everything here is paper money. This is not financial advice and it promises no profit.

---

# Part 0. One page

**What DDG Finance is.** An in-house trading platform that runs on paper money only. Four real broker paper accounts trade by rule. Beside them run about two dozen pretend accounts, each following one written rule on real prices, plus funds built from them. Every decision is written to a record that cannot be quietly changed. The rules are locked in December 2026 and run untouched through all of 2027. In January 2028 one question is answered: is any of this worth real money, or is an index fund better?

**The thesis, in seven sentences.**

1. No single strategy here will beat the share market by skill, and I do not expect one to. Our own registered tests already say so.
2. The platform will work anyway, because of its method: many simple, old, well-evidenced rules, tested at once, on a record nobody can bend.
3. The thing worth owning is a fund, not a winner: lines that do not move together, sized by risk, with a hard cap on borrowing and a coded brake.
4. Prices, not opinions, decide when the fund holds shares, hard assets or cash. That needs no forecast, which matters in a decade nobody can forecast.
5. The cleverer layers (a macro label, outside views, AI) are experiments. They may reduce risk and never add it. Most likely they will not earn their place in one year, and the platform will say so.
6. Over many years I expect such a fund to keep most of the market's return with falls about half as deep. In any single year, 2027 included, it can lag badly or look brilliant by luck.
7. So the platform has two ways to succeed: a fund that passes, or an honest "no". Both are worth a year.

**What I expect of 2027, in six lines.** (Odds in Part 7.)

- The record survives the year unbroken. (85%)
- No single line passes the luck test on 2027 alone. (85%)
- The risk-balanced fund ends the year with a worst fall under 10%. (75%)
- The macro layer, the outside views and the AI each fail to beat the layer below by the agreed margin. (70% to 80% each)
- At least one fund passes every bar in January 2028. (25%)
- The most likely verdict: "nothing has passed yet; the risk-balanced fund is the one to keep testing."

**How to check me.** Part 7 is a numbered list with odds on every line. In January 2028 each is marked right or wrong from the frozen record. If I am well calibrated, about seven in ten of my 70% calls come true.

---

# Part 1. How to look at the platform

## 1.1 The dashboard, page by page

Six pages (BUILT: `artifacts/dashboard/src/pages/`, routes in `App.tsx`). Page contents below are from the code's headings at `2447d4a`; a redesign is under way.

| Page | What it shows | What a careful visitor should look for |
|---|---|---|
| **Home** (`/`) | The four real paper accounts: equity at each daily close, daily return by account, the mix of holdings, and a full text report to download | Do the lines move differently from each other? Is every figure dated? |
| **League** (`/league`) | "Every line, ranked": each real account, each pretend strategy, each yardstick and each fund. Return after costs, worst fall, days in cash, gap to the S&P 500, and a luck-check column | The yardsticks. A line that cannot beat "just hold the index" or "just hold cash" has shown nothing. Read the luck column before the return column |
| **Forex** (`/forex`) | The AI council's account: open trades, a scorecard for each AI, results by strategy and by how sure the AI said it was, its predictions against what happened, and the news it read. Headed "Does the AI add anything?" | Whether the AI's confidence means anything: do its "very sure" calls do better than its "unsure" ones? |
| **Strategy Bench** (`/bench`) | The research record: newest verdicts, return for risk against worst fall, and the exploration runs | Failed tests are shown, not hidden. Three of the four held-out tests failed their own bars (Part 5) |
| **Controls** (`/controls`) | Bots (pause and resume), drawdown limits, broker connections, and a "Needs you" list | What is waiting on a human. Whether limits are enforced or only reported |
| **Me** (`/me`) | Markus's own pretend account: place a trade with a written reason, holdings, trade log, "Me vs the machines", and the locked predictions for 2027 | A human, the rules and the AIs are scored the same way, on the same record |

PROPOSED additions (roadmap v2): a Macro card and a "Long view" card on the League page, seven funds instead of two, and results also shown in Australian dollars and after inflation.

## 1.2 The documents, in reading order

All in `docs/plans/` of the repository.

1. **This file.** What, why, and what to expect.
2. `fund-roadmap-2026-11-17.md`. The plan Markus agreed: the phases from today to real money.
3. `fund-roadmap-v2-2026-11-21.md`. PROPOSED changes: the macro-led fund, with build orders.
4. `macro-research-2026-11-21.md`. The research behind the macro view. Background only.
5. `finance-2027-plan.md`. The status log. Its last entry is the live state.
6. `order-path-audit-2026-11-16.md`. Every way an order can be placed, and what could go wrong.
7. The registrations: `forex-council-2027-registration.md`, `ai-twins-2027-registration.md`, and one file per strategy in `research_harness/registrations/`.

---

# Part 2. What the machine is

## 2.1 Four real paper accounts (BUILT)

Three Alpaca paper accounts and one OANDA practice account. No real money anywhere.

| Account | Name | Rule today | At the lock |
|---|---|---|---|
| `oracle` | Atlas | 65% share trend (S&P 500 and Nasdaq, up to 1.5 times), 35% trend on bonds, gold, commodities and the dollar | Unchanged |
| `jerome_macro` | Atlas V2 | Share trend alone, up to 1.5 times | AGREED: Defensive stocks. PROPOSED (D2): the cross-asset trend rule alone |
| `spy_qqq_trend` | Momentum | The 50 S&P 500 shares that rose most over the past year, monthly, with a trend brake | AGREED: weekly re-entry and a 25% cap on any one sector |
| `forex_ai` | Forex | Three AI models vote once a day on seven currency pairs. Rules set the size and the stop | Unchanged |

No crypto, on any account, ever. Buys are refused in code.

## 2.2 The pretend accounts, called twins (BUILT)

A twin is a list of decisions ("hold these weights from tomorrow") replayed on real prices by one engine. It places no orders.

- **Mirror twins.** Each real account's own holdings, fed through the engine. If the mirror tracks the real account, the engine is telling the truth. This is the platform's most important self-check.
- **Baseline twins.** The same assets held fully invested, and plain S&P 500.
- **League shadows.** 17 strategies, one rule each: four trend lines (1, 1.5 and 2 times, and today's Atlas), four share-picking lines, three diversifiers (cross-asset trend, gold trend, risk-balanced mix), two short-term lines, four currency lines.
- **Yardsticks.** S&P 500 held, 60/40 held, cash.
- **Funds.** (a) equal money in every line. (b) a rules "Allocator" that shifts between families by a four-way market mood label.
- **AI twins.** The AI council choosing the holdings of each share account; and "AI may reduce or skip" twins of three league lines.
- **Markus's own account.** Him against the rules and the AIs.
- **Predictions.** Markus and each AI lock a written view and numbers for 2027 before the year starts.

PROPOSED in roadmap v2: five more lines (oil trend, a hard-assets basket, world share trend, currency carry, and inflation-linked bonds on a trend rule), five more yardsticks (a managed-futures fund, a four-way permanent mix, gold held, inflation-linked bonds held, and shares with bought insurance), and five more funds: (r) equal risk, (m) macro label, (v) outside views, (c) AI, and (w) a walk-forward rule with the AI's powers and no AI.

## 2.3 The research harness (BUILT)

Where a rule is tested before it is allowed near an account (`research_harness/`).

- A rule is **registered** first: its exact rules, data, costs and pass bars are committed before the test runs.
- Price data from 2021 onward is **locked**. A registration gets one read of it. One shot.
- Every result goes in a **ledger**, pass or fail. Explorations go in a separate log.
- A **luck check** asks: given how many things we tried, could this result be chance?

## 2.4 What happens each day (BUILT)

- Every hour: the real bots run their cycle on the one published runner. The Forex mirror reads the real positions.
- After the US close: each real account is read; every strategy is asked what it would hold; every twin is replayed from its start; mirrors are compared with real accounts; the decision record's hash chain is re-checked; real fills are measured for cost.
- Each morning (Brisbane): one health message.
- Month end: every twin's month is frozen once, a one-page report is written, and a copy can go off-site.
- A new version reaches the live system only while the US market is closed, with read-only checks before and after.

---

# Part 3. Why it is built this way

Each choice, the reason, and the evidence.

**1. Paper first, for a full year, with the rules locked.** A rule changed in mid-year has no record. One year is not proof, but a year with moving rules is not even evidence. (AGREED.)

**2. Write the test down before running it.** Most back-tests that look good were tuned until they did. Registration and the one-shot hold-out stop us fooling ourselves. The cost is real: three of our four held-out tests failed bars we set ourselves (Part 5). That is the system working.

**3. Count the tries.** With 17 strategies, one will look brilliant by luck. The luck check (a deflated Sharpe ratio of at least 0.95, at least 60 days, counted against 17 tries) is on the leaderboard. On one year of data a line would need a return-for-risk of about 2.5 to clear it. Almost nothing real does. That is why roadmap v2 judges on a replay of history plus 2027, not on 2027 alone.

**4. One engine for everything, and mirrors to prove it.** Back-tests, shadows, AI twins and Markus's account all go through the same simulator with the same costs and stops. An error hits every side alike, and the mirror twins show whether the engine matches a real broker.

**5. A record nobody can bend.** Decisions are append-only, enforced by the database, and each row carries the hash of the one before. Months are frozen once. If later price revisions change a frozen month by more than 0.1 points, an alarm says so and the frozen row stays.

**6. A fund, not a winner.** Picking the best of two dozen lines after one year picks mostly luck. Mixing lines that do not move together raises return for risk without needing any line to be special. Six lines that truly move independently are worth more than one line twice as good. (PROPOSED as the decision rule; the fund machinery for (a) and (b) is BUILT.)

**7. Trend rules at the core.** The one family of rules with evidence in every decade since 1880, across 67 markets, and in 8 of the 10 worst stretches for a 60/40 portfolio (research file, 4.7). A trend rule needs no view on what kind of decade this is. This month it is out of gold and cutting shares without anyone deciding to.

**8. More than shares.** Bonds, gold, commodities, the dollar and currencies sit beside shares, because each era of the last hundred years rewarded something different (research file, 4.8). PROPOSED: a hard-assets bucket and a macro label, read from market prices only, that sets how much room each kind of asset gets. Also PROPOSED (D14): inflation-linked bonds, and a defensive bucket made only of lines that can step aside into cash.

**9. Layers, measured one at a time.** Rules first. Then a macro label. Then outside views (Gromen, Bianco, Markus). Then AI. Each layer is its own fund, compared with the fund below it, so we learn which layer earned its keep. (PROPOSED.)

**10. AI and views may only reduce or skip.** They cannot place an order, add borrowing, move a stop or clear a pause. An AI that can only say "less" can cost return but cannot blow up the account. (AGREED.)

**11. Limits the clever parts cannot override.** No line above 40% of a fund. Total exposure at most 1.5 times. A fund that falls 15% from its high goes to cash. Stops on every holding except the trend lines whose monthly call is the exit. Fleet drawdown limits at 15% (no new risk) and 22% (hard). (BUILT, except where Part 5 says otherwise.)

**12. Cheap on purpose.** No new accounts, no paid data, free AI tiers, a US$10 a month cap on AI twins. If it only works with expensive inputs, it does not work for the purpose.

**13. The long view as context only.** The platform records the slow gauges of debt, money and conflict, and tests its rules in other eras. No rule reads them. (PROPOSED.)

**14. Protection has a price, so the price is shown. And the AI gets a rule-based rival.** The fund protects itself in four ways that need no forecast: it spreads risk across unlike assets, its rules step aside into cash, opinions and AI are capped, and a brake stops a long fall. Each gives up some return in a good year. It does not buy insurance (put options), because the published tests say that has cost more than it saved. PROPOSED (D15): a table of what each protection cost and saved, beside a yardstick that does buy insurance. PROPOSED (D16): fund (w), a walk-forward rule with exactly the AI's powers over the fund, so the AI has to beat a short rule and not only doing nothing. A walk-forward rule re-fits the fund's weights from a rolling window of its own recent results; unlike an AI it can be replayed on history.

---

# Part 4. The checks

| # | Check | What it guards against | Where | State |
|---|---|---|---|---|
| 1 | Registration before any held-out test | Tuning to the answer | `research_harness/harness/registry.py`, `registrations/` | BUILT |
| 2 | Data from 2021 locked; one read per registration | Peeking | `research_harness/harness/holdout.py` | BUILT |
| 3 | Ledger of every result | Burying failures | `research_harness/ledger.jsonl`, `exploration_log.jsonl` | BUILT |
| 4 | Luck check | Mistaking chance for skill | `harness/overfit.py`; `twins/leaderboard.py` (`N_TRIALS = 17`, `MIN_LUCK_DAYS = 60`, `LUCK_CLEAR = 0.95`) | BUILT |
| 5 | One simulator for back-tests and twins | Two engines disagreeing | `harness/portfolio.py` (`simulate`), `twins/engine.py` | BUILT |
| 6 | Mirror twin against real account | An engine that flatters | `twins/job.py`, `MIRROR_GUARD_PP = 1.0` (provisional) | BUILT |
| 7 | Append-only decisions with a hash chain, re-checked nightly | Rewriting history | `twins/store.py` (`verify_chain`) | BUILT |
| 8 | Month-end freeze, drift alarm, off-site copy | Quiet revisions | `twins/month_end.py` | BUILT |
| 9 | Trading cost measured from real fills | A cost model that is too kind | `core/slippage_job.py` | BUILT |
| 10 | A stop on every holding, with named exceptions | An unprotected position | `core/stop_policy.py` | BUILT |
| 11 | Drawdown limits, enforced | A slow bleed | `core/risk_limits.py` (`SOFT_DRAWDOWN = 0.15`, `HARD_DRAWDOWN = 0.22`), `core/risk_governor.py` | BUILT |
| 12 | Kill switch: pauses bots on a confirmed fault; never sells | A fault that keeps trading | `core/kill_switch.py` | BUILT, **not armed** (report-only) |
| 13 | One flag that stops all new entries | Needing many buttons in a crisis | `core/fleet_halt.py` | BUILT |
| 14 | No crypto, refused at the lowest level | A rule that is only a promise | `core/no_crypto.py`, `core/broker_http.py` | BUILT |
| 15 | Time limit on every broker call | A hung connection stalling a bot | `core/broker_http.py` | BUILT |
| 16 | Order watchdog | Runaway ordering | `core/order_watchdog.py` | BUILT |
| 17 | Standing checks and a daily health message | Faults nobody notices | `core/invariants.py`, `core/daily_health.py` | BUILT |
| 18 | Outside heartbeat | The whole platform going silent | `core/outside_heartbeat.py` | BUILT, **waiting for the monitor address** |
| 19 | One runner per bot | Two copies trading one account | `core/runner_lock.py` | BUILT |
| 20 | Pretend accounts cannot reach the order path | A twin placing an order | `trading-platform/tests/test_twins_isolation.py` | BUILT |
| 21 | Tests on every change | Regressions | `.github/workflows/tests.yml`; 1,138 and 293 tests passing on 19 Nov (status log) | BUILT |
| 22 | Publish only with the US market closed | Breaking a bot in mid-session | Process rule, `docs/plans/README.md` | In use |
| 23 | Order-path audit | Unknown ways to place an order | `order-path-audit-2026-11-16.md` | Done 16 Nov; fixes merged since |
| 24 | AI cost cap; AI off-switch for Forex | A runaway bill; a misbehaving model | `twins/ai_council.py` (`MONTHLY_CAP_USD = 10.0`), `core/forex_ai_kill.py` | BUILT |
| 25 | Fund limits | A fund concentrating or gearing up | `research_harness/league/allocator.py` (`LINE_CAP = 0.40`, `MAX_EXPOSURE = 1.5`, `STOP_FALL = 0.15`) | BUILT |
| 26 | Predictions locked before the year | Hindsight | `twins/predictions.py` (`LOCK_AT` 1 Jan 2027) | BUILT |
| 27 | Five quiet sessions before the lock (the gate) | Locking a broken engine | Roadmap Phase 0 | Planned 7–11 Dec |

---

# Part 5. The honest numbers so far

## 5.1 Our registered tests (BUILT: `research_harness/ledger.jsonl`)

| Test | Dates | Result after costs | S&P 500, same dates | Verdict |
|---|---|---|---|---|
| FLEET-V1-F1 (today's Atlas) | 2011–2020 | 8.59% a year, worst fall −15.7%, Sharpe 0.77 | 13.65% a year, −33.7%, 0.80 | **Failed** 2 of 5 bars |
| GEAR-V1-G4 | 2021–Oct 2026 | 18.05% a year, −24.5%, 0.76 | 15.18%, −24.5%, 0.74 | **Failed** (fall not smaller) |
| GEAR-V2 | held-out | — | — | **Failed** 2 bars |
| TREND-V1-B | 2021–Oct 2026 | 3.59% a year, −7.4%, Sharpe 0.07 | — | First bar passed, second pending |
| FX-BT1 (currency trend baseline) | 2008–2026 | −1.08% a year, −33.9% | — | Replication; it lost money |

In plain words: our share-trend strategies gave about the market's return for the risk taken, with smaller falls. None beat the market outright. The currency baseline lost money over 18 years.

## 5.2 What has gone wrong, and was found

- 14–21 Oct 2026: a loop of repeated orders on a paper account that no other check saw. The order watchdog exists because of it.
- 16 Nov: the order-path audit found five faults, one of which could send an order twice after a broker timeout.
- 19–20 Nov, the first league night: one strategy made no decision because a data file had no sector column, and the Forex mirror had been failing for three nights on a wrong pair name. Fixes for both were merged the next day.

## 5.3 What is not done on 21 Nov 2026

- The kill switch is not armed.
- The outside heartbeat has no monitor address yet.
- The gate and the lock have not happened. Everything in the league so far is a proving run, not the record.
- The strategies have never been replayed on history as a set (roadmap v2, V2-02).
- Nothing in roadmap v2 is built: no macro label, no funds (r), (m), (v), (c), no outside views.
- A secret for the trading interface was found inside the dashboard's public code on 20 Nov. UNKNOWN whether it is fixed. It must be before any public dashboard.
- An old nightly check called "walk-forward validation" still grades the three share accounts against reference numbers set in July and August, for strategies they no longer run. Its grades say nothing about today's strategies (roadmap v2, D17).
- All fills are simulated or on paper accounts. Real money will fill worse.

---

# Part 6. What I expect, and why

## 6.1 The thesis

DDG Finance will not win 2027 by out-guessing markets. I do not expect any single strategy on it to beat the S&P 500 by skill. It will work because of how it is built. It tests many simple, old rules at once on a record nobody can bend. It sizes by risk. It lets prices, not opinions, decide when to hold shares, hard assets or cash. And it adds the cleverer layers only as measured experiments that can reduce risk and never add it.

A platform like that pays in one of two ways. Either it finds a fund that keeps most of the market's return with much smaller falls across very different kinds of year. Or it gives a truthful "no" before any real money is lost. In the kind of decade the research file describes, where shares start from a very high price, bonds no longer cushion them and inflation is unsettled, the first is worth more than usual.

## 6.2 Why I think this is the best available way

Against the four alternatives a person in Markus's position has:

- **Pick the best back-test and trade it.** This is how most private trading systems die. Our own ledger shows what honest testing does to good-looking back-tests.
- **Follow a macro view, mine included.** The research file's Part 5 is the answer: nobody times it. Markus's view on shares is playing out this month; his view on gold is down a third from its peak. A view can be right about the decade and ruinous for the year.
- **Let an AI trade.** No evidence yet that it adds anything after its cost, here or anywhere I know of. The platform is one of the few places that will measure it cleanly: against doing nothing and, if D16 is agreed, against a short rule with the same powers.
- **Buy an index fund.** The benchmark to beat, and still the answer if nothing passes. Its weakness is the one this platform is built around: falls of a third to a half, which the 2020s can easily deliver from here.

"Best" does not mean highest return. It means the highest chance of ending 2027 knowing something true, and of still having the capital when the era changes.

## 6.3 The numbers I expect

**Over many years** (the claim one year cannot settle): a risk-balanced fund of these lines earns cash plus 3 to 5 points a year after costs, with worst falls of 10% to 15%, and a return-for-risk (Sharpe) of 0.5 to 0.8. The S&P 500's own long-run figure is about 0.4 to 0.5 with falls of 30% to 50% (general knowledge; over 2011 to 2026 our ledger has it at 0.7 to 0.8, an unusually kind stretch).

**In 2027**, from the first session (4 Jan) to the last. Each range is where I expect the result to land eight times in ten.

| What | Middle guess | Eight-in-ten range |
|---|---|---|
| S&P 500 held (Y-SPX), return with dividends | +3% | −22% to +24% |
| Fund (a), equal money | +3% | −12% to +18% |
| Fund (r), equal risk | +5% | −5% to +14% |
| Fund (r), worst fall | 6% | 3% to 11% |
| Atlas real account | +4% | −14% to +22% |
| Forex AI real account | 0% | −8% to +8% |

Why the middle guesses are modest: cash pays about 4%; the year starts with a central bank raising rates into an oil shock; and trend rules lose a little every time a market turns sharply, which 2027 is likely to do more than once.

---

# Part 7. Expectations to score

**Rules for scoring.**
- Counted dates: the first US session of 2027 (Mon 4 Jan) to the close on Fri 31 Dec 2027, unless a line or fund starts later; then from its start.
- Source: the frozen month-end record, the leaderboard at 31 Dec 2027, and the decision and alarm logs.
- Each line is right (1) or wrong (0). A line is void if the thing it needs was never built or cannot be measured. Void lines are listed, not counted.
- Score: the average of (my odds − outcome)² over the counted lines. Always answering "50%" scores 0.25. Lower is better.
- Nothing here is re-worded after the lock.

## A. The record and the engine

| # | Expectation | Odds |
|---|---|---|
| 1 | The nightly hash check finds no broken link on any night of 2027 | 85% |
| 2 | At least 240 US sessions have a complete league night (every line has a decision, or a missed entry with a reason) | 75% |
| 3 | All 12 month-end freezes and reports exist by the fifth session of the next month | 70% |
| 4 | At 31 Dec, at least three of the four mirror twins are within 2.0 points of their real account's return since their start | 65% |
| 5 | No "must never happen" event on a real paper account: an order sent twice, an order while paused, a crypto buy sent, or a position without a stop for more than 15 minutes with no alarm | 55% |
| 6 | The year's whole AI bill (council, AI twins, view cards) is under US$250 | 85% |
| 7 | No version-1 registration file is edited during 2027 | 80% |

## B. Single lines

| # | Expectation | Odds |
|---|---|---|
| 8 | No shadow line shows "clear" on the luck check at 31 Dec | 85% |
| 9 | The best and worst rule lines end more than 30 points apart | 75% |
| 10 | T-1X's worst fall is smaller than Y-SPX's | 70% |
| 11 | T-2X's worst fall is larger than Y-SPX's | 60% |
| 12 | FX-BT1 returns less than cash (Y-CASH) | 70% |
| 13 | The Forex AI real account ends above zero after costs | 40% |
| 14 | The Forex AI real account beats FX-BT1 | 50% |
| 15 | Equal-weight S&P 500 (S-EQW) beats Y-SPX | 60% |
| 16 | D-XTREND "adds to the fund": fund (a) has a higher Sharpe with it than without | 65% |
| 17 | The Momentum real account trails Y-SPX | 55% |
| 18 | The Atlas real account's worst fall is smaller than Y-SPX's | 70% |

## C. Funds

| # | Expectation | Odds |
|---|---|---|
| 19 | Fund (r)'s worst fall is under 10% | 75% |
| 20 | Fund (r)'s Sharpe is higher than fund (a)'s | 60% |
| 21 | Fund (r) beats cash | 60% |
| 22 | Fund (r) beats the better of Y-6040 and Y-PERM | 40% |
| 23 | Fund (r) beats Y-SPX, or comes within 2 points of it with a worst fall at least one third smaller | 55% |
| 24 | Fund (b) beats fund (a) by at least 1 point (the agreed Allocator test) | 30% |
| 25 | Fund (m) beats fund (r) by at least 1 point | 30% |
| 26 | At least one fund passes every bar of the January 2028 rule (roadmap v2, section 8) | 25% |

## D. Views and AI

| # | Expectation | Odds |
|---|---|---|
| 27 | Fund (v) beats fund (m) by at least 1 point over its counted dates | 20% |
| 28 | Fund (c) beats fund (m) by at least 1 point after its AI bill | 20% |
| 29 | At least two of the three "AI may reduce or skip" twins end with a smaller worst fall than their base line | 65% |
| 30 | At least two of those three end with a lower return than their base line | 60% |
| 31 | At least two of the three AI twins of the share accounts end behind their bot's mirror twin | 60% |
| 32 | Bianco's share of scored cards that were right is higher than Gromen's (void under 20 scored cards each) | 55% |

## E. Human and machine

| # | Expectation | Odds |
|---|---|---|
| 33 | Markus's own account beats fund (a) | 45% |
| 34 | Markus scores more direction points than I do on the 2027 predictions (table F) | 50% |

## F. The year itself

My entry in the platform's own prediction format (`twins/predictions.py`): change from the 31 Dec 2026 close to the 31 Dec 2027 close. "Flat" means within 2% either way, so "up" and "down" each need a move of more than 2%. The odds in the table are the odds of that. They are therefore a few points lower than the plain "higher or lower" odds in the research file (6.5): shares ending 2027 higher at all is 52% there; higher by more than 2% is 48% here. Roadmap order V2-23 files this table under the author "Fable 5.2" before the lock, so it is scored by the same rule as Markus and the three AIs.

| Market | Direction | Change | My odds on that direction |
|---|---|---|---|
| US shares (SPY) | up | +4% | 48% |
| US tech (QQQ) | down | −4% | 50% |
| 7–10 year Treasuries (IEF) | up | +6% | 72% |
| Gold (GLD) | up | +6% | 55% |
| Broad commodities (DBC) | down | −5% | 52% |
| US dollar (UUP) | down | −3% | 45% |
| EUR/USD | up | +3% | 48% |
| USD/JPY | down | −6% | 58% |
| AUD/USD | up | +3% | 42% |

| US number | My figure |
|---|---|
| Consumer price inflation, Dec 2026 to Dec 2027 | 3.4% |
| Central bank rate, upper bound, 31 Dec 2027 | 4.00% |
| Unemployment, Dec 2027 | 4.6% |

The thesis in words, for the same record: *2027 starts with a central bank raising rates into an oil shock, shares in a correction from a very high price, and gold a third below its peak. Tight money most likely breaks something or inflation eases before the year is out, so bonds are the likeliest winner, the dollar gives back some ground, and shares are a coin toss. The long-run pressure toward cheaper money is real but I do not expect it to dominate 2027.*

Low confidence. Most of these directions are barely better than a coin. That is itself part of the thesis: the fund is built not to need them.

| # | Expectation | Odds |
|---|---|---|
| 35 | The macro label (V2-06) reads "stagflation" or "bust" on more than half of 2027's sessions | 55% |
| 36 | The central bank's upper rate bound at 31 Dec 2027 is lower than at 31 Dec 2026 | 55% |
| 37 | Consumer price inflation, Dec to Dec, is above 3.0% | 58% |
| 38 | The S&P 500's worst fall inside 2027, on closing prices, is more than 10% | 65% |
| 39 | Gold (GLD) beats US shares (SPY) | 53% |
| 40 | Treasuries (IEF) beat cash (BIL) | 65% |

## G. Other eras

Scored when roadmap orders V2-02, V2-20 and V2-21 report. Void if not run.

| # | Expectation | Odds |
|---|---|---|
| 41 | Replay to 2020 (V2-02): fund (r)'s Sharpe is between 0.4 and 1.0 | 70% |
| 42 | Replay to 2020: fund (r)'s worst fall is under 20% | 65% |
| 43 | US 1929–32 (V2-20): the share-trend rule's worst fall is less than half of buy-and-hold's | 75% |
| 44 | US 1966–82 (V2-20): the share-trend rule returns less than 3% a year after inflation. It does not rescue the era | 65% |
| 45 | Japan 1990–2012 (V2-20): the rule's worst fall is less than half the index's | 75% |
| 46 | Monthly test (V2-21): the share-trend rule trails buy-and-hold in both 1950–65 and 1983–99 | 85% |
| 47 | Monthly test, 1966–82: fund (r) beats the share-trend rule alone by more than 2 points a year after inflation. The hard-assets bucket earns its place | 70% |
| 48 | Monthly test: fund (r) has a positive return after inflation in all five eras | 50% |

## H. One from the research

The research file's least fashionable point (its 6.3, point 5) is that for the fear of inflation, a bond linked to inflation may be cheaper protection today than gold. Void if the two yardsticks are not built (roadmap D12, D14).

| # | Expectation | Odds |
|---|---|---|
| 49 | Inflation-linked Treasuries held (Y-TIPS) beat gold held (Y-GOLD) over 2027 | 54% |

## I. Hedges, and the AI's rule-based rival

Added 21 Nov, 13:30. Void where the thing was not built (roadmap D15 for lines 50 and 51, D16 for 52 to 54). Line 54 is scored when roadmap order V2-02 reports.

| # | Expectation | Odds |
|---|---|---|
| 50 | Bought insurance does not pay for itself: Y-INS (90% shares, 10% a fund that buys put options) ends 2027 behind Y-SPX | 57% |
| 51 | It also protects less than it promises: Y-INS's worst fall is less than a quarter smaller than Y-SPX's | 80% |
| 52 | Fund (w), the walk-forward rule, beats fund (m) by at least 1 point over its counted dates | 20% |
| 53 | Fund (w) ends ahead of fund (c), the AI, over the dates both ran | 55% |
| 54 | Replay to 2020: fund (w)'s worst fall is smaller than fund (m)'s and its return a year is lower. Re-fitting buys safety and pays for it | 55% |

---

# Part 8. What would prove me wrong

The thesis is not "the fund will make money in 2027". It is these four claims. Each has a result that would break it.

| Claim | Broken if |
|---|---|
| **The record can be trusted** | A hash break that cannot be explained; mirrors drifting more than 5 points from their real accounts; a registration edited in mid-year. Then nothing else in 2027 counts, and the fix comes before any other question |
| **A risk-balanced fund of these lines keeps falls small** | Fund (r) falls more than 15% in 2027, or the replay shows a worst fall above 30%. Then the sizing, the brake or the lines are wrong, and no fund goes forward |
| **Mixing beats picking** | The best single line beats fund (r) in the replay and in 2027 and clears the luck check on both together. Then I was wrong about skill, and that line deserves its own real test |
| **The clever layers do not yet earn their place** | Fund (m), (v), (c) or (w) beats its base by the agreed margin in 2027 and is not worse in the replay. Then I was too sceptical, and the layer is promoted exactly as the rule says |

And one result that would be a failure of the whole idea: funds (a) and (r) both trail the S&P 500 and the 60/40 mix, with falls that are not smaller, in the replay and in 2027. Then the answer is the index fund, and the platform has done its job by saying so.

---

# Part 9. Known weaknesses

Said plainly, so nobody finds them later and feels misled.

1. **Paper is not money.** Simulated fills, no market impact, no emotion. The first real dollar will behave differently.
2. **One year is short.** 2027 will be one kind of year. Most of Part 7 section C is close to a coin toss for that reason.
3. **The lines are cousins.** Several share one trend rule on overlapping assets. The fund has fewer truly independent parts than its line count suggests. Roadmap v2 adds a measure of this.
4. **Everything is American.** US-listed funds, US brokers, US dollars, read by an Australian.
5. **The AI models are free tiers** that can be withdrawn or changed by their makers. A model that changes in mid-year is a new version with a shorter record.
6. **The currency side is the weakest.** Its baseline lost money over 18 years. It is here to be measured, not because I expect it to pay.
7. **Our history is short.** Rebuilt prices start in 1985. The other-eras tests (V2-20, V2-21) are there to fix that, on rougher data.
8. **One builder, one reviewer.** Opus builds, Markus merges, I review now and then. There is no second human.
9. **I am an AI writing a thesis about a platform that tests AI.** I have tried to lean against it: my odds on the AI layers are 20%.
10. **My own forecasts.** I have no record at this. Part 7 exists so that in a year there is one.

---

# Part 10. Plain-word glossary

- **Line.** One strategy following one written rule in a pretend account.
- **Twin.** A pretend account: a list of decisions replayed on real prices. No orders.
- **Mirror twin.** A twin that copies a real account's holdings, to prove the engine.
- **Yardstick.** Something simple to beat: the index, a 60/40 mix, cash, gold.
- **Fund.** A mix of lines by a written rule.
- **Trend rule.** Hold a thing while its price is above where it was 3, 6 and 12 months ago; otherwise hold cash.
- **Worst fall.** The largest drop from a high to a later low.
- **Sharpe.** Return above cash divided by how bumpy the ride was. Higher is better. The share market's own long-run figure is about 0.4 to 0.5.
- **Luck check.** A test of whether a result could be chance, given how many things were tried.
- **Hold-out.** Price history set aside and read only once, for the final test.
- **Registration.** The rules, data and pass bars of a test, written down before it runs.
- **The lock.** The weekend (12–13 Dec 2026) after which no rule changes.
- **Intake.** One weekend a quarter when a new idea may join, as a new dated line.
- **The gate.** Five US sessions with no incident and nothing merged, before the lock.
- **Macro label.** A four-way reading of market prices: growth up or down, inflation up or down.
- **Walk-forward.** A rule that re-fits itself on a rolling window of recent results and is judged on the days that follow.
- **Bought insurance.** Put options: contracts that pay when shares fall. The premium is paid whether or not they do.

---

# Part 11. Limits and sources

**Limits.** Nothing was run. The live system, the database and the brokers were not read. Page contents in Part 1 come from code headings, not from using the dashboard. Everything marked PROPOSED depends on Markus's yes to roadmap v2 and may never be built; the Part 7 lines that need it are then void. The repository was being changed by another agent while this was written; main may be past `2447d4a`.

**Sources.** The repository at `2447d4a`: `docs/plans/README.md`, `fund-roadmap-2026-11-17.md`, `finance-2027-plan.md`, `order-path-audit-2026-11-16.md`, the two registration files, `research_harness/ledger.jsonl`, and the code files named in Part 4. For the macro view and every outside number: `macro-research-2026-11-21.md`, Part 9. For hedging and walk-forward: `fund-roadmap-v2-2026-11-21.md`, section 2.5 and its sources in section 11.
