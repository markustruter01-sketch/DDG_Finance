#!/usr/bin/env python3
"""
forex_v2_backtest.py — Forex Gump v2 Strategy Backtest
=======================================================
28-month backtest (2024-01-01 to 2026-05-01) of the proposed mechanical
trend-following strategy for Forex Gump v2.

Strategy:
  Long:  close > EMA200, EMA21 > EMA55, ADX >= 30, close > prev_close
  Short: close < EMA200, EMA21 < EMA55, ADX >= 25, close < prev_close
  Exit:  5×ATR trailing stop  OR  EMA200 regime flip
  Size:  1.5% risk / (5×ATR), capped at 30% equity per position
  Max:   4 concurrent positions  |  Daily cycle
"""

import math
import sys
from datetime import datetime, timezone
from typing import Optional

# ── Universe ───────────────────────────────────────────────────────────────────
PAIRS       = ["EURUSD=X", "GBPUSD=X", "AUDUSD=X", "NZDUSD=X", "JPY=X", "CAD=X", "CHF=X"]
COUNTER_USD = {"EURUSD=X", "GBPUSD=X", "AUDUSD=X", "NZDUSD=X"}
BASE_USD    = {"JPY=X", "CAD=X", "CHF=X"}

# ── Parameters ─────────────────────────────────────────────────────────────────
RISK_PCT       = 0.015
TRAIL_ATR_MULT = 5.0
STOP_ATR_MULT  = 5.0
EMA_FAST       = 21
EMA_SLOW       = 55
EMA_TREND      = 200
ADX_LONG_MIN   = 30
ADX_SHORT_MIN  = 25
MAX_POSITIONS  = 4
CAP_PCT        = 0.30

SIM_START        = "2024-01-01"
SIM_END          = "2026-05-01"
STARTING_EQUITY  = 100_000.0

_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

# ── Data fetch ─────────────────────────────────────────────────────────────────
def _fetch_daily_ohlcv(ticker: str, days: int = 1200) -> Optional[list]:
    import requests
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"range": f"{days}d", "interval": "1d"}
    try:
        resp = requests.get(url, params=params, headers=_YAHOO_HEADERS, timeout=20)
        if resp.status_code != 200:
            return None
        data   = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return None
        r          = result[0]
        timestamps = r.get("timestamp", [])
        quotes     = r.get("indicators", {}).get("quote", [{}])[0]
        rows = []
        for ts, o, h, l, c in zip(
            timestamps,
            quotes.get("open",  []),
            quotes.get("high",  []),
            quotes.get("low",   []),
            quotes.get("close", []),
        ):
            if None in (o, h, l, c):
                continue
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            rows.append({"date": dt, "open": float(o), "high": float(h),
                         "low": float(l), "close": float(c)})
        return rows or None
    except Exception as exc:
        print(f"  [WARN] Yahoo fetch failed for {ticker}: {exc}")
        return None

# ── Indicators ─────────────────────────────────────────────────────────────────
def _ema_series(prices: list, period: int) -> list:
    n = len(prices)
    if n < period:
        return [None] * n
    k      = 2.0 / (period + 1)
    result = [None] * (period - 1)
    ema    = sum(prices[:period]) / period
    result.append(ema)
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
        result.append(ema)
    return result


def _atr_series(highs: list, lows: list, closes: list, period: int = 14) -> list:
    n = len(closes)
    trs = [None]
    for i in range(1, n):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i]  - closes[i - 1]))
        trs.append(tr)
    if n < period + 1:
        return [None] * n
    result = [None] * period
    atr    = sum(trs[1:period + 1]) / period
    result.append(atr)
    for i in range(period + 1, n):
        atr = (atr * (period - 1) + trs[i]) / period
        result.append(atr)
    return result


def _adx_series(highs: list, lows: list, closes: list, period: int = 14) -> list:
    n = len(closes)

    plus_dm, minus_dm, trs = [0.0], [0.0], [0.0]
    for i in range(1, n):
        up   = highs[i]  - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up   if (up > down   and up > 0)   else 0.0)
        minus_dm.append(down if (down > up  and down > 0) else 0.0)
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i]  - closes[i - 1])))

    def _wilder_smooth(arr, p):
        out  = [None] * p
        seed = sum(arr[1:p + 1])
        out.append(seed)
        val = seed
        for i in range(p + 1, len(arr)):
            val = val - val / p + arr[i]
            out.append(val)
        return out

    s_pdm = _wilder_smooth(plus_dm,  period)
    s_mdm = _wilder_smooth(minus_dm, period)
    s_tr  = _wilder_smooth(trs,      period)

    dx_list = [None] * (period + 1)
    for i in range(period + 1, n):
        tr_v = s_tr[i]
        if not tr_v:
            dx_list.append(None)
            continue
        pdi   = 100.0 * s_pdm[i] / tr_v
        mdi   = 100.0 * s_mdm[i] / tr_v
        denom = pdi + mdi
        dx_list.append(100.0 * abs(pdi - mdi) / denom if denom else 0.0)

    first = next((i for i, v in enumerate(dx_list) if v is not None), None)
    if first is None or first + period > len(dx_list):
        return [None] * n

    seed_vals = [v for v in dx_list[first: first + period] if v is not None]
    if len(seed_vals) < period:
        return [None] * n

    adx_result = [None] * (first + period - 1)
    adx        = sum(seed_vals) / period
    adx_result.append(adx)
    for i in range(first + period, len(dx_list)):
        dx_v = dx_list[i]
        if dx_v is None:
            adx_result.append(None)
        else:
            adx = (adx * (period - 1) + dx_v) / period
            adx_result.append(adx)

    while len(adx_result) < n:
        adx_result.append(None)
    return adx_result

