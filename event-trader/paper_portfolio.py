"""Paper portfolio for event trader."""
import json
import os
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(_HERE, "event_paper_portfolio.json")
STARTING_EQUITY = 100_000.0


def _load():
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE) as f:
            return json.load(f)
    return {"cash_usd": STARTING_EQUITY, "positions": {}, "trade_history": []}


def _save(state):
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def get_equity():
    s = _load()
    pos_value = sum(
        p["units"] * p.get("current_price", p["entry_price"])
        for p in s["positions"].values()
    )
    return s["cash_usd"] + pos_value


def get_cash():
    return _load()["cash_usd"]


def has_position(event_id: str) -> bool:
    return event_id in _load()["positions"]


def position_count() -> int:
    return len(_load()["positions"])


def open_position(event_id, asset, units, price, event_date, classification):
    s = _load()
    cost = units * price
    s["cash_usd"] -= cost
    s["positions"][event_id] = {
        "asset": asset,
        "units": units,
        "entry_price": price,
        "current_price": price,
        "peak_price": price,
        "event_date": event_date if isinstance(event_date, str) else event_date.isoformat(),
        "classification": classification,
        "entry_time": datetime.utcnow().isoformat(),
        "partial_exited": False,
    }
    _save(s)


def update_position_price(event_id, current_price):
    s = _load()
    if event_id in s["positions"]:
        s["positions"][event_id]["current_price"] = current_price
        if current_price > s["positions"][event_id].get("peak_price", 0):
            s["positions"][event_id]["peak_price"] = current_price
        _save(s)


def partial_close(event_id, exit_price, fraction=0.5):
    """Close `fraction` of the position. Returns trade dict."""
    s = _load()
    if event_id not in s["positions"]:
        return None
    p = s["positions"][event_id]
    units_to_close = p["units"] * fraction
    proceeds = units_to_close * exit_price
    s["cash_usd"] += proceeds
    p["units"] -= units_to_close
    p["partial_exited"] = True
    pnl = proceeds - (units_to_close * p["entry_price"])
    trade = {
        "event_id": event_id, "asset": p["asset"],
        "entry_price": p["entry_price"], "exit_price": exit_price,
        "units": units_to_close, "pnl_usd": pnl,
        "reason": "partial_pre_event", "classification": p["classification"],
        "entry_time": p["entry_time"], "exit_time": datetime.utcnow().isoformat(),
    }
    s["trade_history"].append(trade)
    _save(s)
    return trade


def close_position(event_id, exit_price, reason):
    """Close full remaining position."""
    s = _load()
    if event_id not in s["positions"]:
        return None
    p = s["positions"].pop(event_id)
    proceeds = p["units"] * exit_price
    s["cash_usd"] += proceeds
    pnl = proceeds - (p["units"] * p["entry_price"])
    trade = {
        "event_id": event_id, "asset": p["asset"],
        "entry_price": p["entry_price"], "exit_price": exit_price,
        "units": p["units"], "pnl_usd": pnl,
        "reason": reason, "classification": p["classification"],
        "entry_time": p["entry_time"], "exit_time": datetime.utcnow().isoformat(),
    }
    s["trade_history"].append(trade)
    _save(s)
    return trade
