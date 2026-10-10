"""FX-BT1: one-off historical backtest of the registered Forex baseline rule.

Spec: businesses/finance/forex-baseline-backtest-registration-2026-10-11.md
(registered before any data was pulled). Read-only: OANDA candle reads only.
No orders, no database. Run from repo root:
    python kraken-bot/forex_baseline_backtest.py
Writes .local/claude_reports/FX-BT1.txt.
"""

from __future__ import annotations

import math
import os
import sys
from datetime import date
from typing import Any

from forex_quant_desk import (
    ATR_DAYS,
    FOREX_PAIRS,
    MOMENTUM_DAYS,
    STOP_ATR_MULTIPLE,
    TREND_SMA_DAYS,
)

RISK_PER_TRADE = 0.005
MAX_OPEN = 4
GROSS_CAP = 2.0
START_EQUITY = 100_000.0
LAST_DAY = date(2026, 10, 9)
WARMUP = TREND_SMA_DAYS + 1
STRESS_WINDOWS = {
    "GFC 2008-09-01..2009-03-31": (date(2008, 9, 1), date(2009, 3, 31)),
    "SNB 2015-01-01..2015-02-28": (date(2015, 1, 1), date(2015, 2, 28)),
    "Brexit 2016-06-01..2016-07-31": (date(2016, 6, 1), date(2016, 7, 31)),
    "COVID 2020-02-01..2020-04-30": (date(2020, 2, 1), date(2020, 4, 30)),
    "USD surge 2022-01-01..2022-10-31": (date(2022, 1, 1), date(2022, 10, 31)),
}


# ── Data shape: per pair, list of dicts {day, bo,bh,bl,bc, ao,ah,al,ac} ──────

def bar_from_candle(candle: dict[str, Any]) -> dict[str, Any]:
    b, a = candle["bid"], candle["ask"]
    return {
        "day": date.fromisoformat(str(candle["time"])[:10]),
        "bo": float(b["o"]), "bh": float(b["h"]), "bl": float(b["l"]), "bc": float(b["c"]),
        "ao": float(a["o"]), "ah": float(a["h"]), "al": float(a["l"]), "ac": float(a["c"]),
    }


def _mid(bar: dict[str, Any], f: str) -> float:
    return (bar["b" + f] + bar["a" + f]) / 2


