"""
oos_validation.py — Out-of-sample validation for Jerome v2 + Buck Futures.

LOCKED PARAMETERS — copied exactly from live strategy files:
  jerome_v2_strategy.py:     TRAIL_ATR_MULT=5.0, ADX_LONG_MIN=30, ADX_SHORT_MIN=25,
                              RISK_PER_TRADE=0.04, SINGLE_POS_CAP=0.50
  buck_futures_strategy.py:  identical parameters, different universe

This is READ-ONLY backtest. No live orders, no DB writes, no strategy changes.

Run:
    cd kraken-bot
    python3 oos_validation.py
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
# EXACT live strategy parameters — do not change
# ─────────────────────────────────────────────────────────────────────────────
TRAIL_ATR_MULT  = 5.0     # jerome_v2_strategy.py line 46
ADX_LONG_MIN    = 30      # jerome_v2_strategy.py line 44
ADX_SHORT_MIN   = 25      # jerome_v2_strategy.py line 45
RISK_PER_TRADE  = 0.04    # jerome_v2_strategy.py line 42
SINGLE_POS_CAP  = 0.50    # jerome_v2_strategy.py line 43
MAX_POSITIONS   = 6       # jerome_v2_strategy.py line 47
THEME_CAP       = 2       # jerome_v2_strategy.py line 48
STARTING_CAPITAL = 100_000.0

# Universes — copied exactly from live strategy files
JEROME_UNIVERSE: dict[str, list[str]] = {
    "ENERGY":          ["XLE", "USO", "XOP"],
    "PRECIOUS_METALS": ["GLD", "SLV", "GDX", "GDXJ"],
}
BUCK_UNIVERSE: dict[str, list[str]] = {
    "INDUSTRIAL": ["DBB", "PICK"],
    "BROAD":      ["DBC", "PDBC", "GSG"],
}

# 5 non-overlapping OOS windows
WINDOWS = [
    ("W1 2019",    date(2019, 1, 1), date(2019, 12, 31)),
    ("W2 2020",    date(2020, 1, 1), date(2020, 12, 31)),
    ("W3 2021",    date(2021, 1, 1), date(2021, 12, 31)),
    ("W4 2022",    date(2022, 1, 1), date(2022, 12, 31)),
    ("W5 2023-24", date(2023, 1, 1), date(2024, 12, 31)),
]

# Fetch far enough back for EMA200 warm-up before W1 (200 trading days ~ 10 months)
FETCH_START = date(2018, 1, 1)
FETCH_END   = date(2025, 1, 3)

_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


# ─────────────────────────────────────────────────────────────────────────────
# Data fetching
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_yahoo(ticker: str) -> Optional[pd.DataFrame]:
    """Fetch daily OHLCV from FETCH_START to FETCH_END via Yahoo Finance v8."""
    p1 = int(datetime(FETCH_START.year, FETCH_START.month, FETCH_START.day).timestamp())
    p2 = int(datetime(FETCH_END.year, FETCH_END.month, FETCH_END.day).timestamp())
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

        opens  = q.get("open",  [None] * len(ts))
        highs  = q.get("high",  [None] * len(ts))
        lows   = q.get("low",   [None] * len(ts))
        closes = q.get("close", [None] * len(ts))
        adjc   = adj[0].get("adjclose", closes) if adj else closes

        rows = [
            (datetime.utcfromtimestamp(ts[i]).date(),
             opens[i], highs[i], lows[i], closes[i], adjc[i])
            for i in range(len(ts))
            if None not in (opens[i], highs[i], lows[i], closes[i])
        ]
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "adjclose"])
        df.set_index("date", inplace=True)
        df.sort_index(inplace=True)
        return df
    except Exception as exc:
        print(f"  WARN: {ticker} fetch failed — {exc}")
        return None


def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add EMA21/55/200, ADX14, ATR14 to df in-place."""
    import ta
    c, h, l = df["close"], df["high"], df["low"]
    df["ema21"]  = ta.trend.EMAIndicator(c, window=21).ema_indicator()
    df["ema55"]  = ta.trend.EMAIndicator(c, window=55).ema_indicator()
    df["ema200"] = ta.trend.EMAIndicator(c, window=200).ema_indicator()
    df["adx"]    = ta.trend.ADXIndicator(h, l, c, window=14).adx()
    df["atr"]    = ta.volatility.AverageTrueRange(h, l, c, window=14).average_true_range()
    return df


