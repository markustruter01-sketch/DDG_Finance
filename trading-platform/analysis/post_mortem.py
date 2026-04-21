"""
Post-Mortem Updater
---------------------
Runs daily (after market close) to reconcile closed Alpaca paper trading
positions against the trade_journal.db, then saves a performance snapshot.

Logic:
  1. Pull all FILLED orders from the Alpaca paper account.
  2. For each filled order that has a corresponding 'Active' journal entry,
     compute the realised P&L vs the journal's entry price.
  3. Determine exit_reason:
       • order_type == "stop"  → ratchet_stop   (GTC stop triggered by Alpaca)
       • otherwise             → "unknown"       (allocation sell / other)
  4. Compute time_in_trade_hours from position_entry_times (PostgreSQL).
  5. Call close_trade() to stamp the trade Closed_Win / Closed_Loss and
     persist all Phase 1 RAG fields (exit_reason, time_in_trade_hours, etc.).
  6. Generate a deterministic lesson string via generate_lesson().
  7. Persist the lesson via log_post_mortem() → execution_post_mortems table.
  8. Fetch current account equity and save a performance_snapshots row.
  9. Clean up position_entry_times for the reconciled symbol.
"""

import asyncio
from datetime import date
from typing import Any

from loguru import logger

from analysis.trade_journal import (
    get_all_active_trades,
    update_trade_fill_price,
    close_trade,
    log_post_mortem,
    get_journal_summary,
    save_performance_snapshot,
    get_performance_snapshots,
)
from analysis.post_mortem_lessons import (
    generate_lesson,
    _load_regime_from_file,
    compute_hours_since,
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
                order_type = "unknown"
                try:
                    raw = order.type
                    order_type = raw.value if hasattr(raw, "value") else str(raw)
                except Exception:
                    pass
                result.append({
                    "order_id":   str(order.id),
                    "ticker":     order.symbol,
                    "side":       order.side.value,
                    "order_type": order_type,
                    "exit_price": float(order.filled_avg_price),
                    "filled_at":  str(order.filled_at),
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
    realised P&L and slippage, updates journal status, generates RAG lessons,
    then saves a performance snapshot.
    """
    logger.info("Post-mortem | Starting daily reconciliation...")

    active_trades = get_all_active_trades()
    if not active_trades:
        logger.info("Post-mortem | No active journal entries to reconcile.")
        await _save_snapshot(wins=0, losses=0)
        return {"wins": 0, "losses": 0, "skipped": 0, "message": "no active trades"}

    active_by_id = {t["trade_id"]: t for t in active_trades}
    logger.info(f"Post-mortem | {len(active_trades)} active journal entries to check")

    # ── Load position entry timestamps and regime once ─────────────────────
    entry_times: dict[str, str] = {}
    try:
        from db.postgres import get_position_entry_times, delete_position_entry
        entry_times = get_position_entry_times()
        logger.debug(f"Post-mortem | Loaded {len(entry_times)} position entry timestamps")
    except Exception as _et_exc:
        logger.warning(f"Post-mortem | Could not load entry timestamps: {_et_exc}")

    regime = _load_regime_from_file()
    logger.debug(f"Post-mortem | Current regime for lessons: {regime}")

    try:
        closed_orders = await _fetch_closed_orders()
    except Exception as exc:
        logger.error(f"Post-mortem | Failed to fetch Alpaca orders: {exc}")
        return {"wins": 0, "losses": 0, "skipped": len(active_trades), "error": str(exc)}

    logger.info(f"Post-mortem | {len(closed_orders)} closed Alpaca orders fetched")

    wins = losses = skipped = 0
    total_slippage_pct = 0.0
    slippage_count = 0
    lessons_logged = 0

    for order in closed_orders:
        order_id   = order["order_id"]
        ticker     = order["ticker"]
        order_type = order.get("order_type", "unknown")

        if order_id not in active_by_id:
            continue

        journal_entry = active_by_id[order_id]
        exit_price    = order["exit_price"]

        actual_fill      = journal_entry.get("actual_fill_price")
        intended_price: float | None = journal_entry.get("intended_price")
        entry_price: float | None = actual_fill or intended_price or journal_entry.get("entry_price")

        if not entry_price:
            logger.warning(
                f"Post-mortem | {ticker}: no entry_price in journal — skipping"
            )
            skipped += 1
            continue

        pnl_pct = (exit_price - entry_price) / entry_price * 100

        slippage_pct = None
        if intended_price and intended_price > 0 and actual_fill and actual_fill > 0:
            slippage_pct = (actual_fill - intended_price) / intended_price * 100
            total_slippage_pct += abs(slippage_pct)
            slippage_count += 1

        # ── Determine exit reason from Alpaca order type ───────────────────
        if order_type == "stop":
            exit_reason = "ratchet_stop"
        elif order_type in ("trailing_stop",):
            exit_reason = "ratchet_stop"
        else:
            exit_reason = "unknown"

        # ── Compute time in trade ──────────────────────────────────────────
        entry_ts_iso     = entry_times.get(ticker)
        time_in_hours    = compute_hours_since(entry_ts_iso)

        # ── Close trade with all Phase 1 RAG fields ────────────────────────
        # Replaces update_trade_fill_price() + update_trade_outcome() with
        # a single atomic call that also stores exit_reason / time / slippage.
        _qty = float(journal_entry.get("qty") or journal_entry.get("shares") or 0)
        realized_pnl_val = round(pnl_pct / 100.0 * entry_price * _qty, 2) if _qty > 0 else None
        try:
            close_trade(
                trade_id=order_id,
                pnl_percentage=pnl_pct,
                realized_pnl=realized_pnl_val,
                exit_reason=exit_reason,
                time_in_trade_hours=time_in_hours,
                close_price=exit_price,
            )
        except Exception as _ct_exc:
            logger.warning(f"Post-mortem | close_trade failed for {ticker}: {_ct_exc}")
            # Fallback to legacy update so we at least stamp status
            try:
                from analysis.trade_journal import update_trade_outcome
                if actual_fill is None:
                    update_trade_fill_price(order_id, exit_price)
                update_trade_outcome(order_id, pnl_pct, realized_pnl=realized_pnl_val)
            except Exception:
                pass

        # ── Generate and persist deterministic lesson ──────────────────────
        asset_class = journal_entry.get("asset_class", "equity") or "equity"
        try:
            lesson = generate_lesson(
                ticker=ticker,
                regime=regime,
                pnl_pct=pnl_pct,
                exit_reason=exit_reason,
                time_in_trade_hours=time_in_hours,
                asset_class=asset_class,
            )
            log_post_mortem(
                ticker=ticker,
                regime=regime,
                hardcoded_lesson_text=lesson,
                asset_class=asset_class,
                exit_reason=exit_reason,
                pnl_pct=pnl_pct,
                time_in_trade_hours=time_in_hours,
            )
            lessons_logged += 1
            logger.debug(f"Post-mortem | Lesson logged for {ticker}: {lesson[:80]}")
        except Exception as _lesson_exc:
            logger.warning(f"Post-mortem | lesson logging failed for {ticker}: {_lesson_exc}")

        # ── Clean up position_entry_times ──────────────────────────────────
        try:
            from db.postgres import delete_position_entry
            delete_position_entry(ticker)
        except Exception:
            pass

        slip_str = f" | slippage={slippage_pct:+.4f}%" if slippage_pct is not None else ""
        label    = f"[{exit_reason}]"

        if pnl_pct >= 0:
            wins += 1
            logger.info(
                f"Post-mortem | WIN  {ticker:8s}: "
                f"entry={entry_price:.4f} exit={exit_price:.4f} "
                f"pnl={pnl_pct:+.2f}%{slip_str} {label}"
            )
            # ── Oracle Profit Reserve — 15% of gross profit swept to ledger ──
            _asset_class = journal_entry.get("asset_class", "")
            if _asset_class == "momentum_equity":
                try:
                    _qty = float(journal_entry.get("qty") or journal_entry.get("shares") or 0)
                    if _qty > 0:
                        _profit_usd = pnl_pct / 100.0 * entry_price * _qty
                        _contribution = round(_profit_usd * 0.15, 4)
                        from db.postgres import add_oracle_profit_contribution
                        add_oracle_profit_contribution(_contribution)
                        logger.info(
                            f"Post-mortem | Oracle Profit Reserve +${_contribution:.2f} "
                            f"(15% of ${_profit_usd:.2f} from {ticker})"
                        )
                except Exception as _opr_exc:
                    logger.warning(f"Post-mortem | Oracle Profit Reserve contribution failed for {ticker}: {_opr_exc}")
        else:
            losses += 1
            logger.warning(
                f"Post-mortem | LOSS {ticker:8s}: "
                f"entry={entry_price:.4f} exit={exit_price:.4f} "
                f"pnl={pnl_pct:+.2f}%{slip_str} {label}"
            )

    avg_slippage = total_slippage_pct / slippage_count if slippage_count > 0 else 0.0

    summary = {
        "wins":          wins,
        "losses":        losses,
        "skipped":       skipped,
        "lessons_logged": lessons_logged,
        "slippage_stats": {
            "trades_with_slippage":  slippage_count,
            "avg_abs_slippage_pct":  round(avg_slippage, 4),
        },
    }
    logger.info(
        f"Post-mortem | Complete — "
        f"Wins: {wins} | Losses: {losses} | Skipped: {skipped} | "
        f"Lessons: {lessons_logged} | "
        f"Avg slippage: {avg_slippage:.4f}%"
    )

    snapshot_info = await _save_snapshot(wins=wins, losses=losses)
    summary["snapshot"] = snapshot_info

    # ── Phase 4: Permanent Rules Rollup ────────────────────────────────────
    # Scan execution_post_mortems for recurring failure patterns and promote
    # them to permanent rules that persist in every future LLM system prompt.
    # This is non-fatal — a rollup failure never aborts the post-mortem cycle.
    try:
        from analysis.rule_engine import rollup_permanent_rules
        rollup_result = rollup_permanent_rules()
        summary["rule_rollup"] = rollup_result
        if rollup_result.get("rules_promoted", 0) > 0:
            logger.info(
                f"Phase 4 | {rollup_result['rules_promoted']} new permanent rule(s) promoted "
                f"from {rollup_result['patterns_scanned']} recurring failure patterns"
            )
    except Exception as exc:
        logger.warning(f"Phase 4 | Permanent rules rollup failed (non-fatal): {exc}")
        summary["rule_rollup"] = {"error": str(exc)}

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
        "saved":                True,
        "date":                 today,
        "equity":               equity,
        "daily_pnl_pct":        daily_pnl_pct,
        "cumulative_pnl_pct":   cumulative_pnl_pct,
    }
