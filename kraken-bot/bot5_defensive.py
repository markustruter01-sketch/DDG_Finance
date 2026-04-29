"""
bot5_defensive.py — Defensive Allocation Bot (Bot #5)

Strategy: Risk-off positioning. Allocates to defensive ETFs based on
          SPY 200-day EMA position and VIX level. Holds cash when risk-on.

STRICT RULE: This is NOT a volatility harvester. NEVER trades VXX, UVXY,
SVXY, TVIX, or VIXM under ANY circumstances. The decay characteristics
of leveraged volatility products make them unsuitable for this strategy.

Universe:  XLP (consumer staples), XLU (utilities), TLT (long bonds), GLD (gold)
BLACKLIST: VXX, UVXY, SVXY, TVIX, VIXM — hardcoded, never tradeable here

Regime rules:
  Risk-on:   SPY > 200d EMA  AND  VIX < 20       → 100% cash
  Moderate:  SPY > 200d EMA  AND  VIX 20–25       → 25% TLT, 75% cash
  Risk-off:  SPY < 200d EMA  OR   VIX > 25        → 30% XLP, 30% TLT, 20% GLD, 20% cash
  Crisis:    SPY < 200d EMA  AND  VIX > 30        → 40% TLT, 30% GLD, 30% cash

Hold: Minimum 14 trading days in risk-off / crisis mode (XLP/TLT/GLD positions).
      Positions closed when regime moves to risk-on after min_hold elapsed.

BOT_ID:  bot5_defensive
DB row:  kraken_heartbeat id=4  (was Apex Predator — replaces it)

ACTIVATION (Week 5):
  Before flipping BOT_PAUSED=False in config.py, run:
    UPDATE kraken_heartbeat
    SET bot_id = 'bot5_defensive', bot_display_name = 'Defensive Guardian'
    WHERE id = 4;
  Then set BOT_PAUSED = False in BOT_PROFILES['bot5_defensive'].

Uses AlpacaEtfEngine (shared) — no LLM.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from alpaca_etf_engine import (
    AlpacaEtfEngine,
    calculate_ema,
    calculate_atr,
    _yahoo_daily_ohlcv,
)

logger = logging.getLogger("bot5.defensive")

# ── Constants ─────────────────────────────────────────────────────────────────

UNIVERSE     = ["XLP", "XLU", "TLT", "GLD"]
NEVER_TRADE  = {"VXX", "UVXY", "SVXY", "TVIX", "VIXM"}  # absolute blacklist

MIN_HOLD_DAYS   = 14
TRAIL_STOP_PCT  = 0.08   # 8% trailing stop on all positions

BOT_ID = "bot5_defensive"

# Regime type alias
Regime = Literal["risk_on", "moderate", "risk_off", "crisis"]

# Target allocations per regime (symbol → fraction of equity)
ALLOCATIONS: dict[Regime, dict[str, float]] = {
    "risk_on":  {},                                           # 100% cash
    "moderate": {"TLT": 0.25},                               # 25% TLT, 75% cash
    "risk_off": {"XLP": 0.30, "TLT": 0.30, "GLD": 0.20},   # 20% cash
    "crisis":   {"TLT": 0.40, "GLD": 0.30},                  # 30% cash
}

# TP targets for tiered scale-out (less aggressive — this is a defensive bot)
TP1_PCT = 0.05
TP2_PCT = 0.10


# ── Regime detection ──────────────────────────────────────────────────────────

def _detect_regime() -> tuple[Regime, dict]:
    """
    Determine current market regime from SPY EMA-200 position and VIX level.

    Returns (regime, context_dict).
    Context includes spy_price, spy_ema200, vix_current for logging.
    """
    spy_ohlcv = _yahoo_daily_ohlcv("SPY", days=250)
    vix_ohlcv = _yahoo_daily_ohlcv("^VIX", days=10)

    # Fallback — if data unavailable, stay defensive (risk_off)
    if not spy_ohlcv or len(spy_ohlcv["closes"]) < 200:
        logger.warning("Bot5 | SPY data unavailable — defaulting to risk_off")
        return "risk_off", {"error": "spy_data_unavailable"}

    spy_closes  = spy_ohlcv["closes"]
    spy_current = spy_closes[-1]
    spy_ema200  = calculate_ema(spy_closes, 200)

    vix_current = 0.0
    if vix_ohlcv and len(vix_ohlcv["closes"]) >= 1:
        vix_current = vix_ohlcv["closes"][-1]
    else:
        logger.warning("Bot5 | VIX data unavailable — treating VIX as 25 (conservative)")
        vix_current = 25.0

    spy_above_ema200 = spy_current > (spy_ema200 or spy_current)

    logger.info(
        f"Bot5 | Regime check — "
        f"SPY={spy_current:.2f} EMA200={f'{spy_ema200:.2f}' if spy_ema200 else 'N/A'} "
        f"spy_above_ema200={spy_above_ema200} VIX={vix_current:.2f}"
    )

    ctx = {
        "spy_price":   round(spy_current, 2),
        "spy_ema200":  round(spy_ema200, 2) if spy_ema200 else None,
        "vix":         round(vix_current, 2),
        "spy_above_ema200": spy_above_ema200,
    }

    # Crisis: SPY below EMA-200 AND VIX > 30
    if not spy_above_ema200 and vix_current > 30:
        regime: Regime = "crisis"

    # Risk-off: SPY below EMA-200 OR VIX > 25
    elif not spy_above_ema200 or vix_current > 25:
        regime = "risk_off"

    # Moderate: SPY above EMA-200 but VIX 20-25 (caution zone)
    elif spy_above_ema200 and 20 <= vix_current <= 25:
        regime = "moderate"

    # Risk-on: SPY above EMA-200 AND VIX < 20 (clear skies)
    else:
        regime = "risk_on"

    logger.info(f"Bot5 | Regime detected: {regime.upper()}")
    return regime, ctx


# ── Main cycle ────────────────────────────────────────────────────────────────

def run_bot5_cycle(profile: dict, db_id: int) -> None:
    """
    Main defensive allocation cycle. Called from main.py when BOT_ID=bot5_defensive.
    Detects regime every cycle. Entry/exit decisions follow the regime allocation table.

    Safety: Enforces NEVER_TRADE blacklist at both the strategy and order level.
    """
    # Pause guard — always first
    if profile.get("BOT_PAUSED", True):
        logger.info("Bot5 | BOT_PAUSED=True — skipping cycle (not yet activated)")
        return

    # Belt-and-suspenders: validate no blacklisted symbol was somehow configured
    for sym in NEVER_TRADE:
        if sym in UNIVERSE:
            logger.critical(
                f"Bot5 | BLACKLIST VIOLATION: {sym} is in UNIVERSE — "
                f"refusing to run. Fix bot5_defensive.py immediately."
            )
            return

    logger.info(
        f"Bot5 | === DEFENSIVE ALLOCATION CYCLE — "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} ==="
    )

    # Connect to Alpaca
    try:
        engine = AlpacaEtfEngine(
            api_key=profile.get("ALPACA_API_KEY", ""),
            secret_key=profile.get("ALPACA_SECRET_KEY", ""),
            base_url=profile.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
        )
    except Exception as exc:
        logger.error(f"Bot5 | Alpaca connection failed: {exc}")
        return

    account = engine.get_account()
    equity  = account["equity"]
    logger.info(
        f"Bot5 | Equity=${equity:,.2f} cash=${account['cash']:,.2f}"
    )

    # Detect current regime
    regime, regime_ctx = _detect_regime()
    target_allocation  = ALLOCATIONS[regime]

    logger.info(
        f"Bot5 | Regime={regime.upper()} — "
        f"target: {target_allocation if target_allocation else 'CASH (no positions)'}"
    )

    live_positions = engine.get_positions()
    db_positions   = engine.get_db_positions(BOT_ID)
    held_symbols   = {p["symbol"] for p in live_positions}

    # ── Exit checks — run every cycle ─────────────────────────────────────────

    for db_pos in db_positions:
        symbol = db_pos["symbol"]

        # Double-check: never let a blacklisted symbol execute even if in DB
        if symbol in NEVER_TRADE:
            logger.critical(f"Bot5 | BLACKLIST: closing {symbol} immediately (should never happen)")
            engine.close_position(symbol)
            engine.record_close(BOT_ID, symbol, "blacklist_emergency_close", None)
            live_positions = engine.get_positions()
            held_symbols   = {p["symbol"] for p in live_positions}
            continue

        # Trailing stop (engine handles, always on)
        exit_reason = engine.run_exit_checks(
            bot_id=BOT_ID,
            db_position=db_pos,
            live_positions=live_positions,
            trail_pct=TRAIL_STOP_PCT,
        )
        if exit_reason:
            logger.info(f"Bot5 | EXIT {symbol}: {exit_reason}")
            live = next((p for p in live_positions if p["symbol"] == symbol), None)
            realised_pnl = live["unrealised_pnl_usd"] if live else None
            engine.close_position(symbol)
            engine.record_close(BOT_ID, symbol, exit_reason, realised_pnl)
            live_positions = engine.get_positions()
            held_symbols   = {p["symbol"] for p in live_positions}
            continue

        # Regime-based exit: if symbol not in target allocation and min_hold elapsed
        if symbol not in target_allocation and engine.check_min_hold(db_pos):
            reason = f"regime_change_{regime} (no allocation for {symbol})"
            logger.info(f"Bot5 | REGIME EXIT {symbol}: {reason}")
            live = next((p for p in live_positions if p["symbol"] == symbol), None)
            realised_pnl = live["unrealised_pnl_usd"] if live else None
            engine.close_position(symbol)
            engine.record_close(BOT_ID, symbol, reason, realised_pnl)
            live_positions = engine.get_positions()
            held_symbols   = {p["symbol"] for p in live_positions}

    # ── Entry scan — regime-driven ────────────────────────────────────────────

    if not target_allocation:
        logger.info(f"Bot5 | {regime.upper()} — staying in cash, no new positions")
        engine.update_heartbeat(db_id, equity, len(engine.get_positions()))
        return

    live_positions = engine.get_positions()
    held_symbols   = {p["symbol"] for p in live_positions}

    for symbol, alloc_pct in target_allocation.items():

        # Hard blacklist check on every entry attempt
        if symbol in NEVER_TRADE:
            logger.critical(f"Bot5 | BLACKLIST violation attempt: {symbol} — skipping")
            continue

        if symbol in held_symbols:
            logger.info(f"Bot5 | {symbol}: already holding at {alloc_pct*100:.0f}% — skip")
            continue

        ohlcv = _yahoo_daily_ohlcv(symbol, days=30)
        if not ohlcv or not ohlcv["closes"]:
            logger.warning(f"Bot5 | {symbol}: no price data — skipping entry")
            continue

        closes      = ohlcv["closes"]
        entry_price = closes[-1]
        atr         = calculate_atr(ohlcv["highs"], ohlcv["lows"], closes, period=14)
        notional    = equity * alloc_pct
        stop_price  = entry_price * (1 - TRAIL_STOP_PCT)
        tp1_price   = entry_price * (1 + TP1_PCT)
        tp2_price   = entry_price * (1 + TP2_PCT)
        qty_approx  = notional / entry_price

        logger.info(
            f"Bot5 | ENTRY {symbol} LONG [{regime.upper()}] "
            f"alloc={alloc_pct*100:.0f}% notional=${notional:,.0f} "
            f"entry~{entry_price:.2f} stop={stop_price:.2f} "
            f"spy_ema_ok={regime_ctx.get('spy_above_ema200')} "
            f"vix={regime_ctx.get('vix')} min_hold={MIN_HOLD_DAYS}d"
        )

        order = engine.place_order(symbol, "buy", notional)
        if order:
            engine.record_open(
                bot_id=BOT_ID,
                symbol=symbol,
                direction="long",
                qty=qty_approx,
                entry_price=entry_price,
                entry_atr=atr,
                notional_usd=notional,
                stop_price=stop_price,
                tp1_price=tp1_price,
                tp2_price=tp2_price,
                min_hold_days=MIN_HOLD_DAYS,
            )
            held_symbols.add(symbol)
            live_positions = engine.get_positions()

    # ── Heartbeat ─────────────────────────────────────────────────────────────
    live_positions = engine.get_positions()
    engine.update_heartbeat(db_id, equity, len(live_positions))
    logger.info(
        f"Bot5 | Cycle complete — regime={regime.upper()} "
        f"equity=${equity:,.2f} positions={len(live_positions)}"
    )
