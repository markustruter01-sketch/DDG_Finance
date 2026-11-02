"""VOL-V1: trend-gated S&P 500 put-writing (plan: research_harness/explore/VOL-V1-PLAN.md).

The backtest model (plan, "Data"): on each day the strategy earns the gate's
notional fraction N times the CBOE PutWrite index's (PUT) daily return, plus
(1 - N) times cash. PUT is fully collateralised in T-bills, so its return
already includes the collateral's interest.

Gate (FLEET-V1's dial, unchanged): votes v over {63, 126, 252} sessions of the
S&P 500 TR series, s = min(1, 0.15 / vol20), N = min(1, (v/3) * s); N < 0.10
means no puts.

Timing (close-only data; declared here, conservative): a decision taken on
day t's close is traded at the next open, so day t+1's return is still earned
at the old N and the new N earns from day t+2. Rolls are decided on the first
session of each calendar month; between rolls N only changes by dropping to
zero (the gate breaks), and then stays zero until the next roll.

Costs (plan): 2 bp of notional per roll leg plus $0.65 per contract per leg.
A monthly roll is two legs (buy to close, sell to open). The contract count
is notional / (strike x 100) with strike ~ S&P 500 price / 10 (SPY); the model
is fractional (a $100k account really holds whole contracts: the live
shadow reports that gap).

V2 (2% out of the money) cannot be built from PUT alone; per the plan it is
estimated per PUT cycle (third Friday to third Friday) as
    r2 = cash + 0.70 x premium - max(0, loss - 0.02)
where, from PUT's cycle return r and the S&P price move, loss = max(0, 1 -
S_end/S_start) (an ATM put's loss per unit notional) and premium = r - cash +
loss. The cycle's adjustment r2 - r is spread evenly over the cycle's days,
so V2 keeps PUT's daily shocks. It is an approximation, flagged as such, and
is judged live rather than historically.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Sequence

from research_harness.sleeves import core_v1

LOOKBACKS = core_v1.LOOKBACKS
VOL_TARGET = core_v1.VOL_TARGET
N_MIN = 0.10
N_MAX = 1.0
COST_BPS_PER_LEG = 2.0
CONTRACT_FEE = 0.65
SPY_PER_SPX = 0.10                      # SPY trades near a tenth of the S&P 500
V2_PREMIUM_FACTOR = 0.70
V2_OTM = 0.02
CANDIDATES = ("V1", "V2")


# ── the gate ──────────────────────────────────────────────────────────────────
def gate_n(closes: Sequence[float]) -> float | None:
    """Target notional fraction from the S&P TR closes up to the signal day.
    None until every vote has history."""
    v = core_v1.votes(list(closes))
    vol = core_v1.vol20(list(closes))
    if v is None or vol is None:
        return None
    s = min(1.0, VOL_TARGET / vol) if vol > 0 else 1.0
    n = min(N_MAX, (v / 3) * s)
    return n if n >= N_MIN else 0.0


# ── PUT cycles and the V2 estimate ────────────────────────────────────────────
def third_friday(year: int, month: int) -> date:
    d = date(year, month, 15)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def roll_days(days: Sequence[date]) -> list[date]:
    """PUT's roll days: the last trading day on or before each month's third
    Friday (a holiday Friday rolls on the Thursday)."""
    out: list[date] = []
    if not days:
        return out
    months = sorted({(d.year, d.month) for d in days})
    ordered = sorted(days)
    for y, m in months:
        tf = third_friday(y, m)
        before = [d for d in ordered if d <= tf and (d.year, d.month) == (y, m)]
        if before:
            out.append(before[-1])
    return out


def v2_cycle_return(r_put: float, cash: float, spx_start: float, spx_end: float) -> dict[str, float]:
    """One PUT cycle's V2 estimate from PUT's cycle return (plan, "Data")."""
    loss = max(0.0, 1 - spx_end / spx_start)
    premium = r_put - cash + loss
    loss2 = max(0.0, loss - V2_OTM)
    return {"loss": loss, "premium": premium, "loss_v2": loss2,
            "r_v2": cash + V2_PREMIUM_FACTOR * premium - loss2}


def v2_levels(put: dict[date, float], spx: dict[date, float], rf_daily: dict[date, float]) -> dict[date, float]:
    """A V2 index on PUT's days: PUT's daily returns plus each cycle's
    adjustment spread evenly (geometrically) over the cycle's days."""
    days = sorted(d for d in put if d in spx)
    rolls = [d for d in roll_days(days)]
    out: dict[date, float] = {days[0]: put[days[0]]} if days else {}
    edges = [days[0]] + [r for r in rolls if r > days[0]] if days else []
    if days and edges[-1] != days[-1]:
        edges.append(days[-1])
    pos = {d: i for i, d in enumerate(days)}
    for a, b in zip(edges, edges[1:]):
        seg = days[pos[a] + 1: pos[b] + 1]
        if not seg:
            continue
        r_put = put[b] / put[a] - 1
        cash = 1.0
        for d in seg:
            cash *= 1 + rf_daily.get(d, 0.0)
        est = v2_cycle_return(r_put, cash - 1, spx[a], spx[b])
        k = ((1 + est["r_v2"]) / (1 + r_put)) ** (1 / len(seg))
        prev = a
        for d in seg:
            out[d] = out[prev] * (put[d] / put[prev]) * k
            prev = d
    return out


