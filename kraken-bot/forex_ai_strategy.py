"""Paused, read-only OANDA account monitor for Forex AI."""

from __future__ import annotations

import math
from typing import Any, Callable

from core.bot_state import write_heartbeat, write_portfolio
from core.oanda_client import OandaClient


BOT_ID = "forex_ai"
BOT_PAUSED = True


def _finite_amount(value: Any, field: str, *, allow_zero: bool = False) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"OANDA {field} is not numeric") from None
    if not math.isfinite(amount) or amount < 0 or (amount == 0 and not allow_zero):
        raise ValueError(f"OANDA {field} must be positive and finite")
    return amount


def run_forex_cycle(
    *,
    profile: dict[str, Any] | None = None,
    db_id: int | None = None,
    client_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Read USD account NAV and open positions, then persist portfolio health.

    This strategy intentionally has no order, trade, or position mutation path.
    """
    del profile, db_id
    factory = client_factory or OandaClient
    with factory() as client:
        account = client.account_summary()
        if account.get("currency") != "USD":
            raise ValueError(
                f"forex_ai requires a USD OANDA account; got {account.get('currency')!r}"
            )
        equity = _finite_amount(account.get("nav"), "NAV")
        cash = _finite_amount(account.get("balance"), "balance", allow_zero=True)
        positions = client.open_positions()
        if not isinstance(positions, list):
            raise ValueError("OANDA open positions response must be a list")

    write_heartbeat(
        BOT_ID,
        equity=equity,
        cash=cash,
        positions=len(positions),
        status="paused",
    )
    write_portfolio(BOT_ID, cash=cash, equity=equity, positions=positions)
    return {
        "bot_id": BOT_ID,
        "currency": "USD",
        "equity_usd": equity,
        "cash_usd": cash,
        "open_positions": len(positions),
    }