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
import sys
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Any

from loguru import logger

# ── Shared core library ────────────────────────────────────────────────────────
# Both bots (Kraken + Alpaca) share RiskProfile, ExitBracket, CircuitBreaker
# from the repo-root shared/ package.
_REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_TRADING_PLATFORM = os.path.join(_REPO_ROOT, "trading-platform")
if _TRADING_PLATFORM not in sys.path:
    sys.path.append(_TRADING_PLATFORM)  # append (not insert) to avoid shadowing kraken-bot/config.py

from shared import RiskProfile, ExitBracket, CircuitBreaker as SharedCircuitBreaker
from microstructure import MicrostructureSignal
from penalty_tracker import PenaltyTracker

# Import our configuration — also handles the PAPER_TRADING startup message
# and validates/creates the exchange connection.
from config import (
    exchange,
    PAPER_TRADING,
    PAPER_STARTING_BALANCE,
    BLACKLIST,
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
    ATR_STOP_MULTIPLIER,
    TRAIL_PCT,
    MIN_NET_PROFIT_PCT,
    EQUITY_REFRESH_INTERVAL,
    LOOP_SLEEP_SECONDS,
    RESTART_SLEEP_SECONDS,
    CB_PRICE_DROP_PCT,
    CB_WINDOW_MINUTES,
    CB_PAUSE_HOURS,
    STATUS_FILE,
    LIVE_STATE_FILE,
    CONTROL_FILE,
    PAPER_PORTFOLIO_FILE,
    VPIN_ENTRY_BLOCK,
    VPIN_ELEVATED_CAP,
    VOLUME_SURGE_RATIO,
    CONTRARIAN_RSI_THRESH,
    CONTRARIAN_EQUITY_PCT,
    VPIN_DECAY_AFTER_CYCLES,
    VPIN_DECAY_RATE,
    DEEP_OVERSOLD_RSI,
    MICRO_LOT_EQUITY_PCT,
    BEAR_MAX_POSITIONS,
    BEAR_MAX_POSITION_FRACTION,
    BOT_ID,
    BOT_DISPLAY_NAME,
    BOT_DB_ID,
    BOT_STRATEGY_LABEL,
    MARKET_CACHE_FILE,
    IS_PRIMARY_FETCHER,
    MARKET_CACHE_TTL,
)

import adaptive_params as _adaptive
import db as _db

from logic import (
    calculate_rsi,
    calculate_zscore,
    calculate_atr,
    get_atr_stop_price,
    build_tranche_orders,
    get_position_size,
    check_circuit_breaker,
    check_stops,
    VPINDecayTracker,
)

# Import the paper trading engine (only actively used when PAPER_TRADING=True,
# but always imported so the module is ready to switch modes).
from paper_engine import (
    get_paper_equity,
    get_paper_positions,
    get_paper_portfolio_summary,
    paper_open_position,
    paper_scale_in_position,
    paper_close_position,
)


# ══════════════════════════════════════════════════════════════════════════════
# STARTUP BANNER
# ══════════════════════════════════════════════════════════════════════════════

logger.info("=" * 65)
if PAPER_TRADING:
    logger.info(f"  {BOT_DISPLAY_NAME.upper()}  —  *** PAPER TRADING MODE ***")
    logger.info(f"  Bot ID: {BOT_ID} (db_id={BOT_DB_ID}) | Strategy: {BOT_STRATEGY_LABEL}")
    logger.info(f"  Simulated balance : ${PAPER_STARTING_BALANCE:,.0f} USD (fake money)")
    logger.info("  No real orders will be placed on Kraken.")
else:
    logger.info(f"  {BOT_DISPLAY_NAME.upper()}  —  *** LIVE TRADING MODE ***")
    logger.info(f"  Bot ID: {BOT_ID} (db_id={BOT_DB_ID}) | Strategy: {BOT_STRATEGY_LABEL}")
    logger.info("  REAL MONEY — Real orders on Kraken Pro.")
logger.info("=" * 65)
logger.info(f"  Symbols        : {', '.join(SYMBOLS)}")
logger.info(f"  Timeframe      : {OHLCV_TIMEFRAME}")
logger.info(f"  Cash reserve   : {CASH_RESERVE*100:.0f}% (always held back)")
logger.info(f"  Max positions  : {MAX_POSITIONS}")
logger.info(f"  Max per trade  : {MAX_POSITION_FRACTION*100:.0f}% of equity")
logger.info(f"  Risk per trade : {RISK_FRACTION*100:.0f}% of equity")
logger.info(f"  Stop loss      : {STOP_LOSS_PCT*100:.0f}% (fallback) | ATR dynamic: {ATR_STOP_MULTIPLIER}x ATR")
logger.info(f"  Trailing profit: {TRAIL_PCT*100:.0f}%")
logger.info(f"  Blacklist      : {', '.join(BLACKLIST) if BLACKLIST else 'none'}")
logger.info(f"  Min net profit : {MIN_NET_PROFIT_PCT*100:.1f}% (mean-reversion exit gate; covers 0.52% fees)")
logger.info(f"  Circuit breaker: >{CB_PRICE_DROP_PCT*100:.0f}% drop in {CB_WINDOW_MINUTES}min → {CB_PAUSE_HOURS}hr pause")
logger.info(f"  Penalty throttle: Kraken API leaky-bucket (15pt ceiling, throttle at 80%)")
logger.info(f"  Microstructure: OFI + VAMP + VPIN entry filter active (order-book primary)")
logger.info(f"  VPIN gate     : base={VPIN_ENTRY_BLOCK} | surge_cap={VPIN_ELEVATED_CAP} | decay_after={VPIN_DECAY_AFTER_CYCLES}cyc @{VPIN_DECAY_RATE*100:.0f}%/cyc")
logger.info(f"  Contrarian    : RSI<{CONTRARIAN_RSI_THRESH} scout={CONTRARIAN_EQUITY_PCT*100:.0f}% | RSI<{DEEP_OVERSOLD_RSI} bypass=micro-lot {MICRO_LOT_EQUITY_PCT*100:.0f}%")
logger.info("=" * 65)

# ── DB schema bootstrap + one-time JSON migration ─────────────────────────────
_db.ensure_schema()
_db.migrate_heartbeat_from_json(STATUS_FILE)
_db.migrate_from_json(PAPER_PORTFOLIO_FILE)
logger.info("DB | Kraken PostgreSQL tables ready")

# One-time migration: seed kraken_adaptive_params from legacy JSON file if DB row absent
_adaptive.migrate_adaptive_from_json("kraken-bot/adaptive_params.json")
_adaptive.initialise()
logger.info("Adaptive params initialised — self-tuning layer active (evaluates every 6h)")


