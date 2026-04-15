"""
main.py — Kraken Current Bot
Bot #8: Trend Following / Time-Series Momentum on Kraken
4-hour cycle | $100,000 paper capital
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

# ── Path setup ────────────────────────────────────────────────────────────────
_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.join(_DIR, "..")
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_TRADING_PLATFORM = os.path.join(_REPO_ROOT, "trading-platform")
if _TRADING_PLATFORM not in sys.path:
    sys.path.append(_TRADING_PLATFORM)

import market_universe as _mu

from config import (
    BOT_ID, DISPLAY_NAME, DB_ID,
    PAPER_STARTING_BALANCE, PAPER_FEE_PCT, LOOP_SLEEP_SECONDS,
    SYMBOLS, EMA_FAST, EMA_SLOW, OHLCV_TIMEFRAME, OHLCV_LIMIT,
    ADX_PERIOD, ADX_ENTRY_MIN, ADX_EXIT_MIN, ADX_STRONG, ADX_VERY_STRONG,
    HURST_MIN, MOMENTUM_DAYS, VPIN_ENTRY_BLOCK, VPIN_EXTREME_EXIT,
    RISK_PER_TRADE, ATR_STOP_MULTIPLIER, ATR_TRAIL_TRIGGER,
    MAX_POSITION_FRACTION, MAX_POSITIONS, MAX_HOLD_DAYS,
    ADX_SCALE_WEAK, ADX_SCALE_STRONG, ADX_SCALE_VERY_STRONG,
    REGIME_BEAR_SHORT_MULT, REGIME_BULL_LONG_MULT, REGIME_SIDEWAYS_MULT,
    CB_DRAWDOWN_PCT, CB_WINDOW_DAYS, CB_PAUSE_HOURS,
    KRAKEN_API_KEY, KRAKEN_SECRET_KEY,
    STATUS_FILE, LIVE_STATE_FILE,
)
from trend_engine import (
    calculate_ema, calculate_atr, calculate_adx, hurst_exponent,
    momentum_return, calculate_position_size, evaluate_trend_signal,
    update_trailing_stop,
)
from paper_portfolio import TrendPosition, PaperPortfolio
from db_utils import (
    ensure_kraken_current_tables, write_heartbeat, write_portfolio,
    record_trade, record_signal_scan, get_kraken_current_equity,
    check_and_clear_force_refresh,
)

# ── Exchange setup ────────────────────────────────────────────────────────────
try:
    import ccxt
    exchange = ccxt.kraken({
        "apiKey": KRAKEN_API_KEY,
        "secret": KRAKEN_SECRET_KEY,
        "enableRateLimit": True,
    })
    logger.info(f"KrakenCurrent | Exchange: Kraken (paper trading mode)")
except Exception as e:
    logger.error(f"KrakenCurrent | ccxt init failed: {e}")
    exchange = None

PORTFOLIO_FILE = os.path.join(_DIR, "kc_paper_portfolio.json")
portfolio = PaperPortfolio(PORTFOLIO_FILE, PAPER_STARTING_BALANCE)

_cycle = 0

# ── Dynamic market universe ────────────────────────────────────────────────────
_UNIVERSE_SIZE = 250
_UNIVERSE_REFRESH_HOURS = 24
_active_symbols: list[str] = list(SYMBOLS)   # start with config fallback
_last_universe_refresh: datetime | None = None


def refresh_universe(force: bool = False):
    """
    Refresh the active trading universe from top-250 CoinGecko coins
    that are available on Kraken. Falls back to config SYMBOLS if fetch fails.
    Cached for 24 hours.
    """
    global _active_symbols, _last_universe_refresh
    now = datetime.now(timezone.utc)
    if (
        not force
        and _last_universe_refresh is not None
        and (now - _last_universe_refresh).total_seconds() < _UNIVERSE_REFRESH_HOURS * 3600
    ):
        return

    logger.info(f"KrakenCurrent | Refreshing market universe (top {_UNIVERSE_SIZE} by market cap)...")
    universe = _mu.get_kraken_universe(exchange, n=_UNIVERSE_SIZE) if exchange else []

    if universe:
        _active_symbols = universe
        _last_universe_refresh = now
        logger.info(
            f"KrakenCurrent | Universe updated: {len(_active_symbols)} symbols "
            f"(from top-{_UNIVERSE_SIZE} CoinGecko × Kraken USD pairs)"
        )
    else:
        logger.warning(
            f"KrakenCurrent | Universe fetch failed — keeping {len(_active_symbols)} symbols"
        )
        if not _last_universe_refresh:
            _last_universe_refresh = now  # don't retry every cycle


# ── Regime loading ────────────────────────────────────────────────────────────

def load_regime() -> str:
    """Load crypto regime from shared state file."""
    regime_files = [
        os.path.join(_REPO_ROOT, "kraken-bot", "crypto_regime.json"),
        os.path.join(_REPO_ROOT, "trading-platform", "data", "crypto_regime.json"),
    ]
    for f in regime_files:
        if os.path.exists(f):
            try:
                data = json.loads(Path(f).read_text())
                return data.get("regime", "Sideways")
            except Exception:
                pass
    return "Sideways"


def regime_multiplier(regime: str, direction: str) -> float:
    r = regime.lower()
    if "bear" in r:
        return REGIME_BEAR_SHORT_MULT if direction == "short" else 1.0
    elif "bull" in r:
        return REGIME_BULL_LONG_MULT if direction == "long" else 1.0
    else:
        return REGIME_SIDEWAYS_MULT


# ── Market data ───────────────────────────────────────────────────────────────

def fetch_ohlcv(symbol: str) -> tuple[list, list, list, list]:
    """Fetch OHLCV bars. Returns (closes, highs, lows, opens)."""
    if exchange is None:
        return [], [], [], []
    try:
        bars = exchange.fetch_ohlcv(symbol, OHLCV_TIMEFRAME, limit=OHLCV_LIMIT)
        if not bars:
            return [], [], [], []
        closes = [float(b[4]) for b in bars if b[4]]
        highs = [float(b[2]) for b in bars if b[2]]
        lows = [float(b[3]) for b in bars if b[3]]
        opens = [float(b[1]) for b in bars if b[1]]
        return closes, highs, lows, opens
    except Exception as e:
        logger.warning(f"KrakenCurrent | fetch_ohlcv {symbol} failed: {e}")
        return [], [], [], []


def fetch_current_price(symbol: str) -> float | None:
    if exchange is None:
        return None
    try:
        ticker = exchange.fetch_ticker(symbol)
        return float(ticker.get("last") or ticker.get("close") or 0) or None
    except Exception as e:
        logger.warning(f"KrakenCurrent | price fetch {symbol} failed: {e}")
        return None


# ── Position exit management ──────────────────────────────────────────────────

def check_exits(current_prices: dict[str, float], ohlcv_data: dict[str, tuple]):
    """Check all open positions for exit conditions."""
    for sym, pos in list(portfolio.positions.items()):
        price = current_prices.get(sym)
        if not price:
            continue

        closes, highs, lows, _ = ohlcv_data.get(sym, ([], [], [], []))
        atr = calculate_atr(highs, lows, closes) if closes else pos.stop_distance / ATR_STOP_MULTIPLIER
        adx = calculate_adx(highs, lows, closes) if closes else 0

        # Update trailing stop
        pos.update_stop(price, atr, ATR_TRAIL_TRIGGER)

        reason = None

        # Stop hit
        if pos.is_stop_hit(price):
            reason = "trailing_stop"

        # EMA crossover reversed
        if closes and len(closes) >= EMA_SLOW:
            ema_f = calculate_ema(closes, EMA_FAST)
            ema_s = calculate_ema(closes, EMA_SLOW)
            if pos.direction == "long" and ema_f < ema_s:
                reason = "ema_reversal"
            elif pos.direction == "short" and ema_f > ema_s:
                reason = "ema_reversal"

        # ADX weakening
        if adx > 0 and adx < ADX_EXIT_MIN:
            reason = "adx_weak"

        # Maximum hold
        if pos.holding_days() >= MAX_HOLD_DAYS:
            reason = "timeout_21d"

        # VPIN extreme (use a proxy — we don't have VPIN in this standalone bot)
        # This would be connected to the VPIN infrastructure in a full integration

        if reason:
            trade = portfolio.close_position(sym, price, reason)
            if trade:
                trade["ema_fast"] = pos.ema_fast
                trade["ema_slow"] = pos.ema_slow
                trade["adx"] = pos.adx
                record_trade(trade)


# ── Entry scan ────────────────────────────────────────────────────────────────

def scan_for_entries(current_prices: dict[str, float], ohlcv_data: dict[str, tuple], regime: str) -> list[dict]:
    """Scan all assets for trend entry signals."""
    scan_results = []

    if portfolio.is_circuit_breaker_active():
        logger.info("KrakenCurrent | Circuit breaker active — skipping entry scan")
        return []

    for sym in _active_symbols:
        closes, highs, lows, _ = ohlcv_data.get(sym, ([], [], [], []))
        price = current_prices.get(sym, 0)

        result = evaluate_trend_signal(
            closes, highs, lows,
            ema_fast_period=EMA_FAST,
            ema_slow_period=EMA_SLOW,
            adx_period=ADX_PERIOD,
            adx_min=ADX_ENTRY_MIN,
            hurst_min=HURST_MIN,
            momentum_days=MOMENTUM_DAYS,
            vpin=0.0,  # VPIN integration handled by platform
            vpin_block=VPIN_ENTRY_BLOCK,
        )
        result["symbol"] = sym

        scan_results.append(result)

        if result.get("passed") and not result.get("direction") is None:
            direction = result["direction"]
            logger.info(
                f"KrakenCurrent | {sym}: {direction.upper()} signal | "
                f"EMA_fast={result.get('ema_fast', 0):.2f} EMA_slow={result.get('ema_slow', 0):.2f} "
                f"ADX={result.get('adx', 0):.1f} H={result.get('hurst', 0):.3f}"
            )

            # Check if we can open
            if not portfolio.can_open(sym, MAX_POSITIONS):
                logger.debug(f"KrakenCurrent | {sym}: position already open or max reached")
                continue

            atr = result.get("atr", 0) or 0
            if atr <= 0 or price <= 0:
                continue

            reg_mult = regime_multiplier(regime, direction)

            sizing = calculate_position_size(
                equity=portfolio.equity(current_prices),
                atr=atr,
                price=price,
                adx=result.get("adx", 25),
                risk_per_trade=RISK_PER_TRADE,
                atr_multiplier=ATR_STOP_MULTIPLIER,
                max_fraction=MAX_POSITION_FRACTION,
                regime_mult=reg_mult,
                adx_scale_weak=ADX_SCALE_WEAK,
                adx_scale_strong=ADX_SCALE_STRONG,
                adx_strong_threshold=ADX_STRONG,
                adx_very_strong_threshold=ADX_VERY_STRONG,
            )

            if sizing["units"] <= 0 or sizing["position_value"] <= 0:
                continue

            pos = TrendPosition(
                symbol=sym,
                direction=direction,
                units=sizing["units"],
                entry_price=price,
                stop_distance=sizing["stop_distance"],
                position_value=sizing["position_value"],
                ema_fast=result.get("ema_fast", 0),
                ema_slow=result.get("ema_slow", 0),
                adx=result.get("adx", 0),
                trail_immediate=sizing.get("trail_immediate", False),
            )

            portfolio.open_position(pos)
        else:
            if result.get("block_reason"):
                logger.debug(f"KrakenCurrent | {sym}: blocked ({result['block_reason']})")

    return scan_results


# ── Live state write ──────────────────────────────────────────────────────────

def write_live_state(current_prices: dict[str, float], equity: float, scan_results: list, regime: str):
    state = {
        "bot_id": BOT_ID,
        "display_name": DISPLAY_NAME,
        "equity": equity,
        "cash": portfolio.cash,
        "open_positions": len(portfolio.positions),
        "regime": regime,
        "positions": {},
        "signal_scan": scan_results,
        "circuit_breaker": portfolio.circuit_breaker_until,
        "cycle": _cycle,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    for sym, pos in portfolio.positions.items():
        price = current_prices.get(sym, pos.entry_price)
        state["positions"][sym] = {
            **pos.to_dict(),
            "current_price": price,
            "unrealised_pnl": pos.unrealised_pnl(price),
            "holding_days": pos.holding_days(),
        }
    Path(LIVE_STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(LIVE_STATE_FILE).write_text(json.dumps(state, indent=2, default=str))


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    global _cycle
    logger.info(f"""
