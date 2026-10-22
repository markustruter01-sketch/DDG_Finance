# BOOST-V1 exploration plan (declared before any crypto data was pulled)

Written by Claude (Opus 5.5), Thu 22 Oct 2026 ~10:20 Brisbane. No BTC or ETH
price data has been fetched into the research harness when this is committed.

## Why this sleeve exists
Markus's rule 2 (18 Oct 2026): aim for ~15% a year, possibly helped by a small
single-digit share of the portfolio in a volatile but strong asset. Approved
change 1 (18 Oct 2026): a booster sleeve capped at 3–5% of fleet equity,
crypto first, with its own stops.

## Honesty notes (read before any result)
- Prior attempts on crypto allocation: at least 1 (Bullion rebuild runs
  125–126, crypto inside a metals + crypto inverse-vol basket, 2018–2022; the
  live Bullion bot holds BTC/ETH today under a 5% fleet crypto cap). This plan
  is attempt 2 or later.
- Hindsight risk: the designer (Claude) knows the broad crypto history,
  including the large 2022 fall that sits inside the held-out period. A trend
  filter is the kind of rule that history flatters. To limit this, candidate A
  is plain buy-and-hold, and the trend rule and look-backs are copied from the
  already-registered TREND-V1-B (sma_210, vol 63) rather than chosen for
  crypto. The 25% stop is copied from the live Bullion crypto stop. None of
  these values are explored.
- One asset class, one held-out period of under six years: any result is a
  data point, not a rate. Trade counts will be small; they are reported.

## Candidate set (complete; nothing may be added after seeing results)
| id | holds | rule |
|---|---|---|
| A | BTC | always held (buy-and-hold, re-entered at the next monthly rebalance after a stop-out) |
| B | BTC | held only when close > its 210-session average; otherwise T-bills |
| C | BTC + ETH | each held only when close > its 210-session average; inverse-volatility (63-session) weights across the eligible coins, as in TREND-V1 (the "off" coin's share stays in T-bills) |

Fixed for all three (not explored): long only, gross <= 1.0 within the sleeve,
no leverage, fractional quantities (crypto is fractional live), monthly
rebalance on the first session close of each month, trade at the next
session open, 25% protective stop re-set at each rebalance, a stop-out stays
flat until the next monthly rebalance. A coin becomes eligible only once it
has enough history (no back-filling).

## Sessions (calendar)
Crypto trades every day; the rest of the fleet trades US sessions. Crypto bars
are resampled onto US trading days (SPY's dates in the ETF dataset): each
session bar takes the open of the first calendar day after the previous
session, the high/low over all those days (so weekend crashes still hit the
stop), and the close of the session day. All annualisation then stays at 252
sessions, the T-bill accrual is correct, and returns align with the other
sleeves day for day. Live, the protective stop works 24/7, so a weekend stop
fills earlier than the resampled backtest assumes; the backtest still sees the
weekend low.

## Data
- BTC-USD, ETH-USD: yfinance daily OHLC (calendar days, UTC), pulled once into
  an immutable dataset via `research_harness.fetch etf`, end 2026-10-15 to
  match the ETF dataset.
- Session calendar: SPY dates from `etf_daily_yf_2026-10-16`.
- Cash rate: FRED DTB3, `fred_dtb3_2026-10-16`.

## Costs (assumptions, not measurements)
Alpaca crypto taker fee 25 bps per trade (Tier 1, 0–100k USD 30-day volume,
docs.alpaca.markets/docs/crypto-fees, read 22 Oct 2026; the page does not say
whether paper accounts charge it, so it is charged here). Half-spread 5 bps,
slippage 5 bps: Claude's assumptions for BTC/ETH on Alpaca, not measured from
fills. No leverage, no shorts, so no financing or borrow costs.

## Sizing in the fleet (fixed design value)
The sleeve is run at 4% of fleet equity (middle of the approved 3–5%),
reset to 4% at each monthly rebalance; the fleet risk governor will cap it at
5% between rebalances.

## Windows
- Exploration: 2015-01-01 to 2020-12-31 (earlier bars are warm-up only;
  ETH-USD data starts in late 2017, so C is BTC-only until ETH is eligible).
- Held-out: 2021-01-01 to 2026-10-15. Untouched until ONE registered
  candidate is tested once.

## How the candidate is chosen
Among candidates whose exploration max drawdown is no worse than -50%,
the highest Sharpe in excess of T-bills over the exploration window. Ties go
to the simpler candidate (A, then B, then C). If none meets the drawdown
limit, nothing is registered and the sleeve idea is reported as failed.

## Pass bar for the held-out test (registered with the candidate)
1. Beats T-bills after costs over the held-out window.
2. Drawdown: sleeve max drawdown no worse than -50% (at 4% of fleet that is at
   most about a 2% hit to the fleet from this sleeve).
3. Correlation of session returns to TREND-V1-B (held-out curve) below 0.5.
4. Fleet test: 96% TREND-V1-B + 4% booster has a higher Sharpe (excess
   T-bills) than TREND-V1-B alone over the held-out window. The momentum
   sleeve has no reproducible backtest yet, so the full-fleet test is
   reported as NOT YET TESTABLE and is re-run when it has one.
Reported every time: return, CAGR, volatility, Sharpe (rf 0 and excess
T-bills), max drawdown, round trips, fills, stops hit, win rate,
expectancy, turnover, leverage, and BTC buy-and-hold for reference.
A fail is reported as a fail; no variant is tried afterwards.

## Amendment 1 — data source (22 Oct 2026 ~10:30 Brisbane)
Made BEFORE any crypto data entered the harness and before any exploration
ran. The yfinance pull failed in the Replit workspace ("BTC-USD: possibly
delisted; no timezone found", no data returned), so no dataset was written.
Data source changed to Coinbase Exchange's free public daily candles
(granularity 86400, UTC days, no key), `research_harness.fetch coinbase`,
dataset `crypto_daily_cb_2026-10-22`. Consequences, stated now: each
product's history starts when Coinbase listed it (the fetch prints the first
date; it may be later than yfinance's), so candidate A starts trading at the
first available bar and B/C only once the 210-session average exists. Prices
are from one exchange, not an aggregate. Nothing else in the plan changes.
