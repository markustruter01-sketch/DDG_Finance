"""
Oracle Short Executor v1.0
--------------------------
Handles short-selling orders from Oracle's momentum scan.

Short candidates are tickers that ranked at the BOTTOM of the momentum
universe (most negative composite_score) and passed all quality filters:
  - composite_score < 0
  - RSI 30–70 (not oversold or overbought)
  - Price below EMA-20 (confirmed downtrend)
  - Not already in an existing short position

Safety checks before each short:
  1. check_shortable() — Alpaca asset must be shortable AND easy-to-borrow
  2. Existing position check — don't double-up on an open short
  3. Minimum price ($5) and minimum notional ($1,000)
  4. Kill switch gate — no new shorts if kill switch is tripped
"""

from __future__ import annotations

import math
from typing import Any

from loguru import logger

from execution.broker import (
    check_shortable,
    get_account,
    get_positions,
    place_short_order,
)
from execution.kill_switch import check as ks_check

MIN_PRICE     = 5.0
MIN_NOTIONAL  = 1_000.0


def execute_oracle_shorts(
    short_signals: list[dict],
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Execute short orders for Oracle's momentum short candidates.

    Parameters
    ----------
    short_signals : list of dicts from algo_scanner.run_algo_scan()["short_signals"]
    dry_run       : if True, log intent but place no orders

    Returns
    -------
    dict with placed, skipped, errors lists and summary counts
    """
    result: dict[str, Any] = {
        "placed":  [],
        "skipped": [],
        "errors":  [],
    }

    if ks_check():
        logger.warning("OracleShort | Kill switch active — no short orders placed")
        result["skipped"].append({"reason": "kill_switch_active", "count": len(short_signals)})
        return result

    if not short_signals:
        return result

    try:
        acct   = get_account()
        equity = float(acct.get("equity", 0.0))
    except Exception as exc:
        logger.error(f"OracleShort | Cannot fetch account — aborting shorts: {exc}")
        result["errors"].append({"reason": f"account_fetch_failed: {exc}"})
        return result

    try:
        open_positions = {p["symbol"]: p for p in get_positions()}
    except Exception as exc:
        logger.error(f"OracleShort | Cannot fetch positions — aborting shorts: {exc}")
        result["errors"].append({"reason": f"positions_fetch_failed: {exc}"})
        return result

    for signal in short_signals:
        ticker        = signal.get("ticker", "").upper()
        kelly         = float(signal.get("kelly_fraction", 0.10))
        price_approx  = signal.get("price")

        if not ticker:
            result["skipped"].append({"ticker": ticker, "reason": "no_ticker"})
            continue

        if ticker in open_positions:
            existing = open_positions[ticker]
            if float(existing.get("qty", 0)) < 0:
                logger.debug(f"OracleShort | {ticker} already short ({existing['qty']} shares) — skipping")
                result["skipped"].append({"ticker": ticker, "reason": "already_short"})
            else:
                logger.warning(f"OracleShort | {ticker} is held LONG — not shorting against existing long")
                result["skipped"].append({"ticker": ticker, "reason": "long_position_exists"})
            continue

        if price_approx is None or float(price_approx) < MIN_PRICE:
            logger.info(f"OracleShort | {ticker} price ${price_approx} below min ${MIN_PRICE} — skipping")
            result["skipped"].append({"ticker": ticker, "reason": f"price_too_low ({price_approx})"})
            continue

        try:
            shortable, etb = check_shortable(ticker)
        except Exception as exc:
            logger.warning(f"OracleShort | {ticker} shortability check failed: {exc}")
            result["skipped"].append({"ticker": ticker, "reason": f"shortability_check_failed: {exc}"})
            continue

        if not shortable or not etb:
            logger.info(f"OracleShort | {ticker} not shortable (shortable={shortable} etb={etb}) — skipping")
            result["skipped"].append({"ticker": ticker, "reason": f"not_shortable (etb={etb})"})
            continue

        notional_usd = equity * kelly
        if notional_usd < MIN_NOTIONAL:
            logger.info(f"OracleShort | {ticker} notional ${notional_usd:.2f} below min ${MIN_NOTIONAL} — skipping")
            result["skipped"].append({"ticker": ticker, "reason": f"notional_too_low (${notional_usd:.2f})"})
            continue

        qty_float = notional_usd / float(price_approx)
        qty_int   = max(1, math.floor(qty_float))

        if dry_run:
            logger.info(
                f"OracleShort [DRY-RUN] | {ticker} qty={qty_int} "
                f"~${qty_int * float(price_approx):,.2f} | {signal.get('thesis', '')[:80]}"
            )
            result["placed"].append({
                "ticker":   ticker,
                "qty":      qty_int,
                "notional": round(qty_int * float(price_approx), 2),
                "dry_run":  True,
            })
            continue

        try:
            order = place_short_order(ticker=ticker, qty_int=qty_int)
            logger.info(
                f"OracleShort | SHORT {ticker} qty={qty_int} "
                f"~${qty_int * float(price_approx):,.2f} "
                f"order_id={order.get('id', '?')}"
            )
            result["placed"].append({
                "ticker":   ticker,
                "qty":      qty_int,
                "notional": round(qty_int * float(price_approx), 2),
                "order_id": order.get("id"),
                "status":   order.get("status"),
            })
        except Exception as exc:
            logger.error(f"OracleShort | {ticker} short order FAILED: {exc}")
            result["errors"].append({"ticker": ticker, "error": str(exc)})

    result["placed"]  = result["placed"]
    result["skipped"] = result["skipped"]
    result["errors"]  = result["errors"]

    logger.info(
        f"OracleShort | Complete: placed={len(result['placed'])} "
        f"skipped={len(result['skipped'])} errors={len(result['errors'])}"
    )
    return result
