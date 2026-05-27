"""
jerome_v2_backtest.py — Jerome v2 commodity trend-following strategy backtest.

Period : 2024-01-01 → 2026-05-01 (~28 months)
Capital: $100,000 starting equity
Signal : EMA21/55/200 + ADX(14) + ATR(14) trailing stop

Run:
    cd kraken-bot
    python3.11 jerome_v2_backtest.py

Results are printed to stdout. No DB writes, no live orders.
"""
from __future__ import annotations

import os
import sys
import math
import json
import time
import requests
import warnings
from datetime import date, datetime, timedelta
from collections import defaultdict
from typing import Optional

import pandas as pd
import numpy as np

warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

# ─────────────────────────────────────────────────────────────────────────────
# Universe (22 instruments, 6 themes)
# ─────────────────────────────────────────────────────────────────────────────
UNIVERSE: dict[str, list[str]] = {
    "ENERGY":          ["XLE", "USO", "XOP", "UNG"],
    "PRECIOUS_METALS": ["GLD", "SLV", "GDX", "GDXJ"],
    "INDUSTRIAL":      ["COPX", "DBB", "PICK"],
    "AGRICULTURE":     ["DBA", "WEAT", "CORN", "SOYB", "MOO"],
    "FERTILISER":      ["NTR", "MOS", "CF"],
    "BROAD":           ["DBC", "PDBC", "GSG"],
}

ALL_TICKERS = [t for tickers in UNIVERSE.values() for t in tickers]
TICKER_THEME = {t: theme for theme, tickers in UNIVERSE.items() for t in tickers}

# ─────────────────────────────────────────────────────────────────────────────
# Strategy parameters
# ─────────────────────────────────────────────────────────────────────────────
START_DATE        = date(2024, 1, 1)
END_DATE          = date(2026, 5, 1)
STARTING_CAPITAL  = 100_000.0
RISK_PER_TRADE    = 0.015         # 1.5% of equity
TRAIL_ATR_MULT    = 3.0           # trailing stop = highest - 3×ATR
MAX_POSITIONS     = 6
THEME_CAP         = 2
SINGLE_POS_CAP    = 0.25          # 25% of equity per position
LONG_ADX_MIN      = 20
SHORT_ADX_MIN     = 25
FETCH_DAYS        = 950           # warm-up (~200d EMA200) + 28m simulation
SHORTING_ENABLED  = True          # confirmed via Alpaca API
_YAHOO_HEADERS    = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


