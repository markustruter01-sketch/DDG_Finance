"""
main.py — Poseidon Bot (#7)
Strategy: Dual-Timeframe Momentum with Volume Confirmation
Exchange: Kraken (paper trading)
Cycle: 15 minutes | Capital: $95,175 paper
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

# ── Path setup (preserved exactly from original) ──────────────────────────────
_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.join(_DIR, "..")
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_TRADING_PLATFORM = os.path.join(_REPO_ROOT, "trading-platform")
if _TRADING_PLATFORM not in sys.path:
    sys.path.append(_TRADING_PLATFORM)

import config as cfg
import strategy as strat
from momentum_portfolio import MomentumPortfolio
from db_utils import (
    ensure_poseidon_tables,
    write_heartbeat,
    write_portfolio,
    record_momentum_trade,
    check_and_clear_force_refresh,
)

# ── Exchange setup (preserved exactly from original) ──────────────────────────
try:
    import ccxt
    exchange = ccxt.kraken({
        "apiKey":          cfg.KRAKEN_API_KEY,
        "secret":          cfg.KRAKEN_SECRET_KEY,
        "enableRateLimit": True,
    })
    logger.info("Poseidon | Exchange: Kraken (paper trading — momentum strategy)")
except Exception as e:
    logger.error(f"Poseidon | ccxt init failed: {e}")
    exchange = None

portfolio = MomentumPortfolio(cfg.PORTFOLIO_FILE, cfg.PAPER_STARTING_BALANCE)

_cycle = 0
_circuit_breaker_until: datetime | None = None


# ── Market data fetching ──────────────────────────────────────────────────────

def fetch_ohlcv(symbol: str, timeframe: str, limit: int) -> list:
    if exchange is None:
        return []
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        return bars or []
    except Exception as e:
        logger.debug(f"Poseidon | fetch_ohlcv {symbol} {timeframe} failed: {e}")
        return []


def fetch_current_price(symbol: str) -> float | None:
    if exchange is None:
        return None
    try:
        ticker = exchange.fetch_ticker(symbol)
        return float(ticker["last"]) if ticker and ticker.get("last") else None
    except Exception as e:
        logger.debug(f"Poseidon | fetch_current_price {symbol} failed: {e}")
        return None


def fetch_symbol_data(symbol: str) -> dict | None:
    """
    Fetch both 4H and 1H OHLCV for a symbol.
    Returns dict with closes/highs/lows/volumes for each timeframe, or None on failure.
    """
    bars_4h = fetch_ohlcv(symbol, "4h", cfg.EMA_SLOW + 60)
    bars_1h = fetch_ohlcv(symbol, "1h", cfg.RSI_PERIOD + cfg.VOLUME_MA_PERIOD + 15)

    if len(bars_4h) < cfg.EMA_SLOW + 10:
        logger.debug(f"Poseidon | {symbol}: insufficient 4H data ({len(bars_4h)} bars)")
        return None
    if len(bars_1h) < cfg.RSI_PERIOD + cfg.VOLUME_MA_PERIOD + 5:
        logger.debug(f"Poseidon | {symbol}: insufficient 1H data ({len(bars_1h)} bars)")
        return None

    return {
        "closes_4h":  [float(b[4]) for b in bars_4h if b[4]],
        "highs_4h":   [float(b[2]) for b in bars_4h if b[2]],
        "lows_4h":    [float(b[3]) for b in bars_4h if b[3]],
        "volumes_4h": [float(b[5]) for b in bars_4h if b[5] is not None],
        "closes_1h":  [float(b[4]) for b in bars_1h if b[4]],
        "volumes_1h": [float(b[5]) for b in bars_1h if b[5] is not None],
    }


# ── Circuit breaker ───────────────────────────────────────────────────────────

_POSEIDON_CONTROL_FILE = Path(_DIR) / "poseidon_control.json"


def _check_force_resume() -> bool:
    """Check if the dashboard has set force_resume=true in poseidon_control.json.
    If found, clear the in-memory circuit breaker and reset consecutive losses."""
    global _circuit_breaker_until
    if not _POSEIDON_CONTROL_FILE.exists():
        return False
    try:
        data = json.loads(_POSEIDON_CONTROL_FILE.read_text())
        if data.get("force_resume"):
            _circuit_breaker_until = None
            portfolio.consecutive_losses = 0
            data["force_resume"] = False
            _POSEIDON_CONTROL_FILE.write_text(json.dumps(data, indent=2))
            logger.warning(
                "Poseidon | FORCE RESUME — circuit breaker cleared and loss streak reset "
                "via dashboard override"
            )
            return True
    except Exception:
        pass
    return False


def is_circuit_breaker_active() -> bool:
    global _circuit_breaker_until
    if _circuit_breaker_until is None:
        return False
    if datetime.now(timezone.utc) >= _circuit_breaker_until:
        logger.info("Poseidon | Circuit breaker cleared")
        _circuit_breaker_until = None
        return False
    remaining = (_circuit_breaker_until - datetime.now(timezone.utc)).total_seconds() / 3600
    logger.info(f"Poseidon | Circuit breaker active — {remaining:.1f}h remaining")
    return True


def check_circuit_breaker():
    global _circuit_breaker_until
    if portfolio.consecutive_losses >= cfg.CB_CONSECUTIVE_LOSSES:
        _circuit_breaker_until = datetime.now(timezone.utc) + timedelta(hours=cfg.CB_PAUSE_HOURS)
        logger.warning(
            f"Poseidon | CIRCUIT BREAKER TRIPPED — {portfolio.consecutive_losses} consecutive losses. "
            f"Pausing until {_circuit_breaker_until.isoformat()[:19]} UTC"
        )


# ── Exit scanning ─────────────────────────────────────────────────────────────

def check_exits(current_prices: dict[str, float]):
    """Check all open positions for exit conditions."""
    symbols_to_close = []

    for symbol, pos in list(portfolio.positions.items()):
        current_price = current_prices.get(symbol)
        if current_price is None:
            current_price = fetch_current_price(symbol)
        if not current_price:
            logger.warning(f"Poseidon | No price for open position {symbol} — skipping exit check")
            continue

        portfolio.update_best_price(symbol, current_price)

        hours_held = portfolio.holding_hours(symbol)

        bars_4h = fetch_ohlcv(symbol, "4h", cfg.EMA_SLOW + 10)
        closes_4h = [float(b[4]) for b in bars_4h if b[4]] if bars_4h else []

        reason = strat.check_exit(pos, current_price, closes_4h, hours_held, cfg)
        if reason:
            symbols_to_close.append((symbol, current_price, reason))

    for symbol, price, reason in symbols_to_close:
        trade = portfolio.close_position(symbol, price, reason)
        if trade:
            record_momentum_trade(trade)
            logger.info(
                f"Poseidon | EXIT {symbol} {reason} "
                f"P&L=${trade['net_pnl']:+.2f} held={trade['holding_hours']:.1f}h"
            )

    if symbols_to_close:
        check_circuit_breaker()


# ── Entry scanning ────────────────────────────────────────────────────────────

def scan_for_entries(current_prices: dict[str, float]):
    """Scan all symbols for entry signals."""
    if is_circuit_breaker_active():
        return

    equity = portfolio.equity(current_prices)

    for symbol in cfg.SYMBOLS:
        if not portfolio.can_open(cfg.MAX_POSITIONS):
            logger.info(f"Poseidon | Max positions ({cfg.MAX_POSITIONS}) reached — skipping scan")
            break

        if portfolio.is_holding(symbol):
            continue

        data = fetch_symbol_data(symbol)
        if data is None:
            continue

        signal = strat.evaluate_entry(
            symbol,
            data["closes_4h"], data["highs_4h"], data["lows_4h"], data["volumes_4h"],
            data["closes_1h"], data["volumes_1h"],
            cfg,
        )

        if signal is None:
            continue

        if signal["direction"] == "short":
            if not cfg.ALLOW_SHORTS:
                continue
            if portfolio.short_count() >= cfg.MAX_SHORTS:
                logger.debug(f"Poseidon | {symbol}: SHORT signal but max_shorts={cfg.MAX_SHORTS} reached")
                continue

        units, position_usd = strat.calculate_position_size(
            equity, signal["price"], signal["atr"], cfg
        )
        if units <= 0:
            logger.debug(f"Poseidon | {symbol}: position size too small, skip")
            continue

        opened = portfolio.open_position(
            symbol=symbol,
            direction=signal["direction"],
            units=units,
            position_usd=position_usd,
            entry_price=signal["price"],
            atr=signal["atr"],
        )
        if opened:
            logger.info(
                f"Poseidon | ENTRY {signal['direction'].upper()} {symbol} "
                f"@ ${signal['price']:.4f} size=${position_usd:.0f} "
                f"conviction={signal['conviction']:.2f} RSI={signal['rsi']:.1f}"
            )


# ── Live state writer ─────────────────────────────────────────────────────────

def write_live_state(current_prices: dict[str, float], equity: float):
    """Write JSON snapshot to LIVE_STATE_FILE for the dashboard."""
    open_positions = []
    for symbol, pos in portfolio.positions.items():
        price = current_prices.get(symbol, pos["entry_price"])
        if pos["direction"] == "long":
            pnl = (price - pos["entry_price"]) * pos["units"] - pos["fees_paid"]
        else:
            pnl = (pos["entry_price"] - price) * pos["units"] - pos["fees_paid"]
        open_positions.append({
            "symbol":          symbol,
            "direction":       pos["direction"],
            "entry_price":     pos["entry_price"],
            "current_price":   price,
            "units":           pos["units"],
            "position_usd":    pos["position_usd"],
            "unrealised_pnl":  round(pnl, 4),
            "atr":             pos["atr"],
            "hours_held":      round(portfolio.holding_hours(symbol), 2),
            "opened_at":       pos["opened_at"],
        })

    state = {
        "bot_id":                 cfg.BOT_ID,
        "strategy":               "dual_timeframe_momentum",
        "cycle":                  _cycle,
        "updated_at":             datetime.now(timezone.utc).isoformat(),
        "equity_usd":             round(equity, 2),
        "cash_usd":               round(portfolio.cash, 2),
        "reserved_margin":        round(portfolio.reserved_margin, 2),
        "open_positions":         open_positions,
        "total_trades":           portfolio.total_trades,
        "consecutive_losses":     portfolio.consecutive_losses,
        "circuit_breaker_active": is_circuit_breaker_active(),
        "circuit_breaker_until":  _circuit_breaker_until.isoformat() if _circuit_breaker_until else None,
        "symbols_universe":       cfg.SYMBOLS,
        "current_prices":         {k: round(v, 6) for k, v in current_prices.items()},
    }

    path = Path(cfg.LIVE_STATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(path)


def _start_health_server() -> None:
    """Start a minimal HTTP health-check server on $PORT.

    The artifact system expects every service to open its assigned port.
    Runs in a daemon thread so it doesn't interfere with the trading loop.
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
            self.wfile.write(json.dumps({"status": "running", "service": "poseidon-bot"}).encode())

        def log_message(self, fmt, *args):
            pass

    def _serve():
        srv = HTTPServer(("0.0.0.0", _port), _Handler)
        srv.serve_forever()

    t = threading.Thread(target=_serve, name="health-http", daemon=True)
    t.start()
    logger.info(f"Poseidon | Health-check server listening on :{_port}")


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    global _cycle

    _start_health_server()
    logger.info(
        f"Poseidon | Starting — strategy=dual_timeframe_momentum "
        f"capital=${cfg.PAPER_STARTING_BALANCE:,.0f} "
        f"universe={len(cfg.SYMBOLS)} symbols "
        f"max_positions={cfg.MAX_POSITIONS}"
    )

    ensure_poseidon_tables()

    while True:
        _cycle += 1
        cycle_start = datetime.now(timezone.utc)
        logger.info(
            f"Poseidon | === Cycle #{_cycle} starting at "
            f"{cycle_start.isoformat()[:19]} UTC ==="
        )

        # ── Fleet halt check (preserved exactly from original) ────────────────
        try:
            import sys as _sys_fh
            import os as _os_fh
            _tp = _os_fh.path.join(_os_fh.path.dirname(_os_fh.path.abspath(__file__)), "..", "trading-platform")
            if _tp not in _sys_fh.path:
                _sys_fh.path.insert(0, _tp)
            from core.fleet_halt import is_halted as _is_fleet_halted
            if _is_fleet_halted():
                logger.warning(
                    "Bot | FLEET HALT ACTIVE — skipping cycle. "
                    "Resume via POST /trading-api/fleet/resume"
                )
                time.sleep(60)
                continue
        except Exception as _fh_exc:
            logger.debug(f"Bot | Fleet halt check failed (non-fatal, continuing): {_fh_exc}")

        # Force-refresh flag: acknowledge and clear (no pair discovery for momentum)
        if check_and_clear_force_refresh():
            logger.info("Poseidon | force_refresh flag cleared (momentum — no discovery required)")

        # Force-resume: clear circuit breaker on operator override
        _check_force_resume()

        try:
            # Fetch current prices for all symbols
            current_prices: dict[str, float] = {}
            for sym in cfg.SYMBOLS:
                price = fetch_current_price(sym)
                if price and price > 0:
                    current_prices[sym] = price

            logger.info(
                f"Poseidon | Prices fetched for {len(current_prices)}/{len(cfg.SYMBOLS)} symbols"
            )

            equity = portfolio.equity(current_prices)

            # Exit checks — always run, never gated by circuit breaker
            check_exits(current_prices)

            # Entry scan — skips internally if circuit breaker active
            scan_for_entries(current_prices)

            # DB writes (signatures preserved from original)
            write_heartbeat(equity, len(portfolio.positions), _cycle)
            write_portfolio(equity, portfolio.cash, len(portfolio.positions))
            write_live_state(current_prices, equity)

            logger.info(
                f"Poseidon | Cycle #{_cycle} complete | "
                f"equity=${equity:,.2f} | "
                f"positions={len(portfolio.positions)}/{cfg.MAX_POSITIONS} | "
                f"CB={'active' if is_circuit_breaker_active() else 'off'}"
            )

        except Exception as e:
            logger.error(f"Poseidon | Cycle #{_cycle} error: {e}")
            try:
                write_heartbeat(
                    portfolio.equity({}),
                    len(portfolio.positions),
                    _cycle,
                    status="error",
                    error=str(e),
                )
            except Exception:
                pass

        elapsed = (datetime.now(timezone.utc) - cycle_start).total_seconds()
        sleep_time = max(1, cfg.LOOP_SLEEP_SECONDS - elapsed)
        logger.info(f"Poseidon | Sleeping {sleep_time:.0f}s until next cycle")
        time.sleep(sleep_time)


if __name__ == "__main__":
    import time as _wdtime
    while True:
        try:
            main()
        except KeyboardInterrupt:
            print("[watchdog] KeyboardInterrupt — exiting cleanly")
            break
        except Exception as _wderr:
            print(f"[watchdog] main() crashed ({type(_wderr).__name__}: {_wderr}) — restarting in 10s")
            _wdtime.sleep(10)
