"""Live fleet equity reads from the configured Alpaca accounts."""

from __future__ import annotations

import math

from loguru import logger

from core import kill_switch


def get_fleet_equity() -> tuple[float, dict[str, float]]:
    """Return the summed live equity and per-bot equity breakdown."""
    from execution.reconciliation import _client_for

    breakdown: dict[str, float] = {}
    for bot_id in kill_switch.ACTIVE_BOTS:
        try:
            client = _client_for(bot_id)
        except Exception as exc:
            raise RuntimeError(
                f"{bot_id}: failed to build broker client: {exc}"
            ) from exc

        try:
            account = client.get_account()
            equity = float(account.equity)
        except Exception as exc:
            raise RuntimeError(
                f"{bot_id}: failed to read account equity: {exc}"
            ) from exc

        if not math.isfinite(equity) or equity <= 0:
            raise RuntimeError(
                f"{bot_id}: account equity must be positive, got {equity!r}"
            )

        breakdown[bot_id] = equity
        logger.info(f"Fleet equity | bot={bot_id} equity=${equity:,.2f}")

    total = sum(breakdown.values())
    if not math.isfinite(total) or total <= 0:
        raise RuntimeError(f"fleet: total equity must be positive, got {total!r}")
    logger.info(
        f"Fleet equity | total=${total:,.2f} breakdown={breakdown}"
    )
    return total, breakdown