# ══════════════════════════════════════════════════════════════════════════════
# BOT STATE
# All of the bot's in-memory state lives here at module level. When the bot
# restarts after an error, this state resets — by design.
# Heartbeat and portfolio are persisted to PostgreSQL (kraken_heartbeat,
# kraken_portfolio) so the dashboard recovers state after a restart.
# Live telemetry (signals, microstructure, thinking_text, open_positions with
# enriched price/P&L fields) is written to live_state.json each cycle.
# ══════════════════════════════════════════════════════════════════════════════

# Dict of currently open positions, keyed by symbol.
# In paper mode: populated from paper_engine's persistent state on startup.
# In live mode:  populated as orders fill.
open_positions: dict[str, dict] = {}

# Pending tranche orders — keyed by symbol, holds T2 and T3 dicts that have
# not yet been executed.  Populated when a new position is opened (T1 fires).
# Each cycle, the bot checks whether price has reached the next tranche level.
# Cleared automatically when the position is closed.
# Persisted to PostgreSQL (kraken_portfolio.pending_tranches JSONB column)
# so tranches survive bot restarts.
_pending_tranches: dict[str, list[dict]] = {}


def _persist_tranches() -> None:
    total = sum(len(v) for v in _pending_tranches.values())
    _db.save_pending_tranches(_pending_tranches)
    logger.debug(f"Tranches | Persisted {total} tranche(s) across {len(_pending_tranches)} symbol(s)")

# A deque that stores recent price observations for the circuit breaker.
price_history: dict[str, deque] = {
    sym: deque(maxlen=100) for sym in SYMBOLS
}

