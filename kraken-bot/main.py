"""
main.py  —  Davy Jones' Portfolio  |  24/7 Kraken Crypto Trading Bot
=====================================================================
Named after Davy Jones' Locker — the mythical ocean abyss where ships
(and poorly-managed capital) go to never return. We aim to avoid that fate.

Strategy: Mean Reversion filtered by RSI
Exchange : Kraken Pro (via ccxt)
Runtime  : Continuous while True loop — restarts automatically on errors

Architecture:
  config.py       → All tunable parameters, exchange connection, and the
                    PAPER_TRADING master switch
  paper_engine.py → Simulated $100K portfolio (used when PAPER_TRADING=True)
  logic.py        → All math: RSI, z-score, position sizing, circuit breaker
  main.py         → This file: the execution loop that ties everything together

How to run:
  Paper mode (default, no keys needed):
    python3 kraken-bot/main.py

  Live mode (real money, requires Kraken API keys in Replit Secrets):
    Set PAPER_TRADING = False in kraken-bot/config.py, add your keys, restart.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Any

from loguru import logger

# Import our configuration — also handles the PAPER_TRADING startup message
# and validates/creates the exchange connection.
from config import (
    exchange,
    PAPER_TRADING,
    PAPER_STARTING_BALANCE,
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
    MIN_NET_PROFIT_PCT,
    EQUITY_REFRESH_INTERVAL,
    LOOP_SLEEP_SECONDS,
    RESTART_SLEEP_SECONDS,
    CB_PRICE_DROP_PCT,
    CB_WINDOW_MINUTES,
    CB_PAUSE_HOURS,
    STATUS_FILE,
    CONTROL_FILE,
)

# Import our trading logic functions (identical in both paper and live mode)
from logic import (
    calculate_rsi,
    calculate_zscore,
    get_position_size,
    check_circuit_breaker,
    check_stops,
)

# Import the paper trading engine (only actively used when PAPER_TRADING=True,
# but always imported so the module is ready to switch modes).
from paper_engine import (
    get_paper_equity,
    get_paper_positions,
    get_paper_portfolio_summary,
    paper_open_position,
    paper_close_position,
)


# ══════════════════════════════════════════════════════════════════════════════
# STARTUP BANNER
# ══════════════════════════════════════════════════════════════════════════════

logger.info("=" * 65)
if PAPER_TRADING:
    logger.info("  DAVY JONES' PORTFOLIO  —  *** PAPER TRADING MODE ***")
    logger.info(f"  Simulated balance : ${PAPER_STARTING_BALANCE:,.0f} USD (fake money)")
    logger.info("  No real orders will be placed on Kraken.")
else:
    logger.info("  DAVY JONES' PORTFOLIO  —  *** LIVE TRADING MODE ***")
    logger.info("  REAL MONEY — Real orders on Kraken Pro.")
logger.info("=" * 65)
logger.info(f"  Symbols        : {', '.join(SYMBOLS)}")
logger.info(f"  Timeframe      : {OHLCV_TIMEFRAME}")
logger.info(f"  Cash reserve   : {CASH_RESERVE*100:.0f}% (always held back)")
logger.info(f"  Max positions  : {MAX_POSITIONS}")
logger.info(f"  Max per trade  : {MAX_POSITION_FRACTION*100:.0f}% of equity")
logger.info(f"  Risk per trade : {RISK_FRACTION*100:.0f}% of equity")
logger.info(f"  Stop loss      : {STOP_LOSS_PCT*100:.0f}%")
logger.info(f"  Trailing profit: {TRAIL_PCT*100:.0f}%")
logger.info(f"  Min net profit : {MIN_NET_PROFIT_PCT*100:.1f}% (mean-reversion exit gate; covers 0.52% fees)")
logger.info(f"  Circuit breaker: >{CB_PRICE_DROP_PCT*100:.0f}% drop in {CB_WINDOW_MINUTES}min → {CB_PAUSE_HOURS}hr pause")
logger.info("=" * 65)


# ══════════════════════════════════════════════════════════════════════════════
# BOT STATE
# All of the bot's in-memory state lives here at module level. When the bot
# restarts after an error, this state resets — by design. The status.json file
# is re-written each cycle so the dashboard always sees the latest state.
# In paper mode, the portfolio itself is persisted in paper_portfolio.json.
# ══════════════════════════════════════════════════════════════════════════════

# Dict of currently open positions, keyed by symbol.
# In paper mode: populated from paper_engine's persistent state on startup.
# In live mode:  populated as orders fill.
open_positions: dict[str, dict] = {}

# A deque that stores recent price observations for the circuit breaker.
price_history: dict[str, deque] = {
    sym: deque(maxlen=100) for sym in SYMBOLS
}

# Total account equity in USD — refreshed every EQUITY_REFRESH_INTERVAL seconds.
total_equity: float = 0.0

# When we last refreshed the equity figure (Unix timestamp).
last_equity_refresh: float = 0.0

# Circuit breaker: when set to a future datetime, all trading is paused.
circuit_breaker_until: datetime | None = None

# Recent trade history for the status file (last 20 trades shown on dashboard).
recent_trades: list[dict] = []

# How many full trading cycles have completed since startup.
cycle_count: int = 0

# Cache of the latest prices seen in this cycle (used for paper equity calc).
latest_prices: dict[str, float] = {}

# Signal snapshot written each cycle — consumed by the dashboard thinking panel.
# Each entry: {symbol, rsi, z_score, price, signal_type, has_position}
latest_signals: list[dict] = []

# Plain-English "what the bot is thinking" written each cycle for the dashboard.
thinking_text: str = "Initialising — fetching market data..."


# ══════════════════════════════════════════════════════════════════════════════
# CONTROL FILE — pause/resume the bot from the dashboard
# ══════════════════════════════════════════════════════════════════════════════

def is_bot_paused() -> bool:
    """Return True if the dashboard has set bot_paused=true in control.json."""
    import json as _json, pathlib as _pl
    ctrl = _pl.Path(CONTROL_FILE)
    if not ctrl.exists():
        return False
    try:
        return bool(_json.loads(ctrl.read_text()).get("bot_paused", False))
    except Exception:
        return False


# STATUS FILE WRITER
# After every cycle, we write a JSON snapshot of the bot's current state.
# The FastAPI server reads this file to power the dashboard card.
# ══════════════════════════════════════════════════════════════════════════════

def write_status(error: str | None = None) -> None:
    """
    Serialise the bot's current state to STATUS_FILE (kraken-bot/status.json).
    The 'paper_trading' field lets the dashboard show a clear PAPER badge.
    Positions are enriched with live P&L, stop/TP prices, and qty for the dashboard table.
    """
    global total_equity, open_positions, circuit_breaker_until, recent_trades, cycle_count
    global latest_signals, thinking_text

    deployed_usd  = sum(p["size_usd"] for p in open_positions.values())
    deployable    = total_equity * (1.0 - CASH_RESERVE)
    deployed_pct  = (deployed_usd / deployable * 100) if deployable > 0 else 0.0

    cb_active = circuit_breaker_until is not None and datetime.now(tz=timezone.utc) < circuit_breaker_until
    cb_until  = circuit_breaker_until.isoformat() if cb_active else None

    positions_list = []
    for sym, pos in open_positions.items():
        current_price = latest_prices.get(sym, pos["entry_price"])
        entry         = pos["entry_price"]
        best          = pos["best_price"]
        size          = pos["size_usd"]
        side          = pos["side"]

        # Compute unrealised P&L
        if side == "long":
            pnl_usd        = (current_price - entry) / entry * size
            stop_loss_px   = round(entry * (1.0 - STOP_LOSS_PCT), 4)
            take_profit_px = round(best  * (1.0 - TRAIL_PCT),     4)  # trailing stop
        else:
            pnl_usd        = (entry - current_price) / entry * size
            stop_loss_px   = round(entry * (1.0 + STOP_LOSS_PCT), 4)
            take_profit_px = round(best  * (1.0 + TRAIL_PCT),     4)

        pnl_pct = (pnl_usd / size * 100) if size > 0 else 0.0
        qty     = size / entry if entry > 0 else 0.0

        positions_list.append({
            "symbol":              sym,
            "side":                side,
            "qty":                 round(qty, 6),
            "entry_price":         round(entry, 4),
            "current_price":       round(current_price, 4),
            "size_usd":            round(size, 2),
            "unrealized_pnl_usd":  round(pnl_usd, 2),
            "unrealized_pnl_pct":  round(pnl_pct, 4),
            "stop_loss_price":     stop_loss_px,
            "take_profit_price":   take_profit_px,
            "entry_time":          pos["entry_time"],
            "best_price":          round(best, 4),
        })

    # Paper-mode extra fields for the dashboard
    paper_summary = get_paper_portfolio_summary() if PAPER_TRADING else None

    paused = is_bot_paused()
    state = {
        "bot_name":         "Davy Jones' Portfolio",
        "paper_trading":    PAPER_TRADING,       # ← dashboard reads this for the PAPER badge
        "bot_paused":       paused,              # ← dashboard toggle writes control.json
        "status":           "paused_dashboard" if paused else ("paused_circuit_breaker" if cb_active else ("running" if not error else "error")),
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
        "circuit_breaker":  {"active": cb_active, "paused_until": cb_until},
        "recent_trades":    recent_trades[-20:],  # last 20 trades
        "paper_summary":    paper_summary,        # None in live mode
        "signals":          latest_signals,       # per-symbol RSI / z-score scan
        "thinking_text":    thinking_text,        # plain-English reasoning for dashboard
        "error":            error,
    }

    try:
        _tmp_status = STATUS_FILE + ".tmp"
        with open(_tmp_status, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(_tmp_status, STATUS_FILE)
    except Exception as exc:
        logger.warning(f"Status | Could not write {STATUS_FILE}: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# EQUITY REFRESH
# ══════════════════════════════════════════════════════════════════════════════

def refresh_equity() -> None:
    """
    Update the total_equity figure.

    PAPER mode  → compute from simulated cash + open position values at
                  the latest known prices (no API call needed).
    LIVE mode   → fetch the real USD balance from the Kraken API.
    """
    global total_equity, last_equity_refresh

    if PAPER_TRADING:
        # ── Paper trading: compute from simulated portfolio ───────────────────
        total_equity        = get_paper_equity(current_prices=latest_prices)
        last_equity_refresh = time.time()
        logger.info(f"Equity | Paper account → ${total_equity:,.2f} (simulated)")

    else:
        # ── Live trading: fetch real balance from Kraken ──────────────────────
        try:
            balance           = exchange.fetch_balance()
            usd_total         = balance.get("total", {}).get("USD", 0.0)
            total_equity      = float(usd_total)
            last_equity_refresh = time.time()
            logger.info(f"Equity | Live account → ${total_equity:,.2f} USD")
        except Exception as exc:
            logger.warning(f"Equity | Failed to refresh: {exc} — using last known: ${total_equity:,.2f}")


# ══════════════════════════════════════════════════════════════════════════════
# ORDER EXECUTION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def open_position(symbol: str, side: str, size_usd: float, current_price: float) -> bool:
    """
    Open a position — simulated (paper mode) or real (live mode).

    PAPER mode → calls paper_engine.paper_open_position()
    LIVE mode  → places a real market order via ccxt
    """
    global open_positions

    if PAPER_TRADING:
        # ── Paper: simulate the fill at current price ─────────────────────────
        success = paper_open_position(symbol, side, size_usd, current_price)
        if success:
            # Sync in-memory state from the paper engine's persisted state
            open_positions = get_paper_positions()
        return success

    else:
        # ── Live: place a real market order on Kraken ─────────────────────────
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
    Close an open position — simulated (paper mode) or real (live mode).

    PAPER mode → calls paper_engine.paper_close_position()
    LIVE mode  → places a real market order via ccxt
    """
    global open_positions, recent_trades

    if symbol not in open_positions:
        return

    pos = open_positions[symbol]

    if PAPER_TRADING:
        # ── Paper: simulate the fill at the last seen price ───────────────────
        current_price = latest_prices.get(symbol, pos["entry_price"])
        trade_record  = paper_close_position(symbol, current_price, reason)
        if trade_record:
            recent_trades.append(trade_record)
        # Sync in-memory state from the paper engine
        open_positions = get_paper_positions()

    else:
        # ── Live: place a real close order on Kraken ──────────────────────────
        try:
            close_side = "sell" if pos["side"] == "long" else "buy"
            order      = exchange.create_market_order(
                symbol=symbol,
                side=close_side,
                amount=pos["size_units"],
            )

            fill_price = float(order.get("average") or order.get("price") or pos["entry_price"])

            if pos["side"] == "long":
                pnl_pct = ((fill_price - pos["entry_price"]) / pos["entry_price"]) * 100
            else:
                pnl_pct = ((pos["entry_price"] - fill_price) / pos["entry_price"]) * 100

            pnl_usd = pos["size_usd"] * (pnl_pct / 100)

            logger.info(
                f"Close | {pos['side'].upper()} {symbol} | "
                f"Reason: {reason} | P&L: {pnl_pct:+.2f}% (${pnl_usd:+,.2f})"
            )

            recent_trades.append({
                "symbol":      symbol,
                "side":        pos["side"],
                "entry_price": pos["entry_price"],
                "exit_price":  fill_price,
                "pnl_pct":     round(pnl_pct, 2),
                "pnl_usd":     round(pnl_usd, 2),
                "reason":      reason,
                "closed_at":   datetime.now(tz=timezone.utc).isoformat(),
                "paper":       False,
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
         a. Fetch latest OHLCV candles (real live data in both modes)
         b. Record price in history (for circuit breaker)
         c. Check if circuit breaker should fire
         d. If we have an open position → evaluate exit conditions (priority order):
              i.  Hard stop loss        — always fires regardless of P&L
              ii. Trailing take-profit  — always fires regardless of P&L
              iii.Mean-reversion exit   — fires ONLY when |z-score| < ZSCORE_EXIT
                                         AND unrealised P&L ≥ MIN_NET_PROFIT_PCT.
                                         If z reverted but profit is below the fee
                                         break-even threshold the position is held so
                                         the fee cost isn't locked in as a loss.
         e. If no position and slots are free → evaluate RSI + z-score entry signals
      4. Write status.json for the dashboard
    """
    global total_equity, circuit_breaker_until, cycle_count, open_positions, latest_prices
    global latest_signals, thinking_text

    cycle_signals: list[dict] = []  # built up during this cycle, written at end

    cycle_count += 1

    # ── Pause check — dashboard can pause the bot without stopping the workflow ─
    if is_bot_paused():
        logger.info("Cycle | Bot is PAUSED by dashboard — skipping signal processing")
        write_status()
        return

    # ── Step 1: Refresh equity if it's been more than 60 minutes ─────────────
    if time.time() - last_equity_refresh >= EQUITY_REFRESH_INTERVAL:
        refresh_equity()

    # If we still have no equity figure, something is wrong — skip this cycle
    if total_equity <= 0:
        logger.warning("Cycle | Total equity is zero or unavailable — skipping cycle")
        write_status(error="Could not determine account balance")
        return

    # In paper mode, resync positions from the persistent paper state each cycle
    # so that positions survive a bot restart.
    if PAPER_TRADING:
        open_positions = get_paper_positions()

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
            # ── 3a. Fetch candles — real live data in both paper and live mode ─
            # Paper trading uses Kraken's public OHLCV endpoint (no auth needed).
            candles = exchange.fetch_ohlcv(
                symbol=symbol,
                timeframe=OHLCV_TIMEFRAME,
                limit=OHLCV_LIMIT,
            )
            if not candles or len(candles) < max(RSI_PERIOD, ZSCORE_WINDOW) + 2:
                logger.debug(f"Signal | {symbol}: Not enough candle data, skipping")
                continue

            closes        = [c[4] for c in candles]
            current_price = closes[-1]

            # Cache the latest price (used by paper equity calculation)
            latest_prices[symbol] = current_price

            # Pre-compute indicators once — used in both position mgmt and entry signals
            sym_rsi     = calculate_rsi(closes, period=RSI_PERIOD)
            sym_z_score = calculate_zscore(closes, window=ZSCORE_WINDOW)

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
                return

            # ── 3d. Manage existing position (if we have one) ─────────────────
            if symbol in open_positions:
                pos = open_positions[symbol]

                # Update the best price seen (high-water for long, low-water for short)
                if pos["side"] == "long":
                    pos["best_price"] = max(pos["best_price"], current_price)
                else:
                    pos["best_price"] = min(pos["best_price"], current_price)

                # Check if we should exit via stop-loss or trailing take-profit
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
                    cycle_signals.append({
                        "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                        "price": round(current_price, 4), "signal_type": f"exit_{exit_reason}",
                        "has_position": False,
                    })
                # Check for mean-reversion exit (z-score returned to mean)
                # ── Exit Conditions (in priority order) ──────────────────────
                # 1. Hard stop loss (check_stops above) — always fires, no P&L gate.
                # 2. Trailing take-profit (check_stops above) — always fires, no P&L gate.
                # 3. Mean-reversion exit — fires only when BOTH:
                #      a. |z-score| has returned below ZSCORE_EXIT (reversion complete), AND
                #      b. unrealised P&L ≥ MIN_NET_PROFIT_PCT (covers 0.52% round-trip fee).
                #    If (a) is true but (b) is not, the position continues to hold
                #    until the trailing stop, hard stop, or enough profit accumulates.
                elif symbol in open_positions:
                    # Compute current unrealised P&L fraction for the fee guard
                    unrealised_pnl_pct = (
                        (current_price - pos["entry_price"]) / pos["entry_price"]
                        if pos["side"] == "long"
                        else (pos["entry_price"] - current_price) / pos["entry_price"]
                    )

                    if abs(sym_z_score) < ZSCORE_EXIT:
                        if unrealised_pnl_pct >= MIN_NET_PROFIT_PCT:
                            # Both conditions met — take the mean-reversion exit
                            close_position(symbol, reason="mean_reversion_complete")
                            deployed_usd = sum(p["size_usd"] for p in open_positions.values())
                            cycle_signals.append({
                                "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                                "price": round(current_price, 4), "signal_type": "exit_mean_reversion",
                                "has_position": False,
                            })
                        else:
                            # Z returned to mean but P&L is below the fee threshold —
                            # hold and wait for the trailing stop or more profit.
                            needed_pct = (MIN_NET_PROFIT_PCT - unrealised_pnl_pct) * 100
                            logger.info(
                                f"Hold   | {pos['side'].upper()} {symbol} | "
                                f"Z reverted ({sym_z_score:+.2f}) but P&L {unrealised_pnl_pct*100:+.2f}% "
                                f"below min-profit threshold ({MIN_NET_PROFIT_PCT*100:.1f}%) — "
                                f"need +{needed_pct:.2f}% more before mean-reversion exit allowed"
                            )
                            thinking_text = (
                                f"{symbol}: Z-score reverted to {sym_z_score:+.2f} but "
                                f"P&L {unrealised_pnl_pct*100:+.2f}% is below the "
                                f"{MIN_NET_PROFIT_PCT*100:.1f}% min-profit gate (covers 0.52% fees). "
                                f"Holding — awaiting min profit threshold."
                            )
                            cycle_signals.append({
                                "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                                "price": round(current_price, 4), "signal_type": "hold_min_profit",
                                "has_position": True, "pnl_pct": round(unrealised_pnl_pct * 100, 2),
                                "side": pos["side"],
                            })
                    else:
                        pnl_pct = unrealised_pnl_pct * 100
                        logger.debug(
                            f"Hold   | {pos['side'].upper()} {symbol} @ ${pos['entry_price']:,.2f} | "
                            f"Now: ${current_price:,.2f} | P&L: {pnl_pct:+.2f}% | Z: {sym_z_score:+.2f}"
                        )
                        cycle_signals.append({
                            "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                            "price": round(current_price, 4), "signal_type": "hold",
                            "has_position": True, "pnl_pct": round(pnl_pct, 2),
                            "side": pos["side"],
                        })
                else:
                    cycle_signals.append({
                        "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                        "price": round(current_price, 4), "signal_type": "exit_stop",
                        "has_position": False,
                    })

                continue  # Don't try to open a new position in the same symbol

            # ── 3e. Evaluate entry signals (no position in this symbol) ────────

            if len(open_positions) >= MAX_POSITIONS:
                logger.debug(f"Signal | {symbol}: Max positions ({MAX_POSITIONS}) reached — skip")
                cycle_signals.append({
                    "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                    "price": round(current_price, 4), "signal_type": "slots_full", "has_position": False,
                })
                continue

            # LONG signal: price is unusually low + RSI is oversold
            if sym_z_score < -ZSCORE_ENTRY and sym_rsi < RSI_OVERSOLD:
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
                        f"Signal | LONG  {symbol} | RSI={sym_rsi:.1f} (oversold<{RSI_OVERSOLD}) | "
                        f"Z={sym_z_score:.2f} (dip>{ZSCORE_ENTRY}) | Size: ${size_usd:,.2f}"
                    )
                    if open_position(symbol, "long", size_usd, current_price):
                        deployed_usd += size_usd
                        cycle_signals.append({
                            "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                            "price": round(current_price, 4), "signal_type": "long_entered",
                            "has_position": True, "size_usd": round(size_usd, 2),
                        })
                    else:
                        cycle_signals.append({
                            "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                            "price": round(current_price, 4), "signal_type": "long_signal",
                            "has_position": False,
                        })
                else:
                    logger.debug(f"Signal | {symbol}: LONG signal but size ${size_usd:.2f} too small")
                    cycle_signals.append({
                        "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                        "price": round(current_price, 4), "signal_type": "long_signal_small",
                        "has_position": False,
                    })

            # SHORT signal: price is unusually high + RSI is overbought
            elif sym_z_score > ZSCORE_ENTRY and sym_rsi > RSI_OVERBOUGHT:
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
                        f"Signal | SHORT {symbol} | RSI={sym_rsi:.1f} (overbought>{RSI_OVERBOUGHT}) | "
                        f"Z={sym_z_score:.2f} (peak>{ZSCORE_ENTRY}) | Size: ${size_usd:,.2f}"
                    )
                    if open_position(symbol, "short", size_usd, current_price):
                        deployed_usd += size_usd
                        cycle_signals.append({
                            "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                            "price": round(current_price, 4), "signal_type": "short_entered",
                            "has_position": True, "size_usd": round(size_usd, 2),
                        })
                    else:
                        cycle_signals.append({
                            "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                            "price": round(current_price, 4), "signal_type": "short_signal",
                            "has_position": False,
                        })
                else:
                    logger.debug(f"Signal | {symbol}: SHORT signal but size ${size_usd:.2f} too small")
                    cycle_signals.append({
                        "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                        "price": round(current_price, 4), "signal_type": "short_signal_small",
                        "has_position": False,
                    })

            else:
                logger.debug(
                    f"Signal | {symbol} | No signal | RSI={sym_rsi:.1f} Z={sym_z_score:+.2f} | "
                    f"Price: ${current_price:,.2f}"
                )
                cycle_signals.append({
                    "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                    "price": round(current_price, 4), "signal_type": "watching", "has_position": False,
                })

        except Exception as exc:
            logger.error(f"Cycle | Error processing {symbol}: {exc}")
            continue

    # ── Step 4: Summarise signals + generate thinking text ────────────────────
    latest_signals = cycle_signals

    active_holds      = [s for s in cycle_signals if s["signal_type"] == "hold"]
    min_profit_holds  = [s for s in cycle_signals if s["signal_type"] == "hold_min_profit"]
    new_longs         = [s for s in cycle_signals if s["signal_type"] == "long_entered"]
    new_shorts        = [s for s in cycle_signals if s["signal_type"] == "short_entered"]
    watching          = [s for s in cycle_signals if s["signal_type"] == "watching"]
    oversold_near     = [s for s in watching if s["rsi"] < RSI_OVERSOLD + 10 and s["z_score"] < 0]
    overbought_near   = [s for s in watching if s["rsi"] > RSI_OVERBOUGHT - 10 and s["z_score"] > 0]

    if new_longs or new_shorts:
        entered = new_longs + new_shorts
        parts   = [f"{'LONG' if e['signal_type']=='long_entered' else 'SHORT'} {e['symbol'].replace('/USD','')} (RSI {e['rsi']}, Z={e['z_score']:+.2f})" for e in entered]
        thinking_text = "⚡ Entering: " + ", ".join(parts) + "."
    elif min_profit_holds:
        # Mean-reversion Z-score reverted but profit is below the fee break-even gate.
        # This is the most actionable state — surface it prominently.
        parts = [
            f"{h['side'].upper()} {h['symbol'].replace('/USD','')} "
            f"{h.get('pnl_pct', 0):+.2f}% (need {MIN_NET_PROFIT_PCT*100:.1f}%) "
            f"· Z={h['z_score']:+.2f}"
            for h in min_profit_holds
        ]
        thinking_text = "⏳ Holding — awaiting min profit threshold: " + " · ".join(parts)
    elif active_holds:
        hold_parts = [f"{h['side'].upper()} {h['symbol'].replace('/USD','')} {h.get('pnl_pct', 0):+.2f}% · Z={h['z_score']:+.2f}" for h in active_holds]
        thinking_text = "⚓ " + " · ".join(hold_parts)
    elif oversold_near:
        sym_list = ", ".join(s["symbol"].replace("/USD", "") for s in oversold_near)
        thinking_text = f"👀 {sym_list} approaching oversold — watching for entry."
    elif overbought_near:
        sym_list = ", ".join(s["symbol"].replace("/USD", "") for s in overbought_near)
        thinking_text = f"👀 {sym_list} drifting overbought — watching for short."
    else:
        thinking_text = "🔍 No setups — markets neutral."

    # ── Step 5: Write status for the dashboard ────────────────────────────────
    write_status()
    logger.debug(
        f"Cycle #{cycle_count} complete | "
        f"{'PAPER' if PAPER_TRADING else 'LIVE'} | "
        f"Equity: ${total_equity:,.2f} | "
        f"Positions: {len(open_positions)}/{MAX_POSITIONS} | "
        f"Deployed: ${sum(p['size_usd'] for p in open_positions.values()):,.2f}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT — The 24/7 Loop
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    """
    The outer execution loop. This is what runs 24/7.

    OUTER loop (try/except) — catches fatal errors, sleeps 30s, then restarts
      INNER loop (while True) — runs trading cycles every 60 seconds
        ├── refresh_equity()
        ├── check circuit breaker
        ├── for each symbol: evaluate signals / manage positions
        └── write_status()
    """
    global total_equity

    # Do an initial equity fetch before starting the loop
    refresh_equity()

    # ── Outer restart loop ────────────────────────────────────────────────────
    while True:
        try:
            logger.info(
                f"Bot | Starting {'PAPER' if PAPER_TRADING else 'LIVE'} trading loop ..."
            )

            # ── Inner trading loop ────────────────────────────────────────────
            while True:
                run_cycle()
                logger.debug(f"Bot | Sleeping {LOOP_SLEEP_SECONDS}s until next cycle ...")
                time.sleep(LOOP_SLEEP_SECONDS)

        except KeyboardInterrupt:
            logger.info("Bot | Keyboard interrupt — shutting down gracefully.")
            write_status(error="Manually stopped")
            break

        except Exception as exc:
            logger.error(f"Bot | Unexpected error: {exc} — restarting in {RESTART_SLEEP_SECONDS}s")
            write_status(error=str(exc))
            time.sleep(RESTART_SLEEP_SECONDS)


# ── Script entry point ────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
