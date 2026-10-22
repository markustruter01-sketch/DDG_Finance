"""Order-rate watchdog: catches any bot or job that keeps placing orders.

Read-only. It never blocks, cancels or places anything; it raises a critical
alert. It reads each Alpaca account's own order history, so it sees every
order whichever part of the code sent it (the 14-21 Oct 2026 vault loop was
invisible to everything else: 8 orders an hour, every market hour, a week).

Two rules per account, counted on the New York trading day:
- daily: more orders today than DAILY_LIMIT;
- sustained: SUSTAINED_PER_HOUR or more orders in each of the last
  SUSTAINED_HOURS completed clock hours. A monthly rebalance is one burst;
  a loop keeps going.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from loguru import logger

NY = ZoneInfo("America/New_York")

# Claude's design values (22 Oct 2026), from Alpaca order history 5-21 Oct
# excluding the vault loop: oracle at most 9 a day, spy_qqq_trend 104 on its
# monthly rebalance day (otherwise 0-3), jerome_macro at most 2. Oracle's
# limit leaves room for the trend sleeve's first rebalance (about 40 orders).
DAILY_LIMIT = {"oracle": 60, "spy_qqq_trend": 150, "jerome_macro": 30}
SUSTAINED_PER_HOUR = 4
SUSTAINED_HOURS = 3


def evaluate(bot_id: str, submitted_at: Iterable[datetime], now: datetime) -> list[dict[str, Any]]:
    """Findings for one account from today's order submission times (any tz)."""
    now_ny = now.astimezone(NY)
    day_start = now_ny.replace(hour=0, minute=0, second=0, microsecond=0)
    times = [t.astimezone(NY) for t in submitted_at]
    today = [t for t in times if t >= day_start]
    findings = []
    limit = DAILY_LIMIT.get(bot_id)
    if limit is not None and len(today) > limit:
        findings.append({"bot_id": bot_id, "rule": "daily", "orders_today": len(today), "limit": limit})
    last_full_hour = now_ny.replace(minute=0, second=0, microsecond=0)
    per_hour = []
    for k in range(SUSTAINED_HOURS, 0, -1):
        start = last_full_hour - timedelta(hours=k)
        per_hour.append(sum(1 for t in today if start <= t < start + timedelta(hours=1)))
    if all(n >= SUSTAINED_PER_HOUR for n in per_hour):
        findings.append({"bot_id": bot_id, "rule": "sustained", "orders_per_hour": per_hour,
                         "threshold": SUSTAINED_PER_HOUR})
    return findings


def _today_submissions(bot_id: str, now: datetime) -> list[datetime]:
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest
    from execution.reconciliation import _client_for

    client = _client_for(bot_id)
    after = now.astimezone(NY).replace(hour=0, minute=0, second=0, microsecond=0)
    out: list[datetime] = []
    while True:                                   # page oldest-first, 500 at a time
        page = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.ALL, after=after,
                                                  limit=500, direction="asc"))
        out.extend(o.submitted_at for o in page if o.submitted_at)
        if len(page) < 500:
            return out
        after = page[-1].submitted_at


def run_watchdog(now: datetime | None = None) -> dict[str, Any]:
    from core.degradation_tracker import mark_resolved, record_degradation

    now = now or datetime.now(NY)
    report: dict[str, Any] = {}
    hits: dict[str, int] = {"daily": 0, "sustained": 0}
    unknown = False
    for bot_id in DAILY_LIMIT:
        try:
            findings = evaluate(bot_id, _today_submissions(bot_id, now), now)
        except Exception as exc:
            logger.warning(f"Order watchdog | {bot_id} order history unreadable: {type(exc).__name__}")
            report[bot_id] = {"status": "unknown"}
            unknown = True
            continue
        report[bot_id] = {"status": "alert" if findings else "ok", "findings": findings}
        for f in findings:
            hits[f["rule"]] += 1
            logger.critical(f"Order watchdog | {bot_id} {f}")
            record_degradation(component="order_watchdog", severity="critical",
                               error_type=f"order_rate_{f['rule']}", bot_id=bot_id,
                               message=f"{bot_id}: unusual order rate ({f['rule']}) - possible loop",
                               detail=str(f))
    # mark_resolved clears every bot's rows for a rule, so only when no bot
    # hits that rule and every account was readable.
    for rule, n in hits.items():
        if n == 0 and not unknown:
            mark_resolved("order_watchdog", f"order_rate_{rule}", reason="order rate normal")
    return report
