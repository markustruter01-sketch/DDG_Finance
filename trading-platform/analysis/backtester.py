"""
Strategy Backtester
--------------------
Replays the current momentum-based regime-switching strategy against
historical price data to produce a simulated equity curve.

Uses cached market data (Alpaca OHLCV) to simulate what trades would
have been placed over the last N days using the same rules the live
system applies.

This is a simplified momentum-backtest (no LLM calls) that tests the
quantitative signal layer:
  - Momentum 3mo/6mo filters
  - 10% position cap
  - ATR trailing stops
  - Overheating override (Z>2 or RSI>75 → 50% cut)
"""

from __future__ import annotations

from typing import Any

import numpy as np
from loguru import logger

from data.yfinance_client import (
    UNIVERSE, ALL_TICKERS, MA_3MO_BARS, MA_6MO_BARS,
    MA_200D_BARS, RSI_PERIOD, _compute_rsi,
)


def _compute_z_score(closes: list[float]) -> float | None:
    if len(closes) < MA_200D_BARS:
        return None
    w = closes[-MA_200D_BARS:]
    sma = float(np.mean(w))
    std = float(np.std(w, ddof=0))
    return round((closes[-1] - sma) / std, 3) if std > 0 else 0.0


def _simple_atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    return float(np.mean(trs[-period:])) if len(trs) >= period else None


