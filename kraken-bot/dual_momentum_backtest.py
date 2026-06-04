"""
dual_momentum_backtest.py — Dual Momentum (cross-sectional + absolute gate)
on the 12-ETF commodity universe.

Strategy (LOCKED — do not optimize):
  Universe  : GLD, SLV, GDX, GDXJ, XLE, USO, XOP, DBB, PICK, DBC, PDBC, GSG
  Signal    : 12-1 momentum = total return from t-252 to t-21 trading days
  Selection : top 3 by momentum, absolute gate (momentum > 0 only)
  Rebalance : first trading day of each calendar month
  Sizing    : equal-weight (1/3 each), long-only, no leverage
  TC        : 0.05% on notional of every buy or sell

BACKTEST ONLY. No live orders, no DB writes, no runner.py changes.

Run:
    cd kraken-bot
    python3 dual_momentum_backtest.py
"""
from __future__ import annotations

import math
import time
import warnings
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import numpy as np
import requests

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# Strategy parameters (canonical — do not change)
# ─────────────────────────────────────────────────────────────────────────────
UNIVERSE = ["GLD", "SLV", "GDX", "GDXJ", "XLE", "USO", "XOP",
            "DBB", "PICK", "DBC", "PDBC", "GSG"]

TOP_N              = 3          # number of holdings
FORMATION_LONG     = 252        # trading days for formation period start
FORMATION_SKIP     = 21         # trading days to skip (recent-month reversal)
STARTING_CAPITAL   = 100_000.0
TC_RATE            = 0.0005     # 0.05% one-way transaction cost on notional

# 5 OOS windows (same as Jerome/Buck for comparability)
WINDOWS = [
    ("W1 2019",    date(2019, 1, 1), date(2019, 12, 31)),
    ("W2 2020",    date(2020, 1, 1), date(2020, 12, 31)),
    ("W3 2021",    date(2021, 1, 1), date(2021, 12, 31)),
    ("W4 2022",    date(2022, 1, 1), date(2022, 12, 31)),
    ("W5 2023-24", date(2023, 1, 1), date(2024, 12, 31)),
]

# Fetch from 2017-01-01 so we have 12+ months lookback before W1 starts 2019-01-01
FETCH_START = date(2017, 1, 1)
FETCH_END   = date(2025, 1, 3)

_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


# ─────────────────────────────────────────────────────────────────────────────
# Data fetching (same pattern as oos_validation.py)
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_yahoo(ticker: str) -> Optional[pd.Series]:
    """Return a daily adjusted-close price Series indexed by date."""
    p1 = int(datetime(FETCH_START.year, FETCH_START.month, FETCH_START.day).timestamp())
    p2 = int(datetime(FETCH_END.year,   FETCH_END.month,   FETCH_END.day).timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"period1": p1, "period2": p2, "interval": "1d"}
    try:
        resp = requests.get(url, params=params, headers=_YAHOO_HEADERS, timeout=30)
        if resp.status_code != 200:
            return None
        data   = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return None
        r   = result[0]
        ts  = r.get("timestamp", [])
        q   = r.get("indicators", {}).get("quote", [{}])[0]
        adj = r.get("indicators", {}).get("adjclose", [{}])
        closes = q.get("close", [None] * len(ts))
        adjc   = adj[0].get("adjclose", closes) if adj else closes

        rows = [
            (datetime.utcfromtimestamp(ts[i]).date(), adjc[i])
            for i in range(len(ts))
            if adjc[i] is not None and not math.isnan(adjc[i])
        ]
        if not rows:
            return None
        s = pd.Series({d: p for d, p in rows}, name=ticker)
        s.index = pd.DatetimeIndex(s.index)
        s.sort_index(inplace=True)
        return s
    except Exception as exc:
        print(f"  WARN: {ticker} fetch failed — {exc}")
        return None


def load_price_matrix() -> pd.DataFrame:
    """Return a DataFrame of adjusted closes: rows=dates, cols=tickers."""
    print(f"Fetching {len(UNIVERSE)} tickers from Yahoo Finance...")
    series: dict[str, pd.Series] = {}
    for i, ticker in enumerate(UNIVERSE, 1):
        print(f"  [{i:02d}/{len(UNIVERSE)}] {ticker:<8}", end=" ", flush=True)
        s = _fetch_yahoo(ticker)
        if s is None or len(s) < 260:
            print("SKIP (insufficient data)")
            continue
        inception = s.index[0].date()
        print(f"OK  ({len(s)} rows, inception={inception})")
        series[ticker] = s
        time.sleep(0.3)

    df = pd.DataFrame(series)
    df.sort_index(inplace=True)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Momentum signal
