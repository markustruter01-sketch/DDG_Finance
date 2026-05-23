"""Per-bot paper portfolio with JSON persistence. Path derived from BOT_ID."""
import json
import os
from threading import Lock
from config import BOT_ID, STARTING_CAPITAL

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATE_FILE = os.path.join(_HERE, f"{BOT_ID}.json")
_lock = Lock()


def _default_state():
    return {"cash_usd": float(STARTING_CAPITAL), "positions": {}}


def _load():
    with _lock:
        if not os.path.exists(_STATE_FILE):
            return _default_state()
        with open(_STATE_FILE) as f:
            return json.load(f)


def _save(state):
    with _lock:
        tmp = _STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, _STATE_FILE)


def get_equity(price_lookup: dict) -> float:
    """Compute total equity: cash + sum of position market values.
    price_lookup: {symbol: current_price}"""
    s = _load()
    equity = s["cash_usd"]
    for sym, pos in s["positions"].items():
        price = price_lookup.get(sym, pos["entry_price"])
        if pos["direction"] == "long":
            equity += pos["qty"] * price
        else:
            entry_value   = pos["qty"] * pos["entry_price"]
            current_value = pos["qty"] * price
            equity += entry_value + (entry_value - current_value)
    return equity


def open_position(symbol, direction, qty, entry_price, trailing_stop,
                  ema20, ema50, adx, entry_reason):
    import datetime
    s = _load()
    cost = qty * entry_price
    s["cash_usd"] -= cost
    s["positions"][symbol] = {
        "direction":        direction,
        "qty":              qty,
        "entry_price":      entry_price,
        "trailing_stop":    trailing_stop,
        "highest_favourable": entry_price,
        "ema20_at_entry":   ema20,
        "ema50_at_entry":   ema50,
        "adx_at_entry":     adx,
        "entry_reason":     entry_reason,
        "opened_at":        datetime.datetime.utcnow().isoformat(),
    }
    _save(s)


def close_position(symbol, exit_price, exit_reason) -> dict:
    s = _load()
    pos = s["positions"].pop(symbol, None)
    if not pos:
        return None
    if pos["direction"] == "long":
        pnl = (exit_price - pos["entry_price"]) * pos["qty"]
        s["cash_usd"] += pos["qty"] * exit_price
    else:
        pnl = (pos["entry_price"] - exit_price) * pos["qty"]
        s["cash_usd"] += pos["qty"] * pos["entry_price"] + pnl
    _save(s)
    pos["exit_price"]        = exit_price
    pos["exit_reason"]       = exit_reason
    pos["realised_pnl_usd"]  = pnl
    return pos


def update_trailing_stop(symbol, current_price, atr):
    s = _load()
    pos = s["positions"].get(symbol)
    if not pos:
        return
    if pos["direction"] == "long":
        if current_price > pos["highest_favourable"]:
            pos["highest_favourable"] = current_price
            pos["trailing_stop"]      = current_price - (atr * 2.0)
    else:
        if current_price < pos["highest_favourable"]:
            pos["highest_favourable"] = current_price
            pos["trailing_stop"]      = current_price + (atr * 2.0)
    _save(s)


def check_stop_hit(symbol, current_price) -> bool:
    s = _load()
    pos = s["positions"].get(symbol)
    if not pos:
        return False
    if pos["direction"] == "long":
        return current_price <= pos["trailing_stop"]
    else:
        return current_price >= pos["trailing_stop"]


def get_open_positions():
    return _load()["positions"]