# ─────────────────────────────────────────────────────────────────────────────
# Data fetching (Yahoo Finance v8 — same path as alpaca_etf_engine.py)
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_yahoo(ticker: str, days: int = FETCH_DAYS) -> Optional[pd.DataFrame]:
    url    = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"range": f"{days}d", "interval": "1d"}
    try:
        resp = requests.get(url, params=params, headers=_YAHOO_HEADERS, timeout=20)
        if resp.status_code != 200:
            return None
        data   = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return None
        r      = result[0]
        ts     = r.get("timestamp", [])
        q      = r.get("indicators", {}).get("quote", [{}])[0]
        adj    = r.get("indicators", {}).get("adjclose", [{}])
        opens  = q.get("open",   [None]*len(ts))
        highs  = q.get("high",   [None]*len(ts))
        lows   = q.get("low",    [None]*len(ts))
        closes = q.get("close",  [None]*len(ts))
        adjc   = adj[0].get("adjclose", closes) if adj else closes
        rows   = [
            (datetime.utcfromtimestamp(ts[i]).date(), opens[i], highs[i], lows[i], closes[i], adjc[i])
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
    """Add EMA21/55/200, ADX14, ATR14 columns in-place."""
    import ta
    c = df["close"]
    h = df["high"]
    l = df["low"]
    df["ema21"]  = ta.trend.EMAIndicator(c, window=21).ema_indicator()
    df["ema55"]  = ta.trend.EMAIndicator(c, window=55).ema_indicator()
    df["ema200"] = ta.trend.EMAIndicator(c, window=200).ema_indicator()
    df["adx"]    = ta.trend.ADXIndicator(h, l, c, window=14).adx()
    df["atr"]    = ta.volatility.AverageTrueRange(h, l, c, window=14).average_true_range()
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Load all data
# ─────────────────────────────────────────────────────────────────────────────
def load_all_data() -> dict[str, pd.DataFrame]:
    print(f"Fetching {len(ALL_TICKERS)} tickers from Yahoo Finance...")
    data: dict[str, pd.DataFrame] = {}
    for i, ticker in enumerate(ALL_TICKERS, 1):
        print(f"  [{i:02d}/{len(ALL_TICKERS)}] {ticker:<8}", end=" ")
        df = _fetch_yahoo(ticker)
        if df is None or len(df) < 220:
            print("SKIP (insufficient data)")
            continue
        df = _add_indicators(df)
        df = df[df.index >= START_DATE - timedelta(days=5)]   # keep a little pre-start for context
        data[ticker] = df
        print(f"OK  ({len(df)} rows, {df.index[0]} → {df.index[-1]})")
        time.sleep(0.25)   # polite to Yahoo
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Signal generation
# ─────────────────────────────────────────────────────────────────────────────
def _get_signal(df: pd.DataFrame, dt: date) -> Optional[str]:
    """Return 'long', 'short', or None for a given date."""
    if dt not in df.index:
        return None
    idx = df.index.get_loc(dt)
    if idx < 1:
        return None
    row  = df.loc[dt]
    prev = df.iloc[idx - 1]

    c, p = row["close"], prev["close"]
    e21, e55, e200 = row["ema21"], row["ema55"], row["ema200"]
    adx = row["adx"]

    if any(pd.isna(v) for v in [c, p, e21, e55, e200, adx]):
        return None

    if c > e200 and e21 > e55 and adx >= LONG_ADX_MIN and c > p:
        return "long"
    if SHORTING_ENABLED and c < e200 and e21 < e55 and adx >= SHORT_ADX_MIN and c < p:
        return "short"
    return None


def _trend_score(df: pd.DataFrame, dt: date) -> float:
    """abs((EMA21-EMA55)/EMA55) × (ADX/100). Higher = stronger trend."""
    if dt not in df.index:
        return 0.0
    row = df.loc[dt]
    e21, e55, adx = row.get("ema21", 0), row.get("ema55", 1), row.get("adx", 0)
    if pd.isna(e55) or e55 == 0:
        return 0.0
    return abs((e21 - e55) / e55) * (adx / 100.0)


# ─────────────────────────────────────────────────────────────────────────────
# Position record
# ─────────────────────────────────────────────────────────────────────────────
class Position:
    __slots__ = [
        "ticker", "theme", "direction", "qty", "entry_price",
        "notional", "entry_date", "trailing_stop", "highest_fav",
        "entry_atr",
    ]

    def __init__(self, ticker: str, theme: str, direction: str,
                 qty: float, entry_price: float, notional: float,
                 entry_date: date, initial_stop: float, entry_atr: float):
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
# Main simulation loop
# ─────────────────────────────────────────────────────────────────────────────
def run_backtest(data: dict[str, pd.DataFrame]) -> dict:
    # Collect all trading dates in range across all tickers
    all_dates: list[date] = sorted({
        d for df in data.values()
        for d in df.index
        if START_DATE <= d <= END_DATE
    })

    equity          = STARTING_CAPITAL
    cash            = STARTING_CAPITAL
    open_positions: list[Position] = []
    closed_trades:  list[dict]     = []
    equity_curve:   list[tuple]    = []   # (date, equity)
    peak_equity     = STARTING_CAPITAL
    max_drawdown    = 0.0

    # Per-instrument diagnostics
    signal_count:   dict[str, int] = defaultdict(int)
    cap_trigger:    dict[str, int] = defaultdict(int)

    for dt in all_dates:
        # ── 1. Update trailing stops + check exits ────────────────────────
        still_open: list[Position] = []
        for pos in open_positions:
            df = data.get(pos.ticker)
            if df is None or dt not in df.index:
                still_open.append(pos)
                continue

            row     = df.loc[dt]
            close   = row["close"]
            atr     = row["atr"]
            e200    = row["ema200"]

            if pd.isna(close):
                still_open.append(pos)
                continue

            exit_reason = None

            if pos.direction == "long":
                # Update highest favourable
                if close > pos.highest_fav:
                    pos.highest_fav = close
                # Update trailing stop
                if not pd.isna(atr) and atr > 0:
                    new_stop = pos.highest_fav - TRAIL_ATR_MULT * atr
                    pos.trailing_stop = max(pos.trailing_stop, new_stop)
                # Check exits
                if close < pos.trailing_stop:
                    exit_reason = "trailing_stop"
                elif not pd.isna(e200) and close < e200:
                    exit_reason = "regime_flip"

            else:  # short
                # Update lowest favourable
                if close < pos.highest_fav:
                    pos.highest_fav = close
                # Update trailing stop (for shorts: stop moves DOWN as price falls)
                if not pd.isna(atr) and atr > 0:
                    new_stop = pos.highest_fav + TRAIL_ATR_MULT * atr
                    pos.trailing_stop = min(pos.trailing_stop, new_stop)
                # Check exits
                if close > pos.trailing_stop:
                    exit_reason = "trailing_stop"
                elif not pd.isna(e200) and close > e200:
                    exit_reason = "regime_flip"

            if exit_reason:
                pnl_usd  = (close - pos.entry_price) * pos.qty
                if pos.direction == "short":
                    pnl_usd = -pnl_usd
                hold_days = (dt - pos.entry_date).days
                cash     += pos.notional + pnl_usd
                equity   += pnl_usd
                closed_trades.append({
                    "ticker":       pos.ticker,
                    "theme":        pos.theme,
                    "direction":    pos.direction,
                    "entry_date":   pos.entry_date,
                    "exit_date":    dt,
                    "hold_days":    hold_days,
                    "entry_price":  pos.entry_price,
                    "exit_price":   close,
                    "qty":          pos.qty,
                    "notional":     pos.notional,
                    "pnl_usd":      round(pnl_usd, 2),
                    "pnl_pct":      round(pnl_usd / pos.notional * 100, 2),
                    "exit_reason":  exit_reason,
                })
            else:
                still_open.append(pos)

        open_positions = still_open

        # ── 2. Mark-to-market equity ──────────────────────────────────────
        mtm = cash
        for pos in open_positions:
            df = data.get(pos.ticker)
            if df is not None and dt in df.index:
                mtm += pos.notional + (df.loc[dt, "close"] - pos.entry_price) * pos.qty * (
                    1 if pos.direction == "long" else -1
                )
            else:
                mtm += pos.notional
        equity = mtm
        equity_curve.append((dt, round(equity, 2)))

        # Drawdown tracking
        if equity > peak_equity:
            peak_equity = equity
        dd = (peak_equity - equity) / peak_equity * 100
        if dd > max_drawdown:
            max_drawdown = dd

        # ── 3. Generate entry signals ─────────────────────────────────────
        # Count open by theme
        themes_open = defaultdict(int)
        tickers_open = {p.ticker for p in open_positions}
        for p in open_positions:
            themes_open[p.theme] += 1

        if len(open_positions) >= MAX_POSITIONS:
            continue

        # Score each candidate
        candidates: list[tuple[float, str, str]] = []   # (score, ticker, signal)
        for ticker in ALL_TICKERS:
            df = data.get(ticker)
            if df is None or dt not in df.index:
                continue
            sig = _get_signal(df, dt)
            if sig is None:
                continue
            signal_count[ticker] += 1
            score = _trend_score(df, dt)
            candidates.append((score, ticker, sig))

        # Sort by score descending — enter strongest trends first
        candidates.sort(key=lambda x: x[0], reverse=True)

        for score, ticker, sig in candidates:
            if len(open_positions) >= MAX_POSITIONS:
                break

            theme = TICKER_THEME[ticker]

            # Guard: already holding
            if ticker in tickers_open:
                continue

            # Guard: theme cap
            if themes_open[theme] >= THEME_CAP:
                continue

            df  = data.get(ticker)
            row = df.loc[dt]
            close = row["close"]
            atr   = row["atr"]

            if pd.isna(close) or pd.isna(atr) or atr <= 0:
                continue

            # Guard: capital check
            risk_usd   = equity * RISK_PER_TRADE
            stop_dist  = TRAIL_ATR_MULT * atr
            qty        = risk_usd / stop_dist
            notional   = qty * close

            # Single position cap
            cap = equity * SINGLE_POS_CAP
            if notional > cap:
                cap_trigger[ticker] += 1
                qty      = cap / close
                notional = cap

            if notional > cash:
                continue   # insufficient cash

            # Open position
            if sig == "long":
                initial_stop = close - stop_dist
                highest_fav  = close
            else:
                initial_stop = close + stop_dist
                highest_fav  = close

            pos = Position(
                ticker=ticker, theme=theme, direction=sig,
                qty=qty, entry_price=close, notional=notional,
                entry_date=dt, initial_stop=initial_stop, entry_atr=atr,
            )
            open_positions.append(pos)
            cash -= notional
            tickers_open.add(ticker)
            themes_open[theme] += 1

    # ── Force-close remaining open positions at last date ─────────────────
    last_dt = all_dates[-1] if all_dates else END_DATE
    for pos in open_positions:
        df = data.get(pos.ticker)
        if df is not None:
            avail = df[df.index <= last_dt]
            close = float(avail["close"].iloc[-1]) if not avail.empty else pos.entry_price
        else:
            close = pos.entry_price
        pnl_usd = (close - pos.entry_price) * pos.qty * (1 if pos.direction == "long" else -1)
        hold_days = (last_dt - pos.entry_date).days
        closed_trades.append({
            "ticker": pos.ticker, "theme": pos.theme, "direction": pos.direction,
            "entry_date": pos.entry_date, "exit_date": last_dt, "hold_days": hold_days,
            "entry_price": pos.entry_price, "exit_price": close, "qty": pos.qty,
            "notional": pos.notional, "pnl_usd": round(pnl_usd, 2),
            "pnl_pct": round(pnl_usd / pos.notional * 100 if pos.notional else 0, 2),
            "exit_reason": "forced_close_eob",
        })

    return {
        "equity_curve":  equity_curve,
        "closed_trades": closed_trades,
        "signal_count":  dict(signal_count),
        "cap_triggers":  dict(cap_trigger),
        "max_drawdown":  round(max_drawdown, 2),
        "final_equity":  round(equity_curve[-1][1] if equity_curve else STARTING_CAPITAL, 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────────
def compute_metrics(results: dict) -> None:
    trades        = results["closed_trades"]
    equity_curve  = results["equity_curve"]
    signal_count  = results["signal_count"]
    cap_triggers  = results["cap_triggers"]
    max_dd        = results["max_drawdown"]
    final_equity  = results["final_equity"]

    eq_series = pd.Series(
        [e for _, e in equity_curve],
        index=[d for d, _ in equity_curve],
    )

    # ── Overall metrics ────────────────────────────────────────────────────
    total_return = (final_equity - STARTING_CAPITAL) / STARTING_CAPITAL * 100
    n_years      = (END_DATE - START_DATE).days / 365.25
    ann_return   = ((final_equity / STARTING_CAPITAL) ** (1 / n_years) - 1) * 100

    # Sharpe on daily returns
    daily_ret    = eq_series.pct_change().dropna()
    sharpe       = (daily_ret.mean() / daily_ret.std()) * math.sqrt(252) if daily_ret.std() > 0 else 0.0

    n_trades     = len(trades)
    winners      = [t for t in trades if t["pnl_usd"] > 0]
    losers       = [t for t in trades if t["pnl_usd"] <= 0]
    win_rate     = len(winners) / n_trades * 100 if n_trades else 0
    avg_win      = sum(t["pnl_usd"] for t in winners) / len(winners) if winners else 0
    avg_loss     = sum(t["pnl_usd"] for t in losers)  / len(losers)  if losers  else 0
    expectancy   = (win_rate/100 * avg_win) + ((1 - win_rate/100) * avg_loss)
    avg_hold     = sum(t["hold_days"] for t in trades) / n_trades if n_trades else 0

    SEP  = "═" * 68
    SEP2 = "─" * 68

    print(f"\n{SEP}")
    print("JEROME v2 BACKTEST — OVERALL METRICS")
    print(f"Period: {START_DATE} → {END_DATE}  ({n_years:.1f} years)")
    print(SEP)
    print(f"  Starting capital : ${STARTING_CAPITAL:>12,.2f}")
    print(f"  Final equity     : ${final_equity:>12,.2f}")
    print(f"  Total return     : {total_return:>+8.2f}%")
    print(f"  Ann. return      : {ann_return:>+8.2f}%")
    print(f"  Sharpe (ann.)    : {sharpe:>8.3f}")
    print(f"  Max drawdown     : {max_dd:>8.2f}%")
    print(f"  Total trades     : {n_trades:>8d}")
    print(f"  Win rate         : {win_rate:>8.1f}%")
    print(f"  Avg winner       : ${avg_win:>+10,.2f}")
    print(f"  Avg loser        : ${avg_loss:>+10,.2f}")
    print(f"  Expectancy       : ${expectancy:>+10,.2f} per trade")
    print(f"  Avg hold (days)  : {avg_hold:>8.1f}")

    go_no_go = (
        sharpe    >= 0.5 and
        max_dd    <= 25  and
        win_rate  >= 40  and
        n_trades  >= 20  and
        sum(1 for v in signal_count.values() if v > 0) >= 12
    )
    print(f"\n  GO / NO-GO : {'✅  GO' if go_no_go else '🚫  NO-GO'}")
    print(f"  Thresholds : Sharpe≥0.5 {'✅' if sharpe>=0.5 else '❌'} "
          f"| MaxDD≤25% {'✅' if max_dd<=25 else '❌'} "
          f"| WR≥40% {'✅' if win_rate>=40 else '❌'} "
          f"| Trades≥20 {'✅' if n_trades>=20 else '❌'} "
          f"| Instruments≥12 {'✅' if sum(1 for v in signal_count.values() if v>0)>=12 else '❌'}")

    # ── Per-theme breakdown ────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("PER-THEME BREAKDOWN")
    print(SEP)
    print(f"  {'Theme':<18} {'Trades':>6} {'WR%':>6} {'Total P&L':>12} {'Avg Hold':>9}")
    print(f"  {SEP2}")
    for theme in UNIVERSE:
        tt = [t for t in trades if t["theme"] == theme]
        if not tt:
            print(f"  {theme:<18} {'—':>6}")
            continue
        w  = [t for t in tt if t["pnl_usd"] > 0]
        wr = len(w)/len(tt)*100
        pl = sum(t["pnl_usd"] for t in tt)
        ah = sum(t["hold_days"] for t in tt) / len(tt)
        print(f"  {theme:<18} {len(tt):>6} {wr:>6.1f}% {pl:>+12,.2f} {ah:>9.1f}d")

    # ── Per-instrument breakdown ────────────────────────────────────────────
    print(f"\n{SEP}")
    print("PER-INSTRUMENT BREAKDOWN")
    print(SEP)
    print(f"  {'Ticker':<7} {'Theme':<16} {'Sigs':>5} {'Trades':>6} "
          f"{'WR%':>6} {'P&L':>10} {'AvgHold':>8} {'CapHits':>8}")
    print(f"  {SEP2}")
    for ticker in ALL_TICKERS:
        tt   = [t for t in trades if t["ticker"] == ticker]
        sigs = signal_count.get(ticker, 0)
        caps = cap_triggers.get(ticker, 0)
        theme = TICKER_THEME[ticker]
        if not tt:
            print(f"  {ticker:<7} {theme:<16} {sigs:>5}   —  (no trades)")
            continue
        w  = [t for t in tt if t["pnl_usd"] > 0]
        wr = len(w)/len(tt)*100
        pl = sum(t["pnl_usd"] for t in tt)
        ah = sum(t["hold_days"] for t in tt)/len(tt)
        print(f"  {ticker:<7} {theme:<16} {sigs:>5} {len(tt):>6} "
              f"{wr:>6.1f}% {pl:>+10,.2f} {ah:>8.1f}d {caps:>8}")

    # ── Top 5 / Bottom 5 ────────────────────────────────────────────────────
    per_ticker_pnl = defaultdict(float)
    for t in trades:
        per_ticker_pnl[t["ticker"]] += t["pnl_usd"]
    ranked = sorted(per_ticker_pnl.items(), key=lambda x: x[1], reverse=True)

    print(f"\n{SEP}")
    print("TOP 5 INSTRUMENTS (by total P&L)")
    print(SEP)
    for i, (ticker, pnl) in enumerate(ranked[:5], 1):
        print(f"  {i}. {ticker:<7}  {pnl:>+10,.2f}")

    print(f"\n{SEP}")
    print("BOTTOM 5 INSTRUMENTS (by total P&L)")
    print(SEP)
    for i, (ticker, pnl) in enumerate(ranked[-5:][::-1], 1):
        print(f"  {i}. {ticker:<7}  {pnl:>+10,.2f}")

    # ── Diagnostic flags ────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("DIAGNOSTIC FLAGS")
    print(SEP)

    zero_signal = [t for t in ALL_TICKERS if signal_count.get(t, 0) == 0]
    if zero_signal:
        print(f"  ⚠  ZERO SIGNALS: {', '.join(zero_signal)}")
        print(f"     These instruments never passed ADX/EMA filters — consider removing.")
    else:
        print(f"  ✅  All instruments generated at least 1 signal.")

    high_caps = [(t, n) for t, n in cap_triggers.items() if n >= 2]
    if high_caps:
        print(f"  ⚠  25% CAP TRIGGERED REPEATEDLY:")
        for t, n in sorted(high_caps, key=lambda x: x[1], reverse=True):
            print(f"     {t}: {n}x — notional sizing exceeds 25% cap (wide ATR vs price)")
    else:
        print(f"  ✅  25% cap not triggered repeatedly.")

    # ATR/price ratio per instrument
    print(f"\n  ATR-to-price ratio (higher = more volatile sizing):")
    atr_ratios = []
    for ticker, sigs in signal_count.items():
        if sigs == 0:
            continue
        tts = [t for t in trades if t["ticker"] == ticker]
        if tts:
            # Use first trade's atr from entry
            pass
    # Compute from trade data if possible
    print(f"  (See per-instrument cap_hits column above for sizing pressure)")

    # Exit reason breakdown
    reasons = defaultdict(int)
    for t in trades:
        reasons[t["exit_reason"]] += 1
    print(f"\n  Exit reason breakdown:")
    for reason, cnt in sorted(reasons.items(), key=lambda x: x[1], reverse=True):
        print(f"    {reason:<25} {cnt:>4} trades  ({cnt/n_trades*100:.1f}%)")

    # Max per-position drawdown from entry to trailing stop
    stop_trades = [t for t in trades if t["exit_reason"] == "trailing_stop"]
    if stop_trades:
        worst_dd_trade = min(stop_trades, key=lambda t: t["pnl_pct"])
        print(f"\n  Worst trailing-stop exit:  {worst_dd_trade['ticker']} "
              f"{worst_dd_trade['pnl_pct']:+.1f}%  ({worst_dd_trade['hold_days']}d held)")

    print(f"\n{SEP}")
    print("END OF BACKTEST REPORT")
    print(SEP)

    # Return go/no-go for caller
    return go_no_go


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("═" * 68)
    print("JEROME v2 BACKTEST — COMMODITY TREND FOLLOWING")
    print("═" * 68)
    print(f"Period          : {START_DATE} → {END_DATE}")
    print(f"Universe        : {len(ALL_TICKERS)} instruments, {len(UNIVERSE)} themes")
    print(f"Capital         : ${STARTING_CAPITAL:,.0f}")
    print(f"Risk/trade      : {RISK_PER_TRADE*100:.1f}% of equity")
    print(f"Trailing stop   : {TRAIL_ATR_MULT:.1f}× ATR(14)")
    print(f"Shorting        : {'ENABLED' if SHORTING_ENABLED else 'DISABLED'}")
    print(f"Max positions   : {MAX_POSITIONS}  (theme cap: {THEME_CAP})")
    print()

    t0   = time.time()
    data = load_all_data()

    n_loaded = len(data)
    print(f"\nLoaded {n_loaded}/{len(ALL_TICKERS)} tickers in {time.time()-t0:.1f}s")
    if n_loaded < 15:
        print("ERROR: too few tickers loaded — check network. Aborting.")
        sys.exit(1)

    print("\nRunning simulation...")
    t1      = time.time()
    results = run_backtest(data)
    print(f"Simulation complete in {time.time()-t1:.1f}s — "
          f"{len(results['closed_trades'])} trades closed")

    go = compute_metrics(results)
    sys.exit(0 if go else 1)
