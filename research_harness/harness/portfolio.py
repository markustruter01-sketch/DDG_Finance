"""Daily target-weight portfolio simulator for sleeves.

Timing (no look-ahead): the strategy sees bars up to and including day t's
close and returns target weights; they are traded at day t+1's OPEN. A
symbol with no bar on t+1 keeps its order pending until its next bar.

Cash earns the T-bill rate; borrowed cash pays T-bill + financing spread;
shorts pay borrow. Trade costs come from the CostModel. Weights are fractions
of equity; sum of |weights| is capped by max_gross.

Live parity options (the live sleeve runs the same rules):
- whole_shares: trade whole shares only (rounded toward zero), as live
  protective stops must cover whole shares.
- stop_pct: every held position carries a protective stop, re-set at each
  rebalance to stop_pct away from that day's open. If a bar trades through
  it, the position exits at the stop (or the open, if it gapped through) and
  stays flat until the strategy's next rebalance.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from research_harness.harness.costs import CostModel, SymbolCosts
from research_harness.harness.holdout import check_window
from research_harness.harness.metrics import TRADING_DAYS, CurvePoint, rf_daily_for
from research_harness.harness.sizing import stop_price, target_shares

EPS = 1e-9


class StrategyError(ValueError):
    """The strategy returned weights that break the sleeve's limits."""


class HistoryView:
    """Read-only bars up to the current day. Future bars are unreachable."""

    def __init__(self, bars: dict[str, list[dict[str, Any]]]) -> None:
        self._bars = bars
        self._days = {s: [b["day"] for b in bs] for s, bs in bars.items()}
        self.today: date | None = None

    def symbols(self) -> list[str]:
        return sorted(self._bars)

    def bars(self, symbol: str) -> list[dict[str, Any]]:
        n = bisect.bisect_right(self._days[symbol], self.today)
        return self._bars[symbol][:n]

    def closes(self, symbol: str) -> list[float]:
        return [b["close"] for b in self.bars(symbol)]

    def window(self, symbol: str, n: int) -> list[dict[str, Any]]:
        """The last n bars up to today (cheap; use this in long backtests)."""
        end = bisect.bisect_right(self._days[symbol], self.today)
        return self._bars[symbol][max(0, end - n):end]


Strategy = Callable[[date, HistoryView], "dict[str, float] | None"]


@dataclass
class SimResult:
    curve: list[CurvePoint] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)  # closed round trips
    fills: int = 0
    traded_notional: float = 0.0
    costs_paid: float = 0.0
    financing_paid: float = 0.0
    borrow_paid: float = 0.0
    cash_interest: float = 0.0
    stops_hit: int = 0
    cost_label: str = ""