def run_backtest(
    bars_by_ticker: dict[str, list[dict]],
    initial_equity: float = 100000.0,
    lookback_days: int = 90,
    max_position_pct: float = 0.10,
    atr_multiplier: float = 2.0,
) -> dict[str, Any]:

    if not bars_by_ticker:
        return {"error": "No market data available for backtest", "equity_curve": []}

    max_bars = max(len(bars) for bars in bars_by_ticker.values()) if bars_by_ticker else 0
    if max_bars < MA_6MO_BARS + lookback_days:
        lookback_days = max(1, max_bars - MA_6MO_BARS)

    equity = initial_equity
    equity_curve: list[dict] = []
    trades: list[dict] = []
    positions: dict[str, dict] = {}

    tickers_to_test = [
        t for t in ALL_TICKERS
        if t in bars_by_ticker and len(bars_by_ticker[t]) >= MA_6MO_BARS + 10
        and t != "SGOV"
    ]

    if not tickers_to_test:
        return {"error": "Insufficient data for backtest", "equity_curve": []}

    spy_bars = bars_by_ticker.get("SPY", [])
    start_idx = max(MA_6MO_BARS, MA_200D_BARS)
    total_bars = len(spy_bars) if spy_bars else max_bars
    sim_start = max(start_idx, total_bars - lookback_days)

    for day_idx in range(sim_start, total_bars):
        day_date = spy_bars[day_idx]["t"][:10] if spy_bars and day_idx < len(spy_bars) else f"day_{day_idx}"

        for sym in list(positions.keys()):
            ticker_bars = bars_by_ticker.get(sym, [])
            if day_idx >= len(ticker_bars):
                continue
            current_price = float(ticker_bars[day_idx]["c"])
            pos = positions[sym]

            if current_price <= pos["stop"]:
                pnl = (current_price - pos["entry"]) / pos["entry"] * 100
                equity += pos["shares"] * (current_price - pos["entry"])
                trades.append({
                    "ticker": sym, "entry_date": pos["entry_date"], "exit_date": day_date,
                    "entry_price": pos["entry"], "exit_price": current_price,
                    "pnl_pct": round(pnl, 2), "reason": "stop_hit",
                })
                del positions[sym]
                continue

            closes_to_now = [float(b["c"]) for b in ticker_bars[:day_idx+1]]
            highs_to_now = [float(b["h"]) for b in ticker_bars[:day_idx+1]]
            lows_to_now = [float(b["l"]) for b in ticker_bars[:day_idx+1]]
            atr = _simple_atr(highs_to_now, lows_to_now, closes_to_now)
            if atr:
                new_stop = current_price - atr_multiplier * atr
                if new_stop > pos["stop"]:
                    pos["stop"] = new_stop

        if day_idx % 5 == 0:
            for ticker in tickers_to_test:
                if ticker in positions:
                    continue
                ticker_bars = bars_by_ticker.get(ticker, [])
                if day_idx >= len(ticker_bars):
                    continue

                closes = [float(b["c"]) for b in ticker_bars[:day_idx+1]]
                if len(closes) < MA_6MO_BARS:
                    continue

                ma_3mo = float(np.mean(closes[-MA_3MO_BARS:])) if len(closes) >= MA_3MO_BARS else None
                ma_6mo = float(np.mean(closes[-MA_6MO_BARS:]))
                current_price = closes[-1]

                if ma_3mo and current_price > ma_3mo and current_price > ma_6mo:
                    z = _compute_z_score(closes)
                    rsi = _compute_rsi(closes)

                    notional = equity * max_position_pct
                    if z is not None and z > 2.0 or (rsi is not None and rsi > 75):
                        notional *= 0.50

                    if notional < 100:
                        continue

                    shares = notional / current_price
                    highs = [float(b["h"]) for b in ticker_bars[:day_idx+1]]
                    lows = [float(b["l"]) for b in ticker_bars[:day_idx+1]]
                    atr = _simple_atr(highs, lows, closes)
                    stop = current_price - (atr_multiplier * atr) if atr else current_price * 0.98

                    positions[ticker] = {
                        "entry": current_price, "shares": shares, "stop": stop,
                        "entry_date": day_date, "notional": notional,
                    }

        total_value = equity
        for sym, pos in positions.items():
            ticker_bars = bars_by_ticker.get(sym, [])
            if day_idx < len(ticker_bars):
                current_price = float(ticker_bars[day_idx]["c"])
                total_value += pos["shares"] * (current_price - pos["entry"])

        equity_curve.append({
            "date": day_date,
            "equity": round(total_value, 2),
            "positions_held": len(positions),
        })

    for sym, pos in list(positions.items()):
        ticker_bars = bars_by_ticker.get(sym, [])
        if ticker_bars:
            final_price = float(ticker_bars[-1]["c"])
            pnl = (final_price - pos["entry"]) / pos["entry"] * 100
            trades.append({
                "ticker": sym, "entry_date": pos["entry_date"], "exit_date": "open",
                "entry_price": pos["entry"], "exit_price": final_price,
                "pnl_pct": round(pnl, 2), "reason": "still_open",
            })

    if equity_curve:
        peak = equity_curve[0]["equity"]
        max_dd = 0
        for point in equity_curve:
            if point["equity"] > peak:
                peak = point["equity"]
            dd = (peak - point["equity"]) / peak * 100
            if dd > max_dd:
                max_dd = dd

        final_equity = equity_curve[-1]["equity"]
        total_return = (final_equity - initial_equity) / initial_equity * 100
    else:
        max_dd = 0
        total_return = 0
        final_equity = initial_equity

    winning_trades = [t for t in trades if t["pnl_pct"] > 0]
    losing_trades = [t for t in trades if t["pnl_pct"] < 0]

    return {
        "initial_equity": initial_equity,
        "final_equity": round(final_equity, 2),
        "total_return_pct": round(total_return, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "total_trades": len(trades),
        "winning_trades": len(winning_trades),
        "losing_trades": len(losing_trades),
        "win_rate": round(len(winning_trades) / len(trades) * 100, 1) if trades else 0,
        "avg_win_pct": round(sum(t["pnl_pct"] for t in winning_trades) / len(winning_trades), 2) if winning_trades else 0,
        "avg_loss_pct": round(sum(t["pnl_pct"] for t in losing_trades) / len(losing_trades), 2) if losing_trades else 0,
        "equity_curve": equity_curve,
        "trades": trades[-20:],
    }
