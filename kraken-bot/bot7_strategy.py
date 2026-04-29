"""
bot7_strategy.py — Main strategy loop for Bot #7 (Macro Bond Trader).

Called from kraken-bot/main.py when BOT_ID=bot7_macro_bond and
strategy_type=llm_bonds.

Cycle pattern (identical to jerome_strategy.py):
  - Groq analysis fires at CYCLE_HOURS_UTC [13, 22] — 9AM ET + 6PM ET
  - Stop/TP/time-stop checks run every cycle (15-min polling)
  - Min hold: 14 days. Max hold: 60 days.
  - Positions written to alpaca_etf_positions (bot_id='bot7_macro_bond')
  - Decisions written to macro_bond_decisions for audit

BOT_ID:  bot7_macro_bond
DB row:  kraken_heartbeat id=7  (was FOMO Fred / Poseidon — replaces it)

ACTIVATION (Week 4):
  Before flipping BOT_PAUSED=False in config.py, run:
    UPDATE kraken_heartbeat
    SET bot_id = 'bot7_macro_bond', bot_display_name = 'Macro Bond Trader'
    WHERE id = 7;
  Then set BOT_PAUSED = False in BOT_PROFILES['bot7_macro_bond'].
"""
from __future__ import annotations
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("bot7.strategy")

_last_groq_cycle: Optional[datetime] = None

# ── Cycle timing (mirror Jerome's pattern) ────────────────────────────────────

def should_run_groq_cycle(cycle_hours: list[int]) -> bool:
    """Fire Groq at configured UTC hours within the first 15 minutes of that hour."""
    global _last_groq_cycle
    now = datetime.now(timezone.utc)
    if now.hour not in cycle_hours or now.minute >= 15:
        return False
    if _last_groq_cycle and (now - _last_groq_cycle).total_seconds() < 3600:
        return False
    _last_groq_cycle = now
    return True


# ── Main cycle ────────────────────────────────────────────────────────────────

def run_bot7_cycle(profile: dict, db_id: int) -> None:
    """
    Main Bot7 cycle. Called every LOOP_SLEEP_SECONDS from main.py.
    Checks exits every cycle. Fires Groq entries at configured UTC hours only.
    """
    # Pause guard — always first
    if profile.get("BOT_PAUSED", True):
        logger.info("Bot7 | BOT_PAUSED=True — skipping cycle (not yet activated)")
        return

    from bot7_alpaca import Bot7Alpaca
    from bot7_market_context import get_bond_context
    from bot7_investor import get_bond_decisions

    try:
        alpaca = Bot7Alpaca(
            api_key=profile.get("ALPACA_API_KEY", ""),
            secret_key=profile.get("ALPACA_SECRET_KEY", ""),
            base_url=profile.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
        )
    except Exception as exc:
        logger.error(f"Bot7 | Alpaca connection failed: {exc}")
        return

    account = alpaca.get_account()
    equity  = account["equity"]
    logger.info(
        f"Bot7 | Equity=${equity:,.2f} "
        f"cash=${account['cash']:,.2f} "
        f"buying_power=${account['buying_power']:,.2f}"
    )

    open_positions = alpaca.get_open_positions()
    logger.info(f"Bot7 | Open positions: {len(open_positions)}")

    # Exit checks run every cycle
    _check_exit_conditions(alpaca, open_positions, profile, db_id)

    # Market hours check
    if not alpaca.is_market_open():
        logger.debug("Bot7 | Market closed — skipping entry check")
        _update_heartbeat(db_id, equity, len(open_positions))
        return

    # Groq fires at configured UTC hours only
    cycle_hours = profile.get("CYCLE_HOURS_UTC", [13, 22])
    if should_run_groq_cycle(cycle_hours):
        logger.info(
            f"Bot7 | === GROQ MACRO BOND CYCLE at "
            f"{datetime.now(timezone.utc).strftime('%H:%M UTC')} ==="
        )

        universe = profile.get("BOND_UNIVERSE", [
            "TLT", "IEF", "SHY", "TIP", "HYG", "LQD", "EMB"
        ])
        context = get_bond_context(open_positions, universe)

        decisions = get_bond_decisions(
            context=context,
            equity=equity,
            open_positions=open_positions,
            config=profile,
        )

        # Process close recommendations
        for close_rec in decisions.get("close", []):
            sym    = close_rec.get("symbol", "")
            reason = close_rec.get("reason", "groq_close")
            if any(p["symbol"] == sym for p in open_positions):
                logger.info(f"Bot7 | Groq recommends closing {sym}: {reason}")
                alpaca.close_position(sym)
                _record_trade_close(sym, reason, db_id)

        open_positions = alpaca.get_open_positions()
        max_pos = profile.get("MAX_POSITIONS", 3)

        # Process entry recommendations
        held_symbols = {p["symbol"] for p in open_positions}
        for entry in decisions.get("enter", []):
            if len(open_positions) >= max_pos:
                logger.info("Bot7 | Max positions reached — skipping remaining entries")
                break

            sym       = entry["symbol"]
            side      = entry["direction"]
            size_pct  = entry.get("position_size_pct", 0.15)
            notional  = equity * size_pct

            if sym in held_symbols:
                logger.info(f"Bot7 | Already holding {sym} — skipping")
                continue

            order = alpaca.place_order(sym, side, notional)
            if order:
                _record_trade_open(
                    symbol=sym,
                    side=side,
                    notional=notional,
                    entry=entry,
                    db_id=db_id,
                )
                open_positions = alpaca.get_open_positions()
                held_symbols   = {p["symbol"] for p in open_positions}

    _update_heartbeat(db_id, equity, len(open_positions))


