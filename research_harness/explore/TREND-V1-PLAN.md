# TREND-V1 exploration plan (declared before any data was pulled)

Written by Claude, Fri 16 Oct 2026 ~03:30 Brisbane. No ETF price data had been
fetched into the harness when this was committed.

## Idea
Cross-asset trend sleeve: long or flat in a fixed ETF list, inverse-volatility
weights, monthly rebalance, cash (T-bills) when a trend is off. Code:
`research_harness/sleeves/trend.py`.

## Prior attempts on ETF trend ideas (counted honestly)
The 5 Oct 2026 roadmap (`quant_terminal_roadmap_2026-10-05.pdf`) records at least
7 earlier runs on ETF trend ideas: fleet test runs 127–130 (FAIL), Atlas rebuild
runs 131–132 (no edge in-sample), Experiment 21 (registered, FAIL vs SPY). This
plan is attempt 8 or later, which makes any pass weaker evidence.

## Candidate set (complete; nothing may be added after seeing results)
| id | rule |
|---|---|
| A | `tsmom_252`: on if 252-day total return > 0 |
| B | `sma_210`: on if close > 210-day average |
| C | `blend_63_126_252`: on if at least 2 of the 63/126/252-day returns are > 0 |

Fixed for all three (not explored): vol look-back 63 days, weight cap 0.30,
long only, gross <= 1.0, monthly rebalance on the first close of each month,
trade at the next open.

## Universe (fixed now)
SPY, IWM, EFA, EEM, VNQ, TLT, IEF, LQD, TIP, GLD, DBC — US large and small caps,
developed and emerging stocks, property, long and medium Treasuries,
corporate bonds, inflation-linked bonds, gold, broad commodities. Each ETF
becomes eligible only once it has enough price history (no back-filling).

## Data
- ETFs: yfinance dividend-adjusted daily OHLC (total-return proxy), pulled once
  into an immutable dataset; the manifest hash is logged with every run.
- Cash rate: FRED DTB3 (3-month T-bill, discount basis).

## Costs (assumptions, not measurements)
Commission 0 bps (Alpaca charges no commission on US ETFs), half-spread 2 bps,
slippage 3 bps per trade. No leverage, so no financing; no shorts, so no borrow
fee. These spread/slippage numbers are Claude's conservative assumptions for
liquid US ETFs, NOT measured from fills; a measured figure replaces them later.

## Windows
- Exploration: 2006-01-01 to 2020-12-31 (pre-2006 bars are warm-up only).
- Held-out: 2021-01-01 to the latest data. Untouched until ONE registered
  candidate is tested once.

## How the candidate is chosen
Highest Sharpe in excess of T-bills over the exploration window. Ties go to
the simpler rule (A, then B, then C). Exploration results go to
`research_harness/exploration_log.jsonl` only and never count as evidence.

## Pass bar for the held-out test (from the rebuild plan)
1. Beats T-bills after costs over the held-out window.
2. Correlation to the other v1 sleeve (equity momentum) below 0.5, and raises
   fleet Sharpe. Until the momentum sleeve has a reproducible backtest, (2) is
   reported as NOT YET TESTABLE and the sleeve is not considered passed.
Reported every time: return, CAGR, volatility, Sharpe (rf 0 and excess
T-bills), max drawdown, round trips, fills, win rate, turnover, leverage, and
SPY buy-and-hold over the same window for reference.
