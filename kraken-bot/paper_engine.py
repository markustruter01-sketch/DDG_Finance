"""
paper_engine.py  —  Simulated $100K Paper Trading Portfolio
============================================================
This module is the "fake brokerage" for paper trading mode.
When PAPER_TRADING = True in config.py, main.py calls the functions
here instead of sending real orders to Kraken.

Everything else — RSI, z-score, position sizing, circuit breaker,
stop-losses — runs identically. The only difference is that orders
are "filled" at the current live market price instead of being
executed on the exchange.

The portfolio state is saved to kraken-bot/paper_portfolio.json
after every trade so it survives bot restarts. If the file does
not exist yet, the engine starts with a fresh PAPER_STARTING_BALANCE.

Fees are simulated at 0.26% per trade (Kraken's standard taker fee)
on both entry and exit, so the numbers reflect realistic conditions.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

from loguru import logger


# ── Internal state (loaded from disk on first call) ───────────────────────────

_portfolio: dict | None = None  # Lazy-loaded from PAPER_PORTFOLIO_FILE


def _load_portfolio() -> dict:
    """
    Load the simulated portfolio from disk, or create a fresh one
    if the file doesn't exist yet (first run).
    """
    # Import here to avoid circular imports at module load time
    from config import PAPER_PORTFOLIO_FILE, PAPER_STARTING_BALANCE

    global _portfolio

    if _portfolio is not None:
        return _portfolio  # Already loaded this session

    if os.path.exists(PAPER_PORTFOLIO_FILE):
        try:
            with open(PAPER_PORTFOLIO_FILE) as f:
                _portfolio = json.load(f)
            logger.info(
                f"Paper | Loaded portfolio from {PAPER_PORTFOLIO_FILE} — "
                f"Cash: ${_portfolio['cash_usd']:,.2f}"
            )
            return _portfolio
        except Exception as exc:
            logger.warning(f"Paper | Could not read {PAPER_PORTFOLIO_FILE}: {exc} — starting fresh")

    # First run — initialise with the configured starting balance
    _portfolio = {
        "starting_balance_usd": PAPER_STARTING_BALANCE,
        "cash_usd":             PAPER_STARTING_BALANCE,
        "positions":            {},   # symbol → position dict
        "all_trades":           [],   # complete trade history (all time)
    }
    logger.info(
        f"Paper | Fresh portfolio created — "
        f"Starting balance: ${PAPER_STARTING_BALANCE:,.2f}"
    )
    _save_portfolio()
    return _portfolio


def _save_portfolio() -> None:
    """
    Write the current portfolio state to disk so it survives restarts.
    """
    from config import PAPER_PORTFOLIO_FILE

    global _portfolio
    if _portfolio is None:
        return
    try:
        with open(PAPER_PORTFOLIO_FILE, "w") as f:
            json.dump(_portfolio, f, indent=2)
    except Exception as exc:
        logger.warning(f"Paper | Could not save portfolio: {exc}")


# ── Public API ────────────────────────────────────────────────────────────────

def get_paper_equity(current_prices: dict[str, float] | None = None) -> float:
    """
    Return the total simulated account value:
      cash  +  current market value of all open positions.

    current_prices: optional dict of {symbol: current_price}.
    If not provided, open positions are valued at their entry price
    (slightly underestimates for longs, overestimates for shorts,
    but accurate enough when called mid-cycle without live prices).
    """
    p = _load_portfolio()
    equity = p["cash_usd"]

    for sym, pos in p["positions"].items():
        price = (current_prices or {}).get(sym, pos["entry_price"])
        # Current market value of the position
        equity += pos["size_units"] * price

    return equity


def paper_open_position(
    symbol: str,
    side: str,
    size_usd: float,
    current_price: float,
) -> bool:
    """
    Simulate opening a position at the current market price.

    Deducts the position value plus the entry fee from cash.
    Returns True on success, False if there is not enough cash.

    Arguments:
      symbol        — e.g. "BTC/USD"
      side          — "long" or "short"
      size_usd      — how many USD to put into this position
      current_price — the live market price used as the fill price
    """
    from config import PAPER_FEE_PCT

    p = _load_portfolio()

    # Simulate Kraken's taker fee on entry
    fee_usd       = size_usd * PAPER_FEE_PCT
    total_cost    = size_usd + fee_usd

    if total_cost > p["cash_usd"]:
        logger.warning(
            f"Paper | Not enough cash to open {side.upper()} {symbol} — "
            f"Need ${total_cost:,.2f}, have ${p['cash_usd']:,.2f}"
        )
        return False

    size_units = size_usd / current_price

    # Deduct cost from cash
    p["cash_usd"] -= total_cost

    # Record the position
    p["positions"][symbol] = {
        "side":        side,
        "entry_price": current_price,
        "size_usd":    size_usd,
        "size_units":  size_units,
        "entry_time":  datetime.now(tz=timezone.utc).isoformat(),
        "best_price":  current_price,
        "entry_fee":   round(fee_usd, 4),
        "order_id":    f"PAPER-{symbol.replace('/', '')}-{int(datetime.now().timestamp())}",
    }

    _save_portfolio()

    logger.success(
        f"Paper | Opened {side.upper()} {symbol} — "
        f"Fill: ${current_price:,.2f} | Size: ${size_usd:,.2f} ({size_units:.6f} units) | "
        f"Fee: ${fee_usd:.2f} | Cash remaining: ${p['cash_usd']:,.2f}"
    )
    return True


def paper_close_position(symbol: str, current_price: float, reason: str) -> dict | None:
    """
    Simulate closing an open position at the current market price.

    Adds the proceeds (minus exit fee) back to cash.
    Returns a trade result dict, or None if there is no open position.

    The trade result dict matches the format used by main.py's
    live close_position() so the dashboard sees identical data.
    """
    from config import PAPER_FEE_PCT

    p = _load_portfolio()

    if symbol not in p["positions"]:
        logger.warning(f"Paper | Tried to close {symbol} but no position found")
        return None

    pos = p["positions"][symbol]

    # How much the position is worth at the current price
    exit_value = pos["size_units"] * current_price

    # Simulate Kraken's taker fee on exit
    exit_fee   = exit_value * PAPER_FEE_PCT
    net_value  = exit_value - exit_fee

    # Calculate P&L
    if pos["side"] == "long":
        # For longs: profit when price goes up
        pnl_pct = ((current_price - pos["entry_price"]) / pos["entry_price"]) * 100
    else:
        # For shorts: profit when price goes down
        pnl_pct = ((pos["entry_price"] - current_price) / pos["entry_price"]) * 100

    # Gross P&L in USD (before exit fee)
    gross_pnl_usd = pos["size_usd"] * (pnl_pct / 100)

    # Net P&L after both entry and exit fees
    total_fees = pos.get("entry_fee", 0) + exit_fee
    net_pnl_usd = gross_pnl_usd - total_fees

    # Return the cash (net of fees) to the simulated account
    p["cash_usd"] += net_value

    trade_record = {
        "symbol":      symbol,
        "side":        pos["side"],
        "entry_price": pos["entry_price"],
        "exit_price":  current_price,
        "pnl_pct":     round(pnl_pct, 2),
        "pnl_usd":     round(net_pnl_usd, 2),
        "fees_usd":    round(total_fees, 4),
        "reason":      reason,
        "closed_at":   datetime.now(tz=timezone.utc).isoformat(),
        "paper":       True,
    }

    # Add to all-time trade history on disk
    p["all_trades"].append(trade_record)

    # Remove from open positions
    del p["positions"][symbol]

    _save_portfolio()

    logger.info(
        f"Paper | Closed {pos['side'].upper()} {symbol} @ ${current_price:,.2f} | "
        f"Reason: {reason} | P&L: {pnl_pct:+.2f}% (${net_pnl_usd:+,.2f} after fees) | "
        f"Cash: ${p['cash_usd']:,.2f}"
    )

    return trade_record


def get_paper_positions() -> dict:
    """
    Return the current open positions from the paper portfolio.
    Format matches what main.py uses for open_positions so the rest
    of the code (position management, status writing) is unchanged.
    """
    p = _load_portfolio()
    return {sym: dict(pos) for sym, pos in p["positions"].items()}


def get_paper_portfolio_summary() -> dict:
    """
    Return a summary of the paper portfolio for the status file.
    Includes starting balance, current equity, all-time P&L, and trade count.
    """
    p = _load_portfolio()
    trades = p.get("all_trades", [])
    wins   = [t for t in trades if t.get("pnl_pct", 0) > 0]

    return {
        "starting_balance_usd": p["starting_balance_usd"],
        "cash_usd":             round(p["cash_usd"], 2),
        "total_trades":         len(trades),
        "win_count":            len(wins),
        "all_time_pnl_usd":     round(sum(t.get("pnl_usd", 0) for t in trades), 2),
    }
