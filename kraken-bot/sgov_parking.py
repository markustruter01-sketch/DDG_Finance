"""
SGOV idle-cash parking — subordinated to all real strategy trades.

Design rules:
  • SGOV is NEVER a strategy position. Never counts toward position caps,
    correlation caps, vol-targeting notional, or P&L attribution.
  • park_idle_cash()  — call AFTER all entry/exit logic; buys SGOV if idle cash > threshold.
  • unpark_for_entry() — call BEFORE any new entry order; sells SGOV to free cash.
  • All errors are fail-open: log loud, skip the parking step, keep cash liquid.
    A parking failure must NEVER block or delay a real trade.
  • Round-trip friction (buy/sell spread cost) is logged per cycle.
"""
from __future__ import annotations

import time
from loguru import logger
from jerome_alpaca import _nyse_is_open
from core.cash_park import CASH_PARK_SYMBOLS, is_cash_park
from core.bot_state import apply_position_fill_delta

PARK_SYMBOL          = next(iter(CASH_PARK_SYMBOLS))
PARK_THRESHOLD_USD   = 1_000.0   # minimum idle cash to bother parking
CASH_BUFFER_USD      = 50.0      # always leave a small liquidity buffer


def is_sgov(pos: dict) -> bool:
    """True if this position is a cash-parking SGOV holding."""
    return is_cash_park(pos.get("symbol"))


def filter_alpha_positions(live_positions: list[dict]) -> list[dict]:
    """
    Return only real strategy positions — strip SGOV cash-park holdings.
    Use this everywhere SGOV must not affect position counts, deployment math,
    or correlation-cap inputs.
    """
    return [p for p in live_positions if not is_sgov(p)]


def _find_sgov(live_positions: list[dict]) -> dict | None:
    """Return the SGOV position dict if held, else None."""
    for p in live_positions:
        if is_sgov(p):
            return p
    return None


def park_idle_cash(
    engine,
    bot_label: str,
    live_positions: list[dict],
    account_cash: float,
    *,
    buy_side: str = "buy",   # "buy" for AlpacaEtfEngine; "long" for JeromeAlpaca
    bot_id: str | None = None,
) -> None:
    """
    After all entry/exit logic: park idle cash in SGOV.

    Args:
        engine:       broker object with place_order(symbol, side, notional) → dict | None
        bot_label:    short string for log lines (e.g. "Asia", "Bot2", "Jerome")
        live_positions: current live positions (may include SGOV; function handles it)
        account_cash: float cash balance from get_account()
        buy_side:     side keyword for place_order ("buy" or "long")
    """
    try:
        if _find_sgov(live_positions) is not None:
            logger.debug(f"{bot_label} | SGOV park: already holding SGOV — skip")
            return

        if account_cash <= PARK_THRESHOLD_USD:
            logger.debug(
                f"{bot_label} | SGOV park: idle cash ${account_cash:,.2f} "
                f"≤ threshold ${PARK_THRESHOLD_USD:,.0f} — skip"
            )
            return

        notional = round(account_cash - CASH_BUFFER_USD, 2)
        if notional <= 0:
            return

        logger.info(
            f"{bot_label} | SGOV PARK: buying ${notional:,.2f} SGOV "
            f"(idle cash=${account_cash:,.2f})"
        )
        t0      = time.monotonic()
        result  = engine.place_order(PARK_SYMBOL, buy_side, notional)
        elapsed = time.monotonic() - t0

        if result:
            if bot_id and result.get("order_id"):
                order = engine.api.get_order(result["order_id"])
                filled_qty = float(getattr(order, "filled_qty", 0) or 0)
                if filled_qty > 0:
                    apply_position_fill_delta(bot_id, PARK_SYMBOL, "buy", filled_qty)
            logger.info(
                f"{bot_label} | SGOV PARK ✅ notional=${notional:,.2f} "
                f"order_id={result.get('order_id', '?')} latency={elapsed:.2f}s"
            )
        else:
            logger.warning(
                f"{bot_label} | SGOV PARK: place_order returned falsy — "
                "cash stays liquid (non-fatal)"
            )
    except Exception as exc:
        logger.error(
            f"{bot_label} | SGOV PARK ERROR (non-fatal, cash stays liquid): {exc}"
        )


def unpark_for_entry(
    engine,
    bot_label: str,
    live_positions: list[dict],
    *,
    bot_id: str | None = None,
) -> float:
    """
    Before placing any new entry order: liquidate SGOV to free up cash.

    Returns approximate market_value freed (0.0 if SGOV not held or on error).
    Failure is non-fatal — entry proceeds whether or not SGOV was sold.
    """
    if not _nyse_is_open():
        logger.debug(
            f"{bot_label} | SGOV unpark skipped — market closed "
            "(entry also gated; nothing to fund after-hours)"
        )
        return 0.0

    sgov = _find_sgov(live_positions)
    if sgov is None:
        return 0.0

    market_value = float(sgov.get("market_value", 0) or 0)
    logger.info(
        f"{bot_label} | SGOV UNPARK: selling SGOV (≈${market_value:,.2f}) "
        "to free cash for incoming entry"
    )
    t0 = time.monotonic()
    try:
        before_qty = abs(float(sgov.get("qty", 0) or 0))
        ok = engine.close_position(PARK_SYMBOL)
        elapsed = time.monotonic() - t0
        if ok:
            if bot_id and before_qty > 0:
                after = next(
                    (p for p in engine.get_strategy_positions(bot_id) if is_sgov(p)),
                    None,
                )
                after_qty = abs(float(after.get("qty", 0) or 0)) if after else 0.0
                sold_qty = max(0.0, before_qty - after_qty)
                if sold_qty > 0:
                    apply_position_fill_delta(bot_id, PARK_SYMBOL, "sell", sold_qty)
            logger.info(
                f"{bot_label} | SGOV UNPARK ✅ freed ≈${market_value:,.2f} "
                f"latency={elapsed:.2f}s "
                f"[friction note: check slippage in next fill log]"
            )
            return market_value
        else:
            logger.warning(
                f"{bot_label} | SGOV UNPARK: close_position returned False "
                "— entry proceeds with existing cash (non-fatal)"
            )
            return 0.0
    except Exception as exc:
        logger.error(
            f"{bot_label} | SGOV UNPARK ERROR (non-fatal, entry proceeds): {exc}"
        )
        return 0.0
