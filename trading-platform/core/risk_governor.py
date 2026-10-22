"""Fleet risk governor, v1: may any sleeve ADD risk right now?

The kill switch (core/kill_switch.py) is the hard layer: when armed it
pauses every bot. This is the soft layer that sits in front of every new
sleeve's buys. It never sells, cancels or pauses anything; it only says no
to new risk. Selling and protective stops are never blocked.

New risk is refused when any of these hold (fail closed: a failed check is a
refusal):
- the kill switch is latched;
- the kill switch WOULD trip on a fresh broker snapshot, armed or not
  (missing stops, broker/ledger mismatch, negative cash, leverage, ...);
- fleet drawdown from its high-water mark is above SOFT_DRAWDOWN, which sits
  below the kill switch's hard limit (settings.kill_switch_drawdown_pct), so
  buying stops before anything has to be paused;
- the fleet drawdown cannot be computed.
"""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

# Claude's design value (22 Oct 2026), not fitted: stop adding risk at a 10%
# fleet drawdown, well before the 15% hard kill-switch limit.
SOFT_DRAWDOWN = 0.10


def new_risk_check(
    *,
    snapshot: dict[str, Any] | None = None,
    latch: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    drawdown = None
    try:
        from core.kill_switch import evaluate_snapshot, latch_tripped

        if (latch or latch_tripped)():
            reasons.append("kill switch latched")
        if snapshot is None:
            from execution.reconciliation import collect_live_snapshot
            snapshot = collect_live_snapshot()
        for t in evaluate_snapshot(snapshot):
            who = " ".join(str(t[k]) for k in ("bot_id", "symbol") if t.get(k))
            reasons.append(f"kill switch would trip: {t.get('trigger', 'unknown')} {who}".strip())
        equity, hwm = snapshot.get("fleet_equity"), snapshot.get("fleet_hwm")
        if equity and hwm and float(hwm) > 0:
            drawdown = max(0.0, (float(hwm) - float(equity)) / float(hwm))
            if drawdown > SOFT_DRAWDOWN:
                reasons.append(f"fleet drawdown {drawdown:.1%} above the {SOFT_DRAWDOWN:.0%} soft limit")
        else:
            reasons.append("fleet drawdown unknown")
    except Exception as exc:
        reasons.append(f"risk check failed: {type(exc).__name__}")
    result = {"allowed": not reasons, "reasons": reasons[:10],
              "fleet_drawdown": None if drawdown is None else round(drawdown, 4)}
    if reasons:
        logger.warning(f"Risk governor | new risk REFUSED | {result}")
    return result
