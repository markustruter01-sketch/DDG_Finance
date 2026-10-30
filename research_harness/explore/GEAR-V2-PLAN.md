# GEAR-V2 plan: what the gearbox holds when it is out of the market (declared before any GEAR-V2 run)

Written by Claude (Opus 5.5), Fri 30 Oct 2026 ~10:35 Brisbane (UTC+10).
When this file is committed: no GEAR-V2 code exists, no GEAR-V2 backtest has
run, no DBMF data has been pulled, and no row of any dataset has been read for
this plan (only manifest headers: symbols, first/last dates, row counts).

## Why this exists (Markus, 30 Oct 2026)
- Target: about 12.5% a year, a worst fall no worse than the S&P 500's, a
  strategy that holds up in a recession, everything free to run, and a public
  paper track record from 1 Jan 2027.
- GEAR-V1-G4 (live in Atlas's paper account since 23 Oct) sits in T-bills
  whenever SPY closes at or below its 200-session average (the "safe gear").
  Markus's "option B" (30 Oct): hold a crisis engine there instead of
  T-bills. Before committing to B, every free alternative is checked here.

## Starting point (read from the exploration log and ledger, not re-run)
| | window | CAGR | max drawdown | Sharpe (excess T-bills) | safe gear |
|---|---|---|---|---|---|
| G4 exploration | 2007-01-03..2020-12-31 | 11.70% | -32.10% | 0.66 | 21.7% of sessions |
| SPY, same window | | 9.39% | -55.19% | 0.50 | |
| G4 held-out (ledger) | 2021-01-04..2026-10-15 | 18.05% | -24.50% | 0.76 | 18.9% of sessions |
| SPY, same window | | 15.18% | -24.50% | 0.74 | |
G4's held-out verdict stays FAIL (worst fall equal to SPY's, not smaller).

