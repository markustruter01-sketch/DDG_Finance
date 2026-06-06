"""
Oracle Stop Backfill — one-shot idempotent GTC stop placement for naked open positions.

Places GTC stop orders on Oracle positions that have a DB stop_price but no broker stop
(stop_order_id IS NULL).  Targets floor(live_qty) whole shares.  Uses the EXISTING
ratchet_stops.stop_price — does NOT recompute stop levels.

Usage (dev console or control endpoint — do NOT wire into entry path):
    from execution.stop_backfill import backfill_oracle_stops
    results = backfill_oracle_stops(dry_run=True)   # inspect first
    results = backfill_oracle_stops()               # live run on Markus's go

Idempotent: positions that already have a non-null stop_order_id are skipped.
Account: Oracle (ALPACA_API_KEY / ALPACA_SECRET_KEY) — NOT Jerome's credentials.
"""

import math

from loguru import logger

from execution.broker import get_positions, place_stop_order
from execution.ratchet_stop import get_stop, save_stop


def backfill_oracle_stops(dry_run: bool = False) -> dict:
    """
    For each open Oracle Alpaca position with stop_order_id IS NULL:
      - Read live qty → floor to whole shares (stop_qty)
      - Use EXISTING ratchet_stops.stop_price (no recompute)
      - Place GTC stop order, capture order_id, persist via save_stop
      - Log: ticker, stop_qty, stop_price, order_id

    Returns dict: {placed: [...], skipped: [...], failed: [...]}
    """
    results: dict = {"placed": [], "skipped": [], "failed": []}

    try:
        live_positions = get_positions()
    except Exception as exc:
        logger.error(f"StopBackfill | Cannot fetch Alpaca positions: {exc}")
        return results

    live_qty_by_symbol: dict[str, float] = {
        p["symbol"]: float(p.get("qty", 0) or 0)
        for p in live_positions
    }

    if not live_qty_by_symbol:
        logger.info("StopBackfill | No open Alpaca positions — nothing to backfill")
        return results

    logger.info(
        f"StopBackfill | {'[DRY RUN] ' if dry_run else ''}"
        f"Checking {len(live_qty_by_symbol)} open positions: {sorted(live_qty_by_symbol)}"
    )

    for symbol, live_qty in sorted(live_qty_by_symbol.items()):
        ratchet = get_stop(symbol)

        if ratchet is None:
            logger.debug(f"StopBackfill | {symbol}: no ratchet_stop record — skip")
            results["skipped"].append({"symbol": symbol, "reason": "no_ratchet_record"})
            continue

        existing_order_id = ratchet.get("stop_order_id")
        if existing_order_id is not None:
            logger.info(
                f"StopBackfill | {symbol}: already has stop_order_id={existing_order_id} — skip (idempotent)"
            )
            results["skipped"].append({
                "symbol":   symbol,
                "reason":   "already_has_order",
                "order_id": existing_order_id,
            })
            continue

        stop_price = ratchet.get("stop_price")
        fill_price = ratchet.get("fill_price")
        atr        = ratchet.get("atr", 0.0)
        atr_mult   = ratchet.get("atr_multiplier", 2.0)
        side       = ratchet.get("side", "long")

        if stop_price is None:
            logger.error(f"StopBackfill | {symbol}: ratchet record has no stop_price — skip")
            results["skipped"].append({"symbol": symbol, "reason": "no_stop_price"})
            continue

        stop_qty = math.floor(abs(live_qty))

        if stop_qty < 1:
            logger.error(
                f"StopBackfill | {symbol}: sub-1-share after floor "
                f"(live_qty={live_qty:.6f}) — cannot place broker stop"
            )
            results["failed"].append({
                "symbol":   symbol,
                "reason":   "sub_1_share",
                "live_qty": live_qty,
            })
            continue

        logger.info(
            f"StopBackfill | {symbol}: live_qty={live_qty:.6f} → stop_qty={stop_qty} "
            f"stop_price=${stop_price:.4f} side={side}"
            + (" [DRY RUN]" if dry_run else "")
        )

        if dry_run:
            results["placed"].append({
                "symbol":     symbol,
                "live_qty":   live_qty,
                "stop_qty":   stop_qty,
                "stop_price": stop_price,
                "order_id":   "DRY_RUN",
                "dry_run":    True,
            })
            continue

        try:
            order    = place_stop_order(symbol, stop_qty, stop_price)
            order_id = order.get("id")
            save_stop(
                symbol, stop_price, fill_price, atr, atr_mult,
                side=side, stop_order_id=order_id,
            )
            logger.info(
                f"StopBackfill | ✓ {symbol}: GTC stop placed "
                f"qty={stop_qty} stop=${stop_price:.4f} order_id={order_id}"
            )
            results["placed"].append({
                "symbol":     symbol,
                "live_qty":   live_qty,
                "stop_qty":   stop_qty,
                "stop_price": stop_price,
                "order_id":   order_id,
            })
        except Exception as exc:
            logger.error(
                f"StopBackfill | ✗ {symbol}: GTC stop FAILED "
                f"(qty={stop_qty} stop=${stop_price:.4f}): {exc}"
            )
            results["failed"].append({
                "symbol":     symbol,
                "live_qty":   live_qty,
                "stop_qty":   stop_qty,
                "stop_price": stop_price,
                "error":      str(exc),
            })

    placed  = len(results["placed"])
    skipped = len(results["skipped"])
    failed  = len(results["failed"])
    logger.info(
        f"StopBackfill | {'[DRY RUN] ' if dry_run else ''}"
        f"Done — placed={placed} skipped={skipped} failed={failed}"
    )
    return results