# ── the model ─────────────────────────────────────────────────────────────────
def contract_fee_fraction(n: float, spx_level: float) -> float:
    """$0.65 per contract as a fraction of equity, for notional fraction n."""
    strike = spx_level * SPY_PER_SPX
    return n * CONTRACT_FEE / (strike * 100) if strike > 0 else 0.0


def model(
    asset: dict[date, float],
    gate_closes: dict[date, float],
    spx: dict[date, float],
    cash_annual: dict[date, float],
    start: date,
    end: date,
    *,
    option_costs: bool = True,
    ungated: bool = False,
    log: list[dict[str, Any]] | None = None,
) -> list[tuple[date, float, float]]:
    """Daily curve of (day, equity, notional fraction held), equity 1.0 on the
    first day in [start, end].

    asset: levels of what is held at notional N (PUT, the V2 estimate, or the
    S&P TR for the N1 control). gate_closes: the S&P TR series the dial reads
    (its history before ``start`` is used for warm-up). option_costs: two legs
    of 2 bp + per-contract fees at each roll and one leg at a gate exit;
    False charges 2 bp on the change in N only (the N1 control).
    ungated: N = 1 always, no costs (the PUT control)."""
    from research_harness.harness.metrics import TRADING_DAYS

    gate_days = sorted(gate_closes)
    days = sorted(d for d in asset if start <= d <= end and d in gate_closes and d in spx)
    if len(days) < 2:
        return []
    known_rates = sorted(cash_annual)

    def cash_on(d: date) -> float:
        lo, hi, best = 0, len(known_rates) - 1, None
        while lo <= hi:
            mid = (lo + hi) // 2
            if known_rates[mid] <= d:
                best, lo = known_rates[mid], mid + 1
            else:
                hi = mid - 1
        if best is None:
            raise ValueError(f"no cash rate on or before {d}")
        return cash_annual[best] / TRADING_DAYS

    gi = {d: i for i, d in enumerate(gate_days)}
    closes = [gate_closes[d] for d in gate_days]
    equity = 1.0
    curve = [(days[0], equity, 1.0 if ungated else 0.0)]
    held = 1.0 if ungated else 0.0           # N earning today's return
    pending: tuple[float, float] | None = None   # (new N, cost fraction) taking effect after the next day
    staged: tuple[float, float] | None = None
    month = None
    for i, d in enumerate(days):
        if i:
            if staged is not None:           # traded at yesterday's open; earns from today
                new_n, cost = staged
                equity *= 1 - cost
                held, staged = new_n, None
            r = asset[d] / asset[days[i - 1]] - 1
            equity *= 1 + held * r + (1 - held) * cash_on(d)
            curve.append((d, equity, held))
        if ungated:
            continue
        staged, pending = pending, None
        target = staged[0] if staged is not None else held
        n = gate_n(closes[: gi[d] + 1])
        new_month = (d.year, d.month) != month
        month = (d.year, d.month)
        decision = None
        if new_month and n is not None:
            decision = ("roll", n)
        elif target > 0 and n is not None and n == 0.0:
            decision = ("exit", 0.0)
        if decision is None:
            continue
        kind, new_n = decision
        if option_costs:
            legs = []
            if target > 0:
                legs.append(target)          # buy to close
            if kind == "roll" and new_n > 0:
                legs.append(new_n)           # sell to open
            cost = sum(x * COST_BPS_PER_LEG / 1e4 + contract_fee_fraction(x, spx[d]) for x in legs)
        else:
            cost = abs(new_n - target) * COST_BPS_PER_LEG / 1e4
        pending = (new_n, cost)
        if log is not None:
            log.append({"day": d, "kind": kind, "n": new_n, "cost": cost})
    return curve


def gate_stats(log: Sequence[dict[str, Any]], start: date, end: date) -> dict[str, Any]:
    rows = [r for r in log if start <= r["day"] <= end]
    rolls = [r for r in rows if r["kind"] == "roll"]
    return {
        "rolls": len(rolls),
        "months_out": sum(1 for r in rolls if r["n"] == 0.0),
        "gate_exits": sum(1 for r in rows if r["kind"] == "exit"),
        "mean_n": sum(r["n"] for r in rolls) / len(rolls) if rolls else None,
        "cost_total": sum(r["cost"] for r in rows),
    }
