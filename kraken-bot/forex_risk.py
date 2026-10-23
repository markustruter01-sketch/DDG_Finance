"""Forex risk officer (Phase 5): turns the AI's daily decisions into orders.

Pure functions: no broker, no database. The AI decides direction only; this
module sizes every trade and can shrink or block it, never enlarge it
(registered plan items 3, 4 and 6, businesses/finance/forex-registered-plan-2026-10-10.md):
- risk per trade: 0.5% of Forex NAV, measured to the stop (half that on a
  low-confidence day, when one council member was missing);
- at most 4 open trades; gross exposure at most FOREX_MAX_GROSS x NAV;
- daily loss: if NAV fell 2% or more since the last decision cycle, no new
  trades this cycle (closes still happen);
- event blackout: pairs named in ``blackout_pairs`` get no new trade. No
  calendar source is approved yet, so callers pass none and the report says
  the blackout is not enforced.
Every new trade gets its stop at stop_atr_multiple x ATR(14) from the
decision; the executor attaches it at entry. Open trades are closed when the
day's decision for that pair is flat or the opposite direction.
"""

from __future__ import annotations

import math
from typing import Any

RISK_PER_TRADE = 0.005
LOW_CONFIDENCE_FACTOR = 0.5
MAX_OPEN_TRADES = 4
DAILY_LOSS_LIMIT = 0.02


def quote_of(pair: str) -> str:
    return pair.split("_")[1]


def base_of(pair: str) -> str:
    return pair.split("_")[0]


def usd_per_unit_per_price(pair: str, price: float) -> float:
    """USD profit or loss per unit for a 1.0 move in the pair's price."""
    if quote_of(pair) == "USD":
        return 1.0
    if base_of(pair) == "USD":
        return 1.0 / price
    raise ValueError(f"{pair}: only USD pairs are registered")


def usd_notional_per_unit(pair: str, price: float) -> float:
    if base_of(pair) == "USD":
        return 1.0
    if quote_of(pair) == "USD":
        return price
    raise ValueError(f"{pair}: only USD pairs are registered")


def price_decimals(pair: str) -> int:
    return 3 if quote_of(pair) == "JPY" else 5


def stop_price(pair: str, direction: str, ref_price: float, distance: float) -> float:
    level = ref_price - distance if direction == "long" else ref_price + distance
    if level <= 0:
        raise ValueError(f"{pair}: stop would be at or below zero")
    return round(level, price_decimals(pair))


def _finite_pos(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def plan_forex_actions(
    *,
    decisions: list[dict[str, Any]],
    rows_by_pair: dict[str, dict[str, Any]],
    nav: float,
    open_trades: list[dict[str, Any]],
    low_confidence: bool = False,
    nav_at_last_cycle: float | None = None,
    blackout_pairs: frozenset[str] | None = None,
    max_gross: float,
) -> dict[str, Any]:
    """Return {"closes", "opens", "skipped", "checks"} for one decision cycle."""
    if not (_finite_pos(nav)):
        raise ValueError("NAV must be positive")
    closes: list[dict[str, Any]] = []
    opens: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    by_pair = {d["pair"]: d for d in decisions}

    # 1. Closes: flat or opposite call on a pair we hold.
    kept: list[dict[str, Any]] = []
    for trade in open_trades:
        pair = trade["instrument"]
        side = "long" if float(trade["signed_units"]) > 0 else "short"
        decision = by_pair.get(pair)
        if decision and decision["direction"] in ("flat", "short" if side == "long" else "long"):
            closes.append({"trade_id": str(trade["trade_id"]), "pair": pair,
                           "reason": f"AI call {decision['direction']} vs open {side}"})
        else:
            kept.append(trade)

    held_pairs = {t["instrument"] for t in kept}
    gross = sum(abs(float(t.get("market_value") or 0.0)) for t in kept)
    open_count = len(kept)
    risk_usd = nav * RISK_PER_TRADE * (LOW_CONFIDENCE_FACTOR if low_confidence else 1.0)
    daily_drop = None
    if nav_at_last_cycle and _finite_pos(nav_at_last_cycle):
        daily_drop = (nav_at_last_cycle - nav) / nav_at_last_cycle
    no_new_trades = daily_drop is not None and daily_drop >= DAILY_LOSS_LIMIT
    blackout = blackout_pairs if blackout_pairs is not None else frozenset()

    # 2. Opens: highest conviction first, then pair name, within every limit.
    wanted = sorted((d for d in decisions if d["direction"] in ("long", "short")),
                    key=lambda d: (-int(d.get("conviction") or 0), d["pair"]))
    for d in wanted:
        pair = d["pair"]
        if pair in held_pairs:
            continue                                   # same-direction hold: keep its stop
        if no_new_trades:
            skipped.append({"pair": pair, "reason": f"daily loss {daily_drop:.2%} >= {DAILY_LOSS_LIMIT:.0%}"})
            continue
        if pair in blackout:
            skipped.append({"pair": pair, "reason": "event blackout"})
            continue
        if open_count >= MAX_OPEN_TRADES:
            skipped.append({"pair": pair, "reason": f"already {MAX_OPEN_TRADES} open trades"})
            continue
        row = rows_by_pair.get(pair) or {}
        price, atr = _finite_pos(row.get("close")), _finite_pos(row.get("atr"))
        multiple = _finite_pos(d.get("stop_atr_multiple"))
        if price is None or atr is None or multiple is None:
            skipped.append({"pair": pair, "reason": "no usable price, ATR or stop multiple"})
            continue
        distance = multiple * atr
        units = math.floor(risk_usd / (distance * usd_per_unit_per_price(pair, price)))
        room = max_gross * nav - gross
        notional = usd_notional_per_unit(pair, price)
        if units * notional > room:
            units = math.floor(room / notional)
        if units < 1:
            skipped.append({"pair": pair, "reason": "gross exposure cap reached"})
            continue
        signed = units if d["direction"] == "long" else -units
        opens.append({"pair": pair, "direction": d["direction"], "units": signed,
                      "stop_distance": distance, "ref_price": price,
                      "risk_usd": round(units * distance * usd_per_unit_per_price(pair, price), 2),
                      "conviction": d.get("conviction")})
        gross += units * notional
        open_count += 1
        held_pairs.add(pair)

    checks = {
        "risk_per_trade_usd": round(risk_usd, 2),
        "low_confidence": low_confidence,
        "open_trades_after": open_count,
        "gross_after_usd": round(gross, 2),
        "gross_cap_usd": round(max_gross * nav, 2),
        "daily_drop": None if daily_drop is None else round(daily_drop, 5),
        "event_blackout": "enforced" if blackout_pairs is not None else "not enforced: no approved calendar source",
    }
    return {"closes": closes, "opens": opens, "skipped": skipped, "checks": checks}
