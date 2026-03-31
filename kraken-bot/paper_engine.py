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

PRIMARY STATE: PostgreSQL (kraken_portfolio + kraken_trades tables).
FALLBACK:      paper_portfolio.json on disk (written as backup each save).

On first startup the DB tables are seeded from paper_portfolio.json if
they are empty and the file exists, so no trade history is lost on upgrade.

Fees are simulated at 0.26% per trade (Kraken's standard taker fee)
on both entry and exit, so the numbers reflect realistic conditions.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

from loguru import logger


# ── Internal state (lazy-loaded) ──────────────────────────────────────────────

_portfolio: dict | None = None  # In-memory cache; DB is the source of truth


def _load_portfolio() -> dict:
    """
    Load the simulated portfolio.

    Order of precedence:
      1. In-memory cache (_portfolio) — already loaded this session
      2. PostgreSQL kraken_portfolio (survives restarts + redeploys)
      3. paper_portfolio.json on disk (legacy fallback)
      4. Fresh starting balance (truly first run)
    """
    from config import PAPER_PORTFOLIO_FILE, PAPER_STARTING_BALANCE
    import db as _db

    global _portfolio

    if _portfolio is not None:
        return _portfolio

    # ── 1. Try PostgreSQL ────────────────────────────────────────────────────
    # Row existence is the authoritative signal — not cash amount.
    # A zero-cash portfolio (fully deployed, edge state) is still valid state.
    pg_pf = _db.load_portfolio()
    if pg_pf is not None:
        _portfolio = pg_pf
        # Ensure all_trades key exists for in-memory compat
        if "all_trades" not in _portfolio:
            _portfolio["all_trades"] = []
        logger.info(
            f"Paper | Loaded portfolio from PostgreSQL — "
            f"Cash: ${_portfolio['cash_usd']:,.2f}, "
            f"Positions: {len(_portfolio.get('positions', {}))}"
        )
        return _portfolio

    # ── 2. Try JSON file (legacy / first-boot migration) ─────────────────────
    if os.path.exists(PAPER_PORTFOLIO_FILE):
        try:
            with open(PAPER_PORTFOLIO_FILE) as f:
                _portfolio = json.load(f)
            logger.info(
                f"Paper | Loaded portfolio from JSON — "
                f"Cash: ${_portfolio['cash_usd']:,.2f} (will migrate to DB)"
            )
            # Seed the DB from the JSON file so future restarts use DB
            _db.save_portfolio(
                cash_usd=_portfolio["cash_usd"],
                positions=_portfolio.get("positions", {}),
                starting_balance_usd=_portfolio.get("starting_balance_usd", PAPER_STARTING_BALANCE),
            )
            # Also seed trade history if DB is empty
            all_trades = _portfolio.get("all_trades", [])
            if all_trades:
                _db.migrate_from_json(PAPER_PORTFOLIO_FILE)
            return _portfolio
        except Exception as exc:
            logger.warning(f"Paper | Could not read {PAPER_PORTFOLIO_FILE}: {exc} — starting fresh")

    # ── 3. Fresh portfolio ────────────────────────────────────────────────────
    _portfolio = {
        "starting_balance_usd": PAPER_STARTING_BALANCE,
        "cash_usd":             PAPER_STARTING_BALANCE,
        "positions":            {},
        "all_trades":           [],
    }
    logger.info(
        f"Paper | Fresh portfolio created — "
        f"Starting balance: ${PAPER_STARTING_BALANCE:,.2f}"
    )
    _save_portfolio()
    return _portfolio


def _save_portfolio() -> None:
    """
    Persist the current in-memory portfolio to PostgreSQL (primary).
    JSON file is NOT written in the primary path — DB is the sole persistent store.
    """
    import db as _db

    global _portfolio
    if _portfolio is None:
        return

    _db.save_portfolio(
        cash_usd=_portfolio["cash_usd"],
        positions=_portfolio.get("positions", {}),
        starting_balance_usd=_portfolio.get("starting_balance_usd"),
    )


# ── Public API ────────────────────────────────────────────────────────────────

def get_paper_equity(current_prices: dict[str, float] | None = None) -> float:
    """
    Return the total simulated account value:
      cash  +  current market value of all open positions.

    current_prices: optional dict of {symbol: current_price}.
    If not provided, open positions are valued at their entry price.
    """
    p = _load_portfolio()
    equity = p["cash_usd"]

    for sym, pos in p["positions"].items():
        price = (current_prices or {}).get(sym, pos["entry_price"])
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
    """
    from config import PAPER_FEE_PCT

    p = _load_portfolio()

    fee_usd    = size_usd * PAPER_FEE_PCT
    total_cost = size_usd + fee_usd

    if total_cost > p["cash_usd"]:
        logger.warning(
            f"Paper | Not enough cash to open {side.upper()} {symbol} — "
            f"Need ${total_cost:,.2f}, have ${p['cash_usd']:,.2f}"
        )
        return False

    size_units = size_usd / current_price

    p["cash_usd"] -= total_cost

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

    The trade is written to DB (kraken_trades) immediately.
    """
    from config import PAPER_FEE_PCT
    import db as _db

    p = _load_portfolio()

    if symbol not in p["positions"]:
        logger.warning(f"Paper | Tried to close {symbol} but no position found")
        return None

    pos = p["positions"][symbol]

    exit_value = pos["size_units"] * current_price
    exit_fee   = exit_value * PAPER_FEE_PCT
    net_value  = exit_value - exit_fee

    if pos["side"] == "long":
        pnl_pct = ((current_price - pos["entry_price"]) / pos["entry_price"]) * 100
    else:
        pnl_pct = ((pos["entry_price"] - current_price) / pos["entry_price"]) * 100

    gross_pnl_usd = pos["size_usd"] * (pnl_pct / 100)
    total_fees    = pos.get("entry_fee", 0) + exit_fee
    net_pnl_usd   = gross_pnl_usd - total_fees

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
        "order_id":    pos.get("order_id"),
    }

    # Persist to DB immediately (primary store)
    _db.insert_trade(trade_record)

    # Keep in-memory all_trades list for backward compat
    if "all_trades" not in p:
        p["all_trades"] = []
    p["all_trades"].append(trade_record)

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
    Format matches what main.py uses for open_positions.
    """
    p = _load_portfolio()
    return {sym: dict(pos) for sym, pos in p["positions"].items()}


def get_paper_portfolio_summary() -> dict:
    """
    Return a summary of the paper portfolio for the status file.
    Includes starting balance, current equity, all-time P&L, and trade count.
    """
    import db as _db

    p = _load_portfolio()

    # Load full trade history from DB (source of truth)
    db_trades = _db.load_all_trades()
    if db_trades:
        trades = db_trades
    else:
        trades = p.get("all_trades", [])

    wins = [t for t in trades if t.get("pnl_pct", 0) > 0]

    return {
        "starting_balance_usd": p["starting_balance_usd"],
        "cash_usd":             round(p["cash_usd"], 2),
        "total_trades":         len(trades),
        "win_count":            len(wins),
        "all_time_pnl_usd":     round(sum(t.get("pnl_usd", 0) for t in trades), 2),
    }
