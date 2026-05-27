"""
bot2_spy_qqq.py — SPY/QQQ Trend Follower (Bot #2)

Strategy: Long-only trend following on SPY and QQQ.

Entry:  Both EMA-50 and EMA-200 sloping upward AND price above EMA-50.
Exit:   Price closes below EMA-50  OR  8% trailing stop  OR
        5% drop in any 3-day rolling window.
Hold:   Minimum 5 trading days (locked by min_hold_until in DB).
Sizing: 40% equity per position when trend confirmed (max 80% deployed,
        20% cash reserve always maintained).
Cycle:  Once daily at ~4:30 PM ET (after market close) — triggered by
        main.py LOOP_SLEEP_SECONDS + caller schedule.

BOT_ID:  bot2_spy_qqq
DB row:  kraken_heartbeat id=1  (was Davy Jones — replaces it)

ACTIVATION (Week 2):
  Before flipping BOT_PAUSED=False in config.py, run:
    UPDATE kraken_heartbeat
    SET bot_id = 'bot2_spy_qqq', bot_display_name = 'SPY/QQQ Trend'
    WHERE id = 1;
  Then set BOT_PAUSED = False in BOT_PROFILES['bot2_spy_qqq'].

Uses AlpacaEtfEngine (shared) — no LLM.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from alpaca_etf_engine import (
    AlpacaEtfEngine,
    calculate_ema,
    calculate_atr,
    _yahoo_daily_ohlcv,
)

logger = logging.getLogger("bot2.spy_qqq")

# ── Constants ─────────────────────────────────────────────────────────────────

UNIVERSE         = ["SPY", "QQQ"]
EMA_FAST         = 50
EMA_SLOW         = 200
TRAIL_STOP_PCT   = 0.08
MAX_3DAY_DROP_PCT = 0.05
POSITION_SIZE_PCT = 0.40
MIN_HOLD_DAYS    = 5
MAX_DEPLOYMENT   = 0.80   # never deploy more than 80% of equity
CASH_RESERVE     = 0.20   # minimum 20% cash always

BOT_ID           = "bot2_spy_qqq"

# TP targets for tiered scale-out (from entry price)
TP1_PCT          = 0.06   # +6% → scale 33%
TP2_PCT          = 0.12   # +12% → scale another 33%


# ── Entry rules ───────────────────────────────────────────────────────────────

def _should_enter(symbol: str) -> tuple[bool, dict]:
    """
    Entry criteria:
      1. EMA-50 > EMA-200 (fast above slow = uptrend)
      2. EMA-50 itself is sloping up (today > 5 bars ago)
      3. Latest close > EMA-50

    Returns (should_enter: bool, context: dict with prices for sizing).
    """
    ohlcv = _yahoo_daily_ohlcv(symbol, days=250)
    if not ohlcv or len(ohlcv["closes"]) < EMA_SLOW + 5:
        logger.warning(f"Bot2 | {symbol}: insufficient OHLCV data for trend check")
        return False, {}

    closes = ohlcv["closes"]
    highs  = ohlcv["highs"]
    lows   = ohlcv["lows"]
    current = closes[-1]

    ema_fast_now  = calculate_ema(closes, EMA_FAST)
    ema_slow_now  = calculate_ema(closes, EMA_SLOW)
    ema_fast_prev = calculate_ema(closes[:-5], EMA_FAST)   # 5 bars ago
    atr = calculate_atr(highs, lows, closes, period=14)

    if any(v is None for v in (ema_fast_now, ema_slow_now, ema_fast_prev, atr)):
        logger.warning(f"Bot2 | {symbol}: indicator calculation failed")
        return False, {}

    # Conditions
    fast_above_slow  = ema_fast_now > ema_slow_now
    fast_sloping_up  = ema_fast_now > ema_fast_prev
    price_above_fast = current > ema_fast_now

    logger.info(
        f"Bot2 | {symbol} entry check — "
        f"price={current:.2f} EMA50={ema_fast_now:.2f} EMA200={ema_slow_now:.2f} "
        f"fast_above_slow={fast_above_slow} fast_up={fast_sloping_up} "
        f"price_above_fast={price_above_fast}"
    )

    if fast_above_slow and fast_sloping_up and price_above_fast:
        return True, {
            "current_price": current,
            "ema_fast":      ema_fast_now,
            "ema_slow":      ema_slow_now,
            "atr":           atr,
        }
    return False, {}


# ── Exit rules ────────────────────────────────────────────────────────────────

def _should_exit_trend(symbol: str, ema_fast_value: float) -> tuple[bool, str]:
    """
    Trend-based exit: price closes below EMA-50 OR 5% drop in any 3-day window.
    Trailing stop is handled by AlpacaEtfEngine.run_exit_checks().
    """
    ohlcv = _yahoo_daily_ohlcv(symbol, days=10)
    if not ohlcv or len(ohlcv["closes"]) < 4:
        return False, ""

    closes  = ohlcv["closes"]
    current = closes[-1]

    # Exit 1: price below EMA-50
    ema_fast_now = calculate_ema(closes[-EMA_FAST:] if len(closes) >= EMA_FAST else closes, EMA_FAST)
    if ema_fast_now and current < ema_fast_now:
        return True, f"price_below_ema50 (price={current:.2f} ema50={ema_fast_now:.2f})"

    # Exit 2: 5% drop in any 3-day window
    for i in range(len(closes) - 3, len(closes)):
        if i < 1:
            continue
        start = closes[i - 1]
        end   = closes[i]
        if start > 0 and (start - end) / start >= MAX_3DAY_DROP_PCT:
            return True, f"3day_drop_{((start-end)/start*100):.1f}%"

    return False, ""


# ── Main cycle ────────────────────────────────────────────────────────────────

def run_bot2_cycle(profile: dict, db_id: int) -> None:
    """
    Main SPY/QQQ trend cycle. Called from main.py when BOT_ID=bot2_spy_qqq.
    Runs once after market close (cycle timing managed by main.py sleep).
    """
    # Pause guard — always first
    if profile.get("BOT_PAUSED", False):
        logger.info(f"Bot2 | BOT_PAUSED=True — skipping cycle (not yet activated)")
        return

    logger.info(f"Bot2 | === SPY/QQQ TREND CYCLE — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} ===")

    # Connect to Alpaca
    try:
        engine = AlpacaEtfEngine(
            api_key=profile.get("ALPACA_API_KEY", ""),
            secret_key=profile.get("ALPACA_SECRET_KEY", ""),
            base_url=profile.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
        )
    except Exception as exc:
        logger.error(f"Bot2 | Alpaca connection failed: {exc}")
        return

    account = engine.get_account()
    equity  = account["equity"]
    logger.info(
        f"Bot2 | Equity=${equity:,.2f} cash=${account['cash']:,.2f} "
        f"buying_power=${account['buying_power']:,.2f}"
    )

    # Market open check — this bot only acts after market closes (4:30 PM ET)
    # We allow running regardless of market open status — exits need to go through
    # regardless (Alpaca queues orders for next open if market is closed)
    live_positions = engine.get_positions()
    db_positions   = engine.get_db_positions(BOT_ID)

    logger.info(
        f"Bot2 | Positions: {len(live_positions)} live, {len(db_positions)} in DB"
    )

    # ── Exit checks ───────────────────────────────────────────────────────────
    for db_pos in db_positions:
        symbol = db_pos["symbol"]

        # 1. Engine handles trailing stop + TP scale-outs
        exit_reason = engine.run_exit_checks(
            bot_id=BOT_ID,
            db_position=db_pos,
            live_positions=live_positions,
            trail_pct=TRAIL_STOP_PCT,
        )
        if exit_reason:
            logger.info(f"Bot2 | EXIT {symbol}: {exit_reason}")
            live = next((p for p in live_positions if p["symbol"] == symbol), None)
            realised_pnl = live["unrealised_pnl_usd"] if live else None
            engine.close_position(symbol)
            engine.record_close(BOT_ID, symbol, exit_reason, realised_pnl)
            live_positions = engine.get_positions()
            continue

        # 2. Trend-based exit (after min-hold check)
        if engine.check_min_hold(db_pos):
            ema_fast = float(db_pos.get("entry_price", 0)) * 0.95  # fallback
            trend_exit, trend_reason = _should_exit_trend(symbol, ema_fast)
            if trend_exit:
                logger.info(f"Bot2 | TREND EXIT {symbol}: {trend_reason}")
                live = next((p for p in live_positions if p["symbol"] == symbol), None)
                realised_pnl = live["unrealised_pnl_usd"] if live else None
                engine.close_position(symbol)
                engine.record_close(BOT_ID, symbol, trend_reason, realised_pnl)
                live_positions = engine.get_positions()

    # ── Entry scan ────────────────────────────────────────────────────────────
    live_positions = engine.get_positions()
    deployed_usd   = sum(p["market_value"] for p in live_positions)
    deployed_pct   = deployed_usd / equity if equity > 0 else 1.0
    held_symbols   = {p["symbol"] for p in live_positions}

    logger.info(
        f"Bot2 | Deployed: ${deployed_usd:,.0f} ({deployed_pct*100:.1f}%) — "
        f"max={MAX_DEPLOYMENT*100:.0f}%"
    )

    for symbol in UNIVERSE:
        if symbol in held_symbols:
            logger.info(f"Bot2 | {symbol}: already holding — skip")
            continue

        if deployed_pct + POSITION_SIZE_PCT > MAX_DEPLOYMENT:
            logger.info(f"Bot2 | Deployment ceiling reached ({deployed_pct*100:.1f}%) — skipping {symbol}")
            continue

        enter, ctx = _should_enter(symbol)
        if not enter:
            logger.info(f"Bot2 | {symbol}: trend conditions not met — holding cash")
            continue

        entry_price = ctx["current_price"]
        atr         = ctx["atr"]
        notional    = equity * POSITION_SIZE_PCT

        # Safety check: don't deploy if cash would drop below reserve
        if notional > equity * (1 - CASH_RESERVE):
            notional = equity * (1 - CASH_RESERVE)

        # Calculate stops and TPs
        stop_price = entry_price * (1 - TRAIL_STOP_PCT)
        tp1_price  = entry_price * (1 + TP1_PCT)
        tp2_price  = entry_price * (1 + TP2_PCT)
        qty_approx = notional / entry_price  # approximate before fill

        logger.info(
            f"Bot2 | ENTRY {symbol} LONG notional=${notional:,.0f} "
            f"entry~{entry_price:.2f} stop={stop_price:.2f} "
            f"tp1={tp1_price:.2f} tp2={tp2_price:.2f} "
            f"min_hold={MIN_HOLD_DAYS}d"
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
            deployed_pct += POSITION_SIZE_PCT
            held_symbols.add(symbol)
            live_positions = engine.get_positions()

    # ── Trades reconciler (self-heals any missing trades rows every cycle) ─────
    engine.reconcile_etf_trades(BOT_ID)

    # ── Portfolio heartbeat ────────────────────────────────────────────────────
    live_positions = engine.get_positions()
    try:
        from core.bot_state import write_portfolio as _write_portfolio
        _write_portfolio(
            BOT_ID,
            cash=account["cash"],
            equity=equity,
            positions=live_positions,
        )
    except Exception as exc:
        logger.debug(f"Bot2 | write_portfolio failed (non-fatal): {exc}")
    logger.info(
        f"Bot2 | Cycle complete — equity=${equity:,.2f} "
        f"positions={len(live_positions)}"
    )
