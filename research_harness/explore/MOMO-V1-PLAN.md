# MOMO-V1 plan: regime-gated single-stock momentum (declared before any new run)

Written by Claude (Fable 5.1), Mon 2 Nov 2026 ~17:20 Brisbane, at Markus's
instruction: three accounts, three strategies, compared on paper through
2027, then a real-money decision. No MOMO-V1 code exists when this is committed.

## Why this exists
- Markus (2 Nov 2026): the platform must hold individual stocks. A fleet that
  cannot own a Nvidia, Meta or Intel in a run like 2023-25 leaves return on
  the table. Required: higher return than FLEET-V1-F1, with worst falls kept
  near half the S&P 500's.
- The platform's own record (research ledger, experiments 18 and 19,
  universe 2019-02..2026-07): 12-1 momentum, top 20 of the largest 500,
  monthly, equal weight: +322% vs about +150% for the S&P, Sharpe 0.70,
  **max drawdown -72%**. With a 200-day S&P regime filter: +209%, Sharpe
  0.89, max drawdown -34% (equal to the S&P's in that window). Both failed
  their own bars on drawdown. Stock momentum buys return and pays in drawdown.
- The literature: cross-sectional momentum (Jegadeesh & Titman 1993) is the
  most robust return anomaly on record (US 1927-, 40+ countries), with a
  known failure mode: momentum crashes in sharp rebounds after bear markets
  (Daniel & Moskowitz 2016). Volatility-managed momentum roughly doubles its
  Sharpe (Barroso & Santa-Clara 2015). MOMO-V1 is that paper's idea with the
  platform's existing dial.

## Honesty notes (read before any result)
- **Hindsight.** The AI run is known; so is every year of the only clean data
  (2018-2026). The designer has seen it all. The historical test below is
  therefore a sanity check, not evidence. **The test that counts is the
  forward paper record, 2027.**
- **Attempt count.** Stock-momentum attempts on this platform before this
  plan: at least 6 (experiments 14-19 and the 64-run sweep of 3 Sep 2026,
  void but run). MOMO-V1 adds 2 candidates: N = 8 for the deflated Sharpe.
- **Data.** Free, survivorship-aware daily stock history exists on this
  platform only from 2018-01 (the rank-500 point-in-time panel in the
  research database, `bot2_mechanical_assets` + price table, with its
  parity gate). Nothing before. So: 7.5 years, one bear (2022), one crash
  (2020). Any claim about 2000-02 or 2008 is a literature claim, not ours.
- **Where the return comes from.** The momentum premium (owning what has
  been rising), concentrated in 20 names. The dial exists so that
  concentration cannot ride a bear market down.
- **What is new vs experiment 19.** Experiment 19 gated on the S&P's
  200-day average (binary). MOMO-V1 uses FLEET-V1's dial (3 trend votes x
  20-day volatility scale), copied unchanged, because it is already
  declared, tested on 40 years of index data, and reacts to volatility
  within days, which a 200-day average cannot. No new parameter is introduced.

## The strategy (all values fixed now)
Signal read at the close; trades at the next open.

1. **Universe.** The 500 largest US common stocks by dollar volume over the
   last 60 sessions, rebuilt point-in-time each month from the research
   panel (as experiments 18-19 did); price >= $5; at least 252 sessions of
   history. ETFs, ADRs, preferreds and units are excluded as the panel's
   screen already does.
2. **Ranking.** 12-1 momentum: close 21 sessions ago divided by close 252
   sessions ago, minus 1. Top **20** by rank, **equal weight** (1/20 each
   of the invested amount).
3. **Exposure dial (copied from FLEET-V1 sleeve 1, unchanged).** On the
   S&P 500 total-return series: votes v = number of {63, 126, 252}-session
   look-backs with the close above its past close; s = min(1, 0.15 /
   vol20). Book exposure **E = (v/3) x s, capped at 1.0**. E < 0.10 -> the
   whole book is sold to cash (SGOV). No leverage in the stock book, ever.
4. **Rebalance.** The 20 names are re-ranked at the first session close of
   each month. E is re-read daily; the book is resized when the vote count
   changes or at the month start (as FLEET-V1), not on volatility alone.
5. **Stops.** 20% below the rebalance reference price on every name, re-set
   at each rebalance (platform standing rule). A stopped name stays in cash
   until the next monthly ranking.
6. **Cash.** SGOV.