# ─────────────────────────────────────────────────────────────────────────────
def _compute_momentum(
    prices: pd.DataFrame,
    ref_date: pd.Timestamp,
    formation_long: int = FORMATION_LONG,
    formation_skip: int = FORMATION_SKIP,
) -> dict[str, float]:
    """
    Compute 12-1 momentum for each ticker as of ref_date.
    momentum = price[ref_date - formation_skip bars] / price[ref_date - formation_long bars] - 1
    Returns only tickers with valid (non-NaN) momentum values.
    """
    # Get the integer position of ref_date in the index
    idx_arr = prices.index
    pos = idx_arr.searchsorted(ref_date)
    if pos >= len(idx_arr):
        pos = len(idx_arr) - 1

    # Actual positions
    end_pos   = pos - formation_skip          # t-21 (exclude recent month)
    start_pos = pos - formation_long          # t-252

    if end_pos < 0 or start_pos < 0:
        return {}

    end_date   = idx_arr[end_pos]
    start_date = idx_arr[start_pos]

    mom: dict[str, float] = {}
    for ticker in prices.columns:
        p_end   = prices.loc[end_date,   ticker] if end_date   in prices.index else float("nan")
        p_start = prices.loc[start_date, ticker] if start_date in prices.index else float("nan")
        if math.isnan(p_end) or math.isnan(p_start) or p_start <= 0:
            continue
        mom[ticker] = p_end / p_start - 1.0
    return mom


def _select_holdings(momentum: dict[str, float]) -> list[str]:
    """Apply absolute gate (mom > 0) then take top-N by momentum rank."""
    positive = {t: m for t, m in momentum.items() if m > 0}
    ranked   = sorted(positive, key=lambda t: positive[t], reverse=True)
    return ranked[:TOP_N]


# ─────────────────────────────────────────────────────────────────────────────
# Monthly rebalance date generation
# ─────────────────────────────────────────────────────────────────────────────
def _monthly_rebalance_dates(prices: pd.DataFrame, start: date, end: date) -> list[pd.Timestamp]:
    """Return the first trading day of each calendar month within [start, end]."""
    trading_days = prices.loc[pd.Timestamp(start):pd.Timestamp(end)].index
    rebal_dates: list[pd.Timestamp] = []
    seen_months: set[tuple] = set()
    for d in trading_days:
        key = (d.year, d.month)
        if key not in seen_months:
            seen_months.add(key)
            rebal_dates.append(d)
    return rebal_dates