# ── P&L + sizing ───────────────────────────────────────────────────────────────
def _pnl_usd(direction: str, entry: float, exit_price: float,
             units: float, pair: str) -> float:
    raw = ((exit_price - entry) if direction == "long"
           else (entry - exit_price)) * units
    return raw / exit_price if pair in BASE_USD else raw


def _size_units(equity: float, price: float, atr: float, pair: str) -> float:
    risk_usd  = equity * RISK_PCT
    stop_dist = STOP_ATR_MULT * atr
    if pair in COUNTER_USD:
        units     = risk_usd / stop_dist
        pos_value = units * price
    else:
        units     = risk_usd * price / stop_dist
        pos_value = units / price
    cap_usd = equity * CAP_PCT
    if pos_value > cap_usd:
        units *= cap_usd / pos_value
    return units

# ── Main ───────────────────────────────────────────────────────────────────────
def run_backtest():
    print("=" * 70)
    print("  FOREX GUMP v2 — 28-Month Backtest (2024-01-01 → 2026-05-01)")
    print("=" * 70)
    print()

    pair_data = {}
    for pair in PAIRS:
        print(f"  Fetching {pair}...", end=" ", flush=True)
        rows = _fetch_daily_ohlcv(pair, days=1200)
        if not rows:
            print("FAILED")
            continue
        pair_data[pair] = rows
        print(f"{len(rows)} bars  [{rows[0]['date']} → {rows[-1]['date']}]")
    print()

    if len(pair_data) < 5:
        print("ERROR: fewer than 5 pairs fetched. Aborting.")
        return

    sim_dates = sorted({r["date"]
                        for rows in pair_data.values()
                        for r in rows
                        if SIM_START <= r["date"] <= SIM_END})
    print(f"  Sim window: {sim_dates[0]} → {sim_dates[-1]}  ({len(sim_dates)} bars)\n")

    print("  Computing indicators...", flush=True)
    indicators = {}
    for pair, rows in pair_data.items():
        closes = [r["close"] for r in rows]
        highs  = [r["high"]  for r in rows]
        lows   = [r["low"]   for r in rows]
        indicators[pair] = {
            "dates":    [r["date"] for r in rows],
            "closes":   closes,
            "highs":    highs,
            "lows":     lows,
            "ema21":    _ema_series(closes, EMA_FAST),
            "ema55":    _ema_series(closes, EMA_SLOW),
            "ema200":   _ema_series(closes, EMA_TREND),
            "atr14":    _atr_series(highs, lows, closes),
            "adx14":    _adx_series(highs, lows, closes),
            "date_idx": {r["date"]: i for i, r in enumerate(rows)},
        }
    print("  Done.\n")

    equity        = STARTING_EQUITY
    positions     = {}
    trades        = []
    signal_counts = {p: 0 for p in PAIRS}
    cap_fires     = {p: 0 for p in PAIRS}

    for date in sim_dates:

        # ── Exit pass ────────────────────────────────────────────────────────
        to_close = []
        for pair, pos in positions.items():
            ind = indicators.get(pair, {})
            idx = ind["date_idx"].get(date)
            if idx is None:
                continue
            closes = ind["closes"]
            highs  = ind["highs"]
            lows   = ind["lows"]
            close  = closes[idx]
            high   = highs[idx]
            low    = lows[idx]
            ema200 = ind["ema200"][idx]
            atr    = ind["atr14"][idx]
            direction  = pos["direction"]
            trail_stop = pos["trail_stop"]
            extreme    = pos["extreme_price"]

            if atr:
                if direction == "long":
                    if high > extreme:
                        extreme = high
                        pos["extreme_price"] = high
                    new_trail = extreme - TRAIL_ATR_MULT * atr
                    if new_trail > trail_stop:
                        trail_stop = new_trail
                        pos["trail_stop"] = trail_stop
                else:
                    if low < extreme:
                        extreme = low
                        pos["extreme_price"] = low
                    new_trail = extreme + TRAIL_ATR_MULT * atr
                    if new_trail < trail_stop:
                        trail_stop = new_trail
                        pos["trail_stop"] = trail_stop

            exit_reason = None
            exit_price  = close
            if direction == "long":
                if low <= trail_stop:
                    exit_reason = "trailing_stop"
                    exit_price  = trail_stop
                elif ema200 and close < ema200:
                    exit_reason = "regime_flip"
            else:
                if high >= trail_stop:
                    exit_reason = "trailing_stop"
                    exit_price  = trail_stop
                elif ema200 and close > ema200:
                    exit_reason = "regime_flip"

            if exit_reason:
                pnl = _pnl_usd(direction, pos["entry"], exit_price, pos["units"], pair)
                equity += pnl
                hold_days = len([d for d in sim_dates if pos["entry_date"] <= d <= date])
                trades.append({
                    "pair":       pair,
                    "direction":  direction,
                    "entry_date": pos["entry_date"],
                    "exit_date":  date,
                    "entry":      pos["entry"],
                    "exit":       exit_price,
                    "units":      pos["units"],
                    "pnl_usd":    round(pnl, 2),
                    "reason":     exit_reason,
                    "hold_days":  hold_days,
                })
                to_close.append(pair)

        for pair in to_close:
            del positions[pair]

        # ── Entry pass ───────────────────────────────────────────────────────
        if len(positions) >= MAX_POSITIONS:
            continue

        for pair in PAIRS:
            if pair in positions or len(positions) >= MAX_POSITIONS:
                continue
            ind = indicators.get(pair)
            if ind is None:
                continue
            idx = ind["date_idx"].get(date)
            if idx is None or idx < 1:
                continue

            close      = ind["closes"][idx]
            prev_close = ind["closes"][idx - 1]
            ema21      = ind["ema21"][idx]
            ema55      = ind["ema55"][idx]
            ema200     = ind["ema200"][idx]
            adx        = ind["adx14"][idx]
            atr        = ind["atr14"][idx]

            if None in (ema21, ema55, ema200, adx, atr) or atr <= 0:
                continue

            long_sig  = (close > ema200 and ema21 > ema55
                         and adx >= ADX_LONG_MIN  and close > prev_close)
            short_sig = (close < ema200 and ema21 < ema55
                         and adx >= ADX_SHORT_MIN and close < prev_close)

            direction = ("long" if long_sig else "short" if short_sig else None)
            if not direction:
                continue

            signal_counts[pair] += 1
            units = _size_units(equity, close, atr, pair)

            pos_val = units * close if pair in COUNTER_USD else units / close
            if pos_val >= equity * CAP_PCT * 0.99:
                cap_fires[pair] += 1

            stop_dist  = STOP_ATR_MULT * atr
            trail_stop = (close - stop_dist) if direction == "long" else (close + stop_dist)

            positions[pair] = {
                "direction":    direction,
                "entry":        close,
                "units":        units,
                "trail_stop":   trail_stop,
                "extreme_price": close,
                "entry_date":   date,
            }

    # Force-close any still-open at end
    last_date = sim_dates[-1] if sim_dates else SIM_END
    for pair, pos in list(positions.items()):
        ind       = indicators.get(pair, {})
        idx       = ind.get("date_idx", {}).get(last_date)
        exit_px   = ind["closes"][idx] if idx is not None else pos["entry"]
        pnl       = _pnl_usd(pos["direction"], pos["entry"], exit_px, pos["units"], pair)
        equity   += pnl
        hold_days = len([d for d in sim_dates if pos["entry_date"] <= d <= last_date])
        trades.append({
            "pair": pair, "direction": pos["direction"],
            "entry_date": pos["entry_date"], "exit_date": last_date,
            "entry": pos["entry"], "exit": exit_px,
            "units": pos["units"], "pnl_usd": round(pnl, 2),
            "reason": "end_of_test", "hold_days": hold_days,
        })

    _report(trades, equity, sim_dates, signal_counts, cap_fires)


