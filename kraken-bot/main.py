"""
main.py  —  Davy Jones' Portfolio  |  24/7 Kraken Crypto Trading Bot
=====================================================================
Named after Davy Jones' Locker — the mythical ocean abyss where ships
(and poorly-managed capital) go to never return. We aim to avoid that fate.

Strategy: Mean Reversion filtered by RSI
Exchange : Kraken Pro (via ccxt)
Runtime  : Continuous while True loop — restarts automatically on errors

Architecture:
  config.py  → All tunable parameters and exchange connection
  logic.py   → All math: RSI, z-score, position sizing, circuit breaker, stops
  main.py    → This file: the execution loop that ties everything together

Required secrets (add in Replit → padlock icon → Secrets):
  KRAKEN_API_KEY    — Kraken Pro API key
  KRAKEN_SECRET_KEY — Kraken Pro secret key

Run with:  python3 kraken-bot/main.py
"""

from __future__ import annotations

import json
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Any

from loguru import logger

# Import our configuration (also validates API keys at import time)
from config import (
    exchange,
    SYMBOLS,
    RSI_PERIOD,
    RSI_OVERSOLD,
    RSI_OVERBOUGHT,
    ZSCORE_WINDOW,
    ZSCORE_ENTRY,
    ZSCORE_EXIT,
    OHLCV_TIMEFRAME,
    OHLCV_LIMIT,
    CASH_RESERVE,
    MAX_POSITION_FRACTION,
    MAX_POSITIONS,
    RISK_FRACTION,
    STOP_LOSS_PCT,
    TRAIL_PCT,
    EQUITY_REFRESH_INTERVAL,
    LOOP_SLEEP_SECONDS,
    RESTART_SLEEP_SECONDS,
    CB_PRICE_DROP_PCT,
    CB_WINDOW_MINUTES,
    CB_PAUSE_HOURS,
    STATUS_FILE,
)

# Import our trading logic functions
from logic import (
    calculate_rsi,
    calculate_zscore,
    get_position_size,
    check_circuit_breaker,
    check_stops,
)


# ══════════════════════════════════════════════════════════════════════════════
# STARTUP BANNER
# ══════════════════════════════════════════════════════════════════════════════

logger.info("=" * 65)
logger.info("  DAVY JONES' PORTFOLIO  —  Kraken Mean-Reversion Bot")
logger.info("=" * 65)
logger.info(f"  Symbols        : {', '.join(SYMBOLS)}")
logger.info(f"  Timeframe      : {OHLCV_TIMEFRAME}")
logger.info(f"  Cash reserve   : {CASH_RESERVE*100:.0f}% (always held back)")
logger.info(f"  Max positions  : {MAX_POSITIONS}")
logger.info(f"  Max per trade  : {MAX_POSITION_FRACTION*100:.0f}% of equity")
logger.info(f"  Risk per trade : {RISK_FRACTION*100:.0f}% of equity")
logger.info(f"  Stop loss      : {STOP_LOSS_PCT*100:.0f}%")
logger.info(f"  Trailing profit: {TRAIL_PCT*100:.0f}%")
logger.info(f"  Circuit breaker: >{CB_PRICE_DROP_PCT*100:.0f}% drop in {CB_WINDOW_MINUTES}min → {CB_PAUSE_HOURS}hr pause")
logger.info("=" * 65)


# ══════════════════════════════════════════════════════════════════════════════
# BOT STATE
# All of the bot's in-memory state lives here at module level. When the bot
# restarts after an error, this state resets — by design. The status.json file
# is re-written each cycle so the dashboard always sees the latest state.
# ══════════════════════════════════════════════════════════════════════════════

# Dict of currently open positions, keyed by symbol.
# Structure: {
#   "BTC/USD": {
#       "side":         "long" | "short",
#       "entry_price":  float,
#       "size_usd":     float,
#       "size_units":   float,
#       "entry_time":   str (ISO UTC),
#       "best_price":   float,  # highest seen for long, lowest for short
#       "order_id":     str,
#   }
# }
open_positions: dict[str, dict] = {}

# A deque (double-ended queue with max length) that stores recent price
# observations for each symbol, used by the circuit breaker.
# Structure: {symbol: deque([(datetime, price), ...])}
price_history: dict[str, deque] = {
    sym: deque(maxlen=100) for sym in SYMBOLS
}

