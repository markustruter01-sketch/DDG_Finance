"""Live fleet equity reads from configured Alpaca accounts and OANDA."""

from __future__ import annotations

import math

from loguru import logger

def get_fleet_equity() -> tuple[float, dict[str, float]]:
    """Return the summed live equity and per-bot equity breakdown."""
    from core.bot_registry import active_bot_ids
    from core.oanda_client import OandaClient
    from execution.reconciliation import _client_for

    breakdown: dict[str, float] = {}
    for bot_id in active_bot_ids():
        if bot_id == "forex_ai":
            try:
                with OandaClient() as client:
                    account = client.account_summary()
                if account.get("currency") != "USD":
                    raise ValueError(
                        f"account currency is {account.get('currency')!r}, expected 'USD'"
                    )
                equity = float(account["nav"])
            except Exception as exc:
                raise RuntimeError(
                    f"{bot_id}: failed to read USD account NAV: {exc}"
                ) from exc
            if not math.isfinite(equity) or equity <= 0:
                raise RuntimeError(
                    f"{bot_id}: account NAV must be positive, got {equity!r}"
                )
            breakdown[bot_id] = equity
            logger.info(f"Fleet equity | bot={bot_id} equity=${equity:,.2f}")
            continue

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