"""
paper_engine.py — Simulated $100K Paper Trading Portfolio for Forex
====================================================================
Mirrors the Kraken bot paper_engine.py pattern.
PostgreSQL-backed, with simulated spread costs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

_portfolio: dict | None = None


def _load_portfolio() -> dict:
    from forex_config import PAPER_STARTING_BALANCE
    import forex_nav_db as _db

    global _portfolio

    if _portfolio is not None:
        return _portfolio

    pg_pf = _db.load_portfolio()
    if pg_pf is not None:
        _portfolio = pg_pf
        logger.info(
            f"Forex Paper | Loaded portfolio from PostgreSQL — "
            f"Cash: ${_portfolio['cash_usd']:,.2f}, "
            f"Positions: {len(_portfolio.get('positions', {}))}"
        )
        return _portfolio

    logger.info("Forex Paper | No portfolio row in DB — initialising fresh $100k account")

    _portfolio = {
        "starting_balance_usd": PAPER_STARTING_BALANCE,
        "cash_usd": PAPER_STARTING_BALANCE,
        "positions": {},
        "hwm_usd": PAPER_STARTING_BALANCE,
        "vault_total_usd": 0.0,
        "last_sweep_date": None,
    }
    _save_portfolio()
    return _portfolio


def _save_portfolio() -> None:
    import forex_nav_db as _db

    global _portfolio
    if _portfolio is None:
        return

    _db.save_portfolio(
        cash_usd=_portfolio["cash_usd"],
        positions=_portfolio.get("positions", {}),
        starting_balance_usd=_portfolio.get("starting_balance_usd"),
        hwm_usd=_portfolio.get("hwm_usd"),
        vault_total_usd=_portfolio.get("vault_total_usd"),
        last_sweep_date=_portfolio.get("last_sweep_date"),
    )


def get_paper_equity(current_prices: dict[str, float] | None = None) -> float:
    from forex_config import get_quote_to_usd
    p = _load_portfolio()
    prices = current_prices or {}
    equity = p["cash_usd"]

    for pair, pos in p["positions"].items():
        price = prices.get(pair, pos["entry_price"])
        if pos["direction"] == "long":
            pnl = (price - pos["entry_price"]) * pos["units"]
        else:
            pnl = (pos["entry_price"] - price) * pos["units"]
        conv = get_quote_to_usd(pair, price, prices)
        pnl_usd = pnl * conv if conv is not None else 0.0
        equity += pos["size_usd"] + pnl_usd

    return equity


def get_available_capital() -> float:
    p = _load_portfolio()
    vault = p.get("vault_total_usd", 0.0)
    return max(0, p["cash_usd"] - vault)


def paper_open_position(
    pair: str,
    direction: str,
    size_usd: float,
    entry_price: float,
    units: float,
    sl_price: float,
    tp_price: float,
    llm_thesis: str = "",
) -> Optional[int]:
    from forex_config import PAPER_SPREAD_COST_PCT
    import forex_nav_db as _db

    p = _load_portfolio()

    spread_cost = size_usd * PAPER_SPREAD_COST_PCT
    total_cost = size_usd + spread_cost

    available = get_available_capital()
    if total_cost > available:
        logger.warning(
            f"Forex Paper | Not enough capital for {direction.upper()} {pair} — "
            f"Need ${total_cost:,.2f}, available ${available:,.2f}"
        )
        return None

    p["cash_usd"] -= total_cost

    p["positions"][pair] = {
        "direction": direction,
        "entry_price": entry_price,
        "size_usd": size_usd,
        "units": units,
        "sl_price": sl_price,
        "tp_price": tp_price,
        "original_sl": sl_price,
        "trailing_sl": sl_price,
        "highest_price": entry_price if direction == "long" else None,
        "lowest_price": entry_price if direction == "short" else None,
        "entry_time": datetime.now(tz=timezone.utc).isoformat(),
        "spread_cost": round(spread_cost, 4),
    }

    trade_record = {
        "pair": pair,
        "direction": direction,
        "entry_price": entry_price,
        "sl_price": sl_price,
        "tp_price": tp_price,
        "units": units,
        "llm_thesis": llm_thesis,
        "status": "open",
        "entry_time": datetime.now(tz=timezone.utc).isoformat(),
    }
    _db.insert_trade(trade_record)

    _save_portfolio()

    logger.success(
        f"Forex Paper | Opened {direction.upper()} {pair} — "
        f"Entry: {entry_price:.5f} | Units: {units:.0f} | "
        f"Size: ${size_usd:,.2f} | SL: {sl_price:.5f} | TP: {tp_price:.5f} | "
        f"Spread: ${spread_cost:.2f} | Cash: ${p['cash_usd']:,.2f}"
    )
    return True


def paper_close_position(pair: str, current_price: float, reason: str,
                         latest_prices: dict | None = None) -> dict | None:
    from forex_config import PAPER_SPREAD_COST_PCT, PIP_SIZE, get_quote_to_usd
    import forex_nav_db as _db

    p = _load_portfolio()

    if pair not in p["positions"]:
        logger.warning(f"Forex Paper | Tried to close {pair} but no position found")
        return None

    pos = p["positions"][pair]
    direction = pos["direction"]
    entry = pos["entry_price"]
    units = pos["units"]
    size_usd = pos["size_usd"]

    if direction == "long":
        pnl_raw = (current_price - entry) * units
    else:
        pnl_raw = (entry - current_price) * units

    prices = latest_prices or {}
    prices[pair] = current_price
    conv = get_quote_to_usd(pair, current_price, prices)

    if conv is None:
        # Attempt live fallback for cross pairs (e.g. EURJPY, GBPJPY need USDJPY rate)
        try:
            import yfinance as _yf_conv
            _pair_upper = pair.upper()
            if "JPY" in _pair_upper:
                _ref = _yf_conv.Ticker("USDJPY=X").history(period="1d", interval="1m")
                if not _ref.empty:
                    _usdjpy = float(_ref["Close"].iloc[-1])
                    if _usdjpy > 0:
                        conv = 1.0 / _usdjpy
            elif "CHF" in _pair_upper:
                _ref = _yf_conv.Ticker("USDCHF=X").history(period="1d", interval="1m")
                if not _ref.empty:
                    _usdchf = float(_ref["Close"].iloc[-1])
                    if _usdchf > 0:
                        conv = 1.0 / _usdchf
            elif "CAD" in _pair_upper:
                _ref = _yf_conv.Ticker("USDCAD=X").history(period="1d", interval="1m")
                if not _ref.empty:
                    _usdcad = float(_ref["Close"].iloc[-1])
                    if _usdcad > 0:
                        conv = 1.0 / _usdcad
            elif "AUD" in _pair_upper:
                _ref = _yf_conv.Ticker("AUDUSD=X").history(period="1d", interval="1m")
                if not _ref.empty:
                    _audusd = float(_ref["Close"].iloc[-1])
                    if _audusd > 0:
                        conv = _audusd
            elif "GBP" in _pair_upper and "USD" not in _pair_upper:
                _ref = _yf_conv.Ticker("GBPUSD=X").history(period="1d", interval="1m")
                if not _ref.empty:
                    _gbpusd = float(_ref["Close"].iloc[-1])
                    if _gbpusd > 0:
                        conv = _gbpusd
        except Exception as _conv_exc:
            logger.warning(f"paper_close_position | {pair}: live conv fallback failed: {_conv_exc}")

    if conv is None:
        logger.error(
            f"paper_close_position | {pair}: quote-to-USD conversion unavailable "
            f"after live fallback — P&L recorded as 0.0 USD. "
            f"This trade result is unreliable. prices_dict={list(prices.keys())}"
        )
    pnl_raw = pnl_raw * conv if conv is not None else 0.0

    exit_spread = size_usd * PAPER_SPREAD_COST_PCT
    entry_spread = pos.get("spread_cost", 0)
    total_fees = entry_spread + exit_spread

    # LEDGER value: only subtract exit spread here.
    # The entry spread was already deducted from cash at open (paper_open_position
    # line: p["cash_usd"] -= total_cost, where total_cost = size_usd + spread_cost).
    # Deducting total_fees here would double-count the entry spread.
    net_pnl = pnl_raw - exit_spread

    pip_size = PIP_SIZE.get(pair, 0.0001)
    if direction == "long":
        pnl_pips = (current_price - entry) / pip_size
    else:
        pnl_pips = (entry - current_price) / pip_size

    # Cash ledger update: return the original position capital (size_usd) plus the
    # net P&L after exit spread. Entry spread is already accounted for at open.
    p["cash_usd"] += size_usd + net_pnl

    # RECORD value: full round-trip cost (entry + exit spread) for trade journal only.
    # true_net_pnl is NEVER used for the cash ledger — only for the journal record.
    true_net_pnl = pnl_raw - total_fees

    open_trades = _db.load_open_trades()
    trade_id = None
    for t in open_trades:
        if t.get("pair") == pair and t.get("status") == "open":
            trade_id = t.get("id")
            break

    if trade_id:
        _db.update_trade_close(trade_id, current_price, pnl_pips, true_net_pnl,
                               final_trailing_sl=pos.get("trailing_sl"))

    trade_result = {
        "pair": pair,
        "direction": direction,
        "entry_price": entry,
        "exit_price": current_price,
        "pnl_pips": round(pnl_pips, 1),
        "pnl_usd": round(true_net_pnl, 2),
        "fees_usd": round(total_fees, 4),
        "reason": reason,
        "closed_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    del p["positions"][pair]
    _save_portfolio()

    logger.info(
        f"Forex Paper | Closed {direction.upper()} {pair} @ {current_price:.5f} | "
        f"Reason: {reason} | P&L: {pnl_pips:+.1f} pips (${true_net_pnl:+,.2f}) | "
        f"Cash: ${p['cash_usd']:,.2f}"
    )

    return trade_result


def get_paper_positions() -> dict:
    p = _load_portfolio()
    return {pair: dict(pos) for pair, pos in p["positions"].items()}


def update_position_fields(pair: str, updates: dict) -> None:
    p = _load_portfolio()
    if pair in p["positions"]:
        p["positions"][pair].update(updates)
        _save_portfolio()


def get_paper_portfolio_summary() -> dict:
    import forex_nav_db as _db

    p = _load_portfolio()
    trades = _db.load_recent_trades(limit=500)
    closed = [t for t in trades if t.get("status") == "closed"]
    wins = [t for t in closed if (t.get("pnl_usd") or 0) > 0]

    return {
        "starting_balance_usd": p["starting_balance_usd"],
        "cash_usd": round(p["cash_usd"], 2),
        "total_trades": len(closed),
        "win_count": len(wins),
        "all_time_pnl_usd": round(sum(t.get("pnl_usd", 0) for t in closed), 2),
        "hwm_usd": p.get("hwm_usd", p["starting_balance_usd"]),
        "vault_total_usd": p.get("vault_total_usd", 0),
    }


def update_hwm(equity: float) -> None:
    p = _load_portfolio()
    if equity > p.get("hwm_usd", 0):
        p["hwm_usd"] = equity
        _save_portfolio()


def perform_vault_sweep(equity: float) -> float | None:
    from forex_config import VAULT_SWEEP_PCT
    import forex_nav_db as _db

    p = _load_portfolio()
    hwm = p.get("hwm_usd", p["starting_balance_usd"])

    if equity <= hwm:
        return None

    today_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    if p.get("last_sweep_date") == today_str:
        return None

    profit_above_hwm = equity - hwm
    sweep_amount = profit_above_hwm * VAULT_SWEEP_PCT

    if sweep_amount < 1.0:
        return None

    p["vault_total_usd"] = p.get("vault_total_usd", 0) + sweep_amount

    p["last_sweep_date"] = today_str
    p["hwm_usd"] = equity
    _save_portfolio()

    _db.ensure_vault_table()
    _db.insert_vault_sweep(today_str, sweep_amount, p["vault_total_usd"], equity)

    logger.success(
        f"Forex Vault | Swept ${sweep_amount:,.2f} (20% of ${profit_above_hwm:,.2f} profit) | "
        f"Vault total: ${p['vault_total_usd']:,.2f}"
    )
    return sweep_amount
