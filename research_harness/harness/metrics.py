"""The one place backtest results are computed.

``summarize`` reports the full picture every time: return, CAGR, volatility,
Sharpe, max drawdown, trades, win rate, expectancy, turnover and leverage.
Formulas match FX-BT1 (daily returns, sample stdev, sqrt(252)) so registered
results stay comparable.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Sequence

TRADING_DAYS = 252

# curve point: (day, equity, gross_leverage)
CurvePoint = tuple[date, float, float]


def daily_returns(curve: Sequence[CurvePoint]) -> list[tuple[date, float]]:
    return [(curve[i][0], curve[i][1] / curve[i - 1][1] - 1) for i in range(1, len(curve))]


def sharpe(returns: Sequence[float], rf_daily: Sequence[float] | None = None) -> float | None:
    if len(returns) < 2:
        return None
    ex = [r - (rf_daily[i] if rf_daily else 0.0) for i, r in enumerate(returns)]
    mean = sum(ex) / len(ex)
    sd = math.sqrt(sum((x - mean) ** 2 for x in ex) / (len(ex) - 1))
    return mean / sd * math.sqrt(TRADING_DAYS) if sd > 0 else None


def max_drawdown(values: Sequence[float]) -> float:
    peak, mdd = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return mdd


def rf_daily_for(days: Sequence[date], rf_annual: dict[date, float] | None) -> list[float] | None:
    """Daily cash rate per return day, carrying the last known annual rate forward."""
    if rf_annual is None:
        return None
    known = sorted(rf_annual)
    out, j, last = [], 0, None
    for d in days:
        while j < len(known) and known[j] <= d:
            last = rf_annual[known[j]]
            j += 1
        if last is None:
            raise ValueError(f"no cash rate on or before {d}")
        out.append(last / TRADING_DAYS)
    return out


def summarize(
    curve: Sequence[CurvePoint],
    trades: Sequence[dict[str, Any]],
    *,
    start: date | None = None,
    end: date | None = None,
    rf_annual: dict[date, float] | None = None,
    traded_notional: float | None = None,
    cost_label: str | None = None,
) -> dict[str, Any]:
    """trades: dicts with 'close' (date), 'pnl', optional 'r' (risk units)."""
    pts = [c for c in curve if (start is None or c[0] >= start) and (end is None or c[0] <= end)]
    tr = [t for t in trades if (start is None or t["close"] >= start) and (end is None or t["close"] <= end)]
    if len(pts) < 2:
        return {"note": "no data in window"}
    vals = [p[1] for p in pts]
    rets = daily_returns(pts)
    r = [x for _, x in rets]
    rf_d = rf_daily_for([d for d, _ in rets], rf_annual)
    years = (pts[-1][0] - pts[0][0]).days / 365.25
    mean = sum(r) / len(r)
    sd = math.sqrt(sum((x - mean) ** 2 for x in r) / max(1, len(r) - 1))
    wins = [t for t in tr if t["pnl"] > 0]
    lev = [p[2] for p in pts]
    out: dict[str, Any] = {
        "from": pts[0][0].isoformat(), "to": pts[-1][0].isoformat(),
        "total_return_pct": round((vals[-1] / vals[0] - 1) * 100, 2),
        "cagr_pct": round(((vals[-1] / vals[0]) ** (1 / years) - 1) * 100, 2) if years >= 1 else None,
        "vol_pct": round(sd * math.sqrt(TRADING_DAYS) * 100, 2),
        "max_drawdown_pct": round(max_drawdown(vals) * 100, 2),
        "sharpe_daily_rf0": round(s, 2) if (s := sharpe(r)) is not None else None,
        "trades": len(tr),
        "win_rate_pct": round(len(wins) / len(tr) * 100, 1) if tr else None,
        "expectancy_usd": round(sum(t["pnl"] for t in tr) / len(tr), 2) if tr else None,
        "expectancy_R": (
            round(sum(t["r"] for t in tr) / len(tr), 3) if tr and all("r" in t for t in tr) else None
        ),
        "avg_gross_leverage": round(sum(lev) / len(lev), 2),
        "max_gross_leverage": round(max(lev), 2),
        "pct_days_invested": round(sum(1 for x in lev if x > 0) / len(lev) * 100, 1),
    }
    if rf_d is not None:
        s = sharpe(r, rf_d)
        out["sharpe_excess_tbill"] = round(s, 2) if s is not None else None
        cash_growth = math.prod(1 + x for x in rf_d)
        out["excess_return_vs_tbill_pct"] = round((vals[-1] / vals[0] / cash_growth - 1) * 100, 2)
    if traded_notional is not None and years > 0:
        out["turnover_per_year"] = round(traded_notional / (sum(vals) / len(vals)) / years, 2)
    if cost_label is not None:
        out["costs"] = cost_label
    return out