=================================================================
  PAPER TRADING MODE  —  {DISPLAY_NAME}
  Bot ID: {BOT_ID} (DB id={DB_ID}) | Strategy: Trend Following
  Simulated ${PAPER_STARTING_BALANCE:,.0f} account | 4-hour cycle
  Universe: top-250 by market cap (dynamic)
=================================================================
""")

    ensure_kraken_current_tables()

    # Build market universe on startup
    logger.info(f"KrakenCurrent | Building initial market universe (top {_UNIVERSE_SIZE})...")
    refresh_universe(force=True)

    while True:
        _cycle += 1
        cycle_start = datetime.now(timezone.utc)
        logger.info(f"KrakenCurrent | === Cycle #{_cycle} at {cycle_start.isoformat()[:19]} UTC ===")

        # Self-healing kick: API can set force_refresh=TRUE to prompt universe refresh
        if check_and_clear_force_refresh():
            logger.info("KrakenCurrent | force_refresh flag detected — refreshing universe")
            refresh_universe(force=True)

        try:
            # Refresh universe every 24h (no-op if fresh)
            refresh_universe()

            regime = load_regime()
            logger.info(f"KrakenCurrent | Regime: {regime} | Universe: {len(_active_symbols)} symbols")

            # Fetch all OHLCV data for the active universe
            ohlcv_data: dict[str, tuple] = {}
            current_prices: dict[str, float] = {}
            for sym in _active_symbols:
                closes, highs, lows, opens = fetch_ohlcv(sym)
                if closes:
                    ohlcv_data[sym] = (closes, highs, lows, opens)
                    current_prices[sym] = closes[-1]

            logger.info(f"KrakenCurrent | OHLCV loaded for {len(ohlcv_data)}/{len(_active_symbols)} symbols")

            equity = portfolio.equity(current_prices)

            # Check circuit breaker
            portfolio.check_circuit_breaker(equity, CB_DRAWDOWN_PCT, PAPER_STARTING_BALANCE)

            # Exit before entry
            check_exits(current_prices, ohlcv_data)

            # Scan for entries
            scan_results = scan_for_entries(current_prices, ohlcv_data, regime)

            # Write to DB
            write_heartbeat(equity, len(portfolio.positions), _cycle)
            write_portfolio(equity, portfolio.cash, len(portfolio.positions))
            if scan_results:
                record_signal_scan(scan_results)
            write_live_state(current_prices, equity, scan_results, regime)

            signals = [r for r in scan_results if r.get("passed")]
            logger.info(
                f"KrakenCurrent | Cycle #{_cycle} complete | "
                f"equity=${equity:,.2f} | positions={len(portfolio.positions)}/{MAX_POSITIONS} | "
                f"signals={len(signals)}/{len(scan_results)} | regime={regime}"
            )

        except Exception as e:
            logger.error(f"KrakenCurrent | Cycle #{_cycle} error: {e}")
            try:
                write_heartbeat(portfolio.equity({}), len(portfolio.positions), _cycle, status="error", error=str(e))
            except Exception:
                pass

        elapsed = (datetime.now(timezone.utc) - cycle_start).total_seconds()
        sleep_time = max(1, LOOP_SLEEP_SECONDS - elapsed)
        logger.info(f"KrakenCurrent | Sleeping {sleep_time:.0f}s until next cycle")
        time.sleep(sleep_time)


if __name__ == "__main__":
    main()
