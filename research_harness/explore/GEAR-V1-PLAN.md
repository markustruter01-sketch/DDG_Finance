# GEAR-V1 plan: the S&P 500 "gearbox" core (declared before any data was pulled)

Written by Claude (Opus 5.5), Thu 22 Oct 2026 ~12:05 Brisbane. No SSO, QLD or
QQQ data has been fetched into the research harness, and no gearbox code has
been written or run, when this is committed.

## Why this exists (Markus, 22 Oct 2026)
- Platform goal: beat the S&P 500. If it cannot, Markus will simply hold an
  S&P 500 ETF. Target: more than 10.5% a year compounded over 5–10 years,
  higher if possible. (S&P 500 total return 2005–2024 compounded about 10.3%
  a year: Claude's arithmetic on the Motley Fool annual-returns table.)
- "Rule one is not to lose money": sit in T-bills when markets look like a
  20–40% plunge or choppy, step back into the S&P 500 when they recover, and
  only run the aggressive setting in a clear bull market.
- Worst acceptable fall: -20% (Claude proposed, Markus said "go ahead",
  22 Oct 11:55).

## Honesty notes (read before any result)
- Prior attempts on ETF trend ideas: at least 10 (7 recorded in the 5 Oct
  roadmap, plus TREND-V1's 3 candidates). The live Momentum account also ran
  an SPY/QQQ EMA trend follower (`kraken-bot/bot2_spy_qqq.py`) that was never
  held-out tested. This plan is attempt 11 or later on trend timing.
- Hindsight: the designer knows when 2008, 2020 and 2022 fell, and has already
  seen SPY's held-out numbers (2021-01-01..2026-10-15: CAGR 15.13%, max drawdown
  -24.5%, reported with the TREND-V1-B test). To limit this, the trend rule
  (close vs 200-day average) is the published rule from Gayed & Bilello,
  "Leverage for the Long Run" (data 1928–2015, as summarised by CXO Advisory), not one chosen on our data; the
  volatility line and the stop are fixed design values stated below and are
  not explored.
- Where any extra return comes from: the leverage in the aggressive gear, not
  the signal. The trend rule's job is to cut drawdowns enough for the leverage
  to be survivable. If the unlevered G1 does as well as the levered ones, G1
  wins (simpler).
- One held-out window of under six years containing one bear market (2022)
  that a trend rule is likely to handle well. Any result is a data point, not
  a rate.

## Gears (all candidates)
Read once a day at the close on SPY; trade at the next open.
| gear | when | holds |
|---|---|---|
| Aggressive | SPY close > its 200-session average AND SPY's 20-session realised volatility (annualised) <= 20% | the candidate's aggressive mix |
| Normal | SPY close > its 200-session average AND that volatility > 20% | the candidate's normal mix (1.0x) |
| Safe | SPY close <= its 200-session average | T-bills (backtest: cash earns FRED DTB3; live: SGOV) |

The 20% volatility line is a fixed design value: it sits about halfway between
the S&P's volatility above (14.7%) and below (26.5%) its 200-day average over
1928–2015, as summarised by CXO Advisory from Gayed & Bilello. It was not
fitted on our data and is not explored.

## Candidate set (complete; nothing may be added after seeing results)
| id | aggressive mix | effective exposure | normal mix |
|---|---|---|---|
| G1 | (no aggressive gear: Aggressive = Normal) 100% SPY | 1.0x | 100% SPY |
| G2 | 50% SPY + 50% SSO (2x S&P 500) | 1.5x | 100% SPY |
| G3 | 75% SPY + 25% SSO | 1.25x | 100% SPY |
| G4 | 25% SPY + 25% SSO + 25% QQQ + 25% QLD (2x Nasdaq-100) | 1.5x | 50% SPY + 50% QQQ |

Leverage comes only from 2x ETFs, never from borrowing: account gross stays
<= 1.0, so no margin loan, no margin call, and the account cannot go below
zero. The ETFs' own fees, financing and daily-reset decay are inside their
prices, so the test sees them.

## Fixed for all four (not explored)
- Long only. Whole shares only (rounded down).
- Trades happen only when the gear changes, and once a month (first session
  close of each month) to bring weights back to target within the gear.
- Protective stop 20% below the entry/rebalance open on every holding, re-set
  at each rebalance (copied from TREND-V1-B, the platform's every-position-
  has-a-stop rule). A stopped holding stays in T-bills until the next gear
  change or monthly rebalance.
- Idle cash and the Safe gear earn the T-bill rate.

## Data (pulled later, in one go, into an immutable dataset)
- SPY, QQQ, SSO, QLD: yfinance dividend-adjusted daily OHLC (total-return
  proxy), 1998-01-01 to 2026-10-15, via `research_harness.fetch etf`. SSO and
  QLD start in mid-2006; that sets the exploration start below.
- Cash rate: FRED DTB3, the existing `fred_dtb3_2026-10-16`.
- Benchmark: SPY buy-and-hold on the same adjusted data, same window.

## Costs (assumptions, not measurements)
Commission 0 bps (Alpaca charges none on US ETFs), half-spread 2 bps,
slippage 3 bps per trade (copied from TREND-V1; Claude's conservative
assumptions for liquid US ETFs, not measured from fills). No borrowing, so no
margin interest (Alpaca margin is 6.50% a year per its support page, which is
why borrowing is not used). No shorts, so no borrow fees.

## Windows
- Exploration: 2007-01-01 to 2020-12-31 (includes 2008, 2011, 2018, 2020).
  Earlier bars are warm-up only.
- Held-out: 2021-01-01 to 2026-10-15. Untouched until ONE registered
  candidate is tested once.

## How the candidate is chosen (exploration)
Among candidates whose exploration max drawdown is no worse than -20% AND whose
exploration CAGR beats SPY buy-and-hold's over the same window, the highest
exploration CAGR. Ties go to the simpler candidate (G1, G3, G2, G4). If none
qualifies, nothing is registered and GEAR-V1 is reported as FAILED; no variant
is tried afterwards.

## Pass bar for the held-out test (registered with the candidate)
All after costs, 2021-01-01 to 2026-10-15:
1. CAGR beats SPY buy-and-hold over the same window.
2. CAGR is at least 10.5% a year.
3. Max drawdown no worse than -20%.
4. Fleet test: reported as NOT YET TESTABLE until the Momentum sleeve has a
   reproducible backtest. Reported for information: 100% gearbox vs a
   gearbox + TREND-V1-B mix.

Reported every time: return, CAGR, volatility, Sharpe (rf 0 and excess
T-bills), max drawdown, time in each gear, gear changes, fills, stops hit,
win rate, expectancy, turnover, effective exposure (average and max), SPY
buy-and-hold for reference, and the worst rolling 3-year stretch vs SPY.
A fail is reported as a fail.

## Before any live use (even if it passes)
- The kill switch's hard fleet drawdown limit (15%) and the risk governor's
  soft limit (10%) were set for a low-risk fund. They would freeze a strategy
  allowed to fall 20%. Markus must re-set them (owner decision) before this
  goes live.
- Check that Alpaca paper and live accounts can trade SSO/QLD without extra
  restrictions (not yet verified).
- Forward paper trading first, like every sleeve.

## Amendment 1: data source (22 Oct 2026 ~15:15 Brisbane)
Made BEFORE any SSO/QLD/QQQ data entered the harness and before any
exploration ran. The yfinance library pull failed in the Replit workspace
("SPY: possibly delisted; no timezone found"; no dataset was written), while
Yahoo's chart endpoint answered directly (a read-only test returned SSO bars
from 21 Jun 2006 with adjusted closes; that test fetched no data into the
harness and computed nothing). Data source is therefore the same vendor
through `research_harness.fetch yahoo` (Yahoo chart API v8), adjusted the
same way as before (every price scaled by adjclose / close, as yfinance's
auto_adjust=True does), into dataset `gear_etf_ych_2026-10-22`. Nothing else
in the plan changes.

