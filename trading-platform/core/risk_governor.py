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
- the fleet drawdown cannot be computed.

Fleet drawdown limits (core/risk_limits.py, medium risk): above
SOFT_DRAWDOWN, or a kill-switch fleet_drawdown condition, new risk is
refused only when ENFORCE_DRAWDOWN_LIMITS is True. On paper (False) the
check passes and the refusal it would have made is recorded instead
(core/risk_shadow.py, table risk_limit_shadow).
"""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from core.risk_limits import ENFORCE_DRAWDOWN_LIMITS, SOFT_DRAWDOWN

DRAWDOWN_TRIGGERS = frozenset({"fleet_drawdown"})


def new_risk_check(
    *,
    snapshot: dict[str, Any] | None = None,
    latch: Callable[[], bool] | None = None,
    enforce_drawdown: bool = ENFORCE_DRAWDOWN_LIMITS,
    record: Callable[..., None] | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    drawdown_reasons: list[str] = []
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
            reason = f"kill switch would trip: {t.get('trigger', 'unknown')} {who}".strip()
            (drawdown_reasons if t.get("trigger") in DRAWDOWN_TRIGGERS else reasons).append(reason)
        equity, hwm = snapshot.get("fleet_equity"), snapshot.get("fleet_hwm")
        if equity and hwm and float(hwm) > 0:
            drawdown = max(0.0, (float(hwm) - float(equity)) / float(hwm))
            if drawdown > SOFT_DRAWDOWN:
                drawdown_reasons.append(f"fleet drawdown {drawdown:.1%} above the {SOFT_DRAWDOWN:.0%} soft limit")
        else:
            reasons.append("fleet drawdown unknown")
    except Exception as exc:
        reasons.append(f"risk check failed: {type(exc).__name__}")
    if enforce_drawdown:
        reasons.extend(drawdown_reasons)
    elif drawdown_reasons:
        if record is None:
            from core.risk_shadow import record_would_refuse as record
        record(drawdown, snapshot, drawdown_reasons)
    result = {"allowed": not reasons, "reasons": reasons[:10],
              "fleet_drawdown": None if drawdown is None else round(drawdown, 4)}
    if drawdown_reasons and not enforce_drawdown:
        result["record_only"] = drawdown_reasons[:10]
    if reasons:
        logger.warning(f"Risk governor | new risk REFUSED | {result}")
    return result