def _report(trades, final_equity, sim_dates, signal_counts, cap_fires):
    n       = len(trades)
    winners = [t for t in trades if t["pnl_usd"] > 0]
    losers  = [t for t in trades if t["pnl_usd"] <= 0]

    total_ret  = (final_equity - STARTING_EQUITY) / STARTING_EQUITY * 100
    win_rate   = len(winners) / n * 100 if n else 0
    avg_win    = sum(t["pnl_usd"] for t in winners) / len(winners) if winners else 0
    avg_loss   = sum(t["pnl_usd"] for t in losers)  / len(losers)  if losers  else 0
    expectancy = (win_rate / 100) * avg_win + (1 - win_rate / 100) * avg_loss if n else 0
    avg_hold   = sum(t["hold_days"] for t in trades) / n if n else 0

    daily_pnl = {}
    for t in trades:
        daily_pnl[t["exit_date"]] = daily_pnl.get(t["exit_date"], 0.0) + t["pnl_usd"]

    running       = STARTING_EQUITY
    daily_returns = []
    for d in sim_dates:
        pnl = daily_pnl.get(d, 0.0)
        daily_returns.append(pnl / running if running else 0.0)
        running += pnl

    mu  = sum(daily_returns) / len(daily_returns) if daily_returns else 0
    var = sum((r - mu) ** 2 for r in daily_returns) / len(daily_returns) if daily_returns else 0
    std = math.sqrt(var) if var > 0 else 1e-9
    sharpe = (mu / std) * math.sqrt(252)

    peak   = STARTING_EQUITY
    curve  = STARTING_EQUITY
    max_dd = 0.0
    for d in sim_dates:
        curve += daily_pnl.get(d, 0.0)
        peak   = max(peak, curve)
        max_dd = max(max_dd, (peak - curve) / peak)

    print("=" * 70)
    print("  OVERALL METRICS")
    print("=" * 70)
    print(f"  {'Starting equity':<32} ${STARTING_EQUITY:>12,.2f}")
    print(f"  {'Final equity':<32} ${final_equity:>12,.2f}")
    print(f"  {'Total return':<32} {total_ret:>12.1f}%")
    print(f"  {'Sharpe (annualised)':<32} {sharpe:>12.2f}")
    print(f"  {'Max drawdown':<32} {max_dd * 100:>12.1f}%")
    print(f"  {'Win rate':<32} {win_rate:>11.1f}%  ({len(winners)}/{n})")
    print(f"  {'Avg winner':<32} ${avg_win:>12,.2f}")
    print(f"  {'Avg loser':<32} ${avg_loss:>12,.2f}")
    print(f"  {'Expectancy per trade':<32} ${expectancy:>12,.2f}")
    print(f"  {'Total trades':<32} {n:>12d}")
    print(f"  {'Avg hold (days)':<32} {avg_hold:>12.1f}")

    pairs_with_signals = sum(1 for p in PAIRS if signal_counts[p] > 0)

    print()
    print("=" * 70)
    print("  GO / NO-GO THRESHOLDS")
    print("=" * 70)
    checks = [
        ("Sharpe >= 0.50",           sharpe,              sharpe >= 0.5),
        ("Max drawdown <= 20%",      max_dd * 100,        max_dd <= 0.20),
        ("Win rate >= 33%",          win_rate,            win_rate >= 33.0),
        ("Trade count >= 15",        float(n),            n >= 15),
        ("Pairs with signals >= 5",  float(pairs_with_signals), pairs_with_signals >= 5),
    ]
    all_pass = True
    for label, val, ok in checks:
        status    = "PASS" if ok else "FAIL"
        all_pass  = all_pass and ok
        print(f"  [{status}]  {label:<30}  actual: {val:.2f}")

    print()
    verdict = "GO — proceed to Phase B (build)" if all_pass else "NO-GO — adjust parameters before building"
    print(f"  VERDICT: {verdict}")

    print()
    print("=" * 70)
    print("  PER-PAIR BREAKDOWN")
    print("=" * 70)
    hdr = f"  {'Pair':<12} {'Signals':>8} {'Trades':>7} {'WR%':>6} {'AvgHold':>8} {'TotalPnL':>12} {'CapFires':>9}"
    print(hdr)
    print("  " + "-" * 65)
    for pair in PAIRS:
        pt   = [t for t in trades if t["pair"] == pair]
        sigs = signal_counts[pair]
        n_pt = len(pt)
        if n_pt == 0:
            print(f"  {pair:<12} {sigs:>8} {'—':>7} {'—':>6} {'—':>8} {'—':>12} {cap_fires[pair]:>9}")
            continue
        wr   = len([t for t in pt if t["pnl_usd"] > 0]) / n_pt * 100
        ah   = sum(t["hold_days"] for t in pt) / n_pt
        tp   = sum(t["pnl_usd"] for t in pt)
        print(f"  {pair:<12} {sigs:>8} {n_pt:>7} {wr:>6.1f} {ah:>8.1f} ${tp:>11,.2f} {cap_fires[pair]:>9}")

    zero_sig = [p for p in PAIRS if signal_counts[p] == 0]
    if zero_sig:
        print(f"\n  DIAGNOSTIC — Zero-signal pairs: {zero_sig}")
    print()


if __name__ == "__main__":
    run_backtest()