# ─────────────────────────────────────────────────────────────────────────────
# Backtest engine
# ─────────────────────────────────────────────────────────────────────────────
def run_window(
    prices: pd.DataFrame,
    start: date,
    end: date,
    formation_long: int = FORMATION_LONG,
    formation_skip: int = FORMATION_SKIP,
) -> dict:
    rebal_dates = _monthly_rebalance_dates(prices, start, end)
    if not rebal_dates:
        return _empty_result()

    equity      = STARTING_CAPITAL
    cash        = STARTING_CAPITAL
    # holdings: {ticker: shares}
    holdings: dict[str, float] = {}
    monthly_returns: list[float] = []
    equity_curve:   list[tuple[date, float]] = []
    transactions:   list[dict] = []
    monthly_holding_counts: list[int] = []

    prev_equity = equity
    prev_rebal  = None

    for rebal_dt in rebal_dates:
        # ── Mark-to-market at this rebalance date ──────────────────────
        if holdings:
            mtm = cash
            for tkr, shares in holdings.items():
                if rebal_dt in prices.index and not math.isnan(prices.loc[rebal_dt, tkr]):
                    mtm += shares * float(prices.loc[rebal_dt, tkr])
                else:
                    # Use last known price
                    avail = prices[tkr].dropna()
                    avail = avail[avail.index <= rebal_dt]
                    if not avail.empty:
                        mtm += shares * float(avail.iloc[-1])
            equity = mtm

        # Record monthly return (from previous rebalance to this one)
        if prev_rebal is not None:
            month_ret = (equity - prev_equity) / prev_equity
            monthly_returns.append(month_ret)
        equity_curve.append((rebal_dt.date(), round(equity, 2)))
        prev_equity = equity
        prev_rebal  = rebal_dt

        # ── Compute new target holdings ────────────────────────────────
        mom      = _compute_momentum(prices, rebal_dt, formation_long, formation_skip)
        new_hold = _select_holdings(mom)
        monthly_holding_counts.append(len(new_hold))

        # ── Sell positions no longer in target ────────────────────────
        to_sell = [t for t in list(holdings.keys()) if t not in new_hold]
        for ticker in to_sell:
            shares = holdings.pop(ticker)
            px     = float(prices.loc[rebal_dt, ticker]) if rebal_dt in prices.index else None
            if px is None or math.isnan(px):
                avail = prices[ticker].dropna()
                avail = avail[avail.index <= rebal_dt]
                px = float(avail.iloc[-1]) if not avail.empty else 0.0
            proceeds = shares * px
            tc       = proceeds * TC_RATE
            cash    += proceeds - tc
            transactions.append({
                "date": rebal_dt.date(), "ticker": ticker, "side": "sell",
                "shares": shares, "price": px, "notional": proceeds, "tc": tc,
            })

        # ── Buy new positions ──────────────────────────────────────────
        to_buy = [t for t in new_hold if t not in holdings]

        if new_hold:
            target_weight = 1.0 / len(new_hold)   # equal weight
        else:
            target_weight = 0.0

        # Rebalance existing holdings to target weight
        for ticker in [t for t in new_hold if t in holdings]:
            px = float(prices.loc[rebal_dt, ticker]) if rebal_dt in prices.index else None
            if px is None or math.isnan(px):
                avail = prices[ticker].dropna()
                avail = avail[avail.index <= rebal_dt]
                px = float(avail.iloc[-1]) if not avail.empty else 0.0
            current_val    = holdings[ticker] * px
            target_val     = equity * target_weight
            diff           = target_val - current_val
            if abs(diff) > 10:  # only rebalance if >$10 drift
                if diff > 0:    # buy more
                    tc      = diff * TC_RATE
                    shares  = (diff - tc) / px if px > 0 else 0
                    holdings[ticker] = holdings[ticker] + shares
                    cash   -= diff
                else:           # trim
                    trim_shares = abs(diff) / px if px > 0 else 0
                    proceeds    = trim_shares * px
                    tc          = proceeds * TC_RATE
                    holdings[ticker] = holdings[ticker] - trim_shares
                    cash       += proceeds - tc

        for ticker in to_buy:
            px = float(prices.loc[rebal_dt, ticker]) if rebal_dt in prices.index else None
            if px is None or math.isnan(px):
                avail = prices[ticker].dropna()
                avail = avail[avail.index <= rebal_dt]
                px = float(avail.iloc[-1]) if not avail.empty else 0.0
            if px <= 0:
                continue
            target_val = equity * target_weight
            tc         = target_val * TC_RATE
            alloc      = target_val - tc
            shares     = alloc / px
            if cash < target_val:
                alloc  = cash * (1 - TC_RATE)
                shares = alloc / px
            if shares <= 0:
                continue
            holdings[ticker] = shares
            cash -= target_val
            transactions.append({
                "date": rebal_dt.date(), "ticker": ticker, "side": "buy",
                "shares": shares, "price": px, "notional": target_val, "tc": tc,
            })

    # ── Final mark-to-market at window end ────────────────────────────
    end_ts = pd.Timestamp(end)
    avail_end = prices.loc[:end_ts]
    if not avail_end.empty:
        last_ts = avail_end.index[-1]
    else:
        last_ts = pd.Timestamp(end)

    mtm = cash
    for tkr, shares in holdings.items():
        px_series = prices[tkr].dropna()
        px_series = px_series[px_series.index <= last_ts]
        if not px_series.empty:
            mtm += shares * float(px_series.iloc[-1])
    equity = mtm

    # Add final equity point
    if equity_curve and equity_curve[-1][0] < end:
        equity_curve.append((end, round(equity, 2)))

    # ── Max drawdown from equity curve ────────────────────────────────
    equities = [e for _, e in equity_curve]
    peak     = STARTING_CAPITAL
    max_dd   = 0.0
    for eq in equities:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # ── Monthly win rate: % of (ticker, month) holdings that were positive ──
    # We track position-month outcomes from transactions
    all_hold_outcomes: list[bool] = []
    # Simple approximation: for each rebalance period, check holdings
    for i in range(len(rebal_dates) - 1):
        r0 = rebal_dates[i]
        r1 = rebal_dates[i + 1]
        # Holdings at r0 rebalance
        mom   = _compute_momentum(prices, r0, formation_long, formation_skip)
        held  = _select_holdings(mom)
        for ticker in held:
            p0_s = prices[ticker].dropna()
            p0_s = p0_s[p0_s.index <= r0]
            p1_s = prices[ticker].dropna()
            p1_s = p1_s[p1_s.index <= r1]
            if p0_s.empty or p1_s.empty:
                continue
            p0 = float(p0_s.iloc[-1])
            p1 = float(p1_s.iloc[-1])
            if p0 > 0:
                all_hold_outcomes.append(p1 > p0)

    win_rate = (sum(all_hold_outcomes) / len(all_hold_outcomes) * 100
                if all_hold_outcomes else None)

    avg_positions = (sum(monthly_holding_counts) / len(monthly_holding_counts)
                     if monthly_holding_counts else 0)
    pct_in_cash   = (sum(1 for n in monthly_holding_counts if n == 0) /
                     len(monthly_holding_counts) * 100
                     if monthly_holding_counts else 0)
    rebalances_with_changes = len(transactions) // 2 + len(transactions) % 2  # rough

    return {
        "final_equity":        round(equity, 2),
        "equity_curve":        equity_curve,
        "monthly_returns":     monthly_returns,
        "transactions":        transactions,
        "max_drawdown":        round(max_dd, 2),
        "win_rate":            round(win_rate, 1) if win_rate is not None else None,
        "avg_positions":       round(avg_positions, 1),
        "pct_in_cash":         round(pct_in_cash, 1),
        "monthly_rebalances":  len(rebal_dates),
    }


