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
