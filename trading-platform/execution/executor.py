"""
Trade Executor — Converts Allocations → Alpaca Orders
--------------------------------------------------------
Takes the validated AnalysisOutput from Phase 3 and executes each slot:

  1. Fetch current account equity.
  2. Liquidate positions no longer in today's plan (exits).
  3. For each active slot, compute notional USD from Kelly fraction × equity.
  4. Skip SGOV slots and slots that are already held at correct size.
  5. Place market buy orders for new/changed positions.
  6. Log every new trade to the SQLite journal for the RAG loop.

Design decisions:
  - SGOV slots are never traded (they represent "do nothing" cash).
  - We close stale positions BEFORE opening new ones (free capital first).
  - A per-slot min notional of $100 is enforced (Alpaca min is $1, but
    fractional ETF slippage on tiny notionals is not worth it).
  - All orders are DAY market orders (filled same session or cancelled).
"""

from loguru import logger

from analysis.schemas import AnalysisOutput, AllocationSlot
from analysis.trade_journal import log_trade
from execution.broker import (
    close_position,
    get_account,
    get_positions,
    place_order,
)

MIN_NOTIONAL_USD = 100.0   # Minimum dollar size per trade slot
CASH_TICKER      = "SGOV"


def execute_allocations(output: AnalysisOutput, dry_run: bool = False) -> dict:
    """
    Execute the 10-slot allocation plan against Alpaca paper trading.

    Args:
        output:  Validated AnalysisOutput from the analysis cycle.
        dry_run: If True, compute all sizes but don't place real orders.

    Returns:
        Execution summary dict with placed, skipped, closed, errors.
    """
    logger.info("=" * 60)
    logger.info("EXECUTION CYCLE STARTING")
    logger.info("=" * 60)

    acct = get_account()
    equity = acct["equity"]
    logger.info(f"Account equity: ${equity:,.2f} | cash: ${acct['cash']:,.2f}")

    current_positions = {p["symbol"]: p for p in get_positions()}
    logger.info(f"Current open positions: {list(current_positions.keys()) or 'none'}")

    active_tickers = {
        a.ticker for a in output.allocations
        if a.ticker != CASH_TICKER and a.kelly_fraction > 0
    }

    results = {
        "equity":          equity,
        "dry_run":         dry_run,
        "placed":          [],
        "skipped":         [],
        "closed":          [],
        "errors":          [],
    }

    results = _close_stale_positions(
        current_positions, active_tickers, results, dry_run
    )

    for slot in sorted(output.allocations, key=lambda x: x.slot):
        results = _execute_slot(slot, equity, current_positions, results, dry_run)

    logger.info("=" * 60)
    logger.info("EXECUTION CYCLE COMPLETE")
    logger.info(
        f"  Placed:  {len(results['placed'])} orders | "
        f"Closed: {len(results['closed'])} positions | "
        f"Skipped: {len(results['skipped'])} | "
        f"Errors: {len(results['errors'])}"
    )
    logger.info("=" * 60)

    return results


def _close_stale_positions(
    current_positions: dict,
    active_tickers: set,
    results: dict,
    dry_run: bool,
) -> dict:
    """
    Close positions that are no longer in today's allocation plan.
    """
    stale = [sym for sym in current_positions if sym not in active_tickers and sym != CASH_TICKER]

    if not stale:
        logger.info("No stale positions to close")
        return results

    for symbol in stale:
        pos = current_positions[symbol]
        logger.warning(
            f"Closing stale position: {symbol} | "
            f"value=${pos['market_value']:,.2f} | "
            f"P&L={pos['unrealized_pl']:+.2f}"
        )
        if dry_run:
            results["closed"].append({"symbol": symbol, "action": "would_close", "dry_run": True})
            continue
        try:
            order = close_position(symbol)
            results["closed"].append({"symbol": symbol, "order": order})
        except Exception as exc:
            logger.error(f"Failed to close {symbol}: {exc}")
            results["errors"].append({"symbol": symbol, "error": str(exc)})

    return results


def _execute_slot(
    slot: AllocationSlot,
    equity: float,
    current_positions: dict,
    results: dict,
    dry_run: bool,
) -> dict:
    """
    Execute a single allocation slot.
    """
    ticker = slot.ticker

    if ticker == CASH_TICKER or slot.kelly_fraction == 0.0:
        logger.info(f"Slot {slot.slot:2d}: {ticker:6s} → CASH/SKIP (kelly=0)")
        results["skipped"].append({"slot": slot.slot, "ticker": ticker, "reason": "cash_or_zero_kelly"})
        return results

    notional_usd = equity * slot.kelly_fraction

    if notional_usd < MIN_NOTIONAL_USD:
        logger.info(
            f"Slot {slot.slot:2d}: {ticker:6s} → SKIP (${notional_usd:.2f} < ${MIN_NOTIONAL_USD} min)"
        )
        results["skipped"].append({
            "slot": slot.slot, "ticker": ticker,
            "reason": f"below_min_notional (${notional_usd:.2f})",
        })
        return results

    if ticker in current_positions:
        existing_value = current_positions[ticker]["market_value"]
        target_value   = notional_usd
        diff_pct = abs(target_value - existing_value) / existing_value if existing_value > 0 else 1.0

        if diff_pct < 0.10:
            logger.info(
                f"Slot {slot.slot:2d}: {ticker:6s} → HOLD "
                f"(existing=${existing_value:,.2f}, target=${target_value:,.2f}, diff={diff_pct:.1%})"
            )
            results["skipped"].append({
                "slot": slot.slot, "ticker": ticker,
                "reason": f"already_held_within_10pct (diff={diff_pct:.1%})",
            })
            return results

    logger.info(
        f"Slot {slot.slot:2d}: {ticker:6s} | "
        f"kelly={slot.kelly_fraction:.1%} | "
        f"notional=${notional_usd:,.2f} | "
        f"conv={slot.conviction_score:.0%}"
    )

    if dry_run:
        results["placed"].append({
            "slot":         slot.slot,
            "ticker":       ticker,
            "notional_usd": notional_usd,
            "kelly":        slot.kelly_fraction,
            "conviction":   slot.conviction_score,
            "dry_run":      True,
        })
        return results

    try:
        order = place_order(ticker=ticker, notional_usd=notional_usd)
        results["placed"].append({
            "slot":         slot.slot,
            "ticker":       ticker,
            "notional_usd": notional_usd,
            "order_id":     order["id"],
            "order_status": order["status"],
        })
        log_trade(
            trade_id=order["id"],
            ticker=ticker,
            asset_class=slot.asset_class,
            conviction_score=slot.conviction_score,
            original_thesis=slot.thesis,
        )
        logger.info(f"  → Logged to journal: trade_id={order['id']}")

    except Exception as exc:
        logger.error(f"Slot {slot.slot}: order failed for {ticker}: {exc}")
        results["errors"].append({
            "slot":   slot.slot,
            "ticker": ticker,
            "error":  str(exc),
        })

    return results
