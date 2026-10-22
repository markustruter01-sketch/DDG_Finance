"""Broker fills that a bot's own ledger has not booked yet ("settling").

The bots book fills into their own tables on their next hourly cycle. Until
then the broker and the ledger disagree for a reason that clears by itself:
on 22 Oct 2026 Momentum's stop-outs and SGOV cash-parking buys stayed
unbooked for 9-60 minutes and raised about 60 false 'critical' alerts.

A symbol with a broker fill in the last SETTLING_WINDOW is reported as
settling instead of as a mismatch. A gap that is still there after the
window alerts exactly as before. If the fill list cannot be read, nothing is
treated as settling (alerts behave as before).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from loguru import logger

from core.symbols import canonical_symbol

# One hourly bot cycle plus margin (the slowest catch-up seen on 22 Oct was
# about 60 minutes, an SGOV buy at 19:55 UTC still unbooked at 20:47).
SETTLING_WINDOW = timedelta(minutes=90)

# Finding kinds a not-yet-booked fill can cause. Anything else (vault gaps,
# stale portfolios, failed reads, orphaned stops on other symbols) is untouched.
SETTLING_KINDS = frozenset({
    "ledger_without_broker",
    "broker_without_ledger",
    "quantity_mismatch",
    "ledger_orphan",
    "ledger_stop_without_broker",
    "broker_open_order_without_ledger",
})


def recent_fill_symbols(client, now: datetime | None = None,
                        window: timedelta = SETTLING_WINDOW) -> set[str]:
    """Symbols with a fill on this Alpaca account inside ``window``.

    Uses the account-activities feed (by fill time), not the order list, so a
    stop placed days ago that filled minutes ago is caught. Raises on read
    failure; callers decide the fallback.
    """
    now = now or datetime.now(timezone.utc)
    since = now - window
    rows = client.get(
        "/account/activities/FILL",
        {"after": since.strftime("%Y-%m-%dT%H:%M:%SZ"), "direction": "desc", "page_size": 100},
    )
    symbols: set[str] = set()
    for row in rows or []:
        raw_time = str(row.get("transaction_time") or "")
        try:
            filled_at = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        except ValueError:
            continue
        if filled_at >= since and row.get("symbol"):
            symbols.add(canonical_symbol(row["symbol"]))
    return symbols


def safe_recent_fill_symbols(bot_id: str, client, now: datetime | None = None) -> set[str]:
    """recent_fill_symbols, or an empty set (alerts as before) if unreadable."""
    try:
        return recent_fill_symbols(client, now)
    except Exception as exc:
        logger.warning(f"Settling | fill activity unreadable for {bot_id}: {exc}")
        return set()


def split_settling(findings: Iterable[dict[str, Any]],
                   settling: dict[str, set[str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split findings into (still mismatches, settling)."""
    from core.bot_registry import resolve_bot_id

    kept: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    for finding in findings:
        bot_id, symbol = finding.get("bot_id"), finding.get("symbol")
        if finding.get("kind") in SETTLING_KINDS and bot_id and symbol:
            try:
                bot_id = resolve_bot_id(str(bot_id))
            except Exception:
                bot_id = str(bot_id)
            if canonical_symbol(symbol) in settling.get(bot_id, set()):
                held.append(finding)
                continue
        kept.append(finding)
    return kept, held