def _load_universe(universe: dict[str, list[str]]) -> dict[str, pd.DataFrame]:
    all_tickers = [t for ts in universe.values() for t in ts]
    print(f"  Fetching {len(all_tickers)} tickers: {', '.join(all_tickers)}")
    data: dict[str, pd.DataFrame] = {}
    for ticker in all_tickers:
        print(f"    {ticker:<8}", end=" ", flush=True)
        df = _fetch_yahoo(ticker)
        if df is None or len(df) < 220:
            print("SKIP (insufficient data)")
            continue
        df = _add_indicators(df)
        inception = df.index[0]
        print(f"OK  ({len(df)} rows, inception={inception})")
        data[ticker] = df
        time.sleep(0.3)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Signal generation — matches jerome_v2_strategy._build_signal exactly
# ─────────────────────────────────────────────────────────────────────────────
def _get_signal(df: pd.DataFrame, dt: date) -> Optional[str]:
    if dt not in df.index:
        return None
    idx = df.index.get_loc(dt)
    if idx < 1:
        return None
    row  = df.loc[dt]
    prev = df.iloc[idx - 1]

    c, pc = float(row["close"]), float(prev["close"])
    e21, e55, e200 = float(row["ema21"]), float(row["ema55"]), float(row["ema200"])
    adx = float(row["adx"])

    if any(math.isnan(v) for v in [c, pc, e21, e55, e200, adx]):
        return None

    # Long: c > EMA200 AND EMA21 > EMA55 AND ADX >= 30 AND c > prev_close
    if c > e200 and e21 > e55 and adx >= ADX_LONG_MIN and c > pc:
        return "long"
    # Short: c < EMA200 AND EMA21 < EMA55 AND ADX >= 25 AND c < prev_close
    if c < e200 and e21 < e55 and adx >= ADX_SHORT_MIN and c < pc:
        return "short"
    return None


def _trend_score(df: pd.DataFrame, dt: date) -> float:
    """abs((EMA21-EMA55)/EMA55) × (ADX/100) — matches _build_signal score formula."""
    if dt not in df.index:
        return 0.0
    row = df.loc[dt]
    e21 = float(row.get("ema21", 0) or 0)
    e55 = float(row.get("ema55", 1) or 1)
    adx = float(row.get("adx", 0) or 0)
    if e55 == 0:
        return 0.0
    return abs((e21 - e55) / e55) * (adx / 100.0)


# ─────────────────────────────────────────────────────────────────────────────
# Position record
# ─────────────────────────────────────────────────────────────────────────────
class Position:
    __slots__ = ["ticker", "theme", "direction", "qty", "entry_price",
                 "notional", "entry_date", "trailing_stop", "highest_fav", "entry_atr"]

    def __init__(self, ticker, theme, direction, qty, entry_price,
                 notional, entry_date, initial_stop, entry_atr):
        self.ticker        = ticker
        self.theme         = theme
        self.direction     = direction
        self.qty           = qty
        self.entry_price   = entry_price
        self.notional      = notional
        self.entry_date    = entry_date
        self.trailing_stop = initial_stop
        self.highest_fav   = entry_price
        self.entry_atr     = entry_atr


