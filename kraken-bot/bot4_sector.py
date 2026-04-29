"""
bot4_sector.py — Sector Momentum Rotation Bot (Bot #4)

Strategy: Hold the top 2 SPDR sector ETFs by 30-day price return.

Universe:  11 SPDR sector ETFs (XLK, XLE, XLF, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC)
Rebalance: Weekly on Mondays (or first run of the week).
Hold:      Minimum 10 trading days.
Sizing:    40% equity per top sector (80% deployed max, 20% cash always).
Exit:      Sector drops out of top 3 in 30-day momentum ranking + min hold elapsed.
Liquidity: Skip sectors below $100M daily USD volume floor.

BOT_ID:  bot4_sector
DB row:  kraken_heartbeat id=3  (was Calypso — replaces it)

ACTIVATION (Week 3):
  Before flipping BOT_PAUSED=False in config.py, run:
    UPDATE kraken_heartbeat
    SET bot_id = 'bot4_sector', bot_display_name = 'Sector Rotation'
    WHERE id = 3;
  Then set BOT_PAUSED = False in BOT_PROFILES['bot4_sector'].

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

logger = logging.getLogger("bot4.sector")

# ── Constants ─────────────────────────────────────────────────────────────────

UNIVERSE: list[str] = [
    "XLK", "XLE", "XLF", "XLV", "XLI",
    "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
]
LIQUIDITY_FLOOR_USD   = 100_000_000   # $100M daily USD volume
TOP_N_TO_HOLD         = 2
TOP_N_STAY_THRESHOLD  = 3             # exit when drops out of top 3
MIN_HOLD_DAYS         = 10
POSITION_SIZE_PCT     = 0.40
MAX_DEPLOYMENT        = 0.80
CASH_RESERVE          = 0.20
TRAIL_STOP_PCT        = 0.08

BOT_ID = "bot4_sector"

# TP targets for tiered scale-out
TP1_PCT = 0.08
TP2_PCT = 0.15


# ── Momentum scoring ──────────────────────────────────────────────────────────

def _score_sectors() -> list[dict]:
    """
    Rank all UNIVERSE sectors by 30-day price return.
    Filters out sectors below the daily USD liquidity floor.
    Returns list sorted by return_30d descending.
    """
    scores = []
    for sym in UNIVERSE:
        ohlcv = _yahoo_daily_ohlcv(sym, days=35)
        if not ohlcv or len(ohlcv["closes"]) < 22:
            logger.debug(f"Bot4 | {sym}: insufficient data — skipping")
            continue

        closes  = ohlcv["closes"]
        volumes = ohlcv["volumes"]

        current = closes[-1]
        start   = closes[-22] if len(closes) >= 22 else closes[0]  # ~30 calendar days
        return_30d = (current - start) / start * 100 if start > 0 else 0.0

        # Liquidity filter: average daily USD volume over last 10 days
        avg_vol_usd = (
            sum(v * c for v, c in zip(volumes[-10:], closes[-10:])) / 10
            if len(volumes) >= 10 else 0
        )
        if avg_vol_usd < LIQUIDITY_FLOOR_USD:
            logger.info(
                f"Bot4 | {sym}: avg_vol_usd=${avg_vol_usd/1e6:.0f}M below "
                f"${LIQUIDITY_FLOOR_USD/1e6:.0f}M floor — skipping"
            )
            continue

        atr = calculate_atr(ohlcv["highs"], ohlcv["lows"], closes, period=14)
        scores.append({
            "symbol":       sym,
            "return_30d":   round(return_30d, 3),
            "current":      round(current, 2),
            "avg_vol_usd":  avg_vol_usd,
            "atr":          atr,
        })

    scores.sort(key=lambda x: x["return_30d"], reverse=True)
    logger.info(
        f"Bot4 | Sector ranking: "
        + ", ".join(f"{s['symbol']}({s['return_30d']:+.1f}%)" for s in scores[:5])
    )
    return scores


def _is_rebalance_day() -> bool:
    """True if today is Monday (weekly rebalance trigger)."""
    return datetime.now(timezone.utc).weekday() == 0  # 0 = Monday


# ── Main cycle ────────────────────────────────────────────────────────────────

def run_bot4_cycle(profile: dict, db_id: int) -> None:
    """
    Main sector rotation cycle. Called from main.py when BOT_ID=bot4_sector.
    Runs on every main.py sleep loop; rebalance logic triggers only on Mondays.
    Exit checks (trailing stop) run every cycle.
    """
    # Pause guard — always first
    if profile.get("BOT_PAUSED", True):
        logger.info("Bot4 | BOT_PAUSED=True — skipping cycle (not yet activated)")
        return

    logger.info(
        f"Bot4 | === SECTOR ROTATION CYCLE — "
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
        logger.error(f"Bot4 | Alpaca connection failed: {exc}")
        return

    account = engine.get_account()
    equity  = account["equity"]
    logger.info(
        f"Bot4 | Equity=${equity:,.2f} cash=${account['cash']:,.2f}"
    )

    live_positions = engine.get_positions()
    db_positions   = engine.get_db_positions(BOT_ID)
    held_symbols   = {p["symbol"] for p in live_positions}

    logger.info(
        f"Bot4 | Positions: {len(live_positions)} live, {len(db_positions)} in DB"
    )

    # ── Exit checks — run every cycle ─────────────────────────────────────────

    # Score sectors (needed for momentum exit check)
    scores = _score_sectors()
    ranked_symbols = [s["symbol"] for s in scores]

    for db_pos in db_positions:
        symbol = db_pos["symbol"]

        # Trailing stop (always on — engine handles this)
        exit_reason = engine.run_exit_checks(
            bot_id=BOT_ID,
            db_position=db_pos,
            live_positions=live_positions,
            trail_pct=TRAIL_STOP_PCT,
        )
        if exit_reason:
            logger.info(f"Bot4 | EXIT {symbol}: {exit_reason}")
            live = next((p for p in live_positions if p["symbol"] == symbol), None)
            realised_pnl = live["unrealised_pnl_usd"] if live else None
            engine.close_position(symbol)
            engine.record_close(BOT_ID, symbol, exit_reason, realised_pnl)
            live_positions = engine.get_positions()
            held_symbols   = {p["symbol"] for p in live_positions}
            continue

        # Momentum exit: sector dropped out of top-N and min hold elapsed
        if engine.check_min_hold(db_pos):
            rank = ranked_symbols.index(symbol) + 1 if symbol in ranked_symbols else 99
            if rank > TOP_N_STAY_THRESHOLD:
                reason = f"sector_rotation (rank #{rank} > top-{TOP_N_STAY_THRESHOLD})"
                logger.info(f"Bot4 | ROTATION EXIT {symbol}: {reason}")
                live = next((p for p in live_positions if p["symbol"] == symbol), None)
                realised_pnl = live["unrealised_pnl_usd"] if live else None
                engine.close_position(symbol)
                engine.record_close(BOT_ID, symbol, reason, realised_pnl)
                live_positions = engine.get_positions()
                held_symbols   = {p["symbol"] for p in live_positions}

    # ── Entry scan — only on Monday rebalance ─────────────────────────────────

    if not _is_rebalance_day():
        logger.info("Bot4 | Not Monday — skipping rebalance entry scan")
        engine.update_heartbeat(db_id, equity, len(live_positions))
        return

    logger.info("Bot4 | Monday rebalance — scanning for entries")
    live_positions = engine.get_positions()
    deployed_usd   = sum(p["market_value"] for p in live_positions)
    deployed_pct   = deployed_usd / equity if equity > 0 else 1.0
    held_symbols   = {p["symbol"] for p in live_positions}

    for sector in scores[:TOP_N_TO_HOLD]:
        symbol = sector["symbol"]

        if symbol in held_symbols:
            logger.info(f"Bot4 | {symbol}: already holding (rank #{scores.index(sector)+1})")
            continue

        if deployed_pct + POSITION_SIZE_PCT > MAX_DEPLOYMENT:
            logger.info(f"Bot4 | Deployment ceiling hit ({deployed_pct*100:.1f}%) — done")
            break

        entry_price = sector["current"]
        atr         = sector["atr"]
        notional    = equity * POSITION_SIZE_PCT
        stop_price  = entry_price * (1 - TRAIL_STOP_PCT)
        tp1_price   = entry_price * (1 + TP1_PCT)
        tp2_price   = entry_price * (1 + TP2_PCT)
        qty_approx  = notional / entry_price

        rank = scores.index(sector) + 1
        logger.info(
            f"Bot4 | ENTRY {symbol} LONG rank=#{rank} "
            f"return_30d={sector['return_30d']:+.1f}% "
            f"notional=${notional:,.0f} entry~{entry_price:.2f} "
            f"stop={stop_price:.2f} min_hold={MIN_HOLD_DAYS}d"
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

    # ── Heartbeat ─────────────────────────────────────────────────────────────
    live_positions = engine.get_positions()
    engine.update_heartbeat(db_id, equity, len(live_positions))
    logger.info(
        f"Bot4 | Cycle complete — equity=${equity:,.2f} "
        f"positions={len(live_positions)}"
    )
