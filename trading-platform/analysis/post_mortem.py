"""
Post-Mortem Updater
---------------------
Runs daily (after market close) to reconcile closed Alpaca paper trading
positions against the trade_journal.db.

Logic:
  1. Pull all FILLED orders from the Alpaca paper account.
  2. For each filled order that has a corresponding 'Active' journal entry,
     compute the realised P&L vs the journal's entry price.
  3. Call update_trade_outcome() to stamp the trade Closed_Win / Closed_Loss.

Note on P&L calculation:
  Alpaca's filled orders carry a `filled_avg_price` (exit price).
  The entry price is reconstructed from the original order's `filled_avg_price`
  when the trade was first logged. Because paper trading orders may be
  partially filled or split across multiple orders, we match on trade_id
  which equals the original Alpaca order ID stored at order placement time.

  For a long position:
      pnl_pct = (exit_price - entry_price) / entry_price * 100

  The entry price is stored in the journal at log_trade() time by the
  execution module. If it is unavailable (e.g. SGOV cash-equivalent fills),
  the trade is skipped silently.
"""

import asyncio
from typing import Any

from loguru import logger

from analysis.trade_journal import get_all_active_trades, update_trade_outcome
from config.settings import settings


def _get_trading_client():
    """Lazy import so the module can be loaded without Alpaca keys during testing."""
    from alpaca.trading.client import TradingClient
    return TradingClient(
        api_key=settings.alpaca_api_key,
        secret_key=settings.alpaca_secret_key,
        paper=True,
    )


async def _fetch_closed_orders() -> list[dict[str, Any]]:
    """
    Fetch all closed (filled) orders from Alpaca paper account.
    Runs the blocking SDK call in a thread pool.
    """
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus

    def _blocking_fetch() -> list[dict[str, Any]]:
        client = _get_trading_client()
        request = GetOrdersRequest(
            status=QueryOrderStatus.CLOSED,
            limit=500,
        )
        orders = client.get_orders(filter=request)
        result = []
        for order in orders:
            if order.filled_avg_price is not None:
                result.append({
                    "order_id": str(order.id),
                    "ticker": order.symbol,
                    "side": order.side.value,
                    "exit_price": float(order.filled_avg_price),
                    "filled_at": str(order.filled_at),
                })
        return result

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _blocking_fetch)


async def run_post_mortem() -> dict[str, Any]:
    """
    Daily post-mortem reconciliation.

    Matches Alpaca closed orders against active journal entries, computes
    realised P&L, and updates the journal status accordingly.

    Returns:
        Summary dict with counts of wins, losses, and skipped trades.
    """
    logger.info("Post-mortem | Starting daily reconciliation...")

    active_trades = get_all_active_trades()
    if not active_trades:
        logger.info("Post-mortem | No active journal entries to reconcile.")
        return {"wins": 0, "losses": 0, "skipped": 0, "message": "no active trades"}

    active_by_id = {t["trade_id"]: t for t in active_trades}
    logger.info(f"Post-mortem | {len(active_trades)} active journal entries to check")

    try:
        closed_orders = await _fetch_closed_orders()
    except Exception as exc:
        logger.error(f"Post-mortem | Failed to fetch Alpaca orders: {exc}")
        return {"wins": 0, "losses": 0, "skipped": len(active_trades), "error": str(exc)}

    logger.info(f"Post-mortem | {len(closed_orders)} closed Alpaca orders fetched")

    wins = losses = skipped = 0

    for order in closed_orders:
        order_id = order["order_id"]
        if order_id not in active_by_id:
            continue

        journal_entry = active_by_id[order_id]
        exit_price = order["exit_price"]

        entry_price: float | None = journal_entry.get("entry_price")
        if not entry_price:
            logger.warning(
                f"Post-mortem | {order['ticker']}: no entry_price in journal — skipping"
            )
            skipped += 1
            continue

        pnl_pct = (exit_price - entry_price) / entry_price * 100
        update_trade_outcome(order_id, pnl_pct)

        if pnl_pct >= 0:
            wins += 1
            logger.info(
                f"Post-mortem | WIN  {order['ticker']:8s}: "
                f"entry={entry_price:.4f} exit={exit_price:.4f} "
                f"pnl={pnl_pct:+.2f}%"
            )
        else:
            losses += 1
            logger.warning(
                f"Post-mortem | LOSS {order['ticker']:8s}: "
                f"entry={entry_price:.4f} exit={exit_price:.4f} "
                f"pnl={pnl_pct:+.2f}%"
            )

    summary = {"wins": wins, "losses": losses, "skipped": skipped}
    logger.info(
        f"Post-mortem | Complete — "
        f"Wins: {wins} | Losses: {losses} | Skipped: {skipped}"
    )
    return summary