def indicators(bars: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
    """Per bar: baseline call, ATR and strength, using data up to that close only."""
    out: list[dict[str, Any] | None] = []
    closes = [_mid(b, "c") for b in bars]
    for i in range(len(bars)):
        if i < WARMUP:
            out.append(None)
            continue
        close = closes[i]
        sma = sum(closes[i - TREND_SMA_DAYS + 1:i + 1]) / TREND_SMA_DAYS
        mom = close / closes[i - MOMENTUM_DAYS] - 1
        trs = []
        for j in range(i - ATR_DAYS + 1, i + 1):
            h, l, pc = _mid(bars[j], "h"), _mid(bars[j], "l"), closes[j - 1]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        atr = sum(trs) / ATR_DAYS
        if close > sma and mom > 0:
            call = "long"
        elif close < sma and mom < 0:
            call = "short"
        else:
            call = "flat"
        out.append({"call": call, "atr": atr, "strength": abs(mom) / (atr / close) if atr else 0.0})
    return out


def usd_per_unit_move(pair: str, price: float) -> float:
    """USD value of a 1.0 price move per unit (quote currency converted to USD)."""
    return 1.0 if pair.endswith("_USD") else 1.0 / price


def run_backtest(data: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    ind = {p: indicators(bars) for p, bars in data.items()}
    idx = {p: {b["day"]: i for i, b in enumerate(bars)} for p, bars in data.items()}
    days = sorted({b["day"] for bars in data.values() for b in bars if b["day"] <= LAST_DAY})
    equity, cash_pnl = START_EQUITY, 0.0
    positions: dict[str, dict[str, Any]] = {}
    trades: list[dict[str, Any]] = []
    curve: list[tuple[date, float, float]] = []

    def close_pos(pair: str, price: float, day: date, reason: str) -> None:
        nonlocal equity
        pos = positions.pop(pair)
        move = (price - pos["entry"]) if pos["dir"] == "long" else (pos["entry"] - price)
        pnl = move * pos["units"] * usd_per_unit_move(pair, price)
        equity += pnl
        trades.append({"pair": pair, "dir": pos["dir"], "open": pos["day"], "close": day,
                       "pnl": pnl, "r": pnl / pos["risk_usd"] if pos["risk_usd"] else 0.0,
                       "reason": reason})

    for day in days:
        # 1. Stops during this day's bar (entries happened at an earlier close).
        for pair in list(positions):
            i = idx[pair].get(day)
            if i is None:
                continue
            bar, pos = data[pair][i], positions[pair]
            if pos["dir"] == "long" and bar["bl"] <= pos["stop"]:
                close_pos(pair, min(pos["stop"], bar["bo"]), day, "stop")
            elif pos["dir"] == "short" and bar["ah"] >= pos["stop"]:
                close_pos(pair, max(pos["stop"], bar["ao"]), day, "stop")
        # 2. Signal-change exits at this close.
        for pair in list(positions):
            i = idx[pair].get(day)
            sig = ind[pair][i] if i is not None else None
            if sig is None or sig["call"] == positions[pair]["dir"]:
                continue
            bar = data[pair][i]
            close_pos(pair, bar["bc"] if positions[pair]["dir"] == "long" else bar["ac"], day, "signal")
        # 3. New entries at this close, strongest first, within limits.
        candidates = []
        for pair in data:
            i = idx[pair].get(day)
            sig = ind[pair][i] if i is not None else None
            if pair in positions or sig is None or sig["call"] == "flat":
                continue
            candidates.append((sig["strength"], pair, i, sig))
        candidates.sort(reverse=True)
        for _, pair, i, sig in candidates:
            if len(positions) >= MAX_OPEN:
                break
            bar = data[pair][i]
            entry = bar["ac"] if sig["call"] == "long" else bar["bc"]
            stop_dist = STOP_ATR_MULTIPLE * sig["atr"]
            if stop_dist <= 0:
                continue
            risk_usd = RISK_PER_TRADE * equity
            units = risk_usd / (stop_dist * usd_per_unit_move(pair, entry))
            notional = units * (entry if pair.endswith("_USD") else 1.0)
            gross = sum(p["notional"] for p in positions.values())
            room = GROSS_CAP * equity - gross
            if room <= 0:
                break
            if notional > room:
                scale = room / notional
                units, notional, risk_usd = units * scale, room, risk_usd * scale
            positions[pair] = {
                "dir": sig["call"], "entry": entry, "units": units, "day": day,
                "stop": entry - stop_dist if sig["call"] == "long" else entry + stop_dist,
                "risk_usd": risk_usd, "notional": notional,
            }
        # 4. Mark to market at close (mid) for the equity curve.
        mtm = 0.0
        for pair, pos in positions.items():
            i = idx[pair].get(day)
            if i is None:
                continue
            px = _mid(data[pair][i], "c")
            move = (px - pos["entry"]) if pos["dir"] == "long" else (pos["entry"] - px)
            mtm += move * pos["units"] * usd_per_unit_move(pair, px)
        gross = sum(p["notional"] for p in positions.values())
        curve.append((day, equity + mtm, gross / (equity + mtm) if equity + mtm > 0 else 0.0))
    return {"curve": curve, "trades": trades, "open_at_end": len(positions)}


def stats(curve: list[tuple[date, float, float]], trades: list[dict[str, Any]],
          start: date | None = None, end: date | None = None) -> dict[str, Any]:
    pts = [c for c in curve if (start is None or c[0] >= start) and (end is None or c[0] <= end)]
    tr = [t for t in trades if (start is None or t["close"] >= start) and (end is None or t["close"] <= end)]
    if len(pts) < 2:
        return {"note": "no data in window"}
    vals = [p[1] for p in pts]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals))]
    peak, mdd = vals[0], 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    years = (pts[-1][0] - pts[0][0]).days / 365.25
    mean = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1))
    wins = [t for t in tr if t["pnl"] > 0]
    lev = [p[2] for p in pts]
    return {
        "from": pts[0][0].isoformat(), "to": pts[-1][0].isoformat(),
        "total_return_pct": round((vals[-1] / vals[0] - 1) * 100, 2),
        "cagr_pct": round(((vals[-1] / vals[0]) ** (1 / years) - 1) * 100, 2) if years >= 1 else None,
        "max_drawdown_pct": round(mdd * 100, 2),
        "sharpe_daily_rf0": round(mean / sd * math.sqrt(252), 2) if sd > 0 else None,
        "trades": len(tr),
        "win_rate_pct": round(len(wins) / len(tr) * 100, 1) if tr else None,
        "expectancy_R": round(sum(t["r"] for t in tr) / len(tr), 3) if tr else None,
        "avg_gross_leverage": round(sum(lev) / len(lev), 2),
        "max_gross_leverage": round(max(lev), 2),
        "pct_days_invested": round(sum(1 for x in lev if x > 0) / len(lev) * 100, 1),
    }


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(here), "trading-platform"))
    from core.oanda_client import OandaClient

    data, lines = {}, ["FX-BT1 baseline backtest (spec: forex-baseline-backtest-registration-2026-10-11.md)",
                       "Costs: bid/ask spread included; financing EXCLUDED. Fixed rule, one run, no tuning.", ""]
    with OandaClient() as client:
        for pair in FOREX_PAIRS:
            candles = client.daily_candles_bid_ask(pair, count=4999)
            bars = [bar_from_candle(c) for c in candles]
            bars = [b for b in bars if b["day"] <= LAST_DAY]
            data[pair] = bars
            lines.append(f"data {pair}: {len(bars)} bars {bars[0]['day']}..{bars[-1]['day']}" if bars
                         else f"data {pair}: NO DATA")
    result = run_backtest({p: b for p, b in data.items() if b})
    lines += ["", "FULL PERIOD", str(stats(result["curve"], result["trades"])),
              f"open positions at end: {result['open_at_end']}", "", "VS NO POSITION: 0.00% return, 0 drawdown", ""]
    for name, (s, e) in STRESS_WINDOWS.items():
        lines.append(f"{name}: {stats(result['curve'], result['trades'], s, e)}")
    lines += ["", "PER PAIR (closed trades)"]
    for pair in FOREX_PAIRS:
        tr = [t for t in result["trades"] if t["pair"] == pair]
        pnl = sum(t["pnl"] for t in tr)
        stops = sum(1 for t in tr if t["reason"] == "stop")
        lines.append(f"{pair}: trades={len(tr)} pnl_usd={pnl:,.0f} stopped_out={stops}")
    report = "\n".join(lines)
    print(report)
    os.makedirs(".local/claude_reports", exist_ok=True)
    with open(".local/claude_reports/FX-BT1.txt", "w") as fh:
        fh.write(report + "\n")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    raise SystemExit(main())