def simulate(
    bars: dict[str, list[dict[str, Any]]],
    strategy: Strategy,
    *,
    costs: CostModel | SymbolCosts,
    rf_annual: dict[date, float] | None,
    start: date,
    end: date,
    start_equity: float = 100_000.0,
    max_gross: float = 1.0,
    allow_short: bool = False,
    registration_id: str | None = None,
    grant: Any = None,
    whole_shares: bool = False,
    stop_pct: float | None = None,
) -> SimResult:
    check_window(end, registration_id, grant)
    if stop_pct is not None and not 0 < stop_pct < 1:
        raise ValueError("stop_pct must be between 0 and 1")
    bars = {s: [b for b in bs if b["day"] <= end] for s, bs in bars.items()}
    by_day = {s: {b["day"]: b for b in bs} for s, bs in bars.items()}
    days = sorted({b["day"] for bs in bars.values() for b in bs if b["day"] >= start})
    rf_d = rf_daily_for(days, rf_annual) if rf_annual is not None else [0.0] * len(days)
    view = HistoryView(bars)
    res = SimResult(cost_label=costs.label() + ("" if rf_annual is not None else "; cash earns 0"))

    cash = start_equity
    shares: dict[str, float] = {}
    last: dict[str, float] = {}
    episodes: dict[str, dict[str, Any]] = {}
    pending: dict[str, float] | None = None
    stops: dict[str, float] = {}

    def trade(sym: str, qty: float, price: float, day: date, reason: str = "rebalance") -> None:
        nonlocal cash
        notional = qty * price
        cost = costs.trade_cost_for(sym, notional)
        cash -= notional + cost
        res.fills += 1
        res.traded_notional += abs(notional)
        res.costs_paid += cost
        before = shares.get(sym, 0.0)
        after = before + qty
        if abs(before) < EPS:
            episodes[sym] = {"symbol": sym, "open": day, "flow": 0.0}
        episodes[sym]["flow"] -= notional + cost
        if abs(after) < EPS:
            ep = episodes.pop(sym)
            res.trades.append({"symbol": sym, "open": ep["open"], "close": day,
                               "pnl": ep["flow"], "exit": reason})
            shares.pop(sym, None)
            stops.pop(sym, None)
        else:
            shares[sym] = after

    for k, day in enumerate(days):
        # 1. Execute yesterday's targets at today's open.
        if pending is not None:
            equity_open = cash + sum(
                q * (by_day[s][day]["open"] if day in by_day[s] else last[s])
                for s, q in shares.items()
            )
            carry: dict[str, float] = {}
            for sym in sorted(set(pending) | set(shares)):
                w = pending.get(sym, 0.0)
                bar = by_day[sym].get(day)
                if bar is None:
                    carry[sym] = w
                    continue
                px = bar["open"]
                cur = shares.get(sym, 0.0)
                target = target_shares(w, equity_open, px, whole_shares=whole_shares)
                if abs(target - cur) * px >= 0.01:
                    if cur and target and (cur > 0) != (target > 0):  # flip: close first
                        trade(sym, -cur, px, day)
                        cur = 0.0
                    trade(sym, target - cur, px, day)
                if stop_pct is not None and sym in shares:  # re-set at every rebalance
                    stops[sym] = stop_price(px, long=shares[sym] > 0, stop_pct=stop_pct)
            pending = carry or None
        # 1b. Protective stops during today's bar.
        if stop_pct is not None:
            for sym in sorted(stops):
                bar = by_day[sym].get(day)
                if bar is None or sym not in shares:
                    continue
                q, stop = shares[sym], stops[sym]
                if q > 0 and bar["low"] <= stop:
                    trade(sym, -q, min(stop, bar["open"]), day, reason="stop")
                    res.stops_hit += 1
                elif q < 0 and bar["high"] >= stop:
                    trade(sym, -q, max(stop, bar["open"]), day, reason="stop")
                    res.stops_hit += 1
        # 2. Overnight carry: cash interest, financing, short borrow.
        for s, b in ((s, by_day[s].get(day)) for s in bars):
            if b is not None:
                last[s] = b["close"]
        # Short-sale proceeds sit in cash but earn nothing (retail brokers do
        # not pay interest on them), so only cash beyond them earns T-bills.
        short_proceeds = sum(-q * last[s] for s, q in shares.items() if q < 0)
        if cash >= 0:
            earning = max(0.0, cash - short_proceeds)
            res.cash_interest += earning * rf_d[k]
            cash += earning * rf_d[k]
        else:
            charge = -cash * (rf_d[k] + costs.financing_spread_bps_yr / 1e4 / TRADING_DAYS)
            res.financing_paid += charge
            cash -= charge
        for s, q in shares.items():
            if q < 0:
                fee = -q * last[s] * costs.short_borrow_bps_yr / 1e4 / TRADING_DAYS
                res.borrow_paid += fee
                cash -= fee
        # 3. Mark to close.
        mv = {s: q * last[s] for s, q in shares.items()}
        equity = cash + sum(mv.values())
        gross = sum(abs(v) for v in mv.values()) / equity if equity > 0 else float("inf")
        res.curve.append((day, equity, gross))
        if equity <= 0:
            break
        # 4. Ask the strategy for tomorrow's targets.
        view.today = day
        weights = strategy(day, view)
        if weights is not None:
            unknown = set(weights) - set(bars)
            if unknown:
                raise StrategyError(f"{day}: unknown symbols {sorted(unknown)}")
            if not allow_short and any(w < -EPS for w in weights.values()):
                raise StrategyError(f"{day}: short weight but shorts are not allowed")
            if sum(abs(w) for w in weights.values()) > max_gross + EPS:
                raise StrategyError(f"{day}: gross weight above cap {max_gross}")
            pending = {s: w for s, w in weights.items() if abs(w) > EPS}
            for s in shares:
                pending.setdefault(s, 0.0)
    return res
