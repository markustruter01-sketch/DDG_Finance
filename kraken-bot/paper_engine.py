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
      3. Fresh starting balance (truly first run — DB row absent)
    """
    from config import PAPER_STARTING_BALANCE
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

    # ── 2. Fresh portfolio (DB had no row — truly first run) ─────────────────
    # JSON file fallback removed: DB row existence is authoritative.
    # The one-time JSON migration runs on startup (db.migrate_from_json) and
    # is gated by SELECT 1 FROM kraken_portfolio WHERE id=1, so it only fires
    # when the table is genuinely empty. After that, DB is the sole source.
    logger.info("Paper | No portfolio row in DB — initialising fresh $100 k account")

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


def reload_portfolio_from_db() -> dict:
    """Force-reload the in-memory portfolio from the database.
    Called by main.py when the rebalance endpoint signals a force reload."""
    import db as _db

    global _portfolio
    pg_pf = _db.load_portfolio()
    if pg_pf is not None:
        _portfolio = pg_pf
        if "all_trades" not in _portfolio:
            _portfolio["all_trades"] = []
        logger.warning(
            f"Paper | FORCE RELOADED from DB — "
            f"Cash: ${_portfolio['cash_usd']:,.2f}, "
            f"Positions: {len(_portfolio.get('positions', {}))}"
        )
    return _portfolio or {}


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


def compute_dynamic_slippage(
    size_usd: float,
    current_price: float,
    atr: float = 0.0,
) -> float:
    """
    Stage 4: Dynamic Slippage — penalizes paper fills based on trade size and ATR.

    Real-world fills always suffer slippage.  Larger orders eat deeper into the
    order book, and volatile markets have wider spreads.  This model approximates
    the execution reality gap:

      slippage_pct = base_slippage + size_impact + volatility_impact

    Where:
      base_slippage     = 0.01% (1 bps) — minimum market-maker spread
      size_impact       = 0 to 0.05% based on notional vs. $50k reference
      volatility_impact = 0 to 0.10% based on ATR% of price

    Returns the slippage as a fraction of the fill price (e.g., 0.0003 = 3 bps).
    The caller applies this to move the fill price adversely.
    """
    base_bps = 0.0001

    size_ref = 50_000.0
    size_factor = min(size_usd / size_ref, 1.0)
    size_bps = size_factor * 0.0005

    vol_bps = 0.0
    if atr > 0 and current_price > 0:
        atr_pct = atr / current_price
        vol_bps = min(atr_pct * 0.025, 0.0010)

    return base_bps + size_bps + vol_bps


def _apply_slippage(
    price: float,
    side: str,
    size_usd: float,
    atr: float = 0.0,
) -> tuple[float, float]:
    """
    Apply dynamic slippage to a fill price.

    For LONG entries: fill price is HIGHER (worse)
    For SHORT entries: fill price is LOWER (worse)
    For closing: fill price is adverse to the position direction

    Returns: (adjusted_price, slippage_pct)
    """
    slip_pct = compute_dynamic_slippage(size_usd, price, atr)
    if side == "long":
        adjusted = price * (1 + slip_pct)
    else:
        adjusted = price * (1 - slip_pct)
    return (round(adjusted, 8), slip_pct)


FEE_PROFIT_MULTIPLIER = 2.5


def check_fee_profitability(
    size_usd: float,
    tp_pct: float,
) -> tuple[bool, float, float]:
    """
    Pre-entry check: is the expected profit at take-profit at least
    FEE_PROFIT_MULTIPLIER × the estimated round-trip fee cost?

    Round-trip fees = entry fee + exit fee = 2 × (size_usd × PAPER_FEE_PCT).

    Returns:
        (passes, expected_profit, round_trip_fees)
    """
    from config import PAPER_FEE_PCT

    round_trip_fees = 2 * size_usd * PAPER_FEE_PCT
    expected_profit = size_usd * tp_pct
    passes = expected_profit >= (FEE_PROFIT_MULTIPLIER * round_trip_fees)
    return (passes, round(expected_profit, 2), round(round_trip_fees, 2))


def paper_open_position(
    symbol: str,
    side: str,
    size_usd: float,
    current_price: float,
    atr: float = 0.0,
    regime_at_entry: str = "Unknown",
    entry_zscore: float | None = None,
    zscore_source: str = "raw",
) -> bool:
    """
    Simulate opening a position at the current market price with dynamic slippage.

    Deducts the position value plus the entry fee from cash.
    Returns True on success, False if there is not enough cash.
    """
    from config import PAPER_FEE_PCT

    fill_price, slip_pct = _apply_slippage(current_price, side, size_usd, atr)

    p = _load_portfolio()

    fee_usd    = size_usd * PAPER_FEE_PCT
    total_cost = size_usd + fee_usd

    if total_cost > p["cash_usd"]:
        logger.warning(
            f"Paper | Not enough cash to open {side.upper()} {symbol} — "
            f"Need ${total_cost:,.2f}, have ${p['cash_usd']:,.2f}"
        )
        return False

    size_units = size_usd / fill_price

    p["cash_usd"] -= total_cost

    p["positions"][symbol] = {
        "side":            side,
        "entry_price":     fill_price,
        "size_usd":        size_usd,
        "size_units":      size_units,
        "entry_time":      datetime.now(tz=timezone.utc).isoformat(),
        "best_price":      fill_price,
        "entry_fee":       round(fee_usd, 4),
        "slippage_pct":    round(slip_pct * 100, 4),
        "order_id":        f"PAPER-{symbol.replace('/', '')}-{int(datetime.now().timestamp())}",
        "regime_at_entry": regime_at_entry,
        "entry_zscore":    entry_zscore,
        "zscore_source":   zscore_source,
    }

    _save_portfolio()

    _slip_note = f" | Slippage: {slip_pct*100:.2f}%" if slip_pct > 0.0001 else ""
    logger.success(
        f"Paper | Opened {side.upper()} {symbol} — "
        f"Fill: ${fill_price:,.2f} (mkt ${current_price:,.2f}){_slip_note} | "
        f"Size: ${size_usd:,.2f} ({size_units:.6f} units) | "
        f"Fee: ${fee_usd:.2f} | Cash remaining: ${p['cash_usd']:,.2f}"
    )
    return True


def paper_scale_in_position(
    symbol:        str,
    add_size_usd:  float,
    current_price: float,
    atr:           float = 0.0,
) -> bool:
    """
    Simulate adding a second or third tranche to an existing open position.

    This is the paper-trading equivalent of "scaling in" — placing an additional
    buy (for longs) or sell (for shorts) on top of a position we already hold,
    at a more favourable price than our original entry.

    When this executes:
      • Cash is deducted (the new tranche cost + entry fee).
      • The position's size_usd and size_units increase.
      • The position's entry_price is updated to the WEIGHTED AVERAGE
        of all tranches executed so far.
      • The best_price is reset to current_price (the newest entry point).

    Why weighted average entry?
    Because from a P&L perspective, we care about our AVERAGE cost basis,
    not just the first tranche's price.  The dashboard and all stop-loss
    calculations should work from this blended entry.

    Args:
        symbol:        The trading pair (e.g. "BTC/USD").
        add_size_usd:  The additional USD to deploy for this tranche.
        current_price: Current market price (the simulated fill price).

    Returns:
        True if the tranche was executed successfully.
        False if there is not enough cash or no position to add to.
    """
    from config import PAPER_FEE_PCT

    p = _load_portfolio()

    if symbol not in p["positions"]:
        logger.warning(f"Paper | Scale-in {symbol}: no existing position to add to")
        return False

    fee_usd    = add_size_usd * PAPER_FEE_PCT
    total_cost = add_size_usd + fee_usd

    if total_cost > p["cash_usd"]:
        logger.warning(
            f"Paper | Scale-in {symbol}: not enough cash — "
            f"need ${total_cost:,.2f}, have ${p['cash_usd']:,.2f}"
        )
        return False

    pos = p["positions"][symbol]

    fill_price, slip_pct = _apply_slippage(current_price, pos["side"], add_size_usd, atr)
    add_units = add_size_usd / fill_price

    old_size   = pos["size_usd"]
    old_entry  = pos["entry_price"]
    new_size   = old_size + add_size_usd
    new_entry  = (old_size * old_entry + add_size_usd * fill_price) / new_size

    pos["entry_price"] = round(new_entry, 8)
    pos["size_usd"]    = round(new_size, 2)
    pos["size_units"]  = round(pos["size_units"] + add_units, 8)

    if pos["side"] == "long":
        pos["best_price"] = max(pos.get("best_price", fill_price), fill_price)
    else:
        pos["best_price"] = min(pos.get("best_price", fill_price), fill_price)

    p["cash_usd"] -= total_cost

    _save_portfolio()

    _slip_note = f" | Slippage: {slip_pct*100:.2f}%" if slip_pct > 0.0001 else ""
    logger.success(
        f"Paper | Scale-in {symbol} (T{pos.get('tranches_filled', '?')}) — "
        f"Fill: ${fill_price:,.2f} (mkt ${current_price:,.2f}){_slip_note} | "
        f"Added: ${add_size_usd:,.2f} ({add_units:.6f} units) | "
        f"New avg entry: ${new_entry:,.4f} | Total size: ${new_size:,.2f} | "
        f"Fee: ${fee_usd:.2f} | Cash: ${p['cash_usd']:,.2f}"
    )
    return True


def paper_close_position(symbol: str, current_price: float, reason: str, atr: float = 0.0) -> dict | None:
    """
    Simulate closing an open position at the current market price with dynamic slippage.

    Adds the proceeds (minus exit fee and slippage) back to cash.
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

    exit_side = "short" if pos["side"] == "long" else "long"
    exit_value_notional = pos["size_units"] * current_price
    fill_price, slip_pct = _apply_slippage(current_price, exit_side, exit_value_notional, atr)

    exit_value = pos["size_units"] * fill_price
    exit_fee   = exit_value * PAPER_FEE_PCT
    net_value  = exit_value - exit_fee

    if pos["side"] == "long":
        pnl_pct = ((fill_price - pos["entry_price"]) / pos["entry_price"]) * 100
    else:
        pnl_pct = ((pos["entry_price"] - fill_price) / pos["entry_price"]) * 100

    gross_pnl_usd = pos["size_usd"] * (pnl_pct / 100)
    total_fees    = pos.get("entry_fee", 0) + exit_fee
    net_pnl_usd   = gross_pnl_usd - total_fees

    p["cash_usd"] += net_value

    trade_record = {
        "symbol":          symbol,
        "side":            pos["side"],
        "entry_price":     pos["entry_price"],
        "exit_price":      fill_price,
        "pnl_pct":         round(pnl_pct, 2),
        "pnl_usd":         round(net_pnl_usd, 2),
        "fees_usd":        round(total_fees, 4),
        "slippage_pct":    round(slip_pct * 100, 4),
        "reason":          reason,
        "closed_at":       datetime.now(tz=timezone.utc).isoformat(),
        "paper":           True,
        "order_id":        pos.get("order_id"),
        "regime_at_entry": pos.get("regime_at_entry", "Unknown"),
        "entry_zscore":    pos.get("entry_zscore"),
        "zscore_source":   pos.get("zscore_source"),
    }

    # Persist to DB immediately (primary store)
    _db.insert_trade(trade_record)

    # Keep in-memory all_trades list for backward compat
    if "all_trades" not in p:
        p["all_trades"] = []
    p["all_trades"].append(trade_record)

    del p["positions"][symbol]

    _save_portfolio()

    _slip_note = f" (mkt ${current_price:,.2f}, slip {slip_pct*100:.2f}%)" if slip_pct > 0.0001 else ""
    logger.info(
        f"Paper | Closed {pos['side'].upper()} {symbol} @ ${fill_price:,.2f}{_slip_note} | "
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

    wins = [t for t in trades if (t.get("pnl_usd") or 0) > 0]

    return {
        "starting_balance_usd": p["starting_balance_usd"],
        "cash_usd":             round(p["cash_usd"], 2),
        "total_trades":         len(trades),
        "win_count":            len(wins),
        "all_time_pnl_usd":     round(sum(t.get("pnl_usd", 0) for t in trades), 2),
    }