## Candidates (complete; nothing may be added after seeing results)
| id | what |
|---|---|
| M1 | As above: top 20, dial E = (v/3) x s |
| M2 | As above, but the dial can gear: E = 1.5 x (v/3) x s capped at 1.5, the part above 1.0 held as SSO (S&P 2x), never as stocks (tests Markus's "a little more leverage" in the only safe place for it) |

Reported alongside, never selectable:
| id | control or null |
|---|---|
| B | S&P 500 TR buy-and-hold |
| X18 | Experiment 18 rules (no dial) on the same panel and window |
| R | Random-20 null: 20 names drawn at random from the universe each month, same dial, 500 draws; 95th percentile of Sharpe |
| F1 | FLEET-V1-F1 on the same window, from its own code (the thing MOMO must beat on return) |

## Data
- Stocks: the research database's rank-500 point-in-time panel (daily OHLCV,
  2018-01-01 to the latest complete month), pulled once into an immutable
  harness dataset with its manifest hash, by the harness fetch command the
  build adds. The universe parity gate must be PASS at pull time.
- S&P 500 TR, SGOV/T-bill: FLEET-V1's datasets (`fleet_etf_y` SPY adjusted,
  `fleet_rates_fred` DTB3).
- Costs: 5 bp per trade on every stock and SPY/SSO (2 half-spread + 3
  slippage; large caps), 10 bp on SSO; SEC fee 0.3 bp on sales; cash
  DTB3 - 0.50%. Whole shares.

## Windows
- Warm-up 2018-01-01..2019-01-31. **Exploration 2019-02-01..2024-12-31.**
  **Held-out 2025-01-01..2026-10-31** (22 months; weak, and already seen by
  the designer; declared anyway so the number is at least computed once,
  under the lock).
- **The real test: forward paper, 2027-01-01..2027-12-31**, judged at year
  end against B and the other two accounts on the same days.

## Selection (exploration)
Among M1, M2 satisfying ALL of: (a) CAGR >= B's + 2 points; (b) max drawdown
no worse than -25% and no worse than 0.75 x B's; (c) Sharpe above R's 95th
percentile; (d) Sharpe >= X18's (the dial must not destroy the premium):
the higher CAGR. Ties within 1 point go to M1 (no gearing). None qualifies ->
MOMO-V1 FAILED; nothing registered; no variant tried.

## Pass bar (held-out 2025-26, and again for the 2027 paper year)
1. CAGR >= B's + 2 points. 2. Max drawdown no worse than -25% and no worse
than 0.75 x B's. 3. Deflated Sharpe > 0.90 with N = 8 (the window is short;
0.95 is not reachable on 22 months and saying otherwise would be theatre).
4. Turnover and costs reported; a fail is reported as a fail.

## Live (Alpaca paper, Momentum's account, from merge)
Same executor as FLEET-V1 (whole shares, stops, SGOV parking, the 15%/22%
account governor). Bars: Alpaca daily, adjusted. Universe: Alpaca's asset
list filtered to tradable US common stocks, ranked by 60-session dollar
volume from Alpaca bars (the live stand-in for the research panel; the two
are compared monthly in the shadow log). Orders: market at the first hourly
cycle after the signal day. Forward shadow of the research rules from day 1.

## Process
1. Fable: this plan (now). 2. Opus: harness dataset pull from the research
panel (on Replit), `sleeves/momo_v1.py`, `explore/momo_v1.py`, tests
(no look-ahead, universe point-in-time, equal weight, dial parity with
core_v1, stops). 3. Fable: review, one exploration run, selection,
registration, one held-out run. 4. Opus: live runtime `sleeve_runtime/momo_live.py`
on Momentum's account, dashboard panel. 5. Fable: order-path review before merge.

## Amendment 1 — build facts (Opus 5.5, 2 Nov 2026; no real data read)
Factual; no rule changed. Items marked **Fable** need a decision at step 3.
- **Survivorship (Fable).** The research panel's stock list comes from the
  stored Alpaca asset table, which describes listings *today*: experiments
  18-19's gates drop every stock that is inactive or untradable now, i.e.
  every stock delisted since 2018 (bankruptcies, buy-outs). "Survivorship-
  aware" above is therefore not true of the panel as experiments 18-19 used
  it. `fetch.py momo_panel` requires `--delisted include|exclude` with no
  default. `include` keeps inactive stocks whose bars exist in the price
  table (it only helps if the table still holds their history; the pull
  reports how many stored assets are inactive). The choice is written into
  the dataset manifest.