def _empty_result() -> dict:
    return {
        "final_equity": STARTING_CAPITAL, "equity_curve": [],
        "monthly_returns": [], "transactions": [], "max_drawdown": 0.0,
        "win_rate": None, "avg_positions": 0.0, "pct_in_cash": 100.0,
        "monthly_rebalances": 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Per-window stats
# ─────────────────────────────────────────────────────────────────────────────
def _window_stats(result: dict) -> dict:
    ret_series = result["monthly_returns"]
    final_eq   = result["final_equity"]
    max_dd     = result["max_drawdown"]

    total_ret  = (final_eq - STARTING_CAPITAL) / STARTING_CAPITAL * 100

    if len(ret_series) >= 2:
        mr    = pd.Series(ret_series)
        mean  = mr.mean()
        std   = mr.std()
        sharpe = (mean / std * math.sqrt(12)) if std > 0 else None
    else:
        sharpe = None

    return {
        "total_return":  round(total_ret, 2),
        "sharpe":        round(sharpe, 3) if sharpe is not None else None,
        "max_drawdown":  max_dd,
        "win_rate":      result["win_rate"],
        "avg_positions": result["avg_positions"],
        "pct_in_cash":   result["pct_in_cash"],
        "rebalances":    result["monthly_rebalances"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pooled stats across all windows
# ─────────────────────────────────────────────────────────────────────────────
def _pooled_stats(all_results: list[dict]) -> dict:
    all_monthly = []
    total_pnl   = 0.0
    for r in all_results:
        all_monthly.extend(r["monthly_returns"])
        total_pnl += r["final_equity"] - STARTING_CAPITAL

    if len(all_monthly) >= 2:
        mr     = pd.Series(all_monthly)
        mean   = mr.mean()
        std    = mr.std()
        sharpe = (mean / std * math.sqrt(12)) if std > 0 else None
    else:
        sharpe = None

    total_ret = total_pnl / STARTING_CAPITAL * 100

    return {
        "monthly_obs":   len(all_monthly),
        "sharpe":        round(sharpe, 3) if sharpe is not None else None,
        "total_return":  round(total_ret, 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pass/fail evaluation (same 5 criteria as Jerome/Buck)
# ─────────────────────────────────────────────────────────────────────────────
def _evaluate(stats_list: list[dict], pooled: dict) -> tuple:
    pos_return  = sum(1 for s in stats_list if s["total_return"] > 0)
    pos_sharpe  = sum(1 for s in stats_list if s["sharpe"] is not None and s["sharpe"] > 0)
    no_big_dd   = all(s["max_drawdown"] < 20.0 for s in stats_list)
    pooled_ok   = pooled["sharpe"] is not None and pooled["sharpe"] >= 0.5
    w2          = stats_list[1]   # 2020
    w4          = stats_list[3]   # 2022
    stress_ok   = w2["max_drawdown"] < 25.0 and w4["max_drawdown"] < 25.0

    criteria = [
        ("Positive return ≥4/5 windows",   pos_return >= 4,  f"{pos_return}/5"),
        ("Positive Sharpe ≥4/5 windows",    pos_sharpe >= 4,  f"{pos_sharpe}/5"),
        ("No window MaxDD > 20%",           no_big_dd,        "OK" if no_big_dd else "FAIL"),
        ("Pooled Sharpe ≥ 0.5",             pooled_ok,        str(pooled["sharpe"])),
        ("Stress windows (2020+2022) <25%", stress_ok,
         f"W2={w2['max_drawdown']:.1f}%  W4={w4['max_drawdown']:.1f}%"),
    ]
    met = sum(1 for _, p, _ in criteria if p)
    if met >= 5:
        verdict = "PASS"
    elif met >= 3:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"
    return verdict, criteria, met


# ─────────────────────────────────────────────────────────────────────────────
# Print table
# ─────────────────────────────────────────────────────────────────────────────
SEP  = "═" * 84
SEP2 = "─" * 84


def _print_table(label: str, stats_list: list[dict]) -> None:
    print(f"\n{SEP}")
    print(f"  {label}")
    print(SEP)
    print(f"  {'Window':<12} {'Rebal':>6} {'WR%':>6} {'Return':>8} "
          f"{'Sharpe':>7} {'MaxDD':>7} {'AvgPos':>7} {'%Cash':>7}")
    print(f"  {SEP2}")
    for (wname, _, _), s in zip(WINDOWS, stats_list):
        wr_s   = f"{s['win_rate']:.0f}%"    if s["win_rate"]  is not None else "—"
        sh_s   = f"{s['sharpe']:.3f}"       if s["sharpe"]    is not None else "—"
        ret_s  = f"{s['total_return']:+.1f}%"
        dd_s   = f"{s['max_drawdown']:.1f}%"
        ap_s   = f"{s['avg_positions']:.1f}"
        pc_s   = f"{s['pct_in_cash']:.0f}%"
        print(f"  {wname:<12} {s['rebalances']:>6} {wr_s:>6} {ret_s:>8} "
              f"{sh_s:>7} {dd_s:>7} {ap_s:>7} {pc_s:>7}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    print(SEP)
    print("  DUAL MOMENTUM COMMODITY BACKTEST — Primary 12-1 + Robustness Checks")
    print(f"  Universe: {', '.join(UNIVERSE)}")
    print(f"  Strategy: top-{TOP_N} equal-weight | absolute gate | monthly rebalance | TC=0.05%")
    print(f"  Data range: {FETCH_START} → {FETCH_END}")
    print(SEP)

    # ── Load prices ────────────────────────────────────────────────────────
    prices = load_price_matrix()

    available = [t for t in UNIVERSE if t in prices.columns]
    missing   = [t for t in UNIVERSE if t not in prices.columns]
    print(f"\n  Available: {len(available)}/12 tickers")
    if missing:
        print(f"  Missing:   {', '.join(missing)}")

    # Confirm inception
    print("\n  Instrument first-bar dates:")
    for ticker in UNIVERSE:
        if ticker in prices.columns:
            inc = prices[ticker].dropna().index[0].date()
            print(f"    {ticker:<8} {inc}")
        else:
            print(f"    {ticker:<8} NO DATA")

    # ─────────────────────────────────────────────────────────────────────
    # PRIMARY: 12-1 momentum (formation=252, skip=21)
    # ─────────────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  STEP 2 — PRIMARY: 12-1 Momentum (formation=252 days, skip=21 days)")
    print(SEP)

    primary_results = []
    primary_stats   = []
    for wname, wstart, wend in WINDOWS:
        print(f"  → {wname} ({wstart} → {wend})", flush=True)
        res   = run_window(prices, wstart, wend,
                           formation_long=FORMATION_LONG, formation_skip=FORMATION_SKIP)
        stats = _window_stats(res)
        primary_results.append(res)
        primary_stats.append(stats)
        print(f"     return={stats['total_return']:+.1f}%  sharpe={stats['sharpe']}  "
              f"maxDD={stats['max_drawdown']:.1f}%  WR={stats['win_rate']}%  "
              f"avgPos={stats['avg_positions']}  cash%={stats['pct_in_cash']:.0f}%")

    primary_pooled = _pooled_stats(primary_results)
    _print_table("DUAL MOMENTUM — 12-1 (Primary)", primary_stats)
    print(f"\n  POOLED ({primary_pooled['monthly_obs']} months): "
          f"Sharpe={primary_pooled['sharpe']}  "
          f"Total P&L: {primary_pooled['total_return']:+.1f}% across all windows")

    # ─────────────────────────────────────────────────────────────────────
    # STEP 3 — Robustness checks
    # ─────────────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  STEP 3 — ROBUSTNESS: 6-month (126-21) and 3-month (63, no skip)")
    print(SEP)

    # 6-month: formation=126, skip=21
    print("\n  Running 6-month formation (126-21)...")
    six_results, six_stats = [], []
    for wname, wstart, wend in WINDOWS:
        res   = run_window(prices, wstart, wend, formation_long=126, formation_skip=21)
        stats = _window_stats(res)
        six_results.append(res)
        six_stats.append(stats)
    six_pooled = _pooled_stats(six_results)
    _print_table("ROBUSTNESS — 6-month (126-21)", six_stats)
    print(f"\n  POOLED ({six_pooled['monthly_obs']} months): Sharpe={six_pooled['sharpe']}  "
          f"Total P&L: {six_pooled['total_return']:+.1f}%")

    # 3-month: formation=63, skip=0
    print("\n  Running 3-month formation (63, no skip)...")
    three_results, three_stats = [], []
    for wname, wstart, wend in WINDOWS:
        res   = run_window(prices, wstart, wend, formation_long=63, formation_skip=0)
        stats = _window_stats(res)
        three_results.append(res)
        three_stats.append(stats)
    three_pooled = _pooled_stats(three_results)
    _print_table("ROBUSTNESS — 3-month (63, no skip)", three_stats)
    print(f"\n  POOLED ({three_pooled['monthly_obs']} months): Sharpe={three_pooled['sharpe']}  "
          f"Total P&L: {three_pooled['total_return']:+.1f}%")

    # ─────────────────────────────────────────────────────────────────────
    # STEP 4 — Pass/fail
    # ─────────────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  STEP 4 — PASS / MARGINAL / FAIL (PRIMARY 12-1 config only)")
    print(SEP)
    verdict, criteria, met = _evaluate(primary_stats, primary_pooled)
    print(f"\n  Criteria ({met}/5 met):")
    for label, passed, detail in criteria:
        mark = "✅" if passed else "❌"
        print(f"    {mark} {label} — {detail}")
    stars = {"PASS": "✅  PASS", "MARGINAL": "⚠️  MARGINAL", "FAIL": "❌  FAIL"}
    print(f"\n  ┌─ VERDICT: {stars[verdict]} ─┐")

    # ─────────────────────────────────────────────────────────────────────
    # STEP 5 — Comparison table
    # ─────────────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  STEP 5 — COMPARISON: Dual Momentum vs Jerome v2 vs Buck Futures")
    print(SEP)
    print(f"\n  {'Strategy':<30} {'Pooled Sharpe':>14} {'Windows +':>10} {'Verdict':>10}")
    print(f"  {'─'*64}")
    print(f"  {'Jerome v2 (EMA trend)':<30} {'-0.143':>14} {'1/5':>10} {'FAIL':>10}")
    print(f"  {'Buck Futures (EMA trend)':<30} {'-0.169':>14} {'3/5':>10} {'FAIL':>10}")

    pos_windows = sum(1 for s in primary_stats if s["total_return"] > 0)
    dm_sharpe   = str(primary_pooled["sharpe"]) if primary_pooled["sharpe"] is not None else "—"
    print(f"  {'Dual Momentum (12-1)':<30} {dm_sharpe:>14} {f'{pos_windows}/5':>10} {verdict:>10}")

    # Robustness summary
    print(f"\n  Robustness (pooled Sharpe across formation variants):")
    print(f"    12-1 (primary)  : {primary_pooled['sharpe']}")
    print(f"    6-month (126-21): {six_pooled['sharpe']}")
    print(f"    3-month (63)    : {three_pooled['sharpe']}")

    print(f"\n{SEP}")


if __name__ == "__main__":
    main()
