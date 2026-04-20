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

    # ── 2. EMA crossover reversal ─────────────────────────────────────────────
    ema_reversed = (
        (side == "long"  and ema20 < ema50) or
        (side == "short" and ema20 > ema50)
    )
    if ema_reversed:
        logger.warning(
            f"ExitManager | {symbol} ({side}): EMA REVERSAL — "
            f"EMA20={ema20:.3f} EMA50={ema50:.3f}"
        )
        exits.append({
            "symbol":      symbol,
            "exit_reason": "ema_reversal",
            "trade_id":    trade_id,
            "side":        side,
        })
        return

    # ── 3. ADX weakness ───────────────────────────────────────────────────────
    if adx > 0 and adx < ADX_EXIT_MIN:
        logger.warning(
            f"ExitManager | {symbol} ({side}): ADX WEAK — "
            f"ADX={adx:.1f} < {ADX_EXIT_MIN}"
        )
        exits.append({
            "symbol":      symbol,
            "exit_reason": f"adx_weak ({adx:.1f})",
            "trade_id":    trade_id,
            "side":        side,
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
        })
        return

    logger.debug(
        f"ExitManager | {symbol} ({side}): HOLD — "
        f"EMA20={ema20:.2f} EMA50={ema50:.2f} ADX={adx:.1f} "
        f"held≈{td_held}d stop=${ratchet['stop_price']:.3f if ratchet else 'N/A'}"
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
            continue

        # Clean up ratchet stop
        try:
            delete_stop(symbol)
        except Exception:
            pass

        # Record to trade journal
        if trade_id:
            try:
                pos     = all_positions.get(symbol, {})
                raw_pnl = float(pos.get("unrealized_pl", 0) or 0)
                cost    = float(pos.get("cost_basis",    0) or 0)
                pnl_pct = (raw_pnl / abs(cost) * 100) if cost else 0.0
                close_trade(
                    trade_id=trade_id,
                    pnl_percentage=round(pnl_pct, 4),
                    realized_pnl=round(raw_pnl, 2),
                    exit_reason=exit_reason,
                )
                # Profit reserve sweep (15% of winning trades)
                if raw_pnl > 0:
                    try:
                        from db.postgres import add_oracle_profit_contribution
                        add_oracle_profit_contribution(round(raw_pnl * 0.15, 2))
                    except Exception:
                        pass
            except Exception as exc:
                logger.warning(f"ExitManager | Journal write failed for {symbol}: {exc}")

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