# Stateful circuit-breaker instance from shared/ — tracks pause window and
# observation count in memory across cycles.  One per-symbol breaker so each
# pair can trip independently without halting the whole bot.
shared_circuit_breakers: dict[str, "SharedCircuitBreaker"] = {
    sym: SharedCircuitBreaker(pause_hours=CB_PAUSE_HOURS)
    for sym in SYMBOLS
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

_vpin_decay = VPINDecayTracker(
    decay_after=VPIN_DECAY_AFTER_CYCLES,
    decay_rate=VPIN_DECAY_RATE,
)

_volume_history: dict[str, deque] = {
    sym: deque(maxlen=30) for sym in SYMBOLS
}

# Signal snapshot written each cycle — consumed by the dashboard thinking panel.
# Each entry: {symbol, rsi, z_score, price, signal_type, has_position}
latest_signals: list[dict] = []

# Plain-English "what the bot is thinking" written each cycle for the dashboard.
thinking_text: str = "Initialising — fetching market data..."

# Latest microstructure readings per symbol (written to status.json each cycle).
latest_microstructure: dict[str, dict] = {}

# ── Kraken API Penalty Tracker ────────────────────────────────────────────────
# Tracks the leaky-bucket penalty point accumulation for Kraken REST calls.
# Throttles new order placement when the bucket exceeds 80% of the 15-point ceiling.
_penalty_tracker: PenaltyTracker = PenaltyTracker()

# ── Cross-Bot Regime Sync ─────────────────────────────────────────────────────
# Path to the shared file the Alpaca pipeline writes after every successful cycle.
# The Kraken bot reads this file once per cycle to apply Bear/RISK-OFF filters.
_MARKET_REGIME_FILE = os.path.join(_REPO_ROOT, "trading-platform", "data", "market_regime.json")

# Bear and Risk-Off regimes that trigger Kraken's defensive mode.
_BEAR_REGIMES = frozenset({"Bear", "RISK-OFF", "Risk-Off", "bear", "risk-off"})


def _read_market_regime() -> dict:
    """
    Read the shared market_regime.json written by the Alpaca pipeline.
    Returns a dict with at minimum {"regime": str, "is_bear": bool}.
    Falls back gracefully if the file is missing or corrupt.
    """
    try:
        import pathlib as _pl
        _path = _pl.Path(_MARKET_REGIME_FILE)
        if not _path.exists():
            return {"regime": "unknown", "is_bear": False, "source": "no_file"}
        data = json.loads(_path.read_text())
        regime = data.get("regime", "unknown")
        is_bear = regime in _BEAR_REGIMES
        return {**data, "is_bear": is_bear}
    except Exception as _exc:
        logger.debug(f"RegimeSync | Could not read market_regime.json: {_exc}")
        return {"regime": "unknown", "is_bear": False, "source": "read_error"}


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
# After every cycle, we write:
#   - kraken_heartbeat (DB)     — persistent state (status, equity, positions)
#   - live_state.json           — live telemetry (signals, microstructure, thinking)
# The FastAPI server reads kraken_heartbeat (DB) + live_state.json for the dashboard.
# ══════════════════════════════════════════════════════════════════════════════



def _atomic_json_write(filepath: str, payload: dict) -> None:
    """
    Atomically write a JSON payload to filepath using a tmp-then-rename pattern.
    Validates the tmp file before replacing the live copy so a failed write
    never corrupts the live file.
    """
    _tmp = filepath + ".tmp"
    try:
        with open(_tmp, "w") as _f:
            json.dump(payload, _f, indent=2, default=str)
        # Validate before rename — protects against mid-stream failures.
        try:
            with open(_tmp) as _vf:
                json.load(_vf)
        except Exception as _ve:
            logger.warning(f"Status | {filepath} tmp validation failed — aborting replace: {_ve}")
            return
        os.replace(_tmp, filepath)
    except Exception as exc:
        logger.warning(f"Status | Could not write {filepath}: {exc}")


def write_status(error: str | None = None) -> None:
    """
    Write the bot heartbeat to PostgreSQL (kraken_heartbeat, id=1).

    PostgreSQL is the sole persistent store: a single-row upsert that the
    FastAPI server and auto-heal monitor read directly — no file parsing,
    no JSONDecodeError possible.
    """
    global total_equity, open_positions, circuit_breaker_until, cycle_count

    cb_active = circuit_breaker_until is not None and datetime.now(tz=timezone.utc) < circuit_breaker_until
    cb_until  = circuit_breaker_until.isoformat() if cb_active else None

    paused = is_bot_paused()
    status_str = (
        "paused_dashboard"         if paused     else
        "paused_circuit_breaker"   if cb_active  else
        ("running" if not error else "error")
    )

    # Primary: PostgreSQL heartbeat
    _db.upsert_heartbeat(
        status=status_str,
        cycle_count=cycle_count,
        equity_usd=round(total_equity, 2),
        position_count=len(open_positions),
        paper_trading=PAPER_TRADING,
        bot_paused=paused,
        circuit_breaker={"active": cb_active, "paused_until": cb_until},
        error=error,
    )

    # status.json is no longer written in the primary path.
    # PostgreSQL kraken_heartbeat is the sole persistent store for the heartbeat.
    # The _atomic_json_write + STATUS_FILE infrastructure is retained for the
    # one-time bootstrap migration only (see migrate_from_json in db.py).


def write_live_state() -> None:
    """
    Write the larger live trading state to LIVE_STATE_FILE (kraken-bot/live_state.json).

    This file is NOT monitored by the auto-heal check; it holds data that
    the dashboard panels need but that is too large for the heartbeat file:
      - open_positions (enriched with live P&L, stop/TP prices)
      - signals        (per-symbol RSI / z-score scan)
      - microstructure (OFI / VAMP / VPIN per symbol)
      - thinking_text  (plain-English reasoning from the LLM)
      - adaptive_params (self-tuning parameter snapshot)
      - deployment metrics (deployed_usd, deployed_pct, etc.)
    """
    global total_equity, open_positions, latest_signals, thinking_text, latest_microstructure

    deployed_usd  = sum(p["size_usd"] for p in open_positions.values())
    deployable    = total_equity * (1.0 - CASH_RESERVE)
    deployed_pct  = (deployed_usd / deployable * 100) if deployable > 0 else 0.0

    positions_list = []
    for sym, pos in open_positions.items():
        current_price = latest_prices.get(sym, pos["entry_price"])
        entry         = pos["entry_price"]
        best          = pos["best_price"]
        size          = pos["size_usd"]
        side          = pos["side"]

        _ap = _adaptive.get_active_params()
        _pos_atr_stop = pos.get("atr_stop_price")
        if side == "long":
            pnl_usd        = (current_price - entry) / entry * size
            stop_loss_px   = round(_pos_atr_stop, 4) if _pos_atr_stop is not None else round(entry * (1.0 - _ap["STOP_LOSS_PCT"]), 4)
            take_profit_px = round(best  * (1.0 - _ap["TRAIL_PCT"]),     4)
        else:
            pnl_usd        = (entry - current_price) / entry * size
            stop_loss_px   = round(_pos_atr_stop, 4) if _pos_atr_stop is not None else round(entry * (1.0 + _ap["STOP_LOSS_PCT"]), 4)
            take_profit_px = round(best  * (1.0 + _ap["TRAIL_PCT"]),     4)

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

    live_state = {
        "last_updated":           datetime.now(tz=timezone.utc).isoformat(),
        "deployed_usd":           round(deployed_usd, 2),
        "deployed_pct":           round(deployed_pct, 1),
        "deployable_ceiling_pct": round((1.0 - CASH_RESERVE) * 100, 0),
        "cash_reserve_pct":       CASH_RESERVE * 100,
        "max_positions":          MAX_POSITIONS,
        "open_positions":         positions_list,
        "signals":                latest_signals,
        "microstructure":         latest_microstructure,
        "thinking_text":          thinking_text,
        "adaptive_params":        _adaptive.status_snapshot(),
    }
    _atomic_json_write(LIVE_STATE_FILE, live_state)


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
            _penalty_tracker.record_placement()

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
            _pnl = trade_record.get("pnl_usd", 0)
            _pnl_pct = trade_record.get("pnl_pct", 0)
            if _pnl > 0:
                try:
                    from execution.profit_sweep import record_kraken_vault_contribution
                    record_kraken_vault_contribution(_pnl)
                except Exception as _ve:
                    logger.warning(f"Vault | Kraken sweep failed: {_ve}")
                try:
                    from notifications.alert_manager import enqueue_profitable_trade
                    _bot_label = os.environ.get("BOT_DISPLAY_NAME", BOT_DISPLAY_NAME)
                    enqueue_profitable_trade(
                        bot_name=f"Kraken {_bot_label}",
                        symbol=symbol,
                        pnl_pct=_pnl_pct,
                        pnl_usd=_pnl,
                        reason=reason,
                    )
                except Exception:
                    pass
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

    # Tranche cleanup: when a position closes, all its pending tranches are cancelled
    if symbol in _pending_tranches:
        remaining = [t for t in _pending_tranches[symbol] if not t["filled"]]
        if remaining:
            logger.info(
                f"Tranches | {symbol}: {len(remaining)} pending tranche(s) cancelled "
                f"(position closed by {reason})"
            )
        del _pending_tranches[symbol]
        _persist_tranches()


def scale_into_position(symbol: str, tranche: dict, current_price: float) -> bool:
    """
    Execute a pending scale-in tranche (T2 or T3) for an existing position.

    Called when the market price has reached the next tranche's target level.
    Updates the position's size and weighted-average entry price in-place.

    PAPER mode → calls paper_engine.paper_scale_in_position()
    LIVE mode  → places a real additional market order via ccxt

    Args:
        symbol:        The trading pair.
        tranche:       The tranche dict from build_tranche_orders() for this level.
        current_price: The current market price (used as simulated fill).

    Returns:
        True if the scale-in was executed, False if it failed.
    """
    global open_positions

    if symbol not in open_positions:
        logger.warning(f"Tranches | Scale-in {symbol} T{tranche['tranche']}: no open position")
        return False

    add_size_usd = tranche["size_usd"]

    if PAPER_TRADING:
        success = paper_scale_in_position(symbol, add_size_usd, current_price)
        if success:
            open_positions = get_paper_positions()
        return success

    else:
        # Live mode: place an additional market order in the same direction
        try:
            pos       = open_positions[symbol]
            side      = pos["side"]
            add_units = add_size_usd / current_price
            order_side = "buy" if side == "long" else "sell"

            order = exchange.create_market_order(
                symbol=symbol,
                side=order_side,
                amount=add_units,
            )
            _penalty_tracker.record_placement()
            fill_price = float(order.get("average") or order.get("price") or current_price)

            # Weighted average entry update
            old_size  = pos["size_usd"]
            old_entry = pos["entry_price"]
            new_size  = old_size + add_size_usd
            new_entry = (old_size * old_entry + add_size_usd * fill_price) / new_size

            pos["entry_price"] = round(new_entry, 8)
            pos["size_usd"]    = round(new_size, 2)
            pos["size_units"]  = round(pos["size_units"] + add_units, 8)

            logger.success(
                f"Tranches | Scaled into {side.upper()} {symbol} (T{tranche['tranche']}) @ "
                f"${fill_price:,.4f} | Added ${add_size_usd:,.2f} | "
                f"New avg entry: ${new_entry:,.4f} | Total size: ${new_size:,.2f}"
            )
            return True

        except Exception as exc:
            logger.error(f"Tranches | Scale-in {symbol} T{tranche['tranche']} failed: {exc}")
            return False


# ══════════════════════════════════════════════════════════════════════════════
# SINGLE TRADING CYCLE — run once per LOOP_SLEEP_SECONDS
# ══════════════════════════════════════════════════════════════════════════════

def _write_market_cache(data: dict) -> None:
    """Write shared market data cache with file locking (primary fetcher only)."""
    import fcntl
    cache_path = MARKET_CACHE_FILE
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        tmp = cache_path + ".tmp"
        with open(tmp, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            json.dump(data, f, default=str)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        os.replace(tmp, cache_path)
    except Exception as exc:
        logger.debug(f"MarketCache | write failed: {exc}")


def _read_market_cache() -> dict | None:
    """Read shared market data cache. Returns None if stale or missing."""
    import fcntl
    cache_path = MARKET_CACHE_FILE
    try:
        if not os.path.exists(cache_path):
            return None
        with open(cache_path, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        ts = data.get("_cache_ts", 0)
        if time.time() - ts > MARKET_CACHE_TTL:
            return None
        return data
    except Exception as exc:
        logger.debug(f"MarketCache | read failed: {exc}")
        return None


def _fetch_ohlcv_with_cache(symbol: str) -> list | None:
    """Fetch OHLCV data, using shared cache for non-primary bots."""
    if not IS_PRIMARY_FETCHER:
        cache = _read_market_cache()
        if cache and symbol in cache.get("ohlcv", {}):
            return cache["ohlcv"][symbol]

    try:
        candles = exchange.fetch_ohlcv(
            symbol=symbol,
            timeframe=OHLCV_TIMEFRAME,
            limit=OHLCV_LIMIT,
        )
        return candles
    except Exception as exc:
        logger.warning(f"OHLCV | {symbol} fetch failed: {exc}")
        return None


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
      4. Write heartbeat (DB) and live_state.json (live telemetry)
    """
    global total_equity, circuit_breaker_until, cycle_count, open_positions, latest_prices
    global latest_signals, thinking_text, latest_microstructure

    cycle_signals: list[dict] = []  # built up during this cycle, written at end
    cycle_microstructure: dict[str, dict] = {}

    cycle_count += 1

    # ── Heartbeat — write DB heartbeat + live_state at start of every cycle ──
    # This guarantees the timestamp is fresh even if the cycle exits early or
    # the workflow was paused between cycles by the hosting environment.
    write_status()
    write_live_state()

    # ── Pause check — dashboard can pause the bot without stopping the workflow ─
    if is_bot_paused():
        logger.info("Cycle | Bot is PAUSED by dashboard — skipping signal processing")
        write_status()
        write_live_state()
        return

    # ── Step 1: Refresh equity if it's been more than 60 minutes ─────────────
    if time.time() - last_equity_refresh >= EQUITY_REFRESH_INTERVAL:
        refresh_equity()

    # If we still have no equity figure, something is wrong — skip this cycle
    if total_equity <= 0:
        logger.warning("Cycle | Total equity is zero or unavailable — skipping cycle")
        write_status(error="Could not determine account balance")
        write_live_state()
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
        write_live_state()
        return

    # ── Step 3: Process each symbol ──────────────────────────────────────────
    deployed_usd = sum(p["size_usd"] for p in open_positions.values())

    # ── RiskProfile: deployment ceiling guard ─────────────────────────────────
    # Build a RiskProfile from the live equity snapshot.  Uses the same
    # ring-fence / reserve constants as the Alpaca bot for consistency.
    # This is purely a guard — it does not change position sizing math;
    # get_position_size() (logic.py) remains the source of truth.
    _risk_profile = RiskProfile(
        total_equity=total_equity,
        deployed_usd=deployed_usd,
        ring_fenced_pct=0.0,
        deployable_pct=1.0,
        max_position_pct=MAX_POSITION_FRACTION,
        daily_loss_limit_pct=0.05,
        reserve_pct=CASH_RESERVE,
        name="kraken",
    )
    if _risk_profile.is_breached():
        logger.warning(
            f"RiskProfile | Reserve breach: deployed=${deployed_usd:,.2f} "
            f"ceiling=${_risk_profile.active_ceiling_usd():,.2f} "
            f"— new entries BLOCKED for this cycle"
        )
    else:
        logger.debug(
            f"RiskProfile | {_risk_profile.deployed_pct():.1f}% deployed "
            f"(${deployed_usd:,.0f} / ${_risk_profile.active_ceiling_usd():,.0f})"
        )
    _profile_breached = _risk_profile.is_breached()

    # ── Pull current adaptive parameters (self-tuning layer) ─────────────────
    # maybe_adapt() only does real work every 6 hours; otherwise returns fast.
    _adaptive.maybe_adapt()
    _ap = _adaptive.get_active_params()
    _zscore_entry       = _ap["ZSCORE_ENTRY"]
    _zscore_exit        = _ap["ZSCORE_EXIT"]
    _stop_loss_pct      = _ap["STOP_LOSS_PCT"]
    _trail_pct          = _ap["TRAIL_PCT"]
    _min_net_profit_pct = _ap["MIN_NET_PROFIT_PCT"]

    # ── Cross-Bot Regime Sync ─────────────────────────────────────────────────
    # Read the shared market_regime.json file that the Alpaca pipeline writes
    # after every successful analysis cycle.  When the Alpaca bot signals a
    # Bear or RISK-OFF regime, the Kraken bot operates in defensive mode:
    #   • All new LONG entries are blocked (crypto "dip buying" disabled)
    #   • Max simultaneous positions reduced from 10 → BEAR_MAX_POSITIONS (5)
    #   • Max position size reduced from 10% → BEAR_MAX_POSITION_FRACTION (7.5%)
    _regime_data  = _read_market_regime()
    _regime_label = _regime_data.get("regime", "unknown")
    _is_bear      = _regime_data.get("is_bear", False)

    # Apply bear-regime sizing overrides
    _effective_max_positions       = BEAR_MAX_POSITIONS       if _is_bear else MAX_POSITIONS
    _effective_max_position_frac   = BEAR_MAX_POSITION_FRACTION if _is_bear else MAX_POSITION_FRACTION

    if _is_bear:
        logger.info(
            f"RegimeSync | BEAR/RISK-OFF detected (Alpaca regime='{_regime_label}') — "
            f"LONG entries DISABLED | max_positions={_effective_max_positions} | "
            f"max_position_fraction={_effective_max_position_frac:.1%}"
        )
    else:
        logger.debug(
            f"RegimeSync | Regime='{_regime_label}' — normal parameters active "
            f"(max_positions={_effective_max_positions} max_frac={_effective_max_position_frac:.0%})"
        )

    _ohlcv_cache_data: dict[str, list] = {}

    _blacklisted_open = [s for s in list(open_positions.keys()) if s in BLACKLIST]
    for _bl_sym in _blacklisted_open:
        logger.warning(
            f"Blacklist | {_bl_sym}: FORCE CLOSING open position — asset is blacklisted"
        )
        close_position(_bl_sym, reason="blacklisted_asset")
        deployed_usd = sum(p["size_usd"] for p in open_positions.values())

    for symbol in SYMBOLS:
        if symbol in BLACKLIST:
            logger.debug(f"Blacklist | {symbol}: SKIPPED — blacklisted asset")
            continue

        try:
            candles = _fetch_ohlcv_with_cache(symbol)
            if not candles or len(candles) < max(RSI_PERIOD, ZSCORE_WINDOW) + 2:
                logger.debug(f"Signal | {symbol}: Not enough candle data, skipping")
                continue

            closes        = [c[4] for c in candles]
            highs         = [c[2] for c in candles]
            lows          = [c[3] for c in candles]
            volumes       = [c[5] for c in candles]
            current_price = closes[-1]

            if IS_PRIMARY_FETCHER:
                _ohlcv_cache_data[symbol] = candles

            _volume_history[symbol].append(volumes[-1] if volumes else 0.0)
            _vol_24h_sum = sum(list(volumes)[-24:]) if len(volumes) >= 24 else sum(volumes)

            # Cache the latest price (used by paper equity calculation)
            latest_prices[symbol] = current_price

            # ATR — volatility-adjusted risk management
            sym_atr = calculate_atr(highs, lows, closes)

            # Pre-compute indicators once — used in both position mgmt and entry signals
            sym_rsi     = calculate_rsi(closes, period=RSI_PERIOD)
            sym_z_score = calculate_zscore(closes, window=ZSCORE_WINDOW)

            # ── Microstructure signals (OFI / VAMP / VPIN) ────────────────────
            # Primary: order-book snapshot + recent trades (ccxt live data).
            # Fallback: OHLCV-based approximation when order-book fetch fails.
            try:
                _ob     = exchange.fetch_order_book(symbol, limit=20)
                _trades = exchange.fetch_trades(symbol, limit=200)
                _ms = MicrostructureSignal.from_orderbook(
                    _ob, _trades, symbol=symbol,
                )
                cycle_microstructure[symbol] = _ms.to_dict()
                logger.debug(
                    f"Microstructure | {symbol}: OFI={_ms.ofi:+.3f} "
                    f"VAMP={_ms.vamp:.2f} VPIN={_ms.vpin:.3f} (order-book)"
                )
            except Exception as _ms_exc:
                logger.debug(
                    f"Microstructure | {symbol}: order-book fetch failed "
                    f"({_ms_exc}) — falling back to OHLCV"
                )
                try:
                    _ms = MicrostructureSignal.from_ohlcv(candles, symbol=symbol)
                except Exception:
                    _ms = MicrostructureSignal(symbol=symbol, ofi=0.0, vamp=0.0, vpin=0.0)
                cycle_microstructure[symbol] = _ms.to_dict()

            # ── 3b. Record price for circuit breaker ──────────────────────────
            price_history[symbol].append((now_utc, current_price))
            # Also feed the stateful CircuitBreaker so it can maintain an
            # observation count and manage its own pause window.
            shared_circuit_breakers[symbol].record(now_utc, current_price)

            # ── 3c. Check circuit breaker for this symbol ─────────────────────
            # Primary check: stateless helper on the deque (source of truth).
            # Secondary check: stateful CircuitBreaker.check_and_trip() keeps
            # the shared instance's pause window in sync for observation-count
            # tracking and state persistence across the cycle.
            _cb_triggered = check_circuit_breaker(
                price_history[symbol],
                drop_threshold=CB_PRICE_DROP_PCT,
                window_minutes=CB_WINDOW_MINUTES,
            )
            shared_circuit_breakers[symbol].check_and_trip()
            if _cb_triggered:
                pause_until = now_utc + timedelta(hours=CB_PAUSE_HOURS)
                circuit_breaker_until = pause_until
                logger.warning(
                    f"CIRCUIT BREAKER | {symbol} dropped >{CB_PRICE_DROP_PCT*100:.0f}% "
                    f"in {CB_WINDOW_MINUTES}min — ALL trading paused until {pause_until.strftime('%H:%M UTC')}"
                )
                write_status()
                write_live_state()
                return

            # ── 3d. Manage existing position (if we have one) ─────────────────
            if symbol in open_positions:
                pos = open_positions[symbol]

                # Update the best price seen (high-water for long, low-water for short)
                if pos["side"] == "long":
                    pos["best_price"] = max(pos["best_price"], current_price)
                else:
                    pos["best_price"] = min(pos["best_price"], current_price)

                # ── Pending tranche check (T2 / T3 scale-ins) ─────────────────
                # Before evaluating exits, check whether the current price has
                # reached the next pending tranche target.  We only try one
                # tranche per cycle so the bot doesn't overshoot.
                if symbol in _pending_tranches:
                    for _t in _pending_tranches[symbol]:
                        if _t.get("filled"):
                            continue
                        _t_side   = _t["side"]
                        _t_target = _t["target_price"]
                        # For longs T2/T3 are lower (dip-buy); for shorts they are higher
                        _triggered = (
                            (current_price <= _t_target) if _t_side == "long"
                            else (current_price >= _t_target)
                        )
                        if _triggered:
                            ok = scale_into_position(symbol, _t, current_price)
                            if ok:
                                _t["filled"]    = True
                                _t["fill_price"] = current_price
                                _persist_tranches()
                                logger.info(
                                    f"Tranches | {symbol} T{_t['tranche']} filled @ ${current_price:,.4f} "
                                    f"(target was ${_t_target:,.4f})"
                                )
                            break  # only one tranche per cycle

                # Check if we should exit via stop-loss or trailing take-profit
                exit_reason = check_stops(
                    side=pos["side"],
                    entry_price=pos["entry_price"],
                    current_price=current_price,
                    best_price=pos["best_price"],
                    stop_loss_pct=_stop_loss_pct,
                    trail_pct=_trail_pct,
                    atr_stop_price=pos.get("atr_stop_price"),
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

                    if abs(sym_z_score) < _zscore_exit:
                        if unrealised_pnl_pct >= _min_net_profit_pct:
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
                            needed_pct = (_min_net_profit_pct - unrealised_pnl_pct) * 100
                            logger.info(
                                f"Hold   | {pos['side'].upper()} {symbol} | "
                                f"Z reverted ({sym_z_score:+.2f}) but P&L {unrealised_pnl_pct*100:+.2f}% "
                                f"below min-profit threshold ({_min_net_profit_pct*100:.1f}%) — "
                                f"need +{needed_pct:.2f}% more before mean-reversion exit allowed"
                            )
                            thinking_text = (
                                f"{symbol}: Z-score reverted to {sym_z_score:+.2f} but "
                                f"P&L {unrealised_pnl_pct*100:+.2f}% is below the "
                                f"{_min_net_profit_pct*100:.1f}% min-profit gate (covers 0.52% fees). "
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

            if len(open_positions) >= _effective_max_positions:
                logger.debug(
                    f"Signal | {symbol}: Max positions ({_effective_max_positions}"
                    + (" [bear-regime]" if _is_bear else "")
                    + f") reached — skip"
                )
                cycle_signals.append({
                    "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                    "price": round(current_price, 4), "signal_type": "slots_full", "has_position": False,
                })
                continue

            # ── RiskProfile ceiling guard ─────────────────────────────────────
            # If the deployment ceiling is already breached, skip new entries.
            # This does not affect existing positions or exit logic.
            if _profile_breached:
                logger.debug(f"Signal | {symbol}: skipping entry — RiskProfile ceiling breached")
                cycle_signals.append({
                    "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                    "price": round(current_price, 4), "signal_type": "skip_ceiling_breach",
                    "has_position": False,
                })
                continue

            # ── Kraken API penalty throttle ───────────────────────────────────
            # When the leaky-bucket penalty counter exceeds 80% of the ceiling
            # (12/15 points), the bot enters read-only polling mode and skips
            # all new entries until the bucket recovers.
            if _penalty_tracker.is_throttled():
                logger.info(
                    f"Signal | {symbol}: skipping entry — Kraken API penalty throttled "
                    f"({_penalty_tracker.current_points():.1f}/{_penalty_tracker.MAX_POINTS} pts, "
                    f"capacity {_penalty_tracker.remaining_capacity():.0f}%)"
                )
                cycle_signals.append({
                    "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                    "price": round(current_price, 4), "signal_type": "skip_penalty_throttle",
                    "has_position": False,
                })
                continue

            # ── Dynamic VPIN Gate (Stages 3 & 3.5) ─────────────────────────────
            # 1. Dynamic cap: raise threshold from 0.65→0.82 when volume surges
            # 2. Decay: reduce effective VPIN after 4 consecutive blocks + stabilizing vol
            # 3. Deep Oversold bypass: RSI<20 → ignore VPIN for micro-lot (1% equity)
            _vol_hist = _volume_history.get(symbol, deque())
            _vol_hist_list = list(_vol_hist)
            _vol_mean_24h = (sum(_vol_hist_list[-24:]) if len(_vol_hist_list) >= 24
                            else (sum(_vol_hist_list) if _vol_hist_list else 0.0))
            _trailing_mean = (sum(_vol_hist_list) / len(_vol_hist_list)
                             if len(_vol_hist_list) >= 5 else 0.0)
            _trailing_mean_24h = _trailing_mean * min(len(_vol_hist_list), 24)
            _volume_surge = (_trailing_mean_24h > 0
                            and _vol_24h_sum >= _trailing_mean_24h * VOLUME_SURGE_RATIO)
            _effective_vpin_cap = VPIN_ELEVATED_CAP if _volume_surge else VPIN_ENTRY_BLOCK

            _effective_vpin = _vpin_decay.update(
                symbol=symbol,
                vpin=_ms.vpin,
                threshold=_effective_vpin_cap,
                atr=sym_atr,
            )
            _decay_count = _vpin_decay.get_count(symbol)

            _deep_oversold = sym_rsi < DEEP_OVERSOLD_RSI

            if _effective_vpin > _effective_vpin_cap and not _deep_oversold:
                _decay_note = ""
                if _decay_count > VPIN_DECAY_AFTER_CYCLES:
                    _decay_note = (
                        f" (decay active: cycle {_decay_count}, "
                        f"raw={_ms.vpin:.3f}→eff={_effective_vpin:.3f})"
                    )
                logger.info(
                    f"Signal | {symbol}: skipping entry — VPIN={_effective_vpin:.3f} > "
                    f"{_effective_vpin_cap:.2f} "
                    f"(defensive state — toxic/institutional flow detected)"
                    f"{_decay_note}"
                )
                cycle_signals.append({
                    "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                    "price": round(current_price, 4), "signal_type": "skip_vpin_defensive",
                    "has_position": False,
                    "vpin_cap": round(_effective_vpin_cap, 2),
                    "vpin_effective": round(_effective_vpin, 3),
                    "vpin_decay_cycles": _decay_count,
                })
                continue

            if _deep_oversold and _ms.vpin > _effective_vpin_cap:
                _vpin_decay.reset(symbol)
                logger.info(
                    f"Signal | {symbol}: VPIN bypass — RSI={sym_rsi:.1f} < {DEEP_OVERSOLD_RSI} "
                    f"(Deep Oversold) | VPIN={_ms.vpin:.3f} ignored for micro-lot entry"
                )

            if _effective_vpin <= _effective_vpin_cap and _ms.vpin > VPIN_ENTRY_BLOCK:
                _reason = "volume_surge" if _volume_surge else "decay"
                logger.info(
                    f"Signal | {symbol}: VPIN gate relaxed ({_reason}) — "
                    f"raw VPIN={_ms.vpin:.3f}, effective={_effective_vpin:.3f}, "
                    f"cap={_effective_vpin_cap:.2f}"
                )

            # ── Bear Regime LONG Filter + Contrarian Scout (Stage 3) ──────────
            # In a confirmed Bear or RISK-OFF regime, all new LONG signals are
            # normally blocked (SHORT-only mode). EXCEPTION: if RSI is extremely
            # low (< CONTRARIAN_RSI_THRESH), the bot opens a small 3% "scout"
            # position as an insurance play against missing the bottom.
            # The scout only requires RSI < 25 — no z-score/RSI_OVERSOLD gate.
            if _is_bear:
                if sym_rsi < CONTRARIAN_RSI_THRESH:
                    _scout_size = total_equity * CONTRARIAN_EQUITY_PCT
                    if _deep_oversold:
                        _scout_size = total_equity * MICRO_LOT_EQUITY_PCT
                        logger.info(
                            f"ContrScout | {symbol}: DEEP OVERSOLD micro-lot — "
                            f"RSI={sym_rsi:.1f} < {DEEP_OVERSOLD_RSI} | Bear regime "
                            f"VPIN={_ms.vpin:.3f} | micro-lot ${_scout_size:,.2f} (1% equity)"
                        )
                    else:
                        logger.info(
                            f"ContrScout | {symbol}: Contrarian scout entry — "
                            f"RSI={sym_rsi:.1f} < {CONTRARIAN_RSI_THRESH} | Bear regime "
                            f"'{_regime_label}' | scout ${_scout_size:,.2f} (3% equity)"
                        )
                    _atr_stop = get_atr_stop_price("long", current_price, sym_atr, multiplier=ATR_STOP_MULTIPLIER)
                    if open_position(symbol, "long", _scout_size, current_price):
                        deployed_usd += _scout_size
                        if symbol in open_positions:
                            open_positions[symbol]["atr_stop_price"] = _atr_stop
                            open_positions[symbol]["vol_tier"] = "contrarian_scout"
                            open_positions[symbol]["tranches_filled"] = 1
                        cycle_signals.append({
                            "symbol": symbol, "rsi": round(sym_rsi, 1),
                            "z_score": round(sym_z_score, 3),
                            "price": round(current_price, 4),
                            "signal_type": "contrarian_scout_entered",
                            "has_position": True, "size_usd": round(_scout_size, 2),
                            "vol_tier": "contrarian_scout",
                        })
                    else:
                        cycle_signals.append({
                            "symbol": symbol, "rsi": round(sym_rsi, 1),
                            "z_score": round(sym_z_score, 3),
                            "price": round(current_price, 4),
                            "signal_type": "contrarian_scout_signal",
                            "has_position": False,
                        })
                    continue

                if sym_z_score < -_zscore_entry and sym_rsi < RSI_OVERSOLD:
                    logger.info(
                        f"BearRegimeFilter | LONG {symbol} BLOCKED — regime='{_regime_label}' "
                        f"RSI={sym_rsi:.1f} Z={sym_z_score:.2f} | "
                        f"Capital preserved (SHORT-only mode active)"
                    )
                    cycle_signals.append({
                        "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                        "price": round(current_price, 4), "signal_type": "long_blocked_bear_regime",
                        "has_position": False,
                        "regime": _regime_label,
                    })
                    continue

            # LONG signal: price is unusually low + RSI is oversold
            if sym_z_score < -_zscore_entry and sym_rsi < RSI_OVERSOLD:
                size_usd, _vol_tier, _eff_stop = get_position_size(
                    total_equity=total_equity,
                    entry_price=current_price,
                    deployed_usd=deployed_usd,
                    risk_fraction=RISK_FRACTION,
                    stop_loss_pct=_stop_loss_pct,
                    max_position_fraction=_effective_max_position_frac,
                    cash_reserve=CASH_RESERVE,
                    atr=sym_atr,
                    atr_multiplier=ATR_STOP_MULTIPLIER,
                )
                if _deep_oversold and _ms.vpin > _effective_vpin_cap:
                    size_usd = min(size_usd, total_equity * MICRO_LOT_EQUITY_PCT)
                    _vol_tier = "micro_lot_vpin_bypass"
                if size_usd >= 10.0:
                    _ms_vpin_override = 9.99 if _deep_oversold else _effective_vpin_cap
                    _ms_allowed, _ms_reason = _ms.entry_filter(
                        side="long", vpin_block=_ms_vpin_override,
                    )
                    if not _ms_allowed:
                        logger.info(
                            f"Signal | LONG {symbol} blocked by microstructure: {_ms_reason} "
                            f"| OFI={_ms.ofi:+.3f} VPIN={_ms.vpin:.3f}"
                        )
                        cycle_signals.append({
                            "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                            "price": round(current_price, 4), "signal_type": "long_blocked_microstructure",
                            "has_position": False,
                        })
                        continue  # skip this entry
                    # ATR-derived stop price and T1 tranche size (= size_usd)
                    _atr_stop  = get_atr_stop_price("long", current_price, sym_atr, multiplier=ATR_STOP_MULTIPLIER)
                    _tranches  = build_tranche_orders("long", current_price, size_usd, sym_atr)
                    _t1_size   = _tranches[0]["size_usd"] if _tranches else size_usd
                    # ExitBracket: log expected exit levels (audit only).
                    # Existing check_stops() logic is the source of truth.
                    _bracket = ExitBracket(
                        entry_price=current_price,
                        direction="long",
                        stop_loss_pct=_stop_loss_pct,
                        take_profit_pct=_stop_loss_pct * 2,
                        trail_pct=_trail_pct,
                    )
                    _sl, _tp, _trail = _bracket.compute()
                    logger.info(
                        f"Signal | LONG  {symbol} | RSI={sym_rsi:.1f} (oversold<{RSI_OVERSOLD}) | "
                        f"Z={sym_z_score:.2f} (dip>{_zscore_entry}) | T1: ${_t1_size:,.2f} "
                        f"[{_vol_tier}] | ATR stop: ${_atr_stop:,.4f} | "
                        f"OFI={_ms.ofi:+.3f} VPIN={_ms.vpin:.3f} | "
                        f"Exit bracket → SL=${_sl:.4f} Trail@${_trail:.4f}"
                    )
                    if open_position(symbol, "long", _t1_size, current_price):
                        deployed_usd += _t1_size
                        # Store ATR stop price in the position for check_stops()
                        if symbol in open_positions:
                            open_positions[symbol]["atr_stop_price"]    = _atr_stop
                            open_positions[symbol]["vol_tier"]          = _vol_tier
                            open_positions[symbol]["tranches_filled"]   = 1
                        # Register pending T2/T3 tranches (skip T1, already filled)
                        _remaining = [t for t in _tranches if t["tranche"] > 1]
                        if _remaining:
                            _pending_tranches[symbol] = _remaining
                            _persist_tranches()
                            logger.info(
                                f"Tranches | {symbol}: {len(_remaining)} pending "
                                f"tranche(s) queued after T1 fill"
                            )
                        cycle_signals.append({
                            "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                            "price": round(current_price, 4), "signal_type": "long_entered",
                            "has_position": True, "size_usd": round(_t1_size, 2),
                            "vol_tier": _vol_tier,
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
            elif sym_z_score > _zscore_entry and sym_rsi > RSI_OVERBOUGHT:
                size_usd, _vol_tier, _eff_stop = get_position_size(
                    total_equity=total_equity,
                    entry_price=current_price,
                    deployed_usd=deployed_usd,
                    risk_fraction=RISK_FRACTION,
                    stop_loss_pct=_stop_loss_pct,
                    max_position_fraction=_effective_max_position_frac,
                    cash_reserve=CASH_RESERVE,
                    atr=sym_atr,
                    atr_multiplier=ATR_STOP_MULTIPLIER,
                )
                if size_usd >= 10.0:
                    # ── Microstructure entry filter (short) ───────────────────
                    _ms_allowed, _ms_reason = _ms.entry_filter(side="short")
                    if not _ms_allowed:
                        logger.info(
                            f"Signal | SHORT {symbol} blocked by microstructure: {_ms_reason} "
                            f"| OFI={_ms.ofi:+.3f} VPIN={_ms.vpin:.3f}"
                        )
                        cycle_signals.append({
                            "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                            "price": round(current_price, 4), "signal_type": "short_blocked_microstructure",
                            "has_position": False,
                        })
                        continue  # skip this entry
                    # ATR-derived stop price and T1 tranche size
                    _atr_stop  = get_atr_stop_price("short", current_price, sym_atr, multiplier=ATR_STOP_MULTIPLIER)
                    _tranches  = build_tranche_orders("short", current_price, size_usd, sym_atr)
                    _t1_size   = _tranches[0]["size_usd"] if _tranches else size_usd
                    # ExitBracket: log expected exit levels (audit only).
                    # Existing check_stops() logic is the source of truth.
                    _bracket = ExitBracket(
                        entry_price=current_price,
                        direction="short",
                        stop_loss_pct=_stop_loss_pct,
                        take_profit_pct=_stop_loss_pct * 2,
                        trail_pct=_trail_pct,
                    )
                    _sl, _tp, _trail = _bracket.compute()
                    logger.info(
                        f"Signal | SHORT {symbol} | RSI={sym_rsi:.1f} (overbought>{RSI_OVERBOUGHT}) | "
                        f"Z={sym_z_score:.2f} (peak>{_zscore_entry}) | T1: ${_t1_size:,.2f} "
                        f"[{_vol_tier}] | ATR stop: ${_atr_stop:,.4f} | "
                        f"OFI={_ms.ofi:+.3f} VPIN={_ms.vpin:.3f} | "
                        f"Exit bracket → SL=${_sl:.4f} Trail@${_trail:.4f}"
                    )
                    if open_position(symbol, "short", _t1_size, current_price):
                        deployed_usd += _t1_size
                        # Store ATR stop price in the position for check_stops()
                        if symbol in open_positions:
                            open_positions[symbol]["atr_stop_price"]    = _atr_stop
                            open_positions[symbol]["vol_tier"]          = _vol_tier
                            open_positions[symbol]["tranches_filled"]   = 1
                        # Register pending T2/T3 tranches (skip T1, already filled)
                        _remaining = [t for t in _tranches if t["tranche"] > 1]
                        if _remaining:
                            _pending_tranches[symbol] = _remaining
                            _persist_tranches()
                            logger.info(
                                f"Tranches | {symbol}: {len(_remaining)} pending "
                                f"tranche(s) queued after T1 fill"
                            )
                        cycle_signals.append({
                            "symbol": symbol, "rsi": round(sym_rsi, 1), "z_score": round(sym_z_score, 3),
                            "price": round(current_price, 4), "signal_type": "short_entered",
                            "has_position": True, "size_usd": round(_t1_size, 2),
                            "vol_tier": _vol_tier,
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
    latest_microstructure = cycle_microstructure

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
            f"{h.get('pnl_pct', 0):+.2f}% (need {_min_net_profit_pct*100:.1f}%) "
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

    if IS_PRIMARY_FETCHER and _ohlcv_cache_data:
        _write_market_cache({"_cache_ts": time.time(), "ohlcv": _ohlcv_cache_data})

    # ── Step 5: Write status for the dashboard ────────────────────────────────
    write_status()
    write_live_state()
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

def _keepalive_loop() -> None:
    """
    Background daemon thread — writes a DB heartbeat every 2 minutes.

    Purpose: prevents the bot from appearing stale if the main trading cycle
    takes longer than expected (e.g., slow Kraken API, rate-limit backoff,
    or Replit container slowdown).  This thread runs independently of the
    main cycle and guarantees the `kraken_heartbeat.last_updated` column is
    refreshed at most 2 minutes behind real-time, well within the 30-minute
    auto-heal threshold.
    """
    while not getattr(_keepalive_loop, "_stop", False):
        try:
            write_status()
        except Exception as exc:
            logger.debug(f"Keepalive | heartbeat write failed: {exc}")
        time.sleep(120)  # 2-minute interval


def _start_health_server() -> None:
    """Start a minimal HTTP health-check server on $PORT (if set).

    The artifact system expects every service to open its assigned port.
    This lightweight server satisfies that requirement without interfering
    with the bot's trading loop.
    """
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler

    _port = int(os.environ.get("PORT", "0"))
    if not _port:
        return

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "running", "service": "kraken-bot", "bot_id": BOT_ID}).encode())

        def log_message(self, fmt, *args):
            pass

    def _serve():
        srv = HTTPServer(("0.0.0.0", _port), _Handler)
        srv.serve_forever()

    t = threading.Thread(target=_serve, name="health-http", daemon=True)
    t.start()
    logger.info(f"Bot | Health-check server listening on :{_port}")


def main() -> None:
    """
    The outer execution loop. This is what runs 24/7.

    OUTER loop (try/except) — catches fatal errors, sleeps 30s, then restarts
      INNER loop (while True) — runs trading cycles every 60 seconds
        ├── refresh_equity()
        ├── check circuit breaker
        ├── for each symbol: evaluate signals / manage positions
        └── write_status()

    Background keepalive thread writes a heartbeat every 2 min independently
    so the health monitor never sees the bot as stale, even during slow cycles.
    """
    import threading
    global total_equity

    _start_health_server()

    write_status()
    logger.info("Bot | Startup heartbeat written to DB")

    # ── Restore pending tranches from DB ──────────────────────────────────────
    restored = _db.load_pending_tranches()
    if restored:
        current_positions = get_paper_positions() if PAPER_TRADING else open_positions
        pruned_count = 0
        for sym in list(restored.keys()):
            if sym not in current_positions:
                del restored[sym]
                pruned_count += 1
        _pending_tranches.update(restored)
        total_t = sum(len(v) for v in _pending_tranches.values())
        logger.info(
            f"Tranches | Restored {total_t} pending tranche(s) for "
            f"{len(_pending_tranches)} position(s) from DB"
            + (f" (pruned {pruned_count} stale symbol(s))" if pruned_count else "")
        )
        if pruned_count:
            _persist_tranches()
    else:
        logger.debug("Tranches | No pending tranches to restore from DB")

    # ── Background keepalive thread — prevents false-stale alerts ─────────────
    _keepalive = threading.Thread(target=_keepalive_loop, name="keepalive", daemon=True)
    _keepalive.start()
    logger.info("Bot | Keepalive thread started (2-min DB heartbeat, independent of cycle)")

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
            _keepalive_loop._stop = True
            write_status(error="Manually stopped")
            write_live_state()
            break

        except Exception as exc:
            logger.error(f"Bot | Unexpected error: {exc} — restarting in {RESTART_SLEEP_SECONDS}s")
            write_status(error=str(exc))
            write_live_state()
            time.sleep(RESTART_SLEEP_SECONDS)


# ── Script entry point ────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