## Honesty notes (read before any result)
- **Hindsight.** The designer knows the broad history of the crises in both
  windows: in 2008 Treasuries rose and gold recovered while stocks fell; in
  2022 stocks and bonds fell together under high inflation, and trend
  followers had a record year (SG Trend Index +27.3% in 2022, per
  Société Générale's 2022 CTA review as reported by AlphaWeek, read 30 Oct).
  So A1 (gold + Treasuries) can be expected to look good in 2008 and poor in
  2022, and A2/A3 (trend) good in 2022. The held-out window contains 2022.
  Consequence: a held-out PASS for A2 or A3 is weak evidence; a held-out FAIL
  is meaningful. The forward paper record is the evidence that counts.
- **Already seen.** TREND-V1-B, the long-only version of A3's rule, has been
  held-out tested (ledger: CAGR 3.59%, max drawdown -7.40%, 2021..2026-10-15).
- **Attempts so far.** Trend timing on this platform: at least 11 before this
  plan (GEAR-V1 plan count, which includes TREND-V1's 3 candidates). The
  crypto booster (BOOST-V1, 3 candidates) failed exploration on 22 Oct.
  GEAR-V2 declares 4 new candidates (A1, A2, A3, B1). After this plan the
  trend family stands at 15 or more attempts.
- **Where any edge would come from.**
  - A3: time-series momentum across asset classes, long and short
    (Moskowitz, Ooi & Pedersen 2012; Hurst, Ooi & Pedersen, "A Century of
    Evidence on Trend-Following Investing", 2017). Both are from AQR, which
    sells the strategy. Against it: trend returns were weak for about four
    years after past financial crises (Hutchinson & O'Brien 2014: 4.0% in the
    24 months after a crisis starts vs 13.6% in no-crisis periods), and
    buy-and-hold beat trend in almost every asset class over 2009-2018
    (Alpha Architect, Feb 2019). Those studies use futures across many
    markets; A3 uses 11 US-listed ETFs with real shorts. That is a smaller,
    cruder version, and it may capture less of the effect.
  - A1: flight-to-safety assets; no forecasting skill involved.
  - A2: a fund that replicates the returns of a group of CTA hedge funds,
    fee 0.85% a year (stockanalysis.com, read 30 Oct). Someone else's engine.
- **One held-out window, one inflationary bear market (2022).** Any result is
  a data point, not a rate.

## What is NOT re-opened
G4's signal, its aggressive and normal gears, its rebalance timing and its
20% stop stay exactly as registered (`research_harness/sleeves/gear.py`).
G4's held-out window is spent; changing the bull side would be a new
strategy with no untouched data to test it on.

## Part A: what the safe gear holds (complete candidate set)
Everything except the safe gear's holdings is G4 exactly.
| id | safe gear holds | status |
|---|---|---|
| A0 | T-bills (cash earns FRED DTB3; live: SGOV) = G4 as registered | control |
| A1 | 50% GLD + 50% IEF, fixed weights | candidate |
| A2 | 100% DBMF | information only (data rule below) |
| A3 | long/short cross-asset trend (below) | candidate |

A3 rule: universe SPY, IWM, EFA, EEM, VNQ, TLT, IEF, LQD, TIP, GLD, DBC (the
TREND-V1 universe, fixed 16 Oct). Trend call = TREND-V1-B's registered rule
`sma_210`: LONG when the close is above its 210-session average, SHORT when
at or below it (TREND-V1-B goes flat instead). Weight = inverse 63-session
volatility over all eligible ETFs, each capped at 0.30, gross <= 1.0. An ETF
is eligible only once it has enough history (no back-filling).

Rebalancing (all candidates): G4's rule. On a gear change and at the first
session close of each month, the target weights are recomputed; in the safe
gear that means the engine's weights (A3's trend calls are refreshed then).
Signal at the close, trade at the next open.

## Part B: an always-on crisis slice (declared now, run after Part A)
| id | fund |
|---|---|
| B0 | 100% the Part A result |
| B1 | 75% the Part A result + 25% A3's long/short trend run on its own, always on, rebalanced at the first session close of each month |
25% is a fixed design value (one quarter, which maps to one of four equal
paper accounts). It is not explored. The fleet maths uses the harness rule:
constant weights, rebalanced daily (`harness/fleet.py`); live, separate
accounts would drift between rebalances.

## Data rule (declared now)
A candidate can be selected only if its engine has data covering the whole
exploration window. DBMF launched on 8 May 2019 (stockanalysis.com, read
30 Oct), so A2 cannot be selected. It is reported on the held-out window for
information, and it runs in the forward shadow next to the chosen
configuration, so option B keeps being measured.

## Fixed for every candidate (not explored)
- Long and short only as stated above; whole shares (rounded toward zero);
  account gross <= 1.0, so no borrowing for longs.
- Protective stop 20% from the rebalance-day open on every holding (sell
  stop below longs, buy stop above shorts), re-set at each rebalance; a
  stopped holding stays out until the next rebalance (simulator rule).
- Idle cash earns the T-bill rate. Short-sale proceeds earn nothing.

## Data (named datasets, already in git at commit 5d58838 unless stated)
- Gearbox: `gear_etf_ych_2026-10-22` (SPY, QQQ, SSO, QLD), manifest hash
  eb7d2e469206b93406fb8986766542f602bd67ec233c2b99333467169a01127b. This SPY
  series drives the gear AND A3's SPY leg, so one SPY series is used.
- Engines: `etf_daily_yf_2026-10-16` (IWM, EFA, EEM, VNQ, TLT, IEF, LQD,
  TIP, GLD, DBC; its SPY file is not used), manifest hash
  119c8e0ff7781b560c4049ac4c965445bfbd3e97c24747e3b4cfb718a8168221.
  Same vendor and adjustment method as the gearbox data (Yahoo, dividend
  and split adjusted), pulled six days earlier.
- Cash: `fred_dtb3_2026-10-16`, manifest hash
  008c90e42510326b9ed9098e4e634c5fd1a1949e3dfcd7651edf1ec85fb216df.
- DBMF: a new pull through `research_harness.fetch yahoo` into an immutable
  dataset, in the Replit workspace (this sandbox cannot reach Yahoo). Needed
  only for A2's information-only figures.
- If a loaded manifest hash differs from the ones above, the run stops.

## Costs (assumptions stated, nothing omitted)
- Commission 0 bps (Alpaca charges none on US ETFs), half-spread 2 bps,
  slippage 3 bps per trade: Claude's assumptions copied from GEAR-V1, not
  measured from fills.
- Short borrow 0 bps a year: Alpaca's docs state $0 locate and borrow fees on
  easy-to-borrow shares for Trading API users (read 30 Oct). Historical
  easy-to-borrow status cannot be checked, so A3 and B1 are ALSO reported
  with a 100 bps a year borrow fee as a stress test (declared now). The
  selection and pass bar use the 0 bps run.
- Financing: none expected (gross <= 1.0, longs never borrow). A spread of
  650 bps over T-bills is set anyway (Alpaca's non-elite margin rate is
  6.50% a year, docs read 30 Oct; charging it on top of T-bills overstates
  it), so any accidental borrowing shows up as a cost.
- 2x ETF fees and DBMF's fee are inside their prices.

## Windows
- Exploration: 2007-01-01 to 2020-12-31 (as GEAR-V1). Earlier bars are
  warm-up only.
- Held-out: 2021-01-01 to 2026-10-15 (as GEAR-V1, the last bar of the pinned
  datasets). Untouched until ONE registered configuration is tested once.

## Selection (exploration)
1. A0 is re-run first. It must reproduce the logged 11.70% / -32.10%; if it
   does not, stop and find out why before anything is selected.
2. Part A: among A1 and A3, those whose exploration CAGR is above A0's AND
   whose max drawdown is no worse than A0's. Highest CAGR wins; ties go to
   the simpler one (A1, then A3). If none qualifies, Part A keeps A0.
3. Part B: B1 replaces B0 only if, on exploration, the slice passes the
   rebuild plan's sleeve test (`fleet.evaluate_sleeve`: beats T-bills,
   raises the fund's Sharpe, correlation to the core below 0.5) AND B1's max
   drawdown is smaller than B0's.
4. Final configuration = Part A choice + Part B choice. If that is A0 + B0,
   nothing changed: no new held-out test, G4 stays as it is, and GEAR-V2 is
   reported as "no improvement found".

Reported for every candidate: return, CAGR, volatility, Sharpe (rf 0 and
excess T-bills), max drawdown, time in each gear, gear changes, fills, round
trips, stops hit, win rate, expectancy, turnover, average and max gross,
worst rolling 3-year stretch vs SPY, the engine's P&L inside safe-gear
stretches, and two half-windows (2007-2013, 2014-2020) for information.

## Pass bar for the held-out test (registered with the configuration)
All after costs (0 bps borrow), 2021-01-01..2026-10-15, all must hold:
1. CAGR beats SPY buy-and-hold's.
2. CAGR is at least 12.5% a year (Markus, 30 Oct).
3. Max drawdown smaller than SPY's (the strict bar G4 failed).
4. Sharpe in excess of T-bills above SPY's (rebuild plan fleet bar, 15 Oct).
5. If B1 is chosen: the slice's correlation to the core below 0.5 (rebuild
   plan sleeve bar).
Reported alongside, same window: A0 (a replication of the ledger figure),
A2 (information only, if DBMF data exists), SPY, and the 100 bps borrow
stress run. Run once. A fail is reported as a fail; no variant is tried.

## Before anything goes live (not part of the test)
- A3 or B1 needs short selling. Alpaca requires at least $2,000 of account
  equity to sell short (docs, read 30 Oct). The live code has no short
  support today; it must be built under live-system-safety (buy stops on
  shorts, reconciliation of negative positions, kill switch coverage) and
  Markus must approve shorting before any live short order.
- A2 or the forward shadow of A2 needs DBMF to be tradable at Alpaca:
  UNVERIFIED, read-only asset check first.
- B1 needs a second account (Momentum's, only if Markus retires Momentum).
- Every live change is a strategy-rule change: Markus approves, published in
  a US-market-closed window, with read-only checks before and after.

## Forward evidence
Whatever is chosen runs as a no-order shadow from deployment, next to A0 and
A2, until 1 Jan 2027. From 1 Jan the paper account is the public record. That
forward record, not this backtest, is the evidence that counts. Backtest
figures shown publicly are labelled hypothetical.

## Considered and not tested this round (so the gaps are visible)
- Crypto booster: BOOST-V1 exploration (22 Oct) found no candidate within its
  -50% drawdown limit; nothing was registered; closed, no variant.
- FX carry: carry trades carry crash risk and lose when risk appetite and
  funding liquidity fall (Brunnermeier, Nagel & Pedersen, "Carry Trades and
  Currency Crashes", NBER WP 14473, 2008), the opposite of a recession hedge.
  It also needs per-currency interest-rate history whose free sources have
  not been checked.
- Momentum (50 stocks): an honest test needs survivorship-free stock data,
  which costs money; it cannot be validated under the free rule.
- Index put options: Alpaca paper accounts can trade them, but historical
  options data is not free, so they could only be tested forward.
- Futures trend on IBKR: its API needs a funded account (rebuild plan).
- Forex AI council: judged by its own registered plan (10-11 Oct).
- Bullion (live): never tested in this harness; not part of this decision.
- Short-term mean reversion and other trading styles: not examined this
  round.

## Decisions for Markus (outside the test)
1. Which accounts make up the public fund's record.
2. Whether Momentum is retired.
3. Shorting approval, if A3 or B1 is chosen.

## Process
1. This plan is committed to GitHub before any GEAR-V2 code runs on data.
2. Code and tests (synthetic data only).
3. One exploration run; result to `exploration_log.jsonl`.
4. The final configuration is registered (`registrations/GEAR-V2-<id>.json`).
5. DBMF data pulled in Replit (information only).
6. One held-out run; result to `ledger.jsonl`.
7. Report, then Markus's decisions.
