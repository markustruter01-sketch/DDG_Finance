"""
jerome_strategy.py — Main strategy loop for Jerome commodity bot.
Called from kraken-bot/runner.py when bot_id=blackbeard and
strategy_type=llm_commodity.

Cycle runs every LOOP_SLEEP_SECONDS (15 min default).
Groq analysis fires only at configured UTC hours (9AM + 9PM by default).
Stop/TP/time-stop checks run every cycle.
"""
from __future__ import annotations
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("jerome.strategy")

_last_groq_cycle: Optional[datetime] = None


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


def run_jerome_cycle(profile: dict, db_id: int) -> None:
    """
    Main Jerome cycle. Called every LOOP_SLEEP_SECONDS from main.py.
    Checks exits every cycle, fires Groq entries at configured hours only.
    """
    from jerome_alpaca import JeromeAlpaca
    from jerome_market_context import get_commodity_context
    from jerome_investor import get_commodity_decisions

    try:
        alpaca = JeromeAlpaca(
            api_key=profile.get("ALPACA_API_KEY", ""),
            secret_key=profile.get("ALPACA_SECRET_KEY", ""),
            base_url=profile.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
        )
    except Exception as exc:
        logger.error(f"Jerome | Alpaca connection failed: {exc}")
        return

    account = alpaca.get_account()
    equity  = account["equity"]
    logger.info(
        f"Jerome | Equity=${equity:,.2f} "
        f"cash=${account['cash']:,.2f} "
        f"buying_power=${account['buying_power']:,.2f}"
    )

    open_positions = alpaca.get_open_positions()
    logger.info(f"Jerome | Open positions: {len(open_positions)}")

    _check_exit_conditions(alpaca, open_positions, profile)

    # NOTE: No is_market_open() gate. Alpaca queues market orders for next open.
    # SPY/QQQ Trend uses the same pattern. Removing this gate was the fix for
    # Jerome being unable to trade — GROQ_CYCLE_HOURS [9,21] UTC fall outside
    # NYSE hours, making the compound gate mathematically impossible to pass.

    cycle_hours = profile.get("GROQ_CYCLE_HOURS", [9, 21])
    if should_run_groq_cycle(cycle_hours):
        logger.info(
            f"Jerome | === GROQ INVESTMENT CYCLE at "
            f"{datetime.now(timezone.utc).strftime('%H:%M UTC')} ==="
        )

        universe = profile.get("COMMODITY_UNIVERSE", [])
        context  = get_commodity_context(open_positions, universe)

        decisions = get_commodity_decisions(
            context=context,
            equity=equity,
            open_positions=open_positions,
            config=profile,
        )

        for close_rec in decisions.get("close", []):
            sym    = close_rec.get("symbol", "")
            reason = close_rec.get("reason", "groq_close")
            if any(p["symbol"] == sym for p in open_positions):
                logger.info(f"Jerome | Groq recommends closing {sym}: {reason}")
                alpaca.close_position(sym)
                _record_trade_close(sym, reason, db_id)

        open_positions = alpaca.get_open_positions()
        max_pos = profile.get("MAX_POSITIONS", 3)

        for entry in decisions.get("enter", []):
            if len(open_positions) >= max_pos:
                logger.info("Jerome | Max positions reached — skipping remaining entries")
                break

            sym   = entry["symbol"]
            side  = entry["direction"]
            theme = entry["theme"]

            if any(p["symbol"] == sym for p in open_positions):
                logger.info(f"Jerome | Already holding {sym} — skipping")
                continue

            themes_map     = profile.get("COMMODITY_THEMES", {})
            holding_themes = _get_holding_themes(open_positions, themes_map)
            if theme in holding_themes:
                logger.info(f"Jerome | Already holding {theme} theme — skipping {sym}")
                continue

            size_pct = entry.get("position_size_pct", 0.10)
            notional = equity * size_pct

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

    _update_heartbeat(db_id, equity, len(open_positions))


def _check_exit_conditions(
    alpaca: "JeromeAlpaca",
    positions: list[dict],
    profile: dict,
) -> None:
    """Check stop loss, take profit, and time stop on every cycle."""
    sl_pct   = profile.get("STOP_LOSS_PCT", 0.04)
    tp_pct   = profile.get("TAKE_PROFIT_PCT", 0.08)
    max_days = profile.get("MAX_HOLD_DAYS", 21)

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
            logger.info(f"Jerome | EXIT {sym}: {reason}")
            alpaca.close_position(sym)
            _record_trade_close(sym, reason, 2)


def _get_holding_themes(positions: list[dict], themes_map: dict) -> set:
    """Return set of commodity themes currently held."""
    symbol_theme = {s: theme for theme, syms in themes_map.items() for s in syms}
    return {symbol_theme.get(p["symbol"], "unknown") for p in positions}


def _get_days_held(symbol: str) -> Optional[float]:
    """Get days held for a symbol from DB."""
    try:
        _add_trading_platform_to_path()
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return None
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXTRACT(EPOCH FROM (NOW() - opened_at)) / 86400
                    FROM jerome_positions
                    WHERE symbol = %s AND status = 'open'
                    ORDER BY opened_at DESC LIMIT 1
                """, (symbol,))
                row = cur.fetchone()
                return float(row[0]) if row else None
    except Exception:
        return None


def _record_trade_open(
    symbol: str, side: str, notional: float,
    entry: dict, db_id: int,
) -> None:
    """Record new position in jerome_positions table."""
    try:
        _add_trading_platform_to_path()
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO jerome_positions
                        (symbol, direction, theme, notional_usd,
                         conviction, stop_loss_pct, take_profit_pct,
                         max_hold_days, thesis, status, opened_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'open',NOW())
                """, (
                    symbol,
                    side,
                    entry.get("theme", ""),
                    notional,
                    entry.get("conviction", 0),
                    entry.get("stop_loss_pct", 0.04),
                    entry.get("take_profit_pct", 0.08),
                    entry.get("max_hold_days", 7),
                    str(entry.get("thesis", ""))[:200],
                ))
            conn.commit()
        logger.info(f"Jerome | DB: recorded open position {symbol}")
    except Exception as exc:
        logger.debug(f"Jerome | DB open record failed (non-fatal): {exc}")


def _record_trade_close(symbol: str, reason: str, db_id: int) -> None:
    """Mark position as closed in jerome_positions table."""
    try:
        _add_trading_platform_to_path()
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE jerome_positions
                    SET status = 'closed', closed_at = NOW(), exit_reason = %s
                    WHERE symbol = %s AND status = 'open'
                """, (reason, symbol))
            conn.commit()
    except Exception as exc:
        logger.debug(f"Jerome | DB close record failed (non-fatal): {exc}")


def _update_heartbeat(db_id: int, equity: float, position_count: int) -> None:
    """Update kraken_heartbeat for Jerome."""
    try:
        _add_trading_platform_to_path()
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
        logger.debug(f"Jerome | Heartbeat update failed (non-fatal): {exc}")


def _add_trading_platform_to_path() -> None:
    tp = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trading-platform")
    )
    if tp not in sys.path:
        sys.path.insert(0, tp)