# ─────────────────────────────────────────────────────────────────────────────
# Backtest engine (exact live strategy logic, no shorting toggle — mirrors live code)
# ─────────────────────────────────────────────────────────────────────────────
def run_window(
    data: dict[str, pd.DataFrame],
    universe: dict[str, list[str]],
    start: date,
    end: date,
) -> dict:
    ticker_theme = {t: theme for theme, tickers in universe.items() for t in tickers}
    all_tickers  = list(ticker_theme.keys())

    # Only tickers with data covering this window
    tradeable = [
        t for t in all_tickers
        if t in data and not data[t].loc[(data[t].index >= start) & (data[t].index <= end)].empty
    ]

    all_dates: list[date] = sorted({
        d for t in tradeable
        for d in data[t].index
        if start <= d <= end
    })

    equity          = STARTING_CAPITAL
    cash            = STARTING_CAPITAL
    open_positions: list[Position] = []
    closed_trades:  list[dict]     = []
    equity_curve:   list[tuple]    = []
    peak_equity     = STARTING_CAPITAL
    max_drawdown    = 0.0

    for dt in all_dates:
        # ── 1. Manage exits (trailing stop + regime flip) ──────────────────
        still_open: list[Position] = []
        for pos in open_positions:
            df = data.get(pos.ticker)
            if df is None or dt not in df.index:
                still_open.append(pos)
                continue

            row   = df.loc[dt]
            close = float(row["close"])
            atr   = float(row["atr"]) if not pd.isna(row["atr"]) else pos.entry_atr
            e200  = float(row["ema200"]) if not pd.isna(row["ema200"]) else None

            exit_reason = None

            if pos.direction == "long":
                # Ratchet highest_fav upward
                if close > pos.highest_fav:
                    pos.highest_fav = close
                # Update trailing stop (ratchet upward)
                if atr > 0:
                    new_stop = pos.highest_fav - TRAIL_ATR_MULT * atr
                    pos.trailing_stop = max(pos.trailing_stop, new_stop)
                # Exit checks — matches _manage_exits exactly
                if close < pos.trailing_stop:
                    exit_reason = "trailing_stop"
                elif e200 is not None and close < e200:
                    exit_reason = "regime_flip"

            else:  # short
                # Ratchet highest_fav downward (lowest seen)
                if pos.highest_fav == pos.entry_price or close < pos.highest_fav:
                    pos.highest_fav = close
                # Update trailing stop (ratchet downward)
                if atr > 0:
                    new_stop = pos.highest_fav + TRAIL_ATR_MULT * atr
                    pos.trailing_stop = min(pos.trailing_stop, new_stop)
                if close > pos.trailing_stop:
                    exit_reason = "trailing_stop"
                elif e200 is not None and close > e200:
                    exit_reason = "regime_flip"

            if exit_reason:
                pnl_usd = (close - pos.entry_price) * pos.qty
                if pos.direction == "short":
                    pnl_usd = -pnl_usd
                hold_days = (dt - pos.entry_date).days
                cash     += pos.notional + pnl_usd
                equity   += pnl_usd
                closed_trades.append({
                    "ticker":      pos.ticker,
                    "theme":       pos.theme,
                    "direction":   pos.direction,
                    "entry_date":  pos.entry_date,
                    "exit_date":   dt,
                    "hold_days":   hold_days,
                    "entry_price": pos.entry_price,
                    "exit_price":  close,
                    "qty":         pos.qty,
                    "notional":    pos.notional,
                    "pnl_usd":     round(pnl_usd, 2),
                    "pnl_pct":     round(pnl_usd / pos.notional * 100, 2) if pos.notional else 0,
                    "exit_reason": exit_reason,
                })
            else:
                still_open.append(pos)

        open_positions = still_open

        # ── 2. Mark-to-market equity ──────────────────────────────────────
        mtm = cash
        for pos in open_positions:
            df = data.get(pos.ticker)
            if df is not None and dt in df.index:
                close = float(df.loc[dt, "close"])
                if pos.direction == "long":
                    mtm += pos.notional + (close - pos.entry_price) * pos.qty
                else:
                    mtm += pos.notional - (close - pos.entry_price) * pos.qty
            else:
                mtm += pos.notional
        equity = mtm
        equity_curve.append((dt, round(equity, 2)))

        if equity > peak_equity:
            peak_equity = equity
        dd = (peak_equity - equity) / peak_equity * 100
        if dd > max_drawdown:
            max_drawdown = dd

        # ── 3. Entry scan ─────────────────────────────────────────────────
        themes_open  = defaultdict(int)
        tickers_open = {p.ticker for p in open_positions}
        for p in open_positions:
            themes_open[p.theme] += 1

        if len(open_positions) >= MAX_POSITIONS:
            continue

        candidates: list[tuple[float, str, str]] = []
        for ticker in tradeable:
            df = data.get(ticker)
            if df is None or dt not in df.index:
                continue
            sig = _get_signal(df, dt)
            if sig is None:
                continue
            score = _trend_score(df, dt)
            candidates.append((score, ticker, sig))

        candidates.sort(key=lambda x: x[0], reverse=True)

        for score, ticker, sig in candidates:
            if len(open_positions) >= MAX_POSITIONS:
                break
            if ticker in tickers_open:
                continue
            theme = ticker_theme[ticker]
            if themes_open[theme] >= THEME_CAP:
                continue

            df  = data[ticker]
            row = df.loc[dt]
            close = float(row["close"])
            atr   = float(row["atr"]) if not pd.isna(row["atr"]) else 0.0

            if close <= 0 or atr <= 0:
                continue

            risk_usd  = equity * RISK_PER_TRADE
            stop_dist = TRAIL_ATR_MULT * atr
            qty       = risk_usd / stop_dist
            notional  = qty * close

            # Single-position cap (50%)
            cap = equity * SINGLE_POS_CAP
            if notional > cap:
                qty      = cap / close
                notional = cap

            if notional < 500 or notional > cash:
                continue

            # Open position
            if sig == "long":
                initial_stop = close - stop_dist
            else:
                initial_stop = close + stop_dist

            pos = Position(
                ticker=ticker, theme=theme, direction=sig,
                qty=qty, entry_price=close, notional=notional,
                entry_date=dt, initial_stop=initial_stop, entry_atr=atr,
            )
            open_positions.append(pos)
            cash -= notional
            tickers_open.add(ticker)
            themes_open[theme] += 1

    # ── Force-close open positions at window end ──────────────────────────
    last_dt = all_dates[-1] if all_dates else end
    for pos in open_positions:
        df = data.get(pos.ticker)
        if df is not None:
            avail = df[df.index <= last_dt]
            close = float(avail["close"].iloc[-1]) if not avail.empty else pos.entry_price
        else:
            close = pos.entry_price
        pnl_usd   = (close - pos.entry_price) * pos.qty * (1 if pos.direction == "long" else -1)
        hold_days = (last_dt - pos.entry_date).days
        closed_trades.append({
            "ticker": pos.ticker, "theme": pos.theme, "direction": pos.direction,
            "entry_date": pos.entry_date, "exit_date": last_dt, "hold_days": hold_days,
            "entry_price": pos.entry_price, "exit_price": close, "qty": pos.qty,
            "notional": pos.notional,
            "pnl_usd":  round(pnl_usd, 2),
            "pnl_pct":  round(pnl_usd / pos.notional * 100, 2) if pos.notional else 0,
            "exit_reason": "forced_close_eow",
        })

    return {
        "equity_curve":  equity_curve,
        "closed_trades": closed_trades,
        "max_drawdown":  round(max_drawdown, 2),
        "final_equity":  round(equity_curve[-1][1] if equity_curve else STARTING_CAPITAL, 2),
        "tradeable":     tradeable,
        "universe_total": len(all_tickers),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Per-window stats
# ─────────────────────────────────────────────────────────────────────────────
def _window_stats(result: dict, start: date, end: date) -> dict:
    trades       = result["closed_trades"]
    eq_curve     = result["equity_curve"]
    final_equity = result["final_equity"]
    max_dd       = result["max_drawdown"]

    n_trades  = len(trades)
    total_ret = (final_equity - STARTING_CAPITAL) / STARTING_CAPITAL * 100

    if n_trades == 0:
        return {
            "trades": 0, "win_rate": None, "total_return": total_ret,
            "sharpe": None, "max_drawdown": max_dd, "avg_hold": None,
            "best_trade": None, "worst_trade": None,
            "tradeable": result["tradeable"],
            "universe_total": result["universe_total"],
        }

    winners = [t for t in trades if t["pnl_usd"] > 0]
    win_rate = len(winners) / n_trades * 100

    eq_series = pd.Series(
        [e for _, e in eq_curve],
        index=pd.DatetimeIndex([pd.Timestamp(d) for d, _ in eq_curve])
    )
    daily_ret = eq_series.pct_change().dropna()
    sharpe    = (daily_ret.mean() / daily_ret.std() * math.sqrt(252)
                 if len(daily_ret) > 1 and daily_ret.std() > 0 else None)

    pnl_pcts  = [t["pnl_pct"] for t in trades]
    avg_hold  = sum(t["hold_days"] for t in trades) / n_trades
    best      = max(trades, key=lambda t: t["pnl_pct"])
    worst     = min(trades, key=lambda t: t["pnl_pct"])

    return {
        "trades":       n_trades,
        "win_rate":     round(win_rate, 1),
        "total_return": round(total_ret, 2),
        "sharpe":       round(sharpe, 3) if sharpe is not None else None,
        "max_drawdown": max_dd,
        "avg_hold":     round(avg_hold, 1),
        "best_trade":   f"{best['ticker']} {best['pnl_pct']:+.1f}%",
        "worst_trade":  f"{worst['ticker']} {worst['pnl_pct']:+.1f}%",
        "tradeable":    result["tradeable"],
        "universe_total": result["universe_total"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pooled stats (all windows combined)
# ─────────────────────────────────────────────────────────────────────────────
def _pooled_stats(all_results: list[dict]) -> dict:
    all_trades = []
    all_eq: list[tuple] = []
    for r in all_results:
        all_trades.extend(r["closed_trades"])
        all_eq.extend(r["equity_curve"])

    if not all_trades:
        return {"trades": 0, "win_rate": None, "sharpe": None, "total_return": None}

    # For pooled Sharpe, concatenate equity curves in order
    all_eq.sort(key=lambda x: x[0])
    eq_series = pd.Series([e for _, e in all_eq],
                          index=pd.DatetimeIndex([pd.Timestamp(d) for d, _ in all_eq]))
    daily_ret = eq_series.pct_change().dropna()
    sharpe    = (daily_ret.mean() / daily_ret.std() * math.sqrt(252)
                 if len(daily_ret) > 1 and daily_ret.std() > 0 else None)

    n         = len(all_trades)
    winners   = [t for t in all_trades if t["pnl_usd"] > 0]
    win_rate  = len(winners) / n * 100

    # Total return: compound across windows
    total_pnl = sum(t["pnl_usd"] for t in all_trades)
    total_ret = total_pnl / STARTING_CAPITAL * 100

    return {
        "trades":        n,
        "win_rate":      round(win_rate, 1),
        "sharpe":        round(sharpe, 3) if sharpe is not None else None,
        "total_return":  round(total_ret, 2),
        "avg_hold":      round(sum(t["hold_days"] for t in all_trades) / n, 1),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pass/Fail evaluation
# ─────────────────────────────────────────────────────────────────────────────
def _evaluate(window_stats: list[dict], pooled: dict, bot_name: str) -> str:
    """Apply the 5 criteria defined in Step 4 upfront."""
    stats = window_stats  # list of per-window stat dicts

    # 1. Positive total return in >= 4 of 5 windows
    pos_return = sum(1 for s in stats if s["total_return"] is not None and s["total_return"] > 0)

    # 2. Positive Sharpe in >= 4 of 5 windows
    pos_sharpe = sum(1 for s in stats if s["sharpe"] is not None and s["sharpe"] > 0)

    # 3. No single window worse than -20% max drawdown
    no_catastrophic_dd = all(s["max_drawdown"] < 20.0 for s in stats)

    # 4. Pooled Sharpe >= 0.5
    pooled_sharpe_ok = pooled["sharpe"] is not None and pooled["sharpe"] >= 0.5

    # 5. Survived both stress windows (W2=2020, W4=2022) without > -25% drawdown
    w2 = stats[1]  # 2020
    w4 = stats[3]  # 2022
    stress_ok = w2["max_drawdown"] < 25.0 and w4["max_drawdown"] < 25.0

    criteria = [
        ("Positive return ≥4/5 windows", pos_return >= 4, f"{pos_return}/5"),
        ("Positive Sharpe ≥4/5 windows",  pos_sharpe >= 4, f"{pos_sharpe}/5"),
        ("No window MaxDD > 20%",          no_catastrophic_dd, f"{'OK' if no_catastrophic_dd else 'FAIL'}"),
        ("Pooled Sharpe ≥ 0.5",            pooled_sharpe_ok,   f"{pooled['sharpe']}"),
        ("Survived stress windows <25% DD",stress_ok,          f"W2={w2['max_drawdown']:.1f}% W4={w4['max_drawdown']:.1f}%"),
    ]

    met = sum(1 for _, passed, _ in criteria if passed)

    if met >= 5:
        verdict = "PASS"
    elif met >= 3:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"

    return verdict, criteria, met


# ─────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────
SEP  = "═" * 78
SEP2 = "─" * 78


def _print_table(bot_name: str, window_results: list, window_stats_list: list) -> None:
    print(f"\n{SEP}")
    print(f"  {bot_name} — OUT-OF-SAMPLE RESULTS")
    print(SEP)
    print(f"  {'Window':<12} {'Tradeable':>10} {'Trades':>7} {'WR%':>6} "
          f"{'Return':>8} {'Sharpe':>7} {'MaxDD':>7} {'AvgHold':>8} "
          f"{'Best':>20} {'Worst':>20}")
    print(f"  {SEP2}")
    for (wname, wstart, wend), stats in zip(WINDOWS, window_stats_list):
        n_tradeable = len(stats["tradeable"])
        n_universe  = stats["universe_total"]
        tradeable_s = f"{n_tradeable}/{n_universe}"
        trades_s    = str(stats["trades"]) if stats["trades"] else "0"
        wr_s        = f"{stats['win_rate']:.0f}%" if stats["win_rate"] is not None else "—"
        ret_s       = f"{stats['total_return']:+.1f}%" if stats["total_return"] is not None else "—"
        sharpe_s    = f"{stats['sharpe']:.2f}" if stats["sharpe"] is not None else "—"
        dd_s        = f"{stats['max_drawdown']:.1f}%"
        hold_s      = f"{stats['avg_hold']:.0f}d" if stats["avg_hold"] is not None else "—"
        best_s      = stats["best_trade"] or "—"
        worst_s     = stats["worst_trade"] or "—"
        print(f"  {wname:<12} {tradeable_s:>10} {trades_s:>7} {wr_s:>6} "
              f"{ret_s:>8} {sharpe_s:>7} {dd_s:>7} {hold_s:>8} "
              f"{best_s:>20} {worst_s:>20}")


def _print_verdict(bot_name: str, verdict: str, criteria: list, met: int,
                   pooled: dict, in_sample_sharpe: Optional[float] = None) -> None:
    print(f"\n  PASS/FAIL criteria ({met}/5 met):")
    for label, passed, detail in criteria:
        mark = "✅" if passed else "❌"
        print(f"    {mark} {label} — {detail}")

    print(f"\n  OVERALL POOLED:")
    print(f"    Trades: {pooled['trades']}  |  Win rate: {pooled.get('win_rate', '—')}%  |  "
          f"Sharpe: {pooled.get('sharpe', '—')}  |  Avg hold: {pooled.get('avg_hold', '—')}d")

    stars = {"PASS": "✅ PASS", "MARGINAL": "⚠️  MARGINAL", "FAIL": "❌ FAIL"}
    print(f"\n  ┌─ VERDICT: {stars[verdict]} ─┐")

    if in_sample_sharpe is not None:
        oos_sharpe = pooled.get("sharpe")
        if oos_sharpe is not None:
            ratio = oos_sharpe / in_sample_sharpe
            if ratio >= 0.7:
                assessment = "HONEST — OOS within 30% of in-sample (real edge)"
            elif ratio >= 0.4:
                assessment = "DEGRADED — OOS materially below in-sample (regime luck?)"
            else:
                assessment = "COLLAPSE — OOS << in-sample (likely curve-fit)"
            print(f"  In-sample Sharpe: {in_sample_sharpe:.3f} | OOS pooled Sharpe: {oos_sharpe:.3f} "
                  f"| ratio: {ratio:.2f} → {assessment}")


# ─────────────────────────────────────────────────────────────────────────────
# Inception date report
# ─────────────────────────────────────────────────────────────────────────────
def _report_inception(all_data: dict[str, pd.DataFrame], universe: dict) -> None:
    all_tickers = [t for ts in universe.values() for t in ts]
    print(f"\n  Instrument inception dates:")
    for ticker in all_tickers:
        if ticker in all_data:
            inception = all_data[ticker].index[0]
            avail_w   = [wname for wname, ws, we in WINDOWS
                         if not all_data[ticker].loc[
                             (all_data[ticker].index >= ws) &
                             (all_data[ticker].index <= we)
                         ].empty]
            print(f"    {ticker:<8} first bar: {inception}  →  tradeable in: {', '.join(avail_w)}")
        else:
            print(f"    {ticker:<8} NO DATA")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    print(SEP)
    print("  OUT-OF-SAMPLE VALIDATION — Jerome v2 + Buck Futures")
    print(f"  Parameters: TRAIL_ATR={TRAIL_ATR_MULT}x  ADX_LONG≥{ADX_LONG_MIN}  "
          f"RISK={RISK_PER_TRADE*100:.0f}%  POS_CAP={SINGLE_POS_CAP*100:.0f}%  "
          f"MAX_POS={MAX_POSITIONS}  THEME_CAP={THEME_CAP}")
    print(f"  Data range: {FETCH_START} → {FETCH_END}")
    print(SEP)

    # ── Load data ──────────────────────────────────────────────────────────
    print("\n[1/2] Loading Jerome v2 universe data...")
    jerome_data = _load_universe(JEROME_UNIVERSE)

    print("\n[2/2] Loading Buck Futures universe data...")
    buck_data   = _load_universe(BUCK_UNIVERSE)

    # ── Inception date report ──────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  STEP 1 — INSTRUMENT AVAILABILITY")
    print(SEP)
    print("  Jerome v2 universe (7 instruments):")
    _report_inception(jerome_data, JEROME_UNIVERSE)
    print("  Buck Futures universe (5 instruments):")
    _report_inception(buck_data, BUCK_UNIVERSE)

    # ── Run Jerome v2 windows ──────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  STEP 3 — RUNNING JEROME v2 WINDOWS")
    print(SEP)
    jerome_results = []
    jerome_stats   = []
    for wname, wstart, wend in WINDOWS:
        print(f"  → {wname} ({wstart} → {wend})", flush=True)
        res   = run_window(jerome_data, JEROME_UNIVERSE, wstart, wend)
        stats = _window_stats(res, wstart, wend)
        jerome_results.append(res)
        jerome_stats.append(stats)
        print(f"     trades={stats['trades']} WR={stats['win_rate']}% "
              f"return={stats['total_return']:+.1f}% sharpe={stats['sharpe']} "
              f"maxDD={stats['max_drawdown']:.1f}%")

    jerome_pooled = _pooled_stats(jerome_results)

    # ── Run Buck Futures windows ──────────────────────────────────────────
    print(f"\n{SEP}")
    print("  STEP 3 — RUNNING BUCK FUTURES WINDOWS")
    print(SEP)
    buck_results = []
    buck_stats   = []
    for wname, wstart, wend in WINDOWS:
        print(f"  → {wname} ({wstart} → {wend})", flush=True)
        res   = run_window(buck_data, BUCK_UNIVERSE, wstart, wend)
        stats = _window_stats(res, wstart, wend)
        buck_results.append(res)
        buck_stats.append(stats)
        print(f"     trades={stats['trades']} WR={stats['win_rate']}% "
              f"return={stats['total_return']:+.1f}% sharpe={stats['sharpe']} "
              f"maxDD={stats['max_drawdown']:.1f}%")

    buck_pooled = _pooled_stats(buck_results)

    # ── Print tables ──────────────────────────────────────────────────────
    _print_table("JEROME v2", jerome_results, jerome_stats)
    _print_table("BUCK FUTURES", buck_results, buck_stats)

    # ── Verdicts ──────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  STEP 4 — PASS / FAIL VERDICTS")
    print(SEP)

    print("\n  ── Jerome v2 ──")
    j_verdict, j_criteria, j_met = _evaluate(jerome_stats, jerome_pooled, "Jerome v2")
    _print_verdict("Jerome v2", j_verdict, j_criteria, j_met, jerome_pooled,
                   in_sample_sharpe=0.996)

    print("\n  ── Buck Futures ──")
    b_verdict, b_criteria, b_met = _evaluate(buck_stats, buck_pooled, "Buck Futures")
    _print_verdict("Buck Futures", b_verdict, b_criteria, b_met, buck_pooled,
                   in_sample_sharpe=None)

    # ── Backtest strategy note ─────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  STEP 1 — BACKTEST vs LIVE STRATEGY COMPARISON")
    print(SEP)
    print("  This validation uses the EXACT live parameters:")
    print(f"    TRAIL_ATR_MULT : {TRAIL_ATR_MULT}  (original backtest used 3.0 — DIFFERENT)")
    print(f"    ADX_LONG_MIN   : {ADX_LONG_MIN}   (original backtest used 20  — DIFFERENT)")
    print(f"    RISK_PER_TRADE : {RISK_PER_TRADE*100:.0f}%  (original backtest used 1.5% — DIFFERENT)")
    print(f"    SINGLE_POS_CAP : {SINGLE_POS_CAP*100:.0f}%  (original backtest used 25% — DIFFERENT)")
    print(f"    Universe       : live (7+5 tickers) not broad (22 tickers)")
    print(f"  The +33.95%/Sharpe 0.996 in-sample result was from the ORIGINAL")
    print(f"  broader/looser params. This OOS test validates the CURRENT live params.")
    print(SEP)


if __name__ == "__main__":
    main()
