"""Turn a sleeve's target weights into a concrete, safe order plan.

Pure functions only: no broker calls, no database. The executor (separate)
carries the plan out. Sizing uses research_harness.harness.sizing, the same
functions the backtest uses, so live trades match what was tested.

Safety rules built into every plan:
- Whole shares only; every held position ends with a protective stop for
  its full quantity at stop_pct below the rebalance reference price, except
  symbols the caller declares stop-free (``no_stop``: FLEET-V1 sleeve 2,
  whose monthly trend call is the exit by design).
- Sells come before buys; buys are scaled down (never up) to fit the cash
  that will be available, keeping a cash buffer.
- A symbol with no usable price, or one the caller freezes (with a reason),
  is left exactly as it is (no trade, its existing stop untouched) and
  reported, never guessed.
- Execution order is explicit: cancel the stops of positions whose size
  changes (brokers reserve shares held by a stop), sell, buy, then place
  their new stops. Positions whose size does NOT change keep their stop and
  only have its price moved ("replace"), so they are never unprotected.
  The executor must not skip the last step.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from research_harness.harness.sizing import stop_price, target_shares


@dataclass(frozen=True)
class Order:
    symbol: str
    side: str      # "buy" or "sell"
    qty: int


@dataclass(frozen=True)
class StopAction:
    symbol: str
    action: str             # "place" (after fills) or "replace" (move existing stop)
    qty: int = 0
    stop: float = 0.0


@dataclass
class RebalancePlan:
    cancel_stops: list[str] = field(default_factory=list)   # symbols, before any sell
    sells: list[Order] = field(default_factory=list)
    buys: list[Order] = field(default_factory=list)
    stops: list[StopAction] = field(default_factory=list)   # after all fills
    final_qty: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)   # symbol -> reason
    buy_scale: float = 1.0


def plan_rebalance(
    *,
    weights: dict[str, float],
    equity: float,
    cash: float,
    positions: dict[str, float],
    prices: dict[str, float | None],
    stop_pct: float,
    cash_buffer_pct: float,
    max_gross: float = 1.0,
    frozen: dict[str, str] | None = None,
    no_stop: frozenset[str] = frozenset(),
) -> RebalancePlan:
    if equity <= 0:
        raise ValueError("equity must be positive")
    if any(w < 0 for w in weights.values()):
        raise ValueError("long-only sleeve: negative weight")
    if sum(weights.values()) > max_gross + 1e-9:
        raise ValueError(f"weights sum above max_gross {max_gross}")
    if not 0 <= cash_buffer_pct < 1:
        raise ValueError("cash_buffer_pct must be in [0, 1)")
    for sym, q in positions.items():
        if q < 0 or q != math.trunc(q):
            raise ValueError(f"{sym}: position {q} is not a whole long quantity")

    plan = RebalancePlan()
    targets: dict[str, int] = {}
    for sym in sorted(set(weights) | set(positions)):
        cur = int(positions.get(sym, 0))
        px = prices.get(sym)
        if frozen and sym in frozen:
            plan.skipped[sym] = f"frozen: {frozen[sym]}; position and stop left unchanged"
            targets[sym] = cur
            continue
        if px is None or not px > 0:
            plan.skipped[sym] = "no usable price; position and stop left unchanged"
            targets[sym] = cur
            continue
        targets[sym] = int(target_shares(weights.get(sym, 0.0), equity, px, whole_shares=True))

    proceeds = 0.0
    for sym, tgt in targets.items():
        cur = int(positions.get(sym, 0))
        if sym in plan.skipped or tgt >= cur:
            continue
        plan.cancel_stops.append(sym)
        plan.sells.append(Order(sym, "sell", cur - tgt))
        proceeds += (cur - tgt) * prices[sym]

    wanted = {s: t - int(positions.get(s, 0)) for s, t in targets.items()
              if s not in plan.skipped and t > int(positions.get(s, 0))}
    spend = sum(q * prices[s] for s, q in wanted.items())
    available = max(0.0, cash + proceeds - cash_buffer_pct * equity)
    if spend > available and spend > 0:
        plan.buy_scale = available / spend
    for sym, q in sorted(wanted.items()):
        qty = int(math.trunc(q * plan.buy_scale))
        if qty > 0:
            plan.buys.append(Order(sym, "buy", qty))
            # A position that grows also needs its stop re-sized after the buy.
            if positions.get(sym, 0) > 0 and sym not in plan.cancel_stops:
                plan.cancel_stops.append(sym)

    final = {s: int(positions.get(s, 0)) for s in targets}
    for o in plan.sells:
        final[o.symbol] -= o.qty
    for o in plan.buys:
        final[o.symbol] += o.qty
    plan.final_qty = {s: q for s, q in final.items() if q > 0}

    for sym, q in sorted(plan.final_qty.items()):
        if sym in plan.skipped or sym in no_stop:
            continue
        level = round(stop_price(prices[sym], long=True, stop_pct=stop_pct), 2)
        unchanged = q == int(positions.get(sym, 0))
        plan.stops.append(StopAction(sym, "replace" if unchanged else "place", q, level))
    return plan
