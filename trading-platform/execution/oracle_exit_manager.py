"""
Oracle Exit Manager — Stock Trend Follower v1.0
-----------------------------------------------
Evaluates every open Oracle stock position every 15-minute cycle.

Exit conditions (in priority order):
  1. Trailing stop hit            → immediate (overrides min-hold)
  2. EMA20 crosses back through EMA50 → trend reversal confirmed
  3. ADX < 20                     → trend is dying
  4. Held ≥ 15 trading days       → max hold time reached

Min-hold guard:
  Conditions 2/3/4 are suppressed within the first 4 hours after entry.
  Condition 1 (trailing stop) always fires immediately.

Trailing stop lifecycle:
  - Initialised on the first cycle after entry if not yet in ratchet_stops.
    stop = fill_price ± ATR × 2.0
  - Updated (ratcheted) when profit ≥ ATR × 1.5:
    new_stop = best_price − ATR × 2.0  (long)
    new_stop = best_price + ATR × 2.0  (short)
  - Stop only moves in the trade's favour (ratchet — never widens).

Returns
-------
list[dict] — each dict: {symbol, exit_reason, trade_id, side}
The pipeline closes these positions and records them to the trade journal.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any

from loguru import logger

from execution.algo_scanner import (
    _ema, _adx, _atr,
    EMA_FAST, EMA_SLOW, ADX_PERIOD, ATR_PERIOD,
    ADX_EXIT_MIN, ATR_MULTIPLIER, TRAIL_TRIGGER,
)
from execution.ratchet_stop import get_stop, save_stop


MIN_HOLD_HOURS = 4.0
MAX_HOLD_DAYS  = 15      # ≈ 21 calendar days


# ── Helpers ───────────────────────────────────────────────────────────────────

def _approximate_hours_held(entry_date: Any) -> float:
    """Convert entry_date (date or date-str) → approximate hours held."""
    if entry_date is None:
        return 9999.0
    try:
        if isinstance(entry_date, str):
            entry_date = date.fromisoformat(entry_date[:10])
        if hasattr(entry_date, "date"):
            entry_date = entry_date.date()
        return max(0.0, (date.today() - entry_date).days * 24.0)
    except Exception:
        return 9999.0


def _approximate_trading_days(entry_date: Any) -> int:
    """Approximate trading days held (calendar_days × 5/7)."""
    if entry_date is None:
        return 0
    try:
        if isinstance(entry_date, str):
            entry_date = date.fromisoformat(entry_date[:10])
        if hasattr(entry_date, "date"):
            entry_date = entry_date.date()
        cal_days = max(0, (date.today() - entry_date).days)
        return int(cal_days * 5 / 7)
    except Exception:
        return 0


def _get_open_trade_info() -> dict[str, dict]:
    """
    Return {ticker: {trade_id, date}} for all currently active trades.
    Uses asset_class to skip crypto afterhours positions (BTCUSD etc. don't
    appear in the trades table, but guard is here for safety).
    """
    result: dict[str, dict] = {}
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return result
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT trade_id, ticker, date FROM trades "
                    "WHERE status = 'Active' ORDER BY date DESC"
                )
                for row in cur.fetchall():
                    ticker = row[1]
                    if ticker not in result:          # keep most-recent entry only
                        result[ticker] = {"trade_id": row[0], "date": row[2]}
    except Exception as exc:
        logger.debug(f"ExitManager | DB lookup failed (non-fatal): {exc}")
    return result


# ── Position-level exit check ─────────────────────────────────────────────────

def _check_position(
    symbol: str,
    pos: dict,
    db_trades: dict[str, dict],
    by_ticker: dict,
    exits: list[dict],
    dry_run: bool,
) -> None:
    """Check one open position; append to exits if an exit condition fires."""

    trade_info = db_trades.get(symbol, {})
    trade_id   = trade_info.get("trade_id")
    entry_date = trade_info.get("date")

    hours_old = _approximate_hours_held(entry_date)
    td_held   = _approximate_trading_days(entry_date)

    # Side from Alpaca (qty < 0 → short, qty ≥ 0 → long)
    qty  = float(pos.get("qty", 0) or 0)
    side = "short" if qty < 0 else "long"

    current_price = float(pos.get("current_price") or pos.get("avg_entry_price") or 0)
    fill_price    = float(pos.get("avg_entry_price") or current_price)

    if current_price <= 0:
        return

    # Market data for this ticker
    d = by_ticker.get(symbol)
    if d is None or "error" in d:
        logger.debug(f"ExitManager | {symbol}: not in momentum cache — skipping exit check")
        return

    closes = d.get("closes") or []
    bars   = d.get("bars")   or []
    highs  = [float(b["h"]) for b in bars] if bars else []
    lows   = [float(b["l"]) for b in bars] if bars else []

    if len(closes) < EMA_SLOW + 5:
        logger.debug(f"ExitManager | {symbol}: insufficient bars for EMA50 — skip")
        return

    ema20 = _ema(closes, EMA_FAST) or 0.0
    ema50 = _ema(closes, EMA_SLOW) or 0.0
    adx   = _adx(highs, lows, closes, ADX_PERIOD) if highs else 0.0
    atr   = _atr(highs, lows, closes, ATR_PERIOD)  if highs else 0.0

    # ── 1. Trailing stop management ──────────────────────────────────────────
    ratchet = get_stop(symbol)

    if ratchet is None and atr > 0:
        # First cycle after entry — initialise ratchet stop
        if side == "long":
            init_stop = fill_price - atr * ATR_MULTIPLIER
        else:
            init_stop = fill_price + atr * ATR_MULTIPLIER
        if not dry_run:
            save_stop(symbol, init_stop, fill_price, atr, ATR_MULTIPLIER, side)

            # ── Broker GTC stop placement ────────────────────────────────────
            # floor(live qty): GTC stop orders require whole shares on Alpaca paper.
            # Sub-1-share remainder (if any) stays software-only.
            _stop_qty = math.floor(abs(qty))
            if _stop_qty < 1:
                logger.error(
                    f"ExitManager | {symbol}: sub-1-share position after floor "
                    f"({abs(qty):.6f} shares) — DB stop kept, no broker GTC stop"
                )
                try:
                    from core.degradation_tracker import record_degradation
                    record_degradation(
                        component="oracle_stop",
                        severity="high",
                        error_type="sub_1_share_no_broker_stop",
                        message=f"{symbol}: sub-1-share ({abs(qty):.6f} shares) — broker GTC stop not placed",
                    )
                except Exception:
                    pass
            else:
                # ── Pre-submission guard (STEP 2) ─────────────────────────────────
                # Validate init_stop vs live Alpaca price before submitting.
                # Same Jun-9 guard as ratchet_stop.initialise_ratchet_stop().
                _live_price: "float | None" = None
                try:
                    from execution.broker import get_latest_price
                    _live_price = get_latest_price(symbol)
                except Exception as _pp_exc:
                    logger.warning(
                        f"ExitManager | {symbol}: live-price fetch failed: {_pp_exc}"
                    )

                if _live_price is None:
                    # Cannot validate — defer to per-cycle sweep rather than submit blind
                    logger.error(
                        f"ExitManager | {symbol}: Alpaca price unavailable — "
                        f"cannot validate stop ${init_stop:.2f}. "
                        f"Position UNPROTECTED; sweep will retry next cycle."
                    )
                    try:
                        from core.degradation_tracker import record_degradation
                        record_degradation(
                            component="oracle_stop",
                            severity="high",
                            error_type="stop_placement_no_price",
                            message=f"{symbol}: no live price — stop deferred, position unprotected",
                        )
                    except Exception:
                        pass
                else:
                    if init_stop >= _live_price:
                        # Stop at/above current price — Alpaca will reject it.
                        # Reanchor to live price using same ATR distance (or 2% fallback).
                        _init_reanchored = (
                            _live_price - atr * ATR_MULTIPLIER
                            if atr > 0
                            else _live_price * 0.98
                        )
                        _init_reanchored = max(_init_reanchored, 0.01)
                        logger.warning(
                            f"ExitManager | {symbol}: init_stop ${init_stop:.2f} ≥ "
                            f"current ${_live_price:.2f} — reanchored to ${_init_reanchored:.2f} "
                            f"[Jun-9 rejection guard]"
                        )
                        init_stop = _init_reanchored
                        if not dry_run:
                            save_stop(symbol, init_stop, fill_price, atr, ATR_MULTIPLIER, side)

                    try:
                        from execution.broker import place_stop_order
                        _stop_result  = place_stop_order(symbol, _stop_qty, init_stop)
                        _order_id     = _stop_result.get("id")
                        save_stop(
                            symbol, init_stop, fill_price, atr, ATR_MULTIPLIER,
                            side, stop_order_id=_order_id,
                        )
                        logger.info(
                            f"ExitManager | {symbol}: GTC stop placed "
                            f"qty={_stop_qty} stop=${init_stop:.4f} order_id={_order_id}"
                        )
                    except Exception as _stop_exc:
                        logger.error(
                            f"ExitManager | {symbol}: GTC stop FAILED "
                            f"(qty={_stop_qty} stop=${init_stop:.4f}): {_stop_exc} "
                            f"— position UNPROTECTED, sweep will retry next cycle"
                        )
                        try:
                            from core.degradation_tracker import record_degradation
                            record_degradation(
                                component="oracle_stop",
                                severity="high",
                                error_type="stop_placement_failed",
                                message=f"{symbol}: GTC stop FAILED — position UNPROTECTED, retry next cycle",
                                detail=str(_stop_exc)[:500],
                            )
                        except Exception:
                            pass

        logger.info(
            f"ExitManager | {symbol} ({side}): ratchet stop initialised "
            f"@ ${init_stop:.3f} (fill=${fill_price:.3f} ATR={atr:.3f})"
        )
        ratchet = {
            "stop_price":     init_stop,
            "fill_price":     fill_price,
            "atr":            atr,
            "atr_multiplier": ATR_MULTIPLIER,
            "side":           side,
        }

    elif ratchet and atr > 0:
        # Update trailing stop if profit ≥ 1.5 × ATR
        profit_dist  = (current_price - fill_price) if side == "long" else (fill_price - current_price)
        trail_active = profit_dist >= atr * TRAIL_TRIGGER
        existing_stop = ratchet["stop_price"]

        if trail_active:
            if side == "long":
                candidate = current_price - atr * ATR_MULTIPLIER
                if candidate > existing_stop:
                    if not dry_run:
                        save_stop(symbol, candidate, fill_price, atr, ATR_MULTIPLIER, side)
                    logger.info(
                        f"ExitManager | {symbol} (long): trail ratcheted "
                        f"${existing_stop:.3f} → ${candidate:.3f}"
                    )
                    ratchet["stop_price"] = candidate
            else:
                candidate = current_price + atr * ATR_MULTIPLIER
                if candidate < existing_stop:
                    if not dry_run:
                        save_stop(symbol, candidate, fill_price, atr, ATR_MULTIPLIER, side)
                    logger.info(
                        f"ExitManager | {symbol} (short): trail ratcheted "
                        f"${existing_stop:.3f} → ${candidate:.3f}"
                    )
                    ratchet["stop_price"] = candidate

    # ── Check trailing stop hit ───────────────────────────────────────────────
    if ratchet:
        stop_price = ratchet["stop_price"]
        stop_hit   = (
            (side == "long"  and current_price <= stop_price) or
            (side == "short" and current_price >= stop_price)
        )
        if stop_hit:
            logger.warning(
                f"ExitManager | {symbol} ({side}): TRAILING STOP HIT "
                f"price=${current_price:.3f} stop=${stop_price:.3f}"
            )
            exits.append({
                "symbol":      symbol,
                "exit_reason": "trailing_stop",
                "trade_id":    trade_id,
                "side":        side,
                "price":       current_price,
                "stop_price":  stop_price,
                "hours_held":  hours_old,
            })
            return  # stop has priority — do not check other conditions

    # ── Min-hold guard (4 hours) ──────────────────────────────────────────────
    # Within first 4 hours, only trailing stop fires (handled above).
    if hours_old < MIN_HOLD_HOURS:
        logger.debug(
            f"ExitManager | {symbol}: min-hold gate "
            f"({hours_old:.1f}h < {MIN_HOLD_HOURS:.0f}h) — signal exits suppressed"
        )
        return

    # Unrealised P&L for profit-buffer gates below.
    unrealized_pnl = float(pos.get("unrealized_pl", 0) or 0)

    # ── 2. EMA crossover reversal ─────────────────────────────────────────────
    # EMA reversal — only exit if position is in profit.
    # An EMA crossover on a losing position is noise at this timeframe.
    # Let the hard stop handle losers — don't stack two exit signals on a down move.
    ema_reversed = (
        (side == "long"  and ema20 < ema50) or
        (side == "short" and ema20 > ema50)
    )
    if ema_reversed and unrealized_pnl > 0:
        logger.warning(
            f"ExitManager | {symbol} ({side}): EMA REVERSAL — "
            f"EMA20={ema20:.3f} EMA50={ema50:.3f} unrealized_pnl=${unrealized_pnl:.2f}"
        )
        exits.append({
            "symbol":      symbol,
            "exit_reason": "ema_reversal",
            "trade_id":    trade_id,
            "side":        side,
            "hours_held":  hours_old,
        })
        return

    # ── 3. ADX weakness ───────────────────────────────────────────────────────
    # ADX weakness — only exit if position is in profit.
    # An ADX fade on a losing position is noise — let the stop manage the loss.
    if adx > 0 and adx < ADX_EXIT_MIN and unrealized_pnl > 0:
        logger.warning(
            f"ExitManager | {symbol} ({side}): ADX WEAK — "
            f"ADX={adx:.1f} < {ADX_EXIT_MIN} unrealized_pnl=${unrealized_pnl:.2f}"
        )
        exits.append({
            "symbol":      symbol,
            "exit_reason": f"adx_weak ({adx:.1f})",
            "trade_id":    trade_id,
            "side":        side,
            "hours_held":  hours_old,
        })
        return

    # ── 4. Time limit ─────────────────────────────────────────────────────────
    if td_held >= MAX_HOLD_DAYS:
        logger.warning(
            f"ExitManager | {symbol} ({side}): TIME LIMIT — "
            f"{td_held} trading days ≥ {MAX_HOLD_DAYS}"
        )
        exits.append({
            "symbol":      symbol,
            "exit_reason": f"max_hold_{td_held}d",
            "trade_id":    trade_id,
            "side":        side,
            "hours_held":  hours_old,
        })
        return

    _stop_str = f"{ratchet['stop_price']:.3f}" if ratchet else "N/A"
    logger.debug(
        f"ExitManager | {symbol} ({side}): HOLD — "
        f"EMA20={ema20:.2f} EMA50={ema50:.2f} ADX={adx:.1f} "
        f"held≈{td_held}d stop=${_stop_str}"
    )


# ── Main entry point ──────────────────────────────────────────────────────────

def run_oracle_exit_checks(
    momentum_data: dict | None,
    dry_run: bool = False,
) -> list[dict]:
    """
    Evaluate all open Oracle stock positions for exit conditions.

    Parameters
    ----------
    momentum_data : dict from get_cached_momentum_data() (must contain 'by_ticker')
    dry_run       : if True, logs intent but does not write ratchet_stops

    Returns
    -------
    list[dict]   — positions to close: each has {symbol, exit_reason, trade_id, side}
                   The pipeline is responsible for calling close_position() and
                   close_trade() for each returned item.
    """
    exits: list[dict] = []

    if not momentum_data or not momentum_data.get("by_ticker"):
        logger.debug("ExitManager | No momentum data — skipping exit checks this cycle")
        return exits

    by_ticker = momentum_data["by_ticker"]

    # Get current Alpaca positions (stocks only — skip afterhours crypto)
    _CRYPTO_SYMS = frozenset({"BTCUSD", "ETHUSD", "SOLUSD", "AVAXUSD"})
    try:
        from execution.broker import get_positions
        all_positions = get_positions()
    except Exception as exc:
        logger.error(f"ExitManager | Cannot fetch positions: {exc}")
        return exits

    oracle_open = {
        p["symbol"]: p
        for p in all_positions
        if p.get("symbol") not in _CRYPTO_SYMS
    }

    if not oracle_open:
        logger.debug("ExitManager | No open Oracle stock positions to check")
        return exits

    # Fetch entry dates from trades DB
    db_trades = _get_open_trade_info()

    logger.info(
        f"ExitManager | Checking {len(oracle_open)} open position(s): "
        f"{list(oracle_open.keys())}"
    )

    for symbol, pos in oracle_open.items():
        try:
            _check_position(symbol, pos, db_trades, by_ticker, exits, dry_run)
        except Exception as exc:
            logger.warning(f"ExitManager | Error checking {symbol}: {exc}")

    if exits:
        logger.warning(
            f"ExitManager | {len(exits)} exit(s) queued: "
            f"{[(e['symbol'], e['exit_reason']) for e in exits]}"
        )
    else:
        logger.info("ExitManager | All positions within hold conditions — no exits")

    return exits


def execute_exits(exits: list[dict], dry_run: bool = False) -> dict:
    """
    Close positions returned by run_oracle_exit_checks().

    For each exit:
      1. Close the Alpaca position at market
      2. Delete the ratchet_stop entry
      3. Call close_trade() to record in the trade journal
      4. Run post-mortem on the trade (profit reserve sweep)

    Returns summary dict with closed/errors lists.
    """
    result: dict = {"closed": [], "errors": []}

    if not exits:
        return result

    from execution.broker import close_position, get_positions
    from execution.ratchet_stop import delete_stop
    from analysis.trade_journal import close_trade

    # Fetch current positions once for P&L lookup
    try:
        all_positions = {p["symbol"]: p for p in get_positions()}
    except Exception:
        all_positions = {}

    for exit_info in exits:
        symbol      = exit_info["symbol"]
        exit_reason = exit_info.get("exit_reason", "oracle_exit_manager")
        trade_id    = exit_info.get("trade_id")

        if dry_run:
            logger.info(f"ExitManager [DRY-RUN] | Would close {symbol} ({exit_reason})")
            result["closed"].append({"symbol": symbol, "exit_reason": exit_reason, "dry_run": True})
            continue

        try:
            close_position(symbol)
            logger.info(f"ExitManager | Closed {symbol} ({exit_reason})")
        except Exception as exc:
            logger.error(f"ExitManager | Failed to close {symbol}: {exc}")
            result["errors"].append({"symbol": symbol, "error": str(exc)})
            # C-6 fix: capital-risk failure — alert directly (not routed through
            # degradation tracker) so the alert fires even if tracker is down.
            try:
                from notifications.discord import alert_critical
                alert_critical(
                    title=f"🔴 Oracle Exit FAILED | {symbol}",
                    description=(
                        f"**{symbol}** ({exit_reason}): `close_position()` raised an exception.\n"
                        f"Position remains **open at Alpaca** with no stop reattached.\n"
                        f"Next cycle will retry the exit automatically.\n"
                        f"```{str(exc)[:300]}```"
                    ),
                )
            except Exception as _da:
                logger.error(f"ExitManager | Discord alert failed for {symbol}: {_da}")
            try:
                from core.degradation_tracker import record_degradation
                record_degradation(
                    component="oracle_exit",
                    severity="critical",
                    error_type="close_position_failed",
                    message=(
                        f"{symbol} ({exit_reason}): close_position() raised — "
                        f"position open at broker, retry next cycle"
                    ),
                    detail=str(exc)[:500],
                )
            except Exception as _deg_e:
                logger.error(f"ExitManager | record_degradation failed for {symbol}: {_deg_e}")
            continue

        # Clean up ratchet stop
        try:
            delete_stop(symbol)
        except Exception:
            pass

        # Record to trade journal
        # ── Fallback: recover trade_id if it was missing (rapid re-entry race) ──
        if not trade_id:
            try:
                from analysis.trade_journal import find_active_trade_by_ticker
                fallback_trade_id = find_active_trade_by_ticker(symbol)
                if fallback_trade_id:
                    trade_id = fallback_trade_id
                    logger.warning(
                        f"ExitManager | trade_id was None for {symbol} — "
                        f"recovered via ticker lookup: {trade_id}"
                    )
                else:
                    logger.critical(
                        f"ExitManager | PHANTOM-OPEN RISK: {symbol} sell fired in Alpaca "
                        f"but no trade_id found and no Active row to fallback to. "
                        f"DB will diverge from broker. Manual reconciliation required."
                    )
            except Exception as exc:
                logger.critical(
                    f"ExitManager | trade_id fallback failed for {symbol}: {exc}"
                )

        if trade_id:
            try:
                pos     = all_positions.get(symbol, {})
                raw_pnl = float(pos.get("unrealized_pl", 0) or 0)
                cost    = float(pos.get("cost_basis",    0) or 0)
                if cost:
                    pnl_pct = raw_pnl / abs(cost) * 100
                elif raw_pnl > 0:
                    pnl_pct = 1.0    # cost_basis unavailable — use sign of raw P&L, small positive sentinel
                elif raw_pnl < 0:
                    pnl_pct = -1.0   # cost_basis unavailable — use sign of raw P&L, small negative sentinel
                else:
                    pnl_pct = 0.0    # flat exit
                close_trade(
                    trade_id=trade_id,
                    pnl_percentage=round(pnl_pct, 4),
                    realized_pnl=round(raw_pnl, 2),
                    exit_reason=exit_reason,
                    time_in_trade_hours=float(exit_info.get("hours_held") or 0) or None,
                    close_price=float(pos.get("current_price") or 0) or None,
                    bot_id="oracle",
                )
                # Profit reserve sweep (15% of winning trades)
                if raw_pnl > 0:
                    try:
                        from db.postgres import add_oracle_profit_contribution
                        add_oracle_profit_contribution(round(raw_pnl * 0.15, 2))
                    except Exception:
                        pass
            except Exception as exc:
                logger.critical(
                    f"ExitManager | Journal close_trade FAILED for {symbol} "
                    f"trade_id={trade_id}: {exc} — Alpaca sold but DB still Active"
                )
                # B-4 fix: direct Discord alert + tag row so re-entry dedup sees it
                # and audit trail shows why status stayed Active.
                try:
                    from notifications.discord import notify_capital_risk
                    notify_capital_risk(
                        f"🔴 {symbol}: Alpaca SOLD but journal write FAILED "
                        f"(trade_id={trade_id}) — DB still Active, manual check needed",
                        symbol=symbol,
                    )
                except Exception:
                    pass
                if trade_id:
                    try:
                        from db.postgres import _acquire_healthy_conn
                        _conn = _acquire_healthy_conn()
                        with _conn.cursor() as _cur:
                            _cur.execute(
                                "UPDATE trades SET exit_reason='journal_write_failed' WHERE trade_id=%s",
                                (trade_id,)
                            )
                        _conn.commit()
                        _conn.close()
                    except Exception as _ue:
                        logger.error(
                            f"ExitManager | Could not tag trade_id={trade_id} exit_reason: {_ue}"
                        )

        result["closed"].append({
            "symbol":      symbol,
            "exit_reason": exit_reason,
            "trade_id":    trade_id,
        })

    logger.info(
        f"ExitManager | execute_exits complete: "
        f"closed={len(result['closed'])} errors={len(result['errors'])}"
    )
    return result