# The total account equity in USD — refreshed every 60 minutes
total_equity: float = 0.0

# When we last refreshed the equity figure (Unix timestamp)
last_equity_refresh: float = 0.0

# Circuit breaker state — when this is set to a future datetime, all
# trading is paused until that time passes.
circuit_breaker_until: datetime | None = None

# Recent trade history for the status file (last 10 trades)
recent_trades: list[dict] = []

# How many full trading cycles have completed since startup
cycle_count: int = 0


# ══════════════════════════════════════════════════════════════════════════════
# STATUS FILE WRITER
# After every cycle, we write a JSON snapshot of the bot's current state.
# The FastAPI server reads this file to power the "Davy Jones" dashboard card.
# ══════════════════════════════════════════════════════════════════════════════

def write_status(error: str | None = None) -> None:
    """
    Serialise the bot's current state to STATUS_FILE (kraken-bot/status.json).
    This is how the dashboard knows what the bot is doing without coupling
    the bot process to the FastAPI server.
    """
    global total_equity, open_positions, circuit_breaker_until, recent_trades, cycle_count

    # Calculate how much capital is currently deployed
    deployed_usd = sum(p["size_usd"] for p in open_positions.values())
    deployable   = total_equity * (1.0 - CASH_RESERVE)
    deployed_pct = (deployed_usd / deployable * 100) if deployable > 0 else 0.0

    # Is the circuit breaker active right now?
    cb_active  = circuit_breaker_until is not None and datetime.now(tz=timezone.utc) < circuit_breaker_until
    cb_until   = circuit_breaker_until.isoformat() if cb_active else None

    # Build a clean list of open positions for the status
    positions_list = []
    for sym, pos in open_positions.items():
        positions_list.append({
            "symbol":      sym,
            "side":        pos["side"],
            "entry_price": pos["entry_price"],
            "size_usd":    pos["size_usd"],
            "entry_time":  pos["entry_time"],
            "best_price":  pos["best_price"],
        })

    state = {
        "bot_name":         "Davy Jones' Portfolio",
        "status":           "paused_circuit_breaker" if cb_active else ("running" if not error else "error"),
        "last_updated":     datetime.now(tz=timezone.utc).isoformat(),
        "cycle_count":      cycle_count,
        "total_equity_usd": round(total_equity, 2),
        "deployed_usd":     round(deployed_usd, 2),
        "deployed_pct":     round(deployed_pct, 1),
        "deployable_ceiling_pct": round((1.0 - CASH_RESERVE) * 100, 0),
        "cash_reserve_pct": CASH_RESERVE * 100,
        "open_positions":   positions_list,
        "position_count":   len(open_positions),
        "max_positions":    MAX_POSITIONS,
        "circuit_breaker":  {
            "active":       cb_active,
            "paused_until": cb_until,
        },
        "recent_trades":    recent_trades[-10:],  # Last 10 trades only
        "error":            error,
    }

    try:
        with open(STATUS_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as exc:
        logger.warning(f"Status | Could not write {STATUS_FILE}: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# EQUITY REFRESH
# ══════════════════════════════════════════════════════════════════════════════

def refresh_equity() -> None:
    """
    Fetch the current total account balance from Kraken and store it
    in the module-level 'total_equity' variable.

    We do this every 60 minutes (EQUITY_REFRESH_INTERVAL) because crypto
    moves fast — a position opened with stale equity numbers could easily
    over- or under-size a trade.
    """
    global total_equity, last_equity_refresh

    try:
        balance       = exchange.fetch_balance()
        # Kraken returns total equity as the USD balance
        usd_total     = balance.get("total", {}).get("USD", 0.0)
        total_equity  = float(usd_total)
        last_equity_refresh = time.time()
        logger.info(f"Equity | Refreshed → ${total_equity:,.2f} USD total")
    except Exception as exc:
        logger.warning(f"Equity | Failed to refresh: {exc} — using last known: ${total_equity:,.2f}")


# ══════════════════════════════════════════════════════════════════════════════
# ORDER EXECUTION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def open_position(symbol: str, side: str, size_usd: float, current_price: float) -> bool:
    """
    Place a market order to open a new position.

    For a LONG:  we BUY 'size_usd / current_price' units of the symbol.
    For a SHORT: we SELL 'size_usd / current_price' units (margin trade).

    Returns True if the order was successfully placed, False otherwise.
    """
    global open_positions, recent_trades

    try:
        size_units = size_usd / current_price
        order_side = "buy" if side == "long" else "sell"

        logger.info(
            f"Order | {side.upper()} {symbol} | "
            f"Size: ${size_usd:,.2f} ({size_units:.6f} units) @ ~${current_price:,.2f}"
        )

        order = exchange.create_market_order(
            symbol=symbol,
            side=order_side,
            amount=size_units,
        )

        # Record the position in our state
        fill_price = float(order.get("average") or order.get("price") or current_price)
        open_positions[symbol] = {
            "side":        side,
            "entry_price": fill_price,
            "size_usd":    size_usd,
            "size_units":  size_units,
            "entry_time":  datetime.now(tz=timezone.utc).isoformat(),
            "best_price":  fill_price,
            "order_id":    str(order.get("id", "")),
        }

        logger.success(f"Order | Opened {side.upper()} {symbol} @ ${fill_price:,.2f}")
        return True

    except Exception as exc:
        logger.error(f"Order | Failed to open {side.upper()} {symbol}: {exc}")
        return False


def close_position(symbol: str, reason: str) -> None:
    """
    Place a market order to close an open position and record the trade result.

    For a LONG:  we SELL our units back to the market.
    For a SHORT: we BUY to cover (close) the short.
    """
    global open_positions, recent_trades

    if symbol not in open_positions:
        return

    pos = open_positions[symbol]

    try:
        close_side = "sell" if pos["side"] == "long" else "buy"

        order = exchange.create_market_order(
            symbol=symbol,
            side=close_side,
            amount=pos["size_units"],
        )

        fill_price = float(order.get("average") or order.get("price") or pos["entry_price"])

        # Calculate P&L
        if pos["side"] == "long":
            pnl_pct = ((fill_price - pos["entry_price"]) / pos["entry_price"]) * 100
        else:
            pnl_pct = ((pos["entry_price"] - fill_price) / pos["entry_price"]) * 100

        pnl_usd = pos["size_usd"] * (pnl_pct / 100)

        logger.info(
            f"Close | {pos['side'].upper()} {symbol} | "
            f"Reason: {reason} | P&L: {pnl_pct:+.2f}% (${pnl_usd:+,.2f})"
        )

        # Record in recent trades list (for status.json / dashboard)
        recent_trades.append({
            "symbol":      symbol,
            "side":        pos["side"],
            "entry_price": pos["entry_price"],
            "exit_price":  fill_price,
            "pnl_pct":     round(pnl_pct, 2),
            "pnl_usd":     round(pnl_usd, 2),
            "reason":      reason,
            "closed_at":   datetime.now(tz=timezone.utc).isoformat(),
        })

        del open_positions[symbol]

    except Exception as exc:
        logger.error(f"Close | Failed to close {symbol}: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# SINGLE TRADING CYCLE — run once per LOOP_SLEEP_SECONDS
# ══════════════════════════════════════════════════════════════════════════════

def run_cycle() -> None:
    """
    Execute one full trading cycle:
      1. Refresh equity if needed (every 60 min)
      2. Check circuit breaker — if active, skip all trading
      3. For each symbol:
         a. Fetch latest OHLCV candles
         b. Record price in history (for circuit breaker)
         c. Check if circuit breaker should fire for this symbol
         d. If we have an open position → check stops and trail
         e. If we don't have a position and slots are free → evaluate signals
            - Compute RSI + z-score
            - Open a LONG if oversold + z-score < -entry_threshold
            - Open a SHORT if overbought + z-score > +entry_threshold
      4. Write status.json
    """
    global total_equity, circuit_breaker_until, cycle_count

    cycle_count += 1

    # ── Step 1: Refresh equity if it's been more than 60 minutes ─────────────
    if time.time() - last_equity_refresh >= EQUITY_REFRESH_INTERVAL:
        refresh_equity()

    # If we still have no equity figure, something is wrong — skip this cycle
    if total_equity <= 0:
        logger.warning("Cycle | Total equity is zero or unavailable — skipping cycle")
        write_status(error="Could not fetch account balance")
        return

    # ── Step 2: Check if circuit breaker is still active ─────────────────────
    now_utc = datetime.now(tz=timezone.utc)
    if circuit_breaker_until and now_utc < circuit_breaker_until:
        remaining = (circuit_breaker_until - now_utc).seconds // 60
        logger.warning(f"Cycle | Circuit breaker active — {remaining}min remaining, all trading paused")
        write_status()
        return

    # ── Step 3: Process each symbol ──────────────────────────────────────────
    deployed_usd = sum(p["size_usd"] for p in open_positions.values())

    for symbol in SYMBOLS:
        try:
            # ── 3a. Fetch candles ─────────────────────────────────────────────
            candles = exchange.fetch_ohlcv(
                symbol=symbol,
                timeframe=OHLCV_TIMEFRAME,
                limit=OHLCV_LIMIT,
            )
            if not candles or len(candles) < max(RSI_PERIOD, ZSCORE_WINDOW) + 2:
                logger.debug(f"Signal | {symbol}: Not enough candle data, skipping")
                continue

            closes        = [c[4] for c in candles]  # Index 4 = close price
            current_price = closes[-1]

            # ── 3b. Record price for circuit breaker ──────────────────────────
            price_history[symbol].append((now_utc, current_price))

            # ── 3c. Check circuit breaker for this symbol ─────────────────────
            if check_circuit_breaker(
                price_history[symbol],
                drop_threshold=CB_PRICE_DROP_PCT,
                window_minutes=CB_WINDOW_MINUTES,
            ):
                pause_until = now_utc + timedelta(hours=CB_PAUSE_HOURS)
                circuit_breaker_until = pause_until
                logger.warning(
                    f"CIRCUIT BREAKER | {symbol} dropped >{CB_PRICE_DROP_PCT*100:.0f}% "
                    f"in {CB_WINDOW_MINUTES}min — ALL trading paused until {pause_until.strftime('%H:%M UTC')}"
                )
                write_status()
                return  # Stop processing all symbols immediately

            # ── 3d. Manage existing position (if we have one) ─────────────────
            if symbol in open_positions:
                pos = open_positions[symbol]

                # Update the "best price" seen (high-water for long, low-water for short)
                if pos["side"] == "long":
                    pos["best_price"] = max(pos["best_price"], current_price)
                else:
                    pos["best_price"] = min(pos["best_price"], current_price)

                # Check if we should exit (stop loss or trailing take-profit)
                exit_reason = check_stops(
                    side=pos["side"],
                    entry_price=pos["entry_price"],
                    current_price=current_price,
                    best_price=pos["best_price"],
                    stop_loss_pct=STOP_LOSS_PCT,
                    trail_pct=TRAIL_PCT,
                )

                if exit_reason:
                    close_position(symbol, reason=exit_reason)
                    deployed_usd = sum(p["size_usd"] for p in open_positions.values())

                # Check for mean-reversion exit (z-score returned to mean)
                elif symbol in open_positions:
                    z = calculate_zscore(closes, window=ZSCORE_WINDOW)
                    if abs(z) < ZSCORE_EXIT:
                        close_position(symbol, reason="mean_reversion_complete")
                        deployed_usd = sum(p["size_usd"] for p in open_positions.values())
                    else:
                        pnl_pct = (
                            (current_price - pos["entry_price"]) / pos["entry_price"] * 100
                            if pos["side"] == "long"
                            else (pos["entry_price"] - current_price) / pos["entry_price"] * 100
                        )
                        logger.debug(
                            f"Hold   | {pos['side'].upper()} {symbol} @ ${pos['entry_price']:,.2f} | "
                            f"Now: ${current_price:,.2f} | P&L: {pnl_pct:+.2f}% | Z: {z:+.2f}"
                        )

                continue  # Don't try to open a new position in the same symbol

            # ── 3e. Evaluate entry signals (no position in this symbol) ───────

            # Respect the maximum concurrent position limit
            if len(open_positions) >= MAX_POSITIONS:
                logger.debug(f"Signal | {symbol}: Max positions ({MAX_POSITIONS}) reached — skip")
                continue

            # Compute the two signals
            rsi     = calculate_rsi(closes, period=RSI_PERIOD)
            z_score = calculate_zscore(closes, window=ZSCORE_WINDOW)

            # ── LONG signal: price is unusually low + RSI is oversold ─────────
            if z_score < -ZSCORE_ENTRY and rsi < RSI_OVERSOLD:
                size_usd = get_position_size(
                    total_equity=total_equity,
                    entry_price=current_price,
                    deployed_usd=deployed_usd,
                    risk_fraction=RISK_FRACTION,
                    stop_loss_pct=STOP_LOSS_PCT,
                    max_position_fraction=MAX_POSITION_FRACTION,
                    cash_reserve=CASH_RESERVE,
                )
                if size_usd >= 10.0:  # Minimum trade size ($10 to avoid dust orders)
                    logger.info(
                        f"Signal | LONG  {symbol} | RSI={rsi:.1f} (oversold<{RSI_OVERSOLD}) | "
                        f"Z={z_score:.2f} (dip>{ZSCORE_ENTRY}) | Size: ${size_usd:,.2f}"
                    )
                    if open_position(symbol, "long", size_usd, current_price):
                        deployed_usd += size_usd
                else:
                    logger.debug(f"Signal | {symbol}: LONG signal but position size ${size_usd:.2f} too small")

            # ── SHORT signal: price is unusually high + RSI is overbought ─────
            elif z_score > ZSCORE_ENTRY and rsi > RSI_OVERBOUGHT:
                size_usd = get_position_size(
                    total_equity=total_equity,
                    entry_price=current_price,
                    deployed_usd=deployed_usd,
                    risk_fraction=RISK_FRACTION,
                    stop_loss_pct=STOP_LOSS_PCT,
                    max_position_fraction=MAX_POSITION_FRACTION,
                    cash_reserve=CASH_RESERVE,
                )
                if size_usd >= 10.0:
                    logger.info(
                        f"Signal | SHORT {symbol} | RSI={rsi:.1f} (overbought>{RSI_OVERBOUGHT}) | "
                        f"Z={z_score:.2f} (peak>{ZSCORE_ENTRY}) | Size: ${size_usd:,.2f}"
                    )
                    if open_position(symbol, "short", size_usd, current_price):
                        deployed_usd += size_usd
                else:
                    logger.debug(f"Signal | {symbol}: SHORT signal but position size ${size_usd:.2f} too small")

            else:
                logger.debug(
                    f"Signal | {symbol} | No signal | RSI={rsi:.1f} Z={z_score:+.2f} | "
                    f"Price: ${current_price:,.2f}"
                )

        except Exception as exc:
            # One symbol failing should never stop the bot — log and continue
            logger.error(f"Cycle | Error processing {symbol}: {exc}")
            continue

    # ── Step 4: Write status for the dashboard ────────────────────────────────
    write_status()
    logger.debug(
        f"Cycle #{cycle_count} complete | "
        f"Positions: {len(open_positions)}/{MAX_POSITIONS} | "
        f"Deployed: ${sum(p['size_usd'] for p in open_positions.values()):,.2f}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT — The 24/7 Loop
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    """
    The outer execution loop. This is what runs 24/7.

    Structure:
      OUTER loop (try/except) — catches fatal errors, sleeps 30s, then restarts
        INNER loop (while True) — runs trading cycles every 60 seconds
          ├── refresh_equity() if 60min has passed
          ├── check circuit breaker
          ├── for each symbol: evaluate signals / manage positions
          └── write_status()

    The outer try/except is the "auto-restart" mechanism. If the Kraken API
    drops, the internet hiccups, or anything unexpected happens, the bot
    pauses for 30 seconds and then starts the inner loop again — no manual
    intervention needed.
    """
    global total_equity

    # Do an initial equity fetch before starting the loop
    refresh_equity()

    # ── Outer restart loop ────────────────────────────────────────────────────
    while True:
        try:
            logger.info("Bot | Starting trading loop ...")

            # ── Inner trading loop ────────────────────────────────────────────
            while True:
                run_cycle()

                # Sleep until the next cycle
                logger.debug(f"Bot | Sleeping {LOOP_SLEEP_SECONDS}s until next cycle ...")
                time.sleep(LOOP_SLEEP_SECONDS)

        except KeyboardInterrupt:
            # User pressed Ctrl+C — exit cleanly
            logger.info("Bot | Keyboard interrupt — shutting down gracefully.")
            write_status(error="Manually stopped")
            break

        except Exception as exc:
            # Something unexpected happened — log it, write error status,
            # then wait before restarting the inner loop
            logger.error(f"Bot | Unexpected error: {exc} — restarting in {RESTART_SLEEP_SECONDS}s")
            write_status(error=str(exc))
            time.sleep(RESTART_SLEEP_SECONDS)


# ── Script entry point ────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
