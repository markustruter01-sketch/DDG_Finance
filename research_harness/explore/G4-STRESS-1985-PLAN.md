# G4-STRESS-1985: G4 through the 1987 crash and the 2000-02 dot-com crash (information only)

Written by Claude (Opus 5.5), Fri 30 Oct 2026 ~11:10 Brisbane, BEFORE any index or
pre-1990 rate data was pulled. Nothing here can change G4 or any registration:
it is a stress test of the live strategy, reported for information.

## Why
G4 (live in Atlas's paper account) was tested on 2007-2020 (exploration) and
2021-2026 (held-out). Its edge leans on a Nasdaq-100 tilt and 2x ETFs, and
neither window contains a Nasdaq collapse like 2000-02 (the 2x ETFs only start
in mid-2006). Markus asked on 30 Oct why only ~6 years count; this checks the
crash those windows miss.

## Method (fixed now)
- Rules: G4 exactly as registered (`research_harness/sleeves/gear.py`, G4,
  20% stops, whole shares, monthly + gear-change rebalances, T-bills in the
  safe gear). No parameter is changed or explored.
- Reconstructed instruments, from daily index closes (Yahoo chart API):
  - SPY* = S&P 500 price index (^GSPC); QQQ* = Nasdaq-100 price index (^NDX).
  - SSO* = 2 x the daily S&P return, minus the T-bill rate on the borrowed 1x,
    minus 0.88% a year; QLD* = the same on the Nasdaq-100, minus 0.96% a year
    (ProShares gross expense ratios, proshares.com, read 30 Oct 2026).
  - Dividends are left out of every series, the benchmark included (price
    indices). This understates all returns, the S&P side most.
  - Each day's open is set to the previous close and high/low to the day's
    close (close-to-close), because old index data may lack reliable opens.
    Stops can therefore only fire at a close: a simplification.
- Cash: FRED DTB3 (3-month T-bill), new pull from 1985.
- Costs as GEAR-V1: 0 commission, 2 bps half-spread, 3 bps slippage.

## Windows
- Stress window: from the first day G4 has 200 sessions of history (Nasdaq-100
  data starts in Oct 1985) to 2006-12-31. Sub-windows reported: the 1987 crash
  year, and 2000-01-01..2002-12-31.
- Fidelity check: the same reconstruction over 2007-01-01..2020-12-31, compared
  with G4 on the real ETFs in that window (logged 11.70% / -32.10%). Nothing
  from 2021 on is pulled or read.

## Reported
G4* vs S&P 500 price index and Nasdaq-100 price index buy-and-hold: CAGR,
worst fall, Sharpe over T-bills, time in each gear, stops hit; the same for the
sub-windows; the fidelity gap on 2007-2020. No pass bar: a bad result is a risk
finding for Markus, not a reason to tune G4 (any change would be a new,
untested strategy).
