"""Fleet-level judgement: a sleeve is judged by what it does to the fleet.

Pass bars (from the rebuild plan, 15 Oct 2026):
  sleeve: beats T-bills net of costs; raises fleet Sharpe; correlation < 0.5
          to every other sleeve.
  fleet:  beats SPY on BOTH Sharpe and max drawdown, after all costs.

Fleet returns assume constant sleeve weights, rebalanced daily (stated in
every report) — a simplification of the live risk governor.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Sequence

from research_harness.harness.metrics import CurvePoint, max_drawdown, rf_daily_for, sharpe

MAX_SLEEVE_CORRELATION = 0.5


def _aligned(curves: dict[str, Sequence[CurvePoint]]) -> tuple[list[date], dict[str, list[float]]]:
    """Returns between consecutive days that EVERY curve has, so each sleeve's
    return covers the same span (a holiday in one market cannot shift them).
    All curves must label days the same way (calendar date of the close)."""
    values = {n: {d: v for d, v, _ in c} for n, c in curves.items()}
    common = sorted(set.intersection(*(set(v) for v in values.values())))
    rets = {
        n: [v[common[i]] / v[common[i - 1]] - 1 for i in range(1, len(common))]
        for n, v in values.items()
    }
    return common[1:], rets


def correlation(a: Sequence[float], b: Sequence[float]) -> float | None:
    n = len(a)
    if n < 2:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    return cov / math.sqrt(va * vb) if va > 0 and vb > 0 else None


def fleet_returns(rets: dict[str, list[float]], weights: dict[str, float]) -> list[float]:
    total = sum(weights[n] for n in rets)
    n_days = len(next(iter(rets.values())))
    return [sum(weights[n] / total * rets[n][i] for n in rets) for i in range(n_days)]


def fleet_curve(
    curves: dict[str, Sequence[CurvePoint]],
    weights: dict[str, float],
    start_equity: float = 100_000.0,
) -> list[CurvePoint]:
    """The fund's own equity curve: constant weights, rebalanced daily (as
    fleet_returns). Gross on each day = the weighted gross of the sleeves."""
    days, rets = _aligned(curves)
    gross = {n: {d: g for d, _, g in c} for n, c in curves.items()}
    total = sum(weights[n] for n in curves)
    r = fleet_returns(rets, weights)
    first = sorted(set.intersection(*(set(g) for g in gross.values())))[0]
    out: list[CurvePoint] = [(first, start_equity,
                              sum(weights[n] / total * gross[n][first] for n in curves))]
    for d, x in zip(days, r):
        out.append((d, out[-1][1] * (1 + x), sum(weights[n] / total * gross[n][d] for n in curves)))
    return out


def _stats(days: list[date], r: list[float], rf_annual: dict[date, float] | None) -> dict[str, Any]:
    vals = [1.0]
    for x in r:
        vals.append(vals[-1] * (1 + x))
    rf_d = rf_daily_for(days, rf_annual)
    s = sharpe(r, rf_d)
    return {"sharpe": round(s, 3) if s is not None else None,
            "max_drawdown_pct": round(max_drawdown(vals) * 100, 2),
            "total_return_pct": round((vals[-1] - 1) * 100, 2)}


def evaluate_sleeve(
    name: str,
    curves: dict[str, Sequence[CurvePoint]],
    weights: dict[str, float],
    rf_annual: dict[date, float] | None,
) -> dict[str, Any]:
    """Fleet with vs without ``name``, plus its correlations and cash test."""
    days, rets = _aligned(curves)
    if len(days) < 2:
        raise ValueError("sleeves share fewer than 2 return days")
    others = {n: r for n, r in rets.items() if n != name}
    with_ = _stats(days, fleet_returns(rets, weights), rf_annual)
    without = _stats(days, fleet_returns(others, weights), rf_annual) if others else None
    corrs = {n: correlation(rets[name], r) for n, r in others.items()}
    alone = _stats(days, rets[name], rf_annual)
    rf_d = rf_daily_for(days, rf_annual) or [0.0] * len(days)
    beats_cash = math.prod(1 + x for x in rets[name]) > math.prod(1 + x for x in rf_d)
    improves = (
        without is None
        or (with_["sharpe"] is not None and without["sharpe"] is not None
            and with_["sharpe"] > without["sharpe"])
    )
    low_corr = all(c is not None and c < MAX_SLEEVE_CORRELATION for c in corrs.values())
    return {
        "sleeve": name, "days": len(days), "from": days[0].isoformat(), "to": days[-1].isoformat(),
        "standalone": alone, "fleet_with": with_, "fleet_without": without,
        "correlations": {n: round(c, 3) if c is not None else None for n, c in corrs.items()},
        "checks": {"beats_tbills": beats_cash, "improves_fleet_sharpe": improves,
                   "correlation_below_0_5": low_corr},
        "passes": beats_cash and improves and low_corr,
        "assumption": "constant sleeve weights, rebalanced daily",
    }


def evaluate_fleet_vs_spy(
    fleet: Sequence[CurvePoint],
    spy: Sequence[CurvePoint],
    rf_annual: dict[date, float] | None,
) -> dict[str, Any]:
    days, rets = _aligned({"fleet": fleet, "spy": spy})
    f, s = _stats(days, rets["fleet"], rf_annual), _stats(days, rets["spy"], rf_annual)
    better_sharpe = f["sharpe"] is not None and s["sharpe"] is not None and f["sharpe"] > s["sharpe"]
    better_dd = f["max_drawdown_pct"] > s["max_drawdown_pct"]  # less negative
    return {"fleet": f, "spy": s, "checks": {"sharpe_above_spy": better_sharpe,
            "drawdown_smaller_than_spy": better_dd}, "passes": better_sharpe and better_dd}