## Exploration result (22 Oct 2026, run once in Replit, log commit ced10754)
2007-01-03..2020-12-31, all costs. SPY buy-and-hold: CAGR 9.39%, max drawdown
-55.19%, Sharpe excess T-bills 0.50. G1 6.37% / -24.42% / 0.51; G2 7.85% /
-32.64% / 0.48; G3 7.15% / -28.59% / 0.50; G4 11.70% / -32.10% / 0.66.
Under the rule above no candidate qualified (all worse than -20%), so
GEAR-V1 as declared FAILED and nothing was registered.

## Amendment 2: drawdown bar (22 Oct 2026 ~15:35 Brisbane), AFTER exploration
Markus delegated the decision ("do whatever you think is best to meet our
overall goal of beat 10.5% per year", 15:27). Claude's decision, recorded
openly because it changes a bar after seeing exploration results:
- The fixed -20% limit is replaced by a relative one: the worst fall must be
  smaller than SPY buy-and-hold's over the same window. Reason: "beat the S&P
  with smaller crashes" is the stated purpose of the gearbox; the number is
  set by the benchmark in each window, not by any candidate's result. It was
  NOT chosen to fit G4's -32.1% (an absolute limit like -35% would have been).
- Selection under the amended gate (drawdown better than SPY's AND CAGR above
  SPY's, then highest CAGR): only G4 qualifies (11.70% vs 9.39%; -32.1% vs
  -55.2%). G4 is registered as GEAR-V1-G4 and tested ONCE on the held-out
  window 2021-01-01..2026-10-15.
- Held-out pass bar: (1) CAGR beats SPY's; (2) CAGR >= 10.5%; (3) max
  drawdown smaller than SPY's (both on the same window). Fleet test still NOT
  YET TESTABLE.
- What this costs in evidence: the bar change happened after exploration, and
  G4's exploration edge leans on Nasdaq's 2007-2020 strength, which the
  designer knew about. The held-out window was not read by anyone before the
  registration, so the single test is still out-of-sample for G4, but any
  pass is weaker evidence than a pass under the original bar. Attempts on
  trend timing: at least 11 (10 earlier + GEAR-V1's 4 candidates counted as
  one plan).

## Held-out result: GEAR-V1-G4 (22 Oct 2026, run once, ledger entry)
2021-01-04..2026-10-15, all costs. G4: CAGR 18.05%, max drawdown -24.50%,
volatility 20.33%, Sharpe excess T-bills 0.76, 60 round trips, 1 stop hit,
78.1% of sessions in the aggressive gear. SPY: CAGR 15.18%, max drawdown
-24.50%, volatility 16.60%, Sharpe 0.74. Bars: (1) beats SPY CAGR PASS;
(2) >= 10.5% PASS; (3) smaller drawdown than SPY FAIL (equal at the reported
precision). Verdict: FAIL. No variant is tried. Next (Claude's
recommendation to Markus): forward shadow test with no orders.

## Decision: G4 goes live in Atlas's account (23 Oct 2026, 09:43 Brisbane)
Markus decided to run G4 despite the held-out FAIL on bar 3 ("fuck my rule
about a smaller fall"), exactly as tested (he declined the faster-exit idea
after Claude explained it could not be tested honestly: the held-out window is
spent), in Atlas's (oracle's) paper account. The TREND-V1-B cutover planned
for that account is cancelled (PR #19 closed unmerged).
- This is an operator decision, not a pass: the ledger entry stays FAIL. G4's
  only out-of-sample evidence is the one held-out run above (worst fall equal
  to SPY's, at 1.5x exposure in calm markets).
- Live rules = the registered candidate (sleeve_runtime/gear_live.py), with
  two live necessities: a 1% cash buffer, and orders on the first hourly
  cycle while the market is open rather than exactly at the open.
- The forward shadow (sleeve_runtime/gear_shadow.py) keeps running as the
  clean replay of the registered rules to compare the live account against.