- **Lock.** The legacy lock refuses any read past 2020-12-31 without a
  registration. MOMO-V1's declared exploration end (2024-12-31) is now an
  explicit entry in `holdout.DECLARED_EXPLORATION_END`, checked against this
  file by a test; `simulate`, `BarStore.load` and FLEET-V1's helpers take
  `plan="MOMO-V1"`. Rows from 2025-01-01 sit in the datasets' locked parts
  and still need a registry grant.
- **History rule.** "At least 252 sessions of history" is implemented as
  253 closes, because 12-1 momentum needs the close 252 sessions ago.
- **M2's split** is F1's: stocks (2 - E) x 0.99, SSO (E - 1) x 0.99 when E > 1.
- **Stops.** The simulator's 20% stop (reference = the fill's open) handles
  exits; the strategy re-derives which names were stopped, from the same
  bars, only at a mid-month resize, so a stopped name is not re-bought
  before the next ranking (tested against the simulator).
- **Data to pull (Replit; datasets stay there, too large for git):**
  - `fetch.py momo_panel --dataset momo_panel --start 2018-01-01 --end 2026-10-31 --locked-from 2025-01-01 --universe-from 2019-02-01 --delisted <Fable>`
    (writes both parts; the stock set is every stock in the top-500 universe in any month 2019-02..2026-10,
    which leaves every monthly universe exactly as on the full panel)
  - `fetch.py yahoo --dataset momo_etf_y --symbols SPY,SSO,QQQ,QLD,IEF,GLD,DBC,UUP --start 2018-01-01 --end 2024-12-31 --locked-from 2025-01-01`, then the same with `--locked --start 2025-01-01 --end 2026-10-31`
  - `fetch.py fred --dataset momo_rates_fred --series DTB3 ...` the same two parts
- **Run.** `python -m research_harness.explore.momo_v1` (on Replit, where the
  panel is). About 5 minutes, mostly the 500-draw null.

## Amendment 2 — exploration run 1 VOID (Fable 5.1, 2 Nov 2026 ~18:40 Brisbane)
Run 1 (exploration_log.jsonl, code 954825d) reported M1 9.2% CAGR / Sharpe
0.56 / max drawdown −15.8% and verdict FAILED. It is void: a defect in
`harness/portfolio.simulate` made the book sell every holding the day after
any rebalance in which one name had no bar on the fill day (a carried order
left the other holdings with an implied target of zero). From January 2020,
when a December pick stopped trading, the carried order persisted and the
book was emptied after every rebalance (average gross 24% against a dial
average of 73%). Diagnosed on the real data, read-only; no rule was touched.
Fix (same commit as this note): a carried order leaves other holdings alone;
a holding with no bar for 10 sessions is closed at its last close with exit
"delisted" (acquisition cash at about the last price; declared judgment
call). FLEET-V1 is unaffected: its instruments are built on the S&P
calendar and never miss a bar (verified on its data before run 2).
Run 2 is the exploration run of record. Nothing else changes.

## Verdict — exploration run 2 (Fable 5.1, 2 Nov 2026 ~19:00 Brisbane): FAILED
Run of record (exploration_log.jsonl, code 362ffbc), 2019-02-01..2024-12-31,
after costs, whole shares:
| | CAGR | Sharpe | max DD | avg gross |
|---|---|---|---|---|
| B (S&P 500) | 15.8% | 0.72 | −33.7% | 1.00 |
| M1 | 2.8% | 0.16 | −74.1% | 0.62 |
| M2 | 11.0% | 0.44 | −53.2% | 0.73 |
| X18 (no dial) | 9.9% | 0.38 | −78.7% | 0.85 |
| F1 (own code) | 12.7% | 0.86 | −16.2% | 0.74 |
| R null (500 draws) 95th pct Sharpe | | 0.36 | | |
No candidate met (a) or (b); M1 was below the random-20 null and below X18.
Nothing is registered; no variant is tried on this data.

Reading: the S&P-based dial cannot see a momentum crash inside a healthy
index (2021-22: S&P trending, speculative momentum names −70-80%), and
"500 most traded by dollar volume" in this panel selects high-beta small
caps at tops. M2's better figures come from holding fewer stocks (half the
book in SSO at 1.5x), not from gearing. Any stock-momentum follow-up needs a
book-level drawdown control and a large-cap universe, and is a new plan
(trial count then N = 10).