# ── Exit conditions ───────────────────────────────────────────────────────────

def _check_exit_conditions(
    alpaca: "Bot7Alpaca",
    positions: list[dict],
    profile: dict,
    db_id: int,
) -> None:
    """
    Check stop loss, take profit, and time stop on every cycle.
    Also enforces max_hold_days from DB if available.
    """
    from bot7_investor import MIN_HOLD_DAYS, MAX_HOLD_DAYS

    sl_pct   = profile.get("STOP_LOSS_PCT", 0.04)
    tp_pct   = profile.get("TAKE_PROFIT_PCT", 0.08)
    max_days = profile.get("MAX_HOLD_DAYS", MAX_HOLD_DAYS)

    for pos in positions:
        sym  = pos["symbol"]
        pct  = pos["unrealised_pct"]
        days = _get_days_held(sym)

        reason = None
        if pct <= -(sl_pct * 100):
            reason = f"hard_stop ({pct:.2f}%)"
        elif pct >= (tp_pct * 100):
            reason = f"take_profit ({pct:.2f}%)"
        elif days is not None and days >= max_days:
            reason = f"time_stop ({days:.0f}d)"

        if reason:
            logger.info(f"Bot7 | EXIT {sym}: {reason}")
            alpaca.close_position(sym)
            _record_trade_close(sym, reason, db_id)


def _get_days_held(symbol: str) -> Optional[float]:
    """Get days held for a symbol from alpaca_etf_positions table."""
    try:
        _add_tp_path()
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return None
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXTRACT(EPOCH FROM (NOW() - opened_at)) / 86400
                    FROM alpaca_etf_positions
                    WHERE bot_id = 'bot7_macro_bond' AND symbol = %s
                    AND status = 'open'
                    ORDER BY opened_at DESC LIMIT 1
                """, (symbol,))
                row = cur.fetchone()
                return float(row[0]) if row else None
    except Exception:
        return None


# ── DB writes ─────────────────────────────────────────────────────────────────

def _record_trade_open(
    symbol: str, side: str, notional: float,
    entry: dict, db_id: int,
) -> None:
    """Record new position in alpaca_etf_positions table."""
    try:
        _add_tp_path()
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return

        min_hold = int(entry.get("max_hold_days", 14))
        from datetime import timedelta
        min_hold_until = datetime.now(timezone.utc) + timedelta(days=14)

        # Approximate entry price (Alpaca fills async — we use last known price)
        entry_price = entry.get("entry_price_est", 0)
        qty_approx  = notional / entry_price if entry_price > 0 else 0

        sl_pct = entry.get("stop_loss_pct", 0.04)
        tp_pct = entry.get("take_profit_pct", 0.08)
        stop   = entry_price * (1 - sl_pct) if entry_price > 0 else 0
        tp1    = entry_price * (1 + tp_pct * 0.5) if entry_price > 0 else 0
        tp2    = entry_price * (1 + tp_pct) if entry_price > 0 else 0

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO alpaca_etf_positions
                        (bot_id, symbol, direction, qty,
                         entry_price, notional_usd,
                         stop_price, tp1_price, tp2_price,
                         min_hold_until, status, opened_at)
                    VALUES ('bot7_macro_bond',%s,%s,%s,%s,%s,%s,%s,%s,%s,'open',NOW())
                """, (
                    symbol, side, qty_approx,
                    entry_price, notional,
                    stop or None, tp1 or None, tp2 or None,
                    min_hold_until,
                ))
            conn.commit()
        logger.info(f"Bot7 | DB: recorded open {symbol}")
    except Exception as exc:
        logger.debug(f"Bot7 | DB open record failed (non-fatal): {exc}")


def _record_trade_close(symbol: str, reason: str, db_id: int) -> None:
    """Mark position as closed in alpaca_etf_positions table."""
    try:
        _add_tp_path()
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE alpaca_etf_positions
                    SET status = 'closed', closed_at = NOW(), exit_reason = %s
                    WHERE bot_id = 'bot7_macro_bond' AND symbol = %s AND status = 'open'
                """, (reason, symbol))
            conn.commit()
    except Exception as exc:
        logger.debug(f"Bot7 | DB close record failed (non-fatal): {exc}")


def _update_heartbeat(db_id: int, equity: float, position_count: int) -> None:
    """Update kraken_heartbeat for Bot7."""
    try:
        _add_tp_path()
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE kraken_heartbeat
                    SET equity_usd      = %s,
                        position_count  = %s,
                        status          = 'running',
                        last_updated    = NOW()
                    WHERE id = %s
                """, (equity, position_count, db_id))
            conn.commit()
    except Exception as exc:
        logger.debug(f"Bot7 | Heartbeat update failed (non-fatal): {exc}")


def _add_tp_path() -> None:
    tp = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trading-platform")
    )
    if tp not in sys.path:
        sys.path.insert(0, tp)
