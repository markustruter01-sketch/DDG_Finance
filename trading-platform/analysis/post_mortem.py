"""
Post-Mortem Updater
---------------------
Runs daily (after market close) to reconcile closed Alpaca paper trading
positions against the trade_journal.db, then saves a performance snapshot.

Logic:
  1. Pull all FILLED orders from the Alpaca paper account.
  2. For each filled order that has a corresponding 'Active' journal entry,
     compute the realised P&L vs the journal's entry price.
  3. Calculate slippage between intended_price and actual_fill_price.
  4. Call update_trade_outcome() to stamp the trade Closed_Win / Closed_Loss.
  5. Fetch current account equity and save a performance_snapshots row.
"""

import asyncio
from datetime import date
from typing import Any

from loguru import logger

from analysis.trade_journal import (
    get_all_active_trades,
    update_trade_outcome,
    update_trade_fill_price,
    get_journal_summary,
    save_performance_snapshot,
    get_performance_snapshots,
)
from config.settings import settings


def _get_trading_client():
    from alpaca.trading.client import TradingClient
    return TradingClient(
        api_key=settings.alpaca_api_key,
        secret_key=settings.alpaca_secret_key,
        paper=True,
    )


async def _fetch_closed_orders() -> list[dict[str, Any]]:
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


async def _fetch_current_equity() -> float | None:
    def _blocking_fetch() -> float | None:
        try:
            client = _get_trading_client()
            acct = client.get_account()
            return float(acct.equity)
        except Exception as exc:
            logger.warning(f"Post-mortem | Could not fetch equity for snapshot: {exc}")
            return None

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _blocking_fetch)


async def run_post_mortem() -> dict[str, Any]:
    """
    Daily post-mortem reconciliation.

    Matches Alpaca closed orders against active journal entries, computes
    realised P&L and slippage, updates journal status, then saves a
    performance snapshot.
    """
    logger.info("Post-mortem | Starting daily reconciliation...")

    active_trades = get_all_active_trades()
    if not active_trades:
        logger.info("Post-mortem | No active journal entries to reconcile.")
        await _save_snapshot(wins=0, losses=0)
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
    total_slippage_pct = 0.0
    slippage_count = 0

    for order in closed_orders:
        order_id = order["order_id"]
        if order_id not in active_by_id:
            continue

        journal_entry = active_by_id[order_id]
        exit_price = order["exit_price"]

        if journal_entry.get("actual_fill_price") is None:
            update_trade_fill_price(order_id, exit_price)

        actual_fill = journal_entry.get("actual_fill_price")
        intended_price: float | None = journal_entry.get("intended_price")

        entry_price: float | None = actual_fill or intended_price or journal_entry.get("entry_price")

        if not entry_price:
            logger.warning(
                f"Post-mortem | {order['ticker']}: no entry_price in journal — skipping"
            )
            skipped += 1
            continue

        pnl_pct = (exit_price - entry_price) / entry_price * 100

        slippage_pct = None
        if intended_price and intended_price > 0 and actual_fill and actual_fill > 0:
            slippage_pct = (actual_fill - intended_price) / intended_price * 100
            total_slippage_pct += abs(slippage_pct)
            slippage_count += 1

        update_trade_outcome(order_id, pnl_pct)

        slip_str = f" | slippage={slippage_pct:+.4f}%" if slippage_pct is not None else ""

        if pnl_pct >= 0:
            wins += 1
            logger.info(
                f"Post-mortem | WIN  {order['ticker']:8s}: "
                f"entry={entry_price:.4f} exit={exit_price:.4f} "
                f"pnl={pnl_pct:+.2f}%{slip_str}"
            )
        else:
            losses += 1
            logger.warning(
                f"Post-mortem | LOSS {order['ticker']:8s}: "
                f"entry={entry_price:.4f} exit={exit_price:.4f} "
                f"pnl={pnl_pct:+.2f}%{slip_str}"
            )

    avg_slippage = total_slippage_pct / slippage_count if slippage_count > 0 else 0.0

    summary = {
        "wins": wins,
        "losses": losses,
        "skipped": skipped,
        "slippage_stats": {
            "trades_with_slippage": slippage_count,
            "avg_abs_slippage_pct": round(avg_slippage, 4),
        },
    }
    logger.info(
        f"Post-mortem | Complete — "
        f"Wins: {wins} | Losses: {losses} | Skipped: {skipped} | "
        f"Avg slippage: {avg_slippage:.4f}%"
    )

    snapshot_info = await _save_snapshot(wins=wins, losses=losses)
    summary["snapshot"] = snapshot_info
    return summary


async def _save_snapshot(wins: int, losses: int) -> dict[str, Any]:
    today = date.today().isoformat()
    equity = await _fetch_current_equity()
    if equity is None:
        logger.warning("Post-mortem | Skipping performance snapshot — equity unavailable")
        return {"saved": False, "reason": "equity unavailable"}

    win_rate = wins / max(wins + losses, 1) if (wins + losses) > 0 else 0.0

    snapshots = get_performance_snapshots(limit=1000)
    initial_equity = snapshots[0]["equity"] if snapshots else equity
    cumulative_pnl_pct = (equity - initial_equity) / initial_equity * 100 if initial_equity else 0.0

    prev_equity = snapshots[-1]["equity"] if snapshots else equity
    daily_pnl_pct = (equity - prev_equity) / prev_equity * 100 if prev_equity else 0.0

    trades_placed_today = wins + losses

    save_performance_snapshot(
        snap_date=today,
        equity=equity,
        daily_pnl_pct=daily_pnl_pct,
        cumulative_pnl_pct=cumulative_pnl_pct,
        win_rate=win_rate,
        trades_placed=trades_placed_today,
    )
    return {
        "saved": True,
        "date": today,
        "equity": equity,
        "daily_pnl_pct": daily_pnl_pct,
        "cumulative_pnl_pct": cumulative_pnl_pct,
    }